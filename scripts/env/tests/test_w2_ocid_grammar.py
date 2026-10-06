from __future__ import annotations

import importlib
import json
import subprocess

import pytest


ACCEPTED_OCIDS = (
    "ocid1.vaultsecret.oc1.phx.ABCDEFGHIJKLMNOPQRST",
    "ocid1.vaultsecret.oc1.phx.FAKE_UPPERCASE_SUFFIX_000000000001",
    "ocid1.vaultsecret.oc10.eu-fr_1.FAKE_Mixed_Underscore-Hyphen.Dot_000001",
    "ocid1.vaultsecret.oc42..FAKE_Global_Identifier.With-Dots_000001",
)
REJECTED_OCIDS = (
    "",
    "ocid1.vaultsecret.oc1.phx.short",
    "ocid1.vaultsecret.oc1.phx.abcdefghijklmnopqrs",
    "ocid1.vaultsecret.oc1.phx.abcdefghijklmnopqrst/extra",
    "ocid1.vaultsecret.oc1.phx.abcdefghijklmnopqrst with-space",
    'ocid1.vaultsecret.oc1.phx.abcdefghijklmnopqrst"quoted',
    "ocid1.vaultsecret.oc1.phx.abcdefghijklmnopqrs\x01t",
    "ocid1.vault.oc1.phx.FAKE_IDENTIFIER_000000000001",
    "ocid1.vaultsecret.oc.phx.FAKE_IDENTIFIER_000000000001",
)


def _manifest_root(write_manifest, identifier: str):
    return write_manifest(
        """
        version = 1
        [targets.t]
        audience = "backend"
        envs = ["dev"]
        sections = ["S"]
        remote_paths = { dev = "/opt/acx-backend/dev/.env" }
        lease_env = { dev = "dev" }
        """,
        **{
            "10-secrets": f"""
                version = 1
                [[var]]
                name = "API_TOKEN"
                class = "secret"
                targets = ["t"]
                section = "S"
                example = "example-value"
                secret = {{ dev = {json.dumps(f"oci:{identifier}")} }}
            """
        },
    )


@pytest.mark.parametrize("identifier", ACCEPTED_OCIDS)
def test_manifest_and_resolver_accept_the_complete_vault_ocid_grammar(write_manifest, identifier):
    manifest = importlib.import_module("env.manifest")
    secret_refs = importlib.import_module("env.secret_refs")
    calls = []

    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=(
                '{"data":{"secret-bundle-content":{"content-type":"BASE64",'
                '"content":"Zg=="}}}'
            ),
            stderr="",
        )

    loaded = manifest.load_manifest(_manifest_root(write_manifest, identifier))
    assert loaded.vars[0].secret == {"dev": f"oci:{identifier}"}

    assert secret_refs.resolve_secret("API_TOKEN", f"oci:{identifier}", runner=runner) == "f"
    assert len(calls) == 1
    assert calls[0][0][-1] == identifier


@pytest.mark.parametrize("identifier", REJECTED_OCIDS)
def test_manifest_and_resolver_reject_malformed_ids_before_runner(write_manifest, identifier):
    manifest = importlib.import_module("env.manifest")
    secret_refs = importlib.import_module("env.secret_refs")
    calls = []

    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout="{}", stderr="")

    with pytest.raises(manifest.ManifestError, match="valid vault secret OCID"):
        manifest.load_manifest(_manifest_root(write_manifest, identifier))
    with pytest.raises(secret_refs.SecretUnavailable):
        secret_refs.resolve_secret("API_TOKEN", f"oci:{identifier}", runner=runner)
    assert calls == []
