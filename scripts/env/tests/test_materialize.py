from __future__ import annotations

import fcntl
import io
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path

import pytest

from conftest import load_module


INTO = "/opt/acx-backend/dev/.env"
SECRET = "s3cr3t-value"
OWNER = '# ACX_IMAGE_REPO_OWNER={"owner":"' + "a" * 32 + '","prior":"","current":"r/x","phase":"shipped"}\n'


def _toml_table(values: dict[str, str]) -> str:
    return "{ " + ", ".join(f"{key} = {json.dumps(value)}" for key, value in values.items()) + " }"


def _targets() -> str:
    return '\n'.join([
        'version = 1', '[targets.t]', 'audience = "backend"',
        'envs = ["dev"]', 'sections = ["S"]',
        f'remote_paths = {_toml_table({"dev": INTO})}',
        'preserve = ["ACX_IMAGE_REPO"]', 'lease_env = {dev = "dev"}',
    ])


def _var(name, *, cls="config", values=None, secret=None, required=True):
    lines = ['[[var]]', f'name = {json.dumps(name)}',
             f'class = {json.dumps(cls)}', 'targets = ["t"]',
             'section = "S"', 'example = "example-value"']
    if not required:
        lines.append('required = false')
    for key, value in (("values", values), ("secret", secret)):
        if value is not None:
            lines.append(f"{key} = {_toml_table(value)}")
    return '\n'.join(lines)


@dataclass
class Case:
    root: Path
    fs: Path
    file: Path
    bk: Path
    header: str

    @property
    def lease(self):
        return self.bk / "locks/deploy-dev.lease"

    def run(self, mat, **kwargs):
        out, err = io.StringIO(), io.StringIO()
        options = dict(env="dev", target="t", into=INTO, fs_root=self.fs,
                       backup_root=self.bk, lock_timeout=0.2,
                       now=lambda: 1_000_000.0, out=out, err=err)
        options.update(kwargs)
        try:
            rc = mat.run(self.root, **options)
        except Exception as exc:
            assert SECRET not in str(exc)
            raise
        finally:
            assert SECRET not in out.getvalue()
            assert SECRET not in err.getvalue()
        return rc, out.getvalue(), err.getvalue()

    def seed_lease(self, content):
        self.lease.parent.mkdir(parents=True, exist_ok=True)
        self.lease.write_text(content)


@pytest.fixture
def case(tmp_path, write_manifest):
    root = write_manifest(_targets(), **{"10-materialize": "version = 1\n" + '\n'.join([
        _var("LOG_LEVEL", values={"dev": "info"}),
        _var("PGPASSWORD", cls="secret", secret={"dev": "host:"}),
        _var("OPTIONAL_TOKEN", cls="secret", secret={"dev": "host:"}, required=False),
    ])})
    header = load_module("render_env").HEADER_LINE
    fs = tmp_path / "fs"
    file = fs / INTO.lstrip("/")
    file.parent.mkdir(parents=True)
    file.write_bytes((header + '\n# materialized target=t env=dev digest=x\n'
                      'LOG_LEVEL=debug\nPGPASSWORD=' + SECRET + '\n' + OWNER +
                      'ACX_IMAGE_REPO=r/x\n').encode())
    file.chmod(0o600)
    return Case(root, fs, file, tmp_path / "bk", header)


def test_apply_merges_managed_host_and_preserved(case):
    mat = load_module("materialize")
    assert case.run(mat)[0] == 0
    data = case.file.read_bytes()
    assert data.splitlines()[0] == case.header.encode()
    assert data.splitlines()[1].startswith(b"# materialized target=t env=dev digest=")
    assert b"LOG_LEVEL=info" in data.splitlines()
    assert b"PGPASSWORD=s3cr3t-value" in data.splitlines()
    assert data.endswith(('\n# Preserved (host/deploy-owned)\n' + OWNER + 'ACX_IMAGE_REPO=r/x\n').encode())
    assert stat.S_IMODE(case.file.stat().st_mode) == 0o600


def test_optional_host_missing_is_omitted(case):
    mat = load_module("materialize")
    assert case.run(mat)[0] == 0
    assert b"OPTIONAL_TOKEN=" not in case.file.read_bytes()


def test_required_host_missing_exits_4(case):
    mat = load_module("materialize")
    before = case.file.read_bytes().replace(b"PGPASSWORD=s3cr3t-value\n", b"")
    case.file.write_bytes(before)
    rc, _, err = case.run(mat)
    assert rc == 4
    assert "PGPASSWORD" in err
    assert case.file.read_bytes() == before


def test_into_mismatch_exits_2(case):
    mat = load_module("materialize")
    before = case.file.read_bytes()
    assert case.run(mat, into="/opt/acx-backend/prod/.env")[0] == 2
    assert case.file.read_bytes() == before
    assert not (case.fs / "opt/acx-backend/prod/.env").exists()


def test_missing_file_exits_2(case):
    mat = load_module("materialize")
    case.file.unlink()
    assert case.run(mat)[0] == 2
    assert not case.file.exists()


def test_lease_held_exits_75(case):
    mat = load_module("materialize")
    case.seed_lease('{"transaction":"deploy-1","holder":"ci@x","expires_at":1000600}')
    before, lease = case.file.read_bytes(), case.lease.read_bytes()
    assert case.run(mat)[0] == 75
    assert case.file.read_bytes() == before
    assert case.lease.read_bytes() == lease


def test_expired_lease_taken_and_released(case):
    mat = load_module("materialize")
    case.seed_lease('{"transaction":"deploy-1","holder":"ci@x","expires_at":999000}')
    assert case.run(mat)[0] == 0
    assert not case.lease.exists()


def test_malformed_lease_exits_2(case):
    mat = load_module("materialize")
    case.seed_lease("not json")
    before = case.file.read_bytes()
    assert case.run(mat)[0] == 2
    assert case.file.read_bytes() == before


def test_image_repo_lock_busy_exits_75(case):
    mat = load_module("materialize")
    before = case.file.read_bytes()
    with Path(str(case.file) + ".acx-image-repo.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            assert case.run(mat)[0] == 75
            assert case.file.read_bytes() == before
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def test_unmanaged_key_refused_on_apply(case):
    mat = load_module("materialize")
    before = case.file.read_bytes() + b"EXTRA=1\n"
    case.file.write_bytes(before)
    assert case.run(mat)[0] == 2
    assert case.file.read_bytes() == before


def test_allow_unmanaged_keeps_apply(case):
    mat = load_module("materialize")
    case.file.write_bytes(case.file.read_bytes() + b"EXTRA=1\n")
    assert case.run(mat, allow_unmanaged=("EXTRA",))[0] == 0


def test_check_lists_names_only(case):
    mat = load_module("materialize")
    before = case.file.read_bytes() + b"EXTRA=1\n"
    case.file.write_bytes(before)
    mtime = case.file.stat().st_mtime_ns
    rc, out, _ = case.run(mat, check=True)
    assert rc == 1
    assert out == "unmanaged\tEXTRA\ndiffers\tLOG_LEVEL\n"
    assert case.file.read_bytes() == before
    assert case.file.stat().st_mtime_ns == mtime
    assert not case.lease.exists()


def test_check_reports_mode_for_0644(case):
    mat = load_module("materialize")
    case.file.chmod(0o644)
    rc, out, _ = case.run(mat, check=True)
    assert rc == 1
    assert "mode\t/opt/acx-backend/dev/.env\n" in out


def test_check_clean_after_apply(case):
    mat = load_module("materialize")
    assert case.run(mat)[0] == 0
    rc, out, _ = case.run(mat, check=True)
    assert rc == 0
    assert out == ""


def test_owner_preserved_on_file_and_backup(case, monkeypatch):
    mat = load_module("materialize")
    before = b"\n".join(case.file.read_bytes().split(b"\n")[2:])
    case.file.write_bytes(before)
    owner = case.file.stat()
    calls = []
    real_fstat = os.fstat
    real_stat = os.stat

    def record_fchown(fd, uid, gid, *args, **kwargs):
        calls.append((real_fstat(fd).st_ino, uid, gid))

    def record_chown(path, uid, gid, *args, **kwargs):
        calls.append((real_stat(path, follow_symlinks=False).st_ino, uid, gid))

    monkeypatch.setattr(os, "fchown", record_fchown)
    monkeypatch.setattr(os, "chown", record_chown)
    assert case.run(mat, adopt=True)[0] == 0
    backup = Path(str(case.file) + ".pre-envman")
    assert backup.read_bytes() == before
    assert (case.file.stat().st_ino, owner.st_uid, owner.st_gid) in calls
    assert (backup.stat().st_ino, owner.st_uid, owner.st_gid) in calls


def test_unheaded_without_adopt_exits_2(case):
    mat = load_module("materialize")
    before = b"\n".join(case.file.read_bytes().split(b"\n")[2:])
    case.file.write_bytes(before)
    assert case.run(mat)[0] == 2
    assert case.file.read_bytes() == before
