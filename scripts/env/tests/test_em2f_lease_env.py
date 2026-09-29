from __future__ import annotations

import io
import json
from pathlib import Path

from conftest import load_module


INTO = "/opt/acx-backend/dev/.env"


def _run_materializer(tmp_path, write_manifest, lease_env, backup_root):
    targets = f'''\
version = 1
[targets.t]
audience = "backend"
envs = ["dev"]
sections = ["S"]
remote_paths = {{dev = {json.dumps(INTO)}}}
lease_env = {{dev = {json.dumps(lease_env)}}}
'''
    fragment = '''\
version = 1
[[var]]
name = "LOG_LEVEL"
class = "config"
targets = ["t"]
section = "S"
example = "info"
values = {dev = "info"}
'''
    root = write_manifest(targets, **{"10-materialize": fragment})
    mat = load_module("materialize")
    header = load_module("render_env").HEADER_LINE
    fs_root = tmp_path / "fs"
    env_file = fs_root / INTO.lstrip("/")
    env_file.parent.mkdir(parents=True)
    env_file.write_text(
        f"{header}\n# materialized target=t env=dev digest=x\nLOG_LEVEL=debug\n",
        encoding="utf-8",
    )
    before = env_file.read_bytes()
    out, err = io.StringIO(), io.StringIO()

    rc = mat.run(
        root,
        env="dev",
        target="t",
        into=INTO,
        fs_root=fs_root,
        backup_root=backup_root,
        lock_timeout=0.2,
        now=lambda: 1_000_000.0,
        out=out,
        err=err,
    )
    return rc, err.getvalue(), env_file, before


def test_apply_refuses_lease_env_that_escapes_backup_root(tmp_path, write_manifest):
    lease_env = "../../../../../../tmp/marker"
    backup_root = tmp_path / "a" / "b" / "c" / "d" / "backups"
    marker = tmp_path / "a" / "b" / "tmp" / "marker.lease"
    marker.parent.mkdir(parents=True)
    marker_data = b'{"transaction":"deploy-1","holder":"ci@x","expires_at":999000}'
    marker.write_bytes(marker_data)

    rc, err, env_file, before = _run_materializer(tmp_path, write_manifest, lease_env, backup_root)

    assert rc == 2
    assert "lease_env" in err
    assert marker.read_bytes() == marker_data
    assert env_file.read_bytes() == before


def test_apply_refuses_lease_path_resolved_outside_backup_root(tmp_path, write_manifest):
    backup_root = tmp_path / "backups"
    outside = tmp_path / "outside"
    backup_root.mkdir()
    outside.mkdir()
    (backup_root / "locks").symlink_to(outside, target_is_directory=True)
    marker = outside / "deploy-dev.lease"
    marker_data = b'{"transaction":"deploy-1","holder":"ci@x","expires_at":999000}'
    marker.write_bytes(marker_data)

    rc, err, env_file, before = _run_materializer(tmp_path, write_manifest, "dev", backup_root)

    assert rc == 2
    assert "lease_env" in err
    assert marker.read_bytes() == marker_data
    assert env_file.read_bytes() == before
