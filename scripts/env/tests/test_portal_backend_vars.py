from __future__ import annotations

from pathlib import Path

from conftest import load_module


REPO_ROOT = Path(__file__).resolve().parents[3]
PORTAL_CONSUMERS = {
    "RECOGNITION_PORTAL_ENABLED": "apps/prototype-description-service/api/main.py:create_app",
    "ACX_CLERK_ISSUER": "apps/prototype-description-service/recognition/interface_adapters/http/deps/portal_composition.py:_portal_auth_settings",
    "ACX_CLERK_JWKS_URL": "apps/prototype-description-service/recognition/interface_adapters/http/deps/portal_composition.py:_portal_auth_settings",
    "ACX_CLERK_AUDIENCE": "apps/prototype-description-service/recognition/interface_adapters/http/deps/portal_composition.py:_portal_auth_settings",
    "ACX_CLERK_AUTHORIZED_PARTIES": "apps/prototype-description-service/recognition/interface_adapters/http/deps/portal_composition.py:_portal_auth_settings",
    "APP_PUBLIC_ORIGIN": "apps/prototype-description-service/recognition/interface_adapters/http/deps/portal_composition.py:_app_public_origin",
    "APP_ALLOWED_ORIGINS": "apps/prototype-description-service/recognition/interface_adapters/http/deps/portal_composition.py:_app_allowed_origins",
}


def _portal_manifest():
    manifest = load_module("manifest").load_manifest(REPO_ROOT / "config/env")
    return manifest, {var.name: var for var in manifest.vars}


def _assignments(rendered: str) -> dict[str, str]:
    assignments = {}
    for line in rendered.splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        assignments[name] = value.strip().strip("\"'")
    return assignments


def _render_target(render_target, manifest, target: str, env: str) -> str:
    return render_target(
        manifest,
        target,
        env,
        resolve=lambda name, reference: "test-secret-value",
        missing_host_keys=set(),
    )


def test_portal_backend_vars_are_optional_config_for_both_service_targets():
    manifest, vars_by_name = _portal_manifest()

    assert set(PORTAL_CONSUMERS) <= vars_by_name.keys()
    assert "CLERK_SECRET_KEY" not in vars_by_name
    assert not any(name.startswith("POLAR_") for name in vars_by_name)

    for name, consumer in PORTAL_CONSUMERS.items():
        var = vars_by_name[name]
        assert var.cls == "config"
        assert set(var.targets) == {"svc-local", "svc-vm"}
        assert var.section == "API security"
        assert var.required is False
        assert consumer in var.doc
        assert "staging" not in var.values

    assert set(manifest.targets["svc-local"].sections) >= {"API security"}
    assert set(manifest.targets["svc-vm"].sections) >= {"API security"}


def test_portal_backend_values_render_for_local_dev_and_prod():
    manifest, vars_by_name = _portal_manifest()
    render_target = load_module("render_env").render_target

    local = _assignments(_render_target(render_target, manifest, "svc-local", "local"))
    dev = _assignments(_render_target(render_target, manifest, "svc-local", "dev"))
    assert local["RECOGNITION_PORTAL_ENABLED"] == "1"
    assert local["ACX_CLERK_ISSUER"] == "https://saved-frog-4170.clerk.accounts.dev"
    assert local["ACX_CLERK_JWKS_URL"] == "https://saved-frog-4170.clerk.accounts.dev/.well-known/jwks.json"
    assert local["ACX_CLERK_AUDIENCE"] == "altcontext-portal"
    assert local["ACX_CLERK_AUTHORIZED_PARTIES"] == "http://localhost:5173"
    assert local["APP_PUBLIC_ORIGIN"] == "http://localhost:5173"
    assert local["APP_ALLOWED_ORIGINS"] == "http://localhost:5173"

    expected_dev = {
        "RECOGNITION_PORTAL_ENABLED": "1",
        "ACX_CLERK_ISSUER": "https://saved-frog-4170.clerk.accounts.dev",
        "ACX_CLERK_JWKS_URL": "https://saved-frog-4170.clerk.accounts.dev/.well-known/jwks.json",
        "ACX_CLERK_AUDIENCE": "altcontext-portal",
        "ACX_CLERK_AUTHORIZED_PARTIES": "http://localhost:5173",
        "APP_PUBLIC_ORIGIN": "http://localhost:5173",
        "APP_ALLOWED_ORIGINS": "http://localhost:5173",
    }
    assert dev["ACX_CLERK_ISSUER"] == local["ACX_CLERK_ISSUER"]
    assert dev["ACX_CLERK_JWKS_URL"] == dev["ACX_CLERK_ISSUER"] + "/.well-known/jwks.json"
    assert dev["ACX_CLERK_AUTHORIZED_PARTIES"].split(",") == ["http://localhost:5173"]
    assert dev["APP_PUBLIC_ORIGIN"].split(",") == ["http://localhost:5173"]
    assert dev["APP_ALLOWED_ORIGINS"].split(",") == ["http://localhost:5173"]
    assert {name: vars_by_name[name].values.get("dev") for name in PORTAL_CONSUMERS} == expected_dev
    assert {name: dev[name] for name in PORTAL_CONSUMERS} == expected_dev

    prod = {name: vars_by_name[name].values.get("prod") for name in PORTAL_CONSUMERS}
    assert prod == {
        "RECOGNITION_PORTAL_ENABLED": None,
        "ACX_CLERK_ISSUER": "https://clerk.altcontext.com",
        "ACX_CLERK_JWKS_URL": "https://clerk.altcontext.com/.well-known/jwks.json",
        "ACX_CLERK_AUDIENCE": "altcontext-portal",
        "ACX_CLERK_AUTHORIZED_PARTIES": "https://app.altcontext.com",
        "APP_PUBLIC_ORIGIN": "https://app.altcontext.com",
        "APP_ALLOWED_ORIGINS": "https://app.altcontext.com",
    }
    for name in (
        "ACX_CLERK_ISSUER",
        "ACX_CLERK_JWKS_URL",
        "ACX_CLERK_AUTHORIZED_PARTIES",
    ):
        assert prod[name].startswith("https://")

    assert all("staging" not in vars_by_name[name].values for name in PORTAL_CONSUMERS)
    assert vars_by_name["RECOGNITION_PORTAL_ENABLED"].values == {"local": "1", "dev": "1"}


def test_portal_backend_dev_svc_vm_renders_expected_values():
    manifest, _ = _portal_manifest()
    render_target = load_module("render_env").render_target
    rendered = _render_target(render_target, manifest, "svc-vm", "dev")
    expected_lines = {
        "RECOGNITION_PORTAL_ENABLED=1",
        "ACX_CLERK_ISSUER=https://saved-frog-4170.clerk.accounts.dev",
        "ACX_CLERK_JWKS_URL=https://saved-frog-4170.clerk.accounts.dev/.well-known/jwks.json",
        "ACX_CLERK_AUDIENCE=altcontext-portal",
        "ACX_CLERK_AUTHORIZED_PARTIES=http://localhost:5173",
        "APP_PUBLIC_ORIGIN=http://localhost:5173",
        "APP_ALLOWED_ORIGINS=http://localhost:5173",
    }
    assert expected_lines <= set(rendered.splitlines())
