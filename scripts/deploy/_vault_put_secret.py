#!/usr/bin/env python
"""Store a secret value into acx-vault, reading the value from stdin only.

Companion to scripts/deploy/lib/ocir-auth.sh (OCIRV-1). Used by
`make ocir-token-rotate` to land an OCI auth token in the vault without it ever
reaching argv (ps-visible to every user on the host), a shell history file, or
a temp file on disk. The value is read from stdin, base64-encoded in memory,
and handed to the Vaults API.

Creates the secret on first use; on subsequent runs it adds a new version to
the existing secret. The OCID is stable across versions, so nothing downstream
needs reconfiguring on rotation (vault-instance-principal-runbook.md section 5).

Run with the OCI CLI's bundled interpreter, which already has the SDK:
    printf '%s' "$TOKEN" | "$(head -1 "$(command -v oci)" | sed 's|^#!||')" \\
        scripts/deploy/_vault_put_secret.py --secret-name OCIR_AUTH_TOKEN

Prints only the resulting secret OCID, version number, and value byte length --
never the value.
"""

from __future__ import annotations

import argparse
import base64
import sys

import oci

# acx-vault, root compartment, us-ashburn-1. An OCID is not a secret (ADR-013).
DEFAULT_VAULT_OCID = (
    "ocid1.vault.oc1.iad.ejvffpzlaafc4."
    "abuwcljr3j4chidobdkiqx6igrzb4p3wffl43bjelxzfghkehdpuzle7cjla"
)


def resolve_vault_context(kms_client, vaults_client, vault_id):
    """Return (compartment_id, key_id) for the vault.

    The KMS key is read off a sibling secret rather than hardcoded, so a new
    secret always lands on the same key as the ones ADR-013 already stores. A
    second hardcoded OCID here would be a silent divergence waiting to happen.
    """
    vault = kms_client.get_vault(vault_id).data
    compartment_id = vault.compartment_id
    siblings = vaults_client.list_secrets(
        compartment_id=compartment_id, vault_id=vault_id
    ).data
    if not siblings:
        raise SystemExit(
            f"vault {vault_id} holds no existing secret to read the KMS key from; "
            "pass --key-id explicitly"
        )
    return compartment_id, siblings[0].key_id


def find_secret(vaults_client, compartment_id, vault_id, name):
    for s in vaults_client.list_secrets(
        compartment_id=compartment_id, vault_id=vault_id, name=name
    ).data:
        if s.secret_name == name:
            return s
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--secret-name", required=True)
    ap.add_argument("--vault-id", default=DEFAULT_VAULT_OCID)
    ap.add_argument("--key-id", default=None, help="defaults to a sibling secret's key")
    ap.add_argument("--profile", default="DEFAULT")
    ap.add_argument(
        "--description", default=None, help="only applied when creating the secret"
    )
    args = ap.parse_args()

    if sys.stdin.isatty():
        raise SystemExit("refusing to prompt: pipe the value on stdin")

    # Read raw bytes so a token containing non-UTF8 or a trailing newline the
    # operator did not intend is handled explicitly rather than silently.
    value = sys.stdin.buffer.read()
    # A trailing newline from `read`/`printf` would be stored as part of the
    # token and produce an OCIR rejection that looks like a bad token.
    value = value.rstrip(b"\r\n")
    if not value:
        raise SystemExit("refusing to store an empty value")

    config = oci.config.from_file(profile_name=args.profile)
    vaults = oci.vault.VaultsClient(config)
    kms = oci.key_management.KmsVaultClient(config)

    compartment_id, sibling_key = resolve_vault_context(kms, vaults, args.vault_id)
    key_id = args.key_id or sibling_key

    content = oci.vault.models.Base64SecretContentDetails(
        content_type="BASE64",
        content=base64.b64encode(value).decode("ascii"),
    )

    existing = find_secret(vaults, compartment_id, args.vault_id, args.secret_name)
    if existing is None:
        secret = vaults.create_secret(
            oci.vault.models.CreateSecretDetails(
                compartment_id=compartment_id,
                secret_name=args.secret_name,
                vault_id=args.vault_id,
                key_id=key_id,
                description=args.description or f"{args.secret_name} (OCIRV-1)",
                secret_content=content,
            )
        ).data
        action = "created"
    else:
        secret = vaults.update_secret(
            existing.id,
            oci.vault.models.UpdateSecretDetails(secret_content=content),
        ).data
        action = "new version"

    print(f"{action}: {args.secret_name} ({len(value)} bytes)")
    print(f"  secret_id: {secret.id}")
    print(f"  version:   {getattr(secret, 'current_version_number', 'pending')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
