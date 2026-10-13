"""Offline causal RED: portal config must reach the isolated FIR and AuraFace targets.

Source gap (config/env/manifest.d/30-portal-backend.toml): the seven portal
variables attach only to svc-local and svc-vm. svc-fir (env ``fir``) and
svc-auraface (envs ``dev-auraface``, ``staging-auraface``, ``prod-auraface``)
render no router enablement, Clerk issuer/JWKS/audience/authorized-parties,
or origin settings. The portal tests below are expected RED until the source
declares those values. The store-identity and SFace tests are preservation
guards for facts already declared in source.

Synthetic and no-secret: the resolver returns a placeholder, no DSN, token,
or hostname is minted, and no live deployment, DB, OCI, or email is touched.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import load_module


REPO_ROOT = Path(__file__).resolve().parents[3]

PORTAL_VARS = (
    "RECOGNITION_PORTAL_ENABLED",
    "ACX_CLERK_ISSUER",
    "ACX_CLERK_JWKS_URL",
    "ACX_CLERK_AUDIENCE",
    "ACX_CLERK_AUTHORIZED_PARTIES",
    "APP_PUBLIC_ORIGIN",
    "APP_ALLOWED_ORIGINS",
)

# Generic values pinned by test_portal_backend_vars.py. Preserved here, not edited.
LOCAL_DEV_VALUES = {
    "RECOGNITION_PORTAL_ENABLED": "1",
    "ACX_CLERK_ISSUER": "https://saved-frog-4170.clerk.accounts.dev",
    "ACX_CLERK_JWKS_URL": "https://saved-frog-4170.clerk.accounts.dev/.well-known/jwks.json",
    "ACX_CLERK_AUDIENCE": "altcontext-portal",
    "ACX_CLERK_AUTHORIZED_PARTIES": "http://localhost:5173",
    "APP_PUBLIC_ORIGIN": "http://localhost:5173",
    "APP_ALLOWED_ORIGINS": "http://localhost:5173",
}
PROD_VALUES = {
    "RECOGNITION_PORTAL_ENABLED": "1",
    "ACX_CLERK_ISSUER": "https://clerk.altcontext.com",
    "ACX_CLERK_JWKS_URL": "https://clerk.altcontext.com/.well-known/jwks.json",
    "ACX_CLERK_AUDIENCE": "altcontext-portal",
    "ACX_CLERK_AUTHORIZED_PARTIES": "https://app.altcontext.com",
    "APP_PUBLIC_ORIGIN": "https://app.altcontext.com",
    "APP_ALLOWED_ORIGINS": "https://app.altcontext.com",
}

LOCAL_ORIGIN = "http://localhost:5173"
FIR_TARGET = "svc-fir"
FIR_ENV = "fir"
AURA_TARGET = "svc-auraface"
AURA_DEV_ENV = "dev-auraface"
AURA_GATED_ENVS = ("staging-auraface", "prod-auraface")
AURA_ENVS = (AURA_DEV_ENV, *AURA_GATED_ENVS)

# Per-stack store identity: model, DB, role, network, PGDATA, compose project.
STORE_IDENTITY_NAMES = (
    "ACX_MODELS_PATH",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "ACX_NETWORK_NAME",
    "ACX_PGDATA_PATH",
    "COMPOSE_PROJECT_NAME",
)


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


def _no_secret_resolve(name: str, reference: str) -> str:
    """Synthetic placeholder. No secret, DSN, or token is read or minted."""
    return "test-secret-value"


def _render(target: str, env: str) -> dict[str, str]:
    manifest, _ = _portal_manifest()
    rendered = load_module("render_env").render_target(
        manifest,
        target,
        env,
        resolve=_no_secret_resolve,
        missing_host_keys=set(),
    )
    return _assignments(rendered)


def test_portal_vars_attach_to_isolated_fir_and_aura_targets():
    manifest, vars_by_name = _portal_manifest()

    for name in PORTAL_VARS:
        var = vars_by_name[name]
        assert {"svc-local", "svc-vm", FIR_TARGET, AURA_TARGET} <= set(var.targets), (
            f"{name} targets={sorted(var.targets)}: isolated FIR/AuraFace target missing"
        )
        assert var.cls == "config"
        assert var.section == "API security"

    for target in (FIR_TARGET, AURA_TARGET):
        assert "API security" in manifest.targets[target].sections


def test_fir_env_renders_portal_router_with_authorized_dev_instance():
    rendered = _render(FIR_TARGET, FIR_ENV)

    wrong_or_missing = {
        name: rendered.get(name)
        for name in PORTAL_VARS
        if rendered.get(name) != LOCAL_DEV_VALUES[name]
    }
    assert not wrong_or_missing, f"svc-fir/fir portal config not rendered: {sorted(wrong_or_missing)}"
    assert rendered["ACX_CLERK_JWKS_URL"] == rendered["ACX_CLERK_ISSUER"] + "/.well-known/jwks.json"


def test_fir_origin_contract_uses_existing_vite_origin_without_minting_hosts():
    rendered = _render(FIR_TARGET, FIR_ENV)

    assert rendered.get("APP_PUBLIC_ORIGIN") == LOCAL_ORIGIN
    assert rendered.get("ACX_CLERK_AUTHORIZED_PARTIES", "").split(",") == [LOCAL_ORIGIN]
    assert rendered.get("APP_ALLOWED_ORIGINS", "").split(",") == [LOCAL_ORIGIN]
    for name in PORTAL_VARS:
        assert "altcontext.com" not in rendered.get(name, ""), f"{name} mints a hostname"


def test_dev_auraface_renders_same_authorized_dev_instance_and_local_origin():
    rendered = _render(AURA_TARGET, AURA_DEV_ENV)

    assert {name: rendered.get(name) for name in PORTAL_VARS} == LOCAL_DEV_VALUES


@pytest.mark.parametrize("env", AURA_GATED_ENVS)
def test_staging_and_prod_auraface_fail_closed_until_owner_issuer_origin_approved(env):
    _, vars_by_name = _portal_manifest()
    rendered = _render(AURA_TARGET, env)

    assert rendered.get("RECOGNITION_PORTAL_ENABLED") == "0", f"{env}: portal must be explicitly disabled"
    for name in PORTAL_VARS[1:]:
        assert rendered.get(name, "") == "", f"{env}: {name} must stay unassigned until approved"
    for name in PORTAL_VARS:
        generic = (LOCAL_DEV_VALUES[name], PROD_VALUES[name])
        assert rendered.get(name) not in generic, f"{env}: {name} borrows a generic dev/prod value"
        assert vars_by_name[name].values.get(env) not in generic, (
            f"{name} manifest value for {env} borrows a generic dev/prod value"
        )


def test_generic_local_dev_prod_portal_values_stay_byte_equal():
    _, vars_by_name = _portal_manifest()
    local = _render("svc-local", "local")
    dev = _render("svc-vm", "dev")
    prod = _render("svc-vm", "prod")

    for name in PORTAL_VARS:
        assert local.get(name) == LOCAL_DEV_VALUES[name], f"local {name} changed"
        assert dev.get(name) == LOCAL_DEV_VALUES[name], f"dev {name} changed"
        assert prod.get(name) == PROD_VALUES[name], f"prod {name} changed"
        assert vars_by_name[name].values.get("local") == LOCAL_DEV_VALUES[name]
        assert vars_by_name[name].values.get("dev") == LOCAL_DEV_VALUES[name]
        assert vars_by_name[name].values.get("prod") == PROD_VALUES[name]


def test_three_aura_labels_keep_separate_store_identity_at_width_512():
    rendered = {env: _render(AURA_TARGET, env) for env in AURA_ENVS}

    for env, values in rendered.items():
        assert values.get("PGVECTOR_DIM") == "512", f"{env}: AuraFace store width must be 512"
        assert values.get("RECOGNITION_FACE_PIPELINE_PROFILE") == "auraface", env

    for name in STORE_IDENTITY_NAMES:
        seen = [rendered[env].get(name) for env in AURA_ENVS]
        assert None not in seen and len(set(seen)) == len(AURA_ENVS), (
            f"{name} must be distinct across the three Aura labels"
        )


def test_aura_store_identity_is_not_borrowed_from_generic_dev_or_prod():
    generic = {env: _render("svc-vm", env) for env in ("dev", "prod")}
    aura = {env: _render(AURA_TARGET, env) for env in AURA_ENVS}

    for name in STORE_IDENTITY_NAMES:
        generic_values = {generic[env].get(name) for env in generic}
        for env in AURA_ENVS:
            assert aura[env].get(name) not in generic_values, (
                f"{env} borrows generic dev/prod {name}"
            )


def test_sface_128_comparator_is_unchanged_and_not_retargeted():
    fir = _render(FIR_TARGET, FIR_ENV)

    assert fir.get("PGVECTOR_DIM") == "128"
    assert fir.get("RECOGNITION_FACE_PIPELINE_PROFILE") == "face_pipeline"
    assert fir.get("RECOGNITION_FACE_PIPELINE_MODELS_DIR") == "/data/cache/face_pipeline"
    assert fir.get("COMPOSE_PROJECT_NAME") == "acx-dev-fir"

    aura = {env: _render(AURA_TARGET, env) for env in AURA_ENVS}
    for name in STORE_IDENTITY_NAMES:
        for env in AURA_ENVS:
            assert fir.get(name) != aura[env].get(name), (
                f"SFace comparator {name} shares a value with {env}"
            )
