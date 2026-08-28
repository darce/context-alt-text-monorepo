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
import hashlib
import sys
import time

# acx-vault, root compartment, us-ashburn-1. An OCID is not a secret (ADR-013).
DEFAULT_VAULT_OCID = (
    "ocid1.vault.oc1.iad.ejvffpzlaafc4."
    "abuwcljr3j4chidobdkiqx6igrzb4p3wffl43bjelxzfghkehdpuzle7cjla"
)


class SecretNotReadable(RuntimeError):
    """The stored value never became readable through the consumer's API."""


def wait_until_readable(
    read_bundle,
    secret_name,
    expected_digest,
    timeout=120.0,
    sleep=None,
    monotonic=None,
):
    """Block until `secret_name` reads back as the value we just wrote.

    Creating a secret is asynchronous: the OCID exists immediately, but
    `get_secret_bundle_by_name` 404s until the first version reaches ACTIVE.
    Without this gate a verify that runs a second after the write reports
    `secret_missing` and tells the operator to store a token they just stored.
    Observed live on 2026-08-28: the laptop leg failed on the race while the VM
    leg, running a few seconds later, succeeded against the same secret.

    The gate polls the *consumer's* read path rather than the secret's
    lifecycle_state, so a green result means the deploy preflight will succeed
    -- not merely that the control plane finished bookkeeping.

    `read_bundle` is a zero-argument callable returning the decoded bytes, or
    raising on failure. Injected so this stays testable without the OCI SDK.
    """
    # Resolved here rather than as default arguments: a default binds `time.sleep`
    # once at import, so a caller (or a test) that patches `time.sleep` later has
    # no effect on it.
    sleep = sleep or time.sleep
    monotonic = monotonic or time.monotonic
    deadline = monotonic() + timeout
    delay = 1.0
    last = "no attempt made"
    while True:
        try:
            got = read_bundle()
        except Exception as exc:  # noqa: BLE001 -- any read failure is retryable here
            last = f"{type(exc).__name__}: {exc}"
        else:
            if hashlib.sha256(got).hexdigest() == expected_digest:
                return True
            # A stale prior version, not a transient error: the rotation has
            # not propagated yet. Comparing digests rather than lengths means a
            # replacement token of the same length is still correctly rejected.
            last = f"read back {len(got)} bytes that do not match what was written"
        if monotonic() >= deadline:
            raise SecretNotReadable(
                f"{secret_name} was written but did not become readable within "
                f"{timeout:.0f}s (last: {last})"
            )
        sleep(delay)
        delay = min(delay * 1.5, 5.0)


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
    ap.add_argument(
        "--readable-timeout", type=float, default=120.0,
        help="seconds to wait for the written value to read back (0 to skip)",
    )
    args = ap.parse_args()

    import oci  # noqa: PLC0415 -- lazy so the readiness gate stays unit-testable

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

    # Do not return until the value is readable through the same call the deploy
    # preflight makes. Anything less hands the caller a success it cannot use.
    secrets_client = oci.secrets.SecretsClient(config)

    def read_bundle():
        bundle = secrets_client.get_secret_bundle_by_name(
            secret_name=args.secret_name, vault_id=args.vault_id
        ).data
        return base64.b64decode(bundle.secret_bundle_content.content)

    print(f"  waiting for {args.secret_name} to become readable ...", flush=True)
    wait_until_readable(
        read_bundle, args.secret_name, hashlib.sha256(value).hexdigest(),
        timeout=args.readable_timeout,
    )
    print("  readable: value matches what was written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
