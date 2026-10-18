from __future__ import annotations

import pytest

from conftest import load_module


def _targets(lease_env: str) -> str:
    return f'''\
version = 1
[targets.t]
audience = "backend"
envs = ["dev"]
sections = ["Runtime"]
remote_paths = {{dev = "/opt/acx-backend/dev/.env"}}
lease_env = {{dev = {lease_env}}}
'''


def test_load_manifest_rejects_invalid_lease_env_label(write_manifest):
    manifest = load_module("manifest")
    root = write_manifest(_targets('"bad label"'))

    with pytest.raises(ValueError, match="lease_env"):
        manifest.load_manifest(root)


def test_load_manifest_accepts_valid_lease_env_label(write_manifest):
    manifest = load_module("manifest")
    root = write_manifest(_targets('"deploy-dev_1.v2"'))

    loaded = manifest.load_manifest(root)

    assert loaded.targets["t"].lease_env == {"dev": "deploy-dev_1.v2"}
