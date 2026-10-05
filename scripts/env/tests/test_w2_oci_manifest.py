from __future__ import annotations

import importlib

import pytest


SECRET_OCID = "ocid1.vaultsecret.oc1.phx.aaaaaaaaaaaaaaaaaaaaaaaaaa"


def _manifest_root(
    write_manifest, secret_ref: str, *, audience: str = "backend", derive_from_secret: bool = False,
    local_path: str | None = None, remote_path: bool = True,
):
    secret_fragment = f'''
                version = 1
                [[var]]
                name = "API_TOKEN"
                class = "secret"
                targets = ["t"]
                section = "S"
                example = "example-value"
                secret = {{ dev = "{secret_ref}" }}
            '''
    if derive_from_secret:
        secret_fragment += '''
                [[var]]
                name = "DATABASE_URL"
                class = "secret"
                targets = ["t"]
                section = "S"
                example = "example-value"
                derive = "postgresql://u:${API_TOKEN}@db/app"
            '''
    target_fields = [
        f'audience = "{audience}"',
        'envs = ["dev"]',
        'sections = ["S"]',
    ]
    if local_path is not None:
        target_fields.append(f'path = "{local_path}"')
    if remote_path:
        target_fields.extend([
            'remote_paths = { dev = "/opt/acx-backend/dev/.env" }',
            'lease_env = { dev = "dev" }',
        ])
    target_fields_toml = "\n        ".join(target_fields)
    return write_manifest(
        f'''
        version = 1
        [targets.t]
        {target_fields_toml}
        ''',
        **{
            "10-secrets": secret_fragment
        },
    )


def test_manifest_loader_accepts_valid_oci_secret_ref(write_manifest):
    manifest_module = importlib.import_module("env.manifest")

    loaded = manifest_module.load_manifest(_manifest_root(write_manifest, f"oci:{SECRET_OCID}"))

    assert loaded.vars[0].secret == {"dev": f"oci:{SECRET_OCID}"}


def test_manifest_loader_rejects_local_only_oci_secret_ref(write_manifest):
    manifest_module = importlib.import_module("env.manifest")

    with pytest.raises(manifest_module.ManifestError, match="oci secret refs require a remote path"):
        manifest_module.load_manifest(
            _manifest_root(write_manifest, f"oci:{SECRET_OCID}", local_path="out.env", remote_path=False)
        )


def test_manifest_loader_accepts_hybrid_target_with_oci_secret_ref(write_manifest):
    manifest_module = importlib.import_module("env.manifest")

    loaded = manifest_module.load_manifest(
        _manifest_root(write_manifest, f"oci:{SECRET_OCID}", local_path="out.env")
    )

    assert loaded.targets["t"].path == "out.env"
    assert loaded.targets["t"].remote_paths == {"dev": "/opt/acx-backend/dev/.env"}


def test_manifest_loader_rejects_test_audience_oci_secret_ref(write_manifest):
    manifest_module = importlib.import_module("env.manifest")

    with pytest.raises(manifest_module.ManifestError, match="remote secret refs are forbidden"):
        manifest_module.load_manifest(_manifest_root(write_manifest, f"oci:{SECRET_OCID}", audience="test"))


def test_manifest_loader_rejects_derive_from_oci_remote_secret(write_manifest):
    manifest_module = importlib.import_module("env.manifest")

    with pytest.raises(
        manifest_module.ManifestError,
        match="derive references remote secret var API_TOKEN",
    ):
        manifest_module.load_manifest(
            _manifest_root(write_manifest, f"oci:{SECRET_OCID}", derive_from_secret=True)
        )


@pytest.mark.parametrize(
    "identifier",
    [
        "",
        "ocid1.vaultsecret.oc1.phx.too-short",
        "ocid1.vaultsecret.oc1..aaaaaaaaaaaaaaaaaaaaaaaaaa",
        "ocid1.vaultsecret.oc1.phx.aaaaaaaaaaaaaaaaaaaaaaaaaa/extra",
    ],
)
def test_manifest_loader_rejects_malformed_oci_identifier(write_manifest, identifier):
    manifest_module = importlib.import_module("env.manifest")

    with pytest.raises(manifest_module.ManifestError, match="valid vault secret OCID"):
        manifest_module.load_manifest(_manifest_root(write_manifest, f"oci:{identifier}"))
