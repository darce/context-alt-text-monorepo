from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from conftest import load_module


REPO = Path(__file__).resolve().parents[3]


def _repo_env_root() -> Path:
    return REPO / "config/env"


def _copy_env_root(tmp_path: Path) -> Path:
    root = tmp_path / "config/env"
    shutil.copytree(_repo_env_root(), root)
    return root


def _append_fragment(root: Path, name: str, fragment: str) -> None:
    (root / "manifest.d" / name).write_text(fragment, encoding="utf-8")


def test_app_portal_targets_are_public_builds_and_local_key_renders():
    manifest_module = load_module("manifest")
    render = load_module("render_env")
    manifest = manifest_module.load_manifest(_repo_env_root())

    local = manifest.targets["app-portal-local"]
    build = manifest.targets["app-portal-build"]
    assert local.audience == build.audience == "public_build"
    assert (local.envs, local.path, local.example) == (
        ("local",), "apps/app-portal/.env.local", None
    )
    assert (build.envs, build.path, build.example) == (
        ("prod",),
        "apps/app-portal/.env.production.local",
        "apps/app-portal/.env.example",
    )

    rendered = render.render_target(manifest, "app-portal-local", "local")
    assert "VITE_CLERK_PUBLISHABLE_KEY=pk_test_" in rendered


def test_app_portal_prod_build_renders_live_publishable_key():
    manifest_module = load_module("manifest")
    render = load_module("render_env")
    manifest = manifest_module.load_manifest(_repo_env_root())
    rendered = render.render_target(manifest, "app-portal-build", "prod")

    assert "VITE_CLERK_PUBLISHABLE_KEY=pk_live_" in rendered
    assert "VITE_CLERK_FAPI=https://clerk.altcontext.com" in rendered
    assert "pk_test_" not in rendered


def test_app_portal_prod_build_requires_publishable_key(tmp_path: Path):
    manifest_module = load_module("manifest")
    render = load_module("render_env")
    root = _copy_env_root(tmp_path)
    app_portal_fragment = root / "manifest.d/60-app-portal.toml"
    text = app_portal_fragment.read_text(encoding="utf-8")
    configured_value = (
        'values = { local = "pk_test_c2F2ZWQtZnJvZy00MTcwLmNsZXJrLmFjY291bnRzLmRldiQ", '
        'prod = "pk_live_Y2xlcmsuYWx0Y29udGV4dC5jb20k" }'
    )
    assert text.count(configured_value) == 1
    app_portal_fragment.write_text(
        text.replace(
            configured_value,
            'values = { local = "pk_test_c2F2ZWQtZnJvZy00MTcwLmNsZXJrLmFjY291bnRzLmRldiQ" }',
            1,
        ),
        encoding="utf-8",
    )
    manifest = manifest_module.load_manifest(root)

    with pytest.raises(manifest_module.ManifestError, match="VITE_CLERK_PUBLISHABLE_KEY: missing value for env prod"):
        render.render_target(manifest, "app-portal-build", "prod")


def test_app_portal_public_build_rejects_secret_literal(tmp_path: Path):
    manifest_module = load_module("manifest")
    root = _copy_env_root(tmp_path)
    _append_fragment(
        root,
        "99-test.toml",
        '''
        version = 1

        [[var]]
        name = "VITE_FAKE_VALUE"
        class = "public"
        targets = ["app-portal-local"]
        section = "Portal public build"
        example = "safe"
        values = { local = "sk_test_fake-secret" }
        ''',
    )

    with pytest.raises(manifest_module.ManifestError, match="literal secret material is not allowed"):
        manifest_module.load_manifest(root)


def test_app_portal_public_build_rejects_secret_class(tmp_path: Path):
    manifest_module = load_module("manifest")
    root = _copy_env_root(tmp_path)
    _append_fragment(
        root,
        "99-test.toml",
        '''
        version = 1

        [[var]]
        name = "PORTAL_PRIVATE_VALUE"
        class = "secret"
        targets = ["app-portal-local"]
        section = "Portal public build"
        example = "safe"
        secret = { local = "env:PORTAL_PRIVATE_VALUE" }
        ''',
    )

    with pytest.raises(manifest_module.ManifestError, match="secret vars cannot target public builds"):
        manifest_module.load_manifest(root)
