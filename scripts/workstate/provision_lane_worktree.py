#!/usr/bin/env python3
"""Provision a linked worktree without dereferencing dependency trees.

GPUUX-1-REPO-BR-02: `cp -R` / `shutil.copytree` (symlinks=False) turns
`node_modules/.bin/vitest` into a regular file that resolves `./dist/cli.js`
relative to `.bin/` and dies with ERR_MODULE_NOT_FOUND. This provisioner never
copies node_modules or vendor; it either symlinks the primary tree or leaves
the worktree to run `npm ci` / `composer install`.

VMREAP-1-BR-04: linked worktrees do not inherit gitignored overlay surfaces
(Makefile.d except tracked files, scripts/hooks, scripts/workbay,
scripts/workbay_lifecycle). Rsync only ignored entries from the primary
checkout with `-a` so tracked files already checked out in the linked tree are
never overwritten and overlay symlinks stay symlinks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

OVERLAY_PATHS: tuple[str, ...] = (
    "Makefile.d",
    "scripts/hooks",
    "scripts/workbay",
    "scripts/workbay_lifecycle",
    "scripts/remote_agent.sh",
)

DEPENDENCY_TREES: tuple[str, ...] = (
    "apps/prototype-wp-alt-context/node_modules",
    "apps/prototype-wp-alt-context/vendor",
)

DEPENDENCY_LOCKFILES: dict[str, str] = {
    "apps/prototype-wp-alt-context/node_modules": "apps/prototype-wp-alt-context/package-lock.json",
    "apps/prototype-wp-alt-context/vendor": "apps/prototype-wp-alt-context/composer.lock",
}

SECURE_OFFLOAD_MARKER = ".acx-secure-offload"
DEP_SOURCE_SIDECAR = ".acx-dep-source"
# Tail case (PERF-08): one wave of many lanes, each freezing GB-scale trees.
# Keep only live lockfile digests; history of lockfile churn must not accumulate.
DEP_CACHE_SCAN_LIMIT = 32
SIDECAR_ENTRY_KEYS = ("lockfile", "sha256", "readonly", "cache")


def primary_checkout(start: Path) -> Path:
    proc = subprocess.run(
        ["git", "-C", str(start), "rev-parse", "--path-format=absolute", "--git-common-dir"],
        capture_output=True,
        text=True,
        check=False,
    )
    common_dir = proc.stdout.strip()
    if proc.returncode != 0 or not common_dir:
        detail = (proc.stderr or proc.stdout or "no output").strip()
        raise RuntimeError(
            f"git rev-parse --git-common-dir failed for {start} "
            f"(exit {proc.returncode}): {detail}; refusing to guess the primary checkout"
        )
    return Path(common_dir).parent


def _is_secure_offload_sandbox(worktree: Path, *, flagged: bool) -> bool:
    """Return whether the destination is a secret-scanned untrusted sandbox."""
    if flagged:
        return True
    marker = worktree / SECURE_OFFLOAD_MARKER
    return marker.exists() or marker.is_symlink()


def _refuse_secure_offload(worktree: Path) -> None:
    raise RuntimeError(
        f"refusing overlay copy and primary dependency symlinks into secure-offload "
        f"sandbox {worktree}; never add external primary files after the secret scan"
    )


def _require_git_primary(primary: Path) -> None:
    """Refuse an explicit --primary that is missing or not a Git checkout."""
    if not primary.exists():
        raise RuntimeError(f"explicit --primary {primary} does not exist; refusing to provision")
    if not _git_metadata_present(primary):
        raise RuntimeError(
            f"explicit --primary {primary} is not a Git checkout; "
            "pass --fixture-mode only for hermetic tests"
        )


def _remove_existing_path(path: Path) -> None:
    """Remove a destination without following a symlink at its top level."""
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def _git_metadata_present(primary: Path) -> bool:
    """Return whether ``primary`` claims to be a Git checkout.

    ``Path.exists`` is false for a broken ``.git`` link, but that is still Git
    metadata and must not be treated as a fixture.  A checkout with broken or
    unreadable metadata should fail closed instead of copying every overlay
    entry.
    """
    metadata = primary / ".git"
    return metadata.exists() or metadata.is_symlink()


def _ignored_overlay_entries(primary: Path, rel: str) -> list[str] | None:
    """Return ignored entries below ``rel``; ``None`` means no Git metadata."""
    try:
        proc = subprocess.run(
            [
                "git",
                "-C",
                str(primary),
                "ls-files",
                "--others",
                "--ignored",
                "--exclude-standard",
                "-z",
                "--",
                rel,
            ],
            capture_output=True,
            check=False,
        )
    except OSError:
        if _git_metadata_present(primary):
            raise RuntimeError(f"git ls-files could not run for {primary}; refusing overlay copy") from None
        return None
    if proc.returncode != 0:
        if _git_metadata_present(primary):
            raise RuntimeError(f"git ls-files failed for {primary} (exit {proc.returncode}); refusing overlay copy")
        return None

    prefix = f"{rel}/"
    entries: list[str] = []
    for raw_entry in proc.stdout.split(b"\0"):
        if not raw_entry:
            continue
        entry = os.fsdecode(raw_entry)
        if entry == rel:
            entries.append("")
        elif entry.startswith(prefix):
            entries.append(entry[len(prefix) :])
    return entries


def _relocated_symlink_target(source: Path, target: Path) -> str:
    """Relocate a link target so it keeps the source link's meaning.

    ``os.readlink`` returns a relative target relative to ``source.parent``.
    Reusing that text at a different worktree parent silently points at a
    different tree, so recompute the relative spelling from ``target.parent``.
    The path normalization is intentionally non-strict: an overlay may be
    linked before its external target is materialized.
    """
    link_target = os.readlink(source)
    if os.path.isabs(link_target):
        return link_target
    source_target = os.path.abspath(os.path.join(os.fspath(source.parent), link_target))
    return os.path.relpath(source_target, os.fspath(target.parent))


def _relative_stays_inside(rel: str) -> bool:
    """Return whether ``rel`` cannot walk above its overlay root."""
    if not rel:
        return True
    path = Path(rel)
    if path.is_absolute():
        return False
    depth = 0
    for part in path.parts:
        if part == "..":
            depth -= 1
            if depth < 0:
                return False
        elif part in (".", ""):
            continue
        else:
            depth += 1
    return True


def _require_contained_overlay_entry(src: Path, rel: str) -> None:
    if _relative_stays_inside(rel):
        return
    raise RuntimeError(f"ignored overlay entry {rel!r} escapes {src}; refusing overlay copy")


def _copy_overlay_entries(src: Path, dest: Path, entries: list[str]) -> None:
    """Copy an ignored-entry manifest without dereferencing entry symlinks."""
    for rel in entries:
        _require_contained_overlay_entry(src, rel)
        source = src / rel
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        _remove_existing_path(target)
        if source.is_symlink():
            target.symlink_to(_relocated_symlink_target(source, target))
        elif source.is_dir():
            shutil.copytree(source, target, symlinks=True, dirs_exist_ok=True)
        else:
            shutil.copy2(source, target, follow_symlinks=False)


def _rsync_overlay(src: Path, dest: Path, *, entries: list[str] | None = None) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Path.is_dir() follows symlinks.  Test the link first so a plugin-managed
    # overlay such as Makefile.d -> ../workbay-overlay remains a link in the
    # linked worktree instead of becoming a copied directory.
    if src.is_symlink():
        if dest.is_symlink() and os.path.realpath(dest) == os.path.realpath(src):
            return
        _remove_existing_path(dest)
        # Rsync preserves link text, not the link's source-relative meaning.
        # Create the relocated link ourselves even when rsync is available.
        dest.symlink_to(_relocated_symlink_target(src, dest))
        return

    if dest.is_symlink() or dest.is_file():
        _remove_existing_path(dest)

    if entries is not None:
        if not entries:
            return
        for rel in entries:
            _require_contained_overlay_entry(src, rel)
        # rsync preserves link text and, for a one-file files-from list, may
        # replace dest with that file. Copy overlay symlinks ourselves so
        # relative targets keep source meaning on rsync and non-rsync hosts.
        symlink_entries = [rel for rel in entries if (src / rel).is_symlink()]
        other_entries = [rel for rel in entries if rel not in set(symlink_entries)]
        if other_entries:
            dest.mkdir(parents=True, exist_ok=True)
            if shutil.which("rsync"):
                payload = b"".join(os.fsencode(entry) + b"\0" for entry in other_entries)
                subprocess.run(
                    ["rsync", "-a", "--from0", "--files-from=-", f"{src}/", str(dest)],
                    input=payload,
                    check=True,
                )
            else:
                _copy_overlay_entries(src, dest, other_entries)
        if symlink_entries:
            _copy_overlay_entries(src, dest, symlink_entries)
        return

    if shutil.which("rsync"):
        source = f"{src}/" if src.is_dir() else str(src)
        target = str(dest)
        subprocess.run(["rsync", "-a", source, target], check=True)
        return
    if src.is_dir():
        shutil.copytree(src, dest, symlinks=True, dirs_exist_ok=True)
    else:
        shutil.copy2(src, dest, follow_symlinks=False)


def provision_overlay(*, primary: Path, worktree: Path, fixture_mode: bool = False) -> list[str]:
    copied: list[str] = []
    for rel in OVERLAY_PATHS:
        src = primary / rel
        dest = worktree / rel
        # exists() is false for a broken symlink, but the contract is to carry
        # the plugin's overlay link itself even when its target is provisioned
        # separately on the host.
        if not src.exists() and not src.is_symlink():
            continue
        if dest.resolve(strict=False) == src.resolve(strict=False):
            continue

        # A top-level symlink is the overlay contract itself. Preserve it even
        # when its target is outside this checkout or Git cannot inspect it.
        if src.is_symlink():
            _rsync_overlay(src, dest)
            copied.append(rel)
            continue

        ignored_entries = _ignored_overlay_entries(primary, rel)
        if ignored_entries is None:
            if not fixture_mode:
                raise RuntimeError(
                    f"explicit --primary {primary} has no Git metadata; "
                    "refusing overlay copy (pass --fixture-mode only for hermetic tests)"
                )
            # Hermetic callers may provide a directory without Git metadata.
            _rsync_overlay(src, dest)
        elif src.is_dir():
            # In a real checkout, only ignored overlay entries are eligible.
            # Tracked files (for example Makefile.d/demo-auth.mk) are omitted,
            # leaving the linked worktree's branch-owned version untouched.
            _rsync_overlay(src, dest, entries=ignored_entries)
        elif "" in ignored_entries:
            _rsync_overlay(src, dest)
        else:
            continue
        copied.append(rel)
    return copied


def _replace_with_symlink(dest: Path, src: Path) -> None:
    if dest.is_symlink() or dest.is_file():
        dest.unlink()
    elif dest.is_dir():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(src, dest)


def _dep_cache_path(worktree: Path, rel: str, digest: str) -> Path:
    """Return the lockfile-keyed freeze directory for one dependency tree."""
    tree = Path(rel)
    return worktree / tree.parent / ".acx-dep-cache" / digest / tree.name


def _usable_dep_cache(cache: Path) -> bool:
    """Return whether ``cache`` is a real directory snapshot, not a dangling hit."""
    return cache.is_dir()


def _freeze_dependency_tree(src: Path, cache: Path) -> None:
    """Snapshot ``src`` into ``cache`` without dereferencing bin stubs.

    Parallel lanes with the same lockfile digest reuse this snapshot instead of
    the live primary tree, so an ``npm install`` in the primary cannot mutate a
    provisioned lane.
    """
    if _usable_dep_cache(cache):
        return
    if cache.exists() or cache.is_symlink():
        _remove_existing_path(cache)
    cache.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache.parent / f".tmp-{cache.name}.{os.getpid()}"
    _remove_existing_path(tmp)
    try:
        shutil.copytree(src, tmp, symlinks=True)
        try:
            tmp.rename(cache)
        except OSError:
            _remove_existing_path(tmp)
            if not _usable_dep_cache(cache):
                raise
    except Exception:
        _remove_existing_path(tmp)
        raise


def _lockfile_digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sidecar_path(dest: Path) -> Path:
    return dest.parent / DEP_SOURCE_SIDECAR


def _require_sidecar_entry(sidecar: Path, name: object, entry: object) -> None:
    if not isinstance(name, str) or not name:
        raise RuntimeError(f"{sidecar} has an invalid dependency key; refusing to provision")
    if not isinstance(entry, dict):
        raise RuntimeError(f"{sidecar}: {name} must be an object; refusing to provision")
    missing = [key for key in SIDECAR_ENTRY_KEYS if key not in entry]
    if missing:
        raise RuntimeError(
            f"{sidecar}: {name} missing {', '.join(missing)}; refusing to provision"
        )
    lockfile = entry["lockfile"]
    digest = entry["sha256"]
    cache = entry["cache"]
    if not isinstance(lockfile, str) or not lockfile:
        raise RuntimeError(f"{sidecar}: {name}.lockfile must be a non-empty string")
    if not isinstance(digest, str) or not digest:
        raise RuntimeError(f"{sidecar}: {name}.sha256 must be a non-empty string")
    if not isinstance(entry["readonly"], bool):
        raise RuntimeError(f"{sidecar}: {name}.readonly must be a boolean")
    if not isinstance(cache, str) or not cache:
        raise RuntimeError(f"{sidecar}: {name}.cache must be a non-empty string")


def _read_sidecar(dest: Path) -> dict[str, object]:
    sidecar = _sidecar_path(dest)
    if not sidecar.exists() and not sidecar.is_symlink():
        return {}
    if sidecar.is_symlink() or not sidecar.is_file():
        raise RuntimeError(f"{sidecar} is not a regular file; refusing to provision")
    try:
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{sidecar} is not valid JSON; refusing to provision") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{sidecar} must be a JSON object; refusing to provision")
    for name, entry in payload.items():
        _require_sidecar_entry(sidecar, name, entry)
    return payload


def _sidecar_digests(payload: dict[str, object]) -> set[str]:
    keep: set[str] = set()
    for entry in payload.values():
        if isinstance(entry, dict):
            digest = entry.get("sha256")
            if isinstance(digest, str) and digest:
                keep.add(digest)
    return keep


def _evict_stale_dep_caches(worktree: Path, rel: str, *, keep_digests: set[str]) -> None:
    """Drop stale snapshots of ``rel`` so the per-worktree cache stays bounded.

    RES-08 / PERF-08: the miss path is one copytree of the current lockfile
    tree. Retaining old digests does not help the many-lanes-in-one-wave tail;
    it only grows disk. RES-05: directory scan is capped per provision.
    """
    cache_root = worktree / Path(rel).parent / ".acx-dep-cache"
    tree_name = Path(rel).name
    if cache_root.is_symlink() or not cache_root.is_dir():
        return
    scanned = 0
    try:
        iterator = os.scandir(cache_root)
    except OSError as exc:
        raise RuntimeError(f"cannot scan dependency cache {cache_root}: {exc}") from exc
    with iterator:
        for entry in iterator:
            scanned += 1
            if scanned > DEP_CACHE_SCAN_LIMIT:
                break
            path = Path(entry.path)
            if entry.name.startswith(".tmp-"):
                _remove_existing_path(path)
                continue
            if not entry.is_dir(follow_symlinks=False):
                continue
            if entry.name in keep_digests:
                continue
            stale_tree = path / tree_name
            if stale_tree.exists() or stale_tree.is_symlink():
                _remove_existing_path(stale_tree)
            try:
                next(path.iterdir())
            except StopIteration:
                _remove_existing_path(path)
            except OSError:
                continue


def _write_sidecar_entry(dest: Path, *, lockfile: str, digest: str, cache: Path) -> None:
    payload = _read_sidecar(dest)
    payload[dest.name] = {
        "lockfile": lockfile,
        "sha256": digest,
        "readonly": True,
        "cache": str(cache),
    }
    sidecar = _sidecar_path(dest)
    sidecar.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _drop_sidecar_entry(dest: Path) -> None:
    payload = _read_sidecar(dest)
    if dest.name not in payload:
        return
    del payload[dest.name]
    sidecar = _sidecar_path(dest)
    if payload:
        sidecar.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    elif sidecar.exists() or sidecar.is_symlink():
        sidecar.unlink()


def provision_dependency_trees(*, primary: Path, worktree: Path) -> list[str]:
    """Symlink primary trees only when lane and primary lockfiles match."""
    linked: list[str] = []
    mismatches: list[str] = []
    for rel in DEPENDENCY_TREES:
        src = primary / rel
        dest = worktree / rel
        if worktree.resolve(strict=False) == primary.resolve(strict=False):
            # Same checkout root (main tree, or --primary omitted on a normal
            # clone): never rmtree the live node_modules/vendor tree into a
            # dangling link. A separate worktree whose dest symlink merely
            # resolves to primary still needs lock checks and a frozen cache.
            if dest.is_symlink():
                linked.append(rel)
            continue
        if not src.exists():
            continue

        lock_rel = DEPENDENCY_LOCKFILES[rel]
        digest = _lockfile_digest(worktree / lock_rel)
        primary_digest = _lockfile_digest(primary / lock_rel)
        _read_sidecar(dest)
        if digest is None or primary_digest is None or digest != primary_digest:
            if dest.is_symlink():
                dest.unlink()
            _drop_sidecar_entry(dest)
            _evict_stale_dep_caches(worktree, rel, keep_digests=_sidecar_digests(_read_sidecar(dest)))
            mismatches.append(rel)
            print(
                f"{rel}: lockfile mismatch or missing; install dependencies in the lane "
                f"(no shared {rel} symlink). Align {lock_rel} with the primary checkout.",
                file=sys.stderr,
            )
            continue

        cache = _dep_cache_path(worktree, rel, digest)
        _freeze_dependency_tree(src, cache)
        if dest.exists() or dest.is_symlink():
            _replace_with_symlink(dest, cache)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(cache, dest)
        _write_sidecar_entry(dest, lockfile=lock_rel, digest=digest, cache=cache)
        _evict_stale_dep_caches(worktree, rel, keep_digests=_sidecar_digests(_read_sidecar(dest)))
        linked.append(rel)
    if mismatches:
        raise RuntimeError(
            "dependency lockfile mismatch; install dependencies in the lane: "
            + ", ".join(mismatches)
        )
    return linked


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worktree", required=True, type=Path)
    parser.add_argument("--primary", type=Path, default=None)
    parser.add_argument(
        "--secure-offload",
        action="store_true",
        help="Fail closed: do not copy overlays or symlink primary trees into a sandbox",
    )
    parser.add_argument(
        "--fixture-mode",
        action="store_true",
        help="Allow a non-Git --primary for hermetic tests only",
    )
    args = parser.parse_args(argv)
    worktree = args.worktree.resolve()
    try:
        if args.primary is not None:
            primary = args.primary.expanduser()
            if not primary.exists():
                raise RuntimeError(
                    f"explicit --primary {primary} does not exist; refusing to provision"
                )
            primary = primary.resolve()
            if not args.fixture_mode:
                _require_git_primary(primary)
        else:
            primary = primary_checkout(worktree).resolve()
        if _is_secure_offload_sandbox(worktree, flagged=args.secure_offload):
            _refuse_secure_offload(worktree)
        provision_overlay(primary=primary, worktree=worktree, fixture_mode=args.fixture_mode)
        provision_dependency_trees(primary=primary, worktree=worktree)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
