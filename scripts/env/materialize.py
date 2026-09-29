from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shlex
import stat
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import Callable, Sequence, TextIO

from env import render_env as render
from env.manifest import load_manifest
from env.secret_refs import SecretUnavailable


class _InvalidLeaseEnv(ValueError):
    pass


def _lease_path(backup_root: Path, lease_env: str | None) -> Path | None:
    if lease_env is None:
        return None
    if (not isinstance(lease_env, str)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", lease_env) is None
            or ".." in lease_env):
        raise _InvalidLeaseEnv("invalid lease_env")
    lease = backup_root / "locks" / f"deploy-{lease_env}.lease"
    try:
        lease.resolve().relative_to(backup_root.resolve())
    except (OSError, RuntimeError, ValueError):
        raise _InvalidLeaseEnv("lease_env resolves outside backup root") from None
    return lease


@contextmanager
def _lock(path: Path, timeout: float, *, create: bool = True):
    render._inspect_path(path)
    fd = os.open(path, (os.O_CREAT | os.O_RDWR if create else os.O_RDONLY) | os.O_NOFOLLOW, 0o600)
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise ValueError("invalid lock file")
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("lock busy") from None
                time.sleep(min(0.05, remaining))
        yield
    finally:
        os.close(fd)


def _read_lease(path: Path):
    if render._inspect_path(path) is None:
        return None
    with path.open("rb") as stream:
        if os.fstat(stream.fileno()).st_nlink != 1:
            raise ValueError("invalid lease")
        raw = stream.read(4097)
    try:
        record = json.loads(raw.decode("ascii"))
        valid = (
            len(raw) <= 4096 and isinstance(record, dict)
            and set(record) == {"transaction", "holder", "expires_at"}
            and isinstance(record["transaction"], str)
            and re.fullmatch(r"[A-Za-z0-9_.-]+", record["transaction"])
            and isinstance(record["holder"], str)
            and re.fullmatch(r"[A-Za-z0-9_.@:-]{1,128}", record["holder"])
            and type(record["expires_at"]) is int
        )
    except (ValueError, UnicodeError):
        valid = False
    if not valid:
        raise ValueError("invalid lease") from None
    return record


@contextmanager
def _lease(path: Path | None, timeout: float, now: Callable[[], float]):
    if path is None:
        yield
        return
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock = Path(f"{path}.lock")
    transaction = uuid.uuid4().hex
    with _lock(lock, timeout):
        current = _read_lease(path)
        if current is not None and current["expires_at"] > now():
            raise TimeoutError("lease busy")
        record = dict(transaction=transaction, holder="envman-materialize", expires_at=int(now()) + 600)
        render._atomic_write(path, json.dumps(record, separators=(",", ":")).encode("ascii"))
    try:
        yield
    finally:
        with _lock(lock, timeout):
            current = _read_lease(path)
            if current is not None and current["transaction"] == transaction:
                path.unlink()


def _owned_write(path: Path, data: bytes, owner: os.stat_result, *, backup: bool = False):
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    staged = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(data)
            stream.flush()
            os.fchown(stream.fileno(), owner.st_uid, owner.st_gid)
            os.fsync(stream.fileno())
        if backup:
            # Linking publishes the complete backup without overwriting a prior adoption.
            os.link(staged, path)
        else:
            os.replace(staged, path)
    finally:
        staged.unlink(missing_ok=True)


def _assignment_has_value(line: str) -> bool:
    match = render._ASSIGNMENT.match(line)
    if match is None:
        return False
    try:
        return any(shlex.split(match.group(2), comments=False))
    except ValueError:
        return False


def run(
    manifest_root: Path, *, env: str, target: str, into: str,
    check: bool = False, adopt: bool = False, allow_unmanaged: Sequence[str] = (),
    fs_root: Path = Path("/"), backup_root: Path = Path("/opt/acx-backend/.acx-deploy-backups"),
    lock_timeout: float = 30.0, now: Callable[[], float] = time.time,
    out: TextIO = sys.stdout, err: TextIO = sys.stderr,
) -> int:
    try:
        manifest = load_manifest(manifest_root)
        spec = render._target(manifest, target)
        if spec.remote_paths.get(env) != into:
            raise ValueError("target path mismatch")
        lease = _lease_path(backup_root, spec.lease_env.get(env))
        if check:
            lease = None
        path = fs_root / into.lstrip("/")
        if check and path.exists() and not stat.S_ISREG(path.lstat().st_mode):
            print(f"mode\t{into}", file=out)
            return 1
        if render._inspect_path(path) is None:
            raise ValueError("existing file required")
        lock_path = Path(f"{path}.acx-image-repo.lock")
        # A read-only check must not create a lock on an unmaterialized host.
        image_lock = _lock(lock_path, lock_timeout, create=not check) if not check or lock_path.exists() else nullcontext()
        with _lease(lease, lock_timeout, now), image_lock:
            owner = render._inspect_path(path)
            if owner is None:
                raise ValueError("existing file required")
            old = path.read_bytes().decode("utf-8")
            actual = render._runtime_assignments(old)
            variables = render._target_vars(manifest, target)
            managed = {var.name for var in variables}
            missing_host = {
                var.name for var in variables
                if var.secret.get(env) == "host:" and var.required
                and not any(_assignment_has_value(line) for line in actual.get(var.name, ()))
            }
            if missing_host and not check:
                raise SecretUnavailable("missing host key " + sorted(missing_host)[0])
            rendered = render.render_target(
                manifest, target, env, host_lines=actual,
                missing_host_keys=missing_host if check else None,
            )
            body = rendered.split("\n", 2)[2]
            expected = render._runtime_assignments(body)
            stale_managed = (actual.keys() & managed) - expected.keys()
            unmanaged = actual.keys() - managed - set(spec.preserve) - set(allow_unmanaged)
            if check:
                groups = {
                    "missing": expected.keys() - actual.keys() | missing_host,
                    "stale": stale_managed - set(spec.preserve) - set(allow_unmanaged),
                    "unmanaged": unmanaged,
                    "differs": {key for key in expected.keys() & actual.keys() if expected[key] != actual[key]},
                    "mode": {into} if stat.S_IMODE(owner.st_mode) != 0o600 or old.split("\n", 1)[0] != render.HEADER_LINE else set(),
                }
                for group, names in groups.items():
                    for name in sorted(names):
                        print(f"{group}\t{name}", file=out)
                return int(any(groups.values()))
            if unmanaged:
                raise ValueError("unmanaged key " + sorted(unmanaged)[0])
            preserved = [line for line in old.split("\n") if line.startswith("# ACX_IMAGE_REPO_OWNER=")]
            for key in (*spec.preserve, *sorted(set(allow_unmanaged) - managed - set(spec.preserve))):
                preserved.extend(actual.get(key, []))
            digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
            text = f"{render.HEADER_LINE}\n# materialized target={target} env={env} digest={digest}\n{body}"
            if preserved:
                text += "\n# Preserved (host/deploy-owned)\n" + "\n".join(preserved) + "\n"
            plan = render._preflight_env_file(path, text, adopt=adopt, runtime=True,
                                               allow_unmanaged=frozenset(allow_unmanaged) | frozenset(stale_managed))
            if plan.backup is not None:
                _owned_write(Path(f"{path}.pre-envman"), plan.backup, owner, backup=True)
            _owned_write(path, plan.data, owner)
        return 0
    except SecretUnavailable as exc:
        print(str(exc), file=err)
        return 4
    except _InvalidLeaseEnv as exc:
        print(f"materialize refused: {exc}", file=err)
        return 2
    except TimeoutError:
        print("materialize lock or lease busy", file=err)
        return 75
    except (OSError, ValueError):
        print("materialize refused", file=err)
        return 2
