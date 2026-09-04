#!/usr/bin/env python
"""Store a secret value into acx-vault, reading the value from stdin only.

Companion to scripts/deploy/lib/ocir-auth.sh (OCIRV-1). Used by
`make ocir-token-rotate` to land an OCI auth token in the vault without it ever
reaching argv (ps-visible to every user on the host), a shell history file, or
a temp file on disk. The value is read from stdin, base64-encoded in memory,
and handed to the Vaults API.

Creates the secret on first use; on subsequent runs it adds a version only when
the active value differs. An identical recovery rerun is a no-op. The OCID is
stable across versions, so nothing downstream needs reconfiguring on rotation
(vault-instance-principal-runbook.md section 5).

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
import queue
import random
import sys
import threading
import time

# acx-vault, root compartment, us-ashburn-1. An OCID is not a secret (ADR-013).
DEFAULT_VAULT_OCID = "ocid1.vault.oc1.iad.ejvffpzlaafc4.abuwcljr3j4chidobdkiqx6igrzb4p3wffl43bjelxzfghkehdpuzle7cjla"


class SecretNotReadableError(RuntimeError):
    """The stored value never became readable through the consumer's API."""


class OperationDeadline:
    """One wall-clock budget shared by discovery, mutation, and read-back."""

    def __init__(self, timeout, monotonic=None):
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.timeout = timeout
        self.monotonic = monotonic or time.monotonic
        self.deadline = self.monotonic() + timeout

    def remaining(self, label):
        remaining = self.deadline - self.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"Vault operation exceeded the {self.timeout:.0f}s deadline during {label}")
        return remaining

    def call(self, label, operation):
        remaining = self.remaining(label)
        try:
            return _call_with_deadline(operation, remaining, label)
        except TimeoutError as exc:
            raise TimeoutError(
                f"Vault operation exceeded the {self.timeout:.0f}s deadline during {label}; "
                "if this was a mutation, acceptance is indeterminate and the same command is safe to rerun"
            ) from exc


def _is_retryable_read_error(exc):
    """Return whether an OCI consumer read can usefully be attempted again."""
    status = getattr(exc, "status", None)
    code = getattr(exc, "code", None)
    if status == 404 and code == "NotAuthorizedOrNotFound":
        # A newly-created version temporarily has exactly this response while
        # it propagates to the Secrets (data-plane) API.
        return True
    if isinstance(status, int) and 500 <= status < 600:
        return True

    # OCI's transport exceptions come from requests/urllib3. Avoid importing
    # either package here so the module remains usable by its SDK-free tests.
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return True
    exception_type = type(exc)
    return exception_type.__module__.split(".", 1)[0] in {"requests", "urllib3"}


def _call_with_deadline(operation, remaining, label="request"):
    """Run one SDK call without allowing it to outlive the outer deadline."""
    outcome = queue.Queue(maxsize=1)

    def run():
        try:
            outcome.put((True, operation()))
        except BaseException as exc:  # transferred to the calling thread below
            outcome.put((False, exc))

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(remaining)
    if worker.is_alive():
        raise TimeoutError(f"{label} exceeded the remaining deadline")
    succeeded, value = outcome.get_nowait()
    if succeeded:
        return value
    raise value


def _read_with_deadline(read_bundle, remaining):
    try:
        return _call_with_deadline(read_bundle, remaining, "Secrets API read")
    except TimeoutError as exc:
        raise SecretNotReadableError(str(exc)) from exc


def wait_until_readable(
    read_bundle,
    secret_name,
    expected_digest,
    timeout=120.0,
    sleep=None,
    monotonic=None,
    prepare_attempt=None,
    random_uniform=None,
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
    raising on failure. `prepare_attempt`, when provided, receives the seconds
    remaining so the underlying client's own request timeout can be tightened
    before each call. Both are injected so this stays testable without the OCI
    SDK.
    """
    # Resolved here rather than as default arguments: a default binds `time.sleep`
    # once at import, so a caller (or a test) that patches `time.sleep` later has
    # no effect on it.
    sleep = sleep or time.sleep
    monotonic = monotonic or time.monotonic
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    random_uniform = random_uniform or random.uniform
    deadline = monotonic() + timeout
    delay = 1.0
    last = "no attempt made"
    while True:
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise SecretNotReadableError(
                f"{secret_name} was written but did not become readable within {timeout:.0f}s (last: {last})"
            )
        if prepare_attempt is not None:
            prepare_attempt(remaining)
        try:
            got = _read_with_deadline(read_bundle, remaining)
        except SecretNotReadableError as exc:
            raise SecretNotReadableError(
                f"{secret_name} was written but did not become readable within {timeout:.0f}s (last: {exc})"
            ) from exc
        except Exception as exc:
            if not _is_retryable_read_error(exc):
                raise
            last = f"{type(exc).__name__}: {exc}"
        else:
            if hashlib.sha256(got).hexdigest() == expected_digest:
                return True
            # A stale prior version, not a transient error: the rotation has
            # not propagated yet. Comparing digests rather than lengths means a
            # replacement token of the same length is still correctly rejected.
            last = f"read back {len(got)} bytes that do not match what was written"
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise SecretNotReadableError(
                f"{secret_name} was written but did not become readable within {timeout:.0f}s (last: {last})"
            )
        # Equal callers should not synchronize their retries during Vault
        # propagation or a regional 5xx incident. Keep jitter bounded so the
        # authoritative outer deadline remains unchanged.
        sleep(min(delay * random_uniform(0.8, 1.2), remaining))
        delay = min(delay * 1.5, 5.0)


def _list_active_secrets(vaults_client, compartment_id, vault_id, name=None, call=None):
    """Return every ACTIVE secret, following the Vaults API page tokens."""
    active = []
    page = None
    seen_pages = set()
    while True:
        kwargs = {
            "compartment_id": compartment_id,
            "vault_id": vault_id,
            "lifecycle_state": "ACTIVE",
        }
        if name is not None:
            kwargs["name"] = name
        if page is not None:
            kwargs["page"] = page

        def operation(request_kwargs=kwargs):
            return vaults_client.list_secrets(**request_kwargs)

        response = call("list secrets", operation) if call else operation()
        active.extend(secret for secret in response.data if getattr(secret, "lifecycle_state", None) == "ACTIVE")
        headers = getattr(response, "headers", None) or {}
        next_page = headers.get("opc-next-page") or getattr(response, "next_page", None)
        if not next_page:
            return active
        if next_page in seen_pages:
            raise RuntimeError(f"Vaults API repeated pagination token {next_page!r}")
        seen_pages.add(next_page)
        page = next_page


def resolve_vault_context(kms_client, vaults_client, vault_id, key_id=None, call=None):
    """Return (compartment_id, key_id) for the vault.

    An explicit key is authoritative. Otherwise the KMS key is inferred only
    when every ACTIVE sibling agrees, avoiding both a second hardcoded OCID and
    a nondeterministic choice from the Vaults API's result ordering.
    """

    def operation():
        return kms_client.get_vault(vault_id)

    vault = (call("get vault", operation) if call else operation()).data
    compartment_id = vault.compartment_id
    if key_id is not None:
        return compartment_id, key_id

    siblings = _list_active_secrets(vaults_client, compartment_id, vault_id, call=call)
    if not siblings:
        raise SystemExit(
            f"vault {vault_id} holds no existing secret to read the KMS key from; pass --key-id explicitly"
        )
    sibling_keys = {getattr(sibling, "key_id", None) for sibling in siblings}
    if None in sibling_keys or len(sibling_keys) != 1:
        rendered_keys = ", ".join(sorted(key or "<missing>" for key in sibling_keys))
        raise RuntimeError(
            f"ACTIVE secrets in vault {vault_id} use divergent KMS keys: {rendered_keys}; pass --key-id explicitly"
        )
    return compartment_id, sibling_keys.pop()


def find_secret(vaults_client, compartment_id, vault_id, name, call=None):
    for s in _list_active_secrets(vaults_client, compartment_id, vault_id, name=name, call=call):
        if s.secret_name == name:
            return s
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--secret-name", required=True)
    ap.add_argument("--vault-id", default=DEFAULT_VAULT_OCID)
    ap.add_argument("--key-id", default=None, help="defaults to a sibling secret's key")
    ap.add_argument("--profile", default="DEFAULT")
    ap.add_argument("--description", default=None, help="only applied when creating the secret")
    ap.add_argument(
        "--readable-timeout",
        type=float,
        default=120.0,
        help="positive end-to-end seconds for discovery, mutation, and read-back",
    )
    args = ap.parse_args()
    if args.readable_timeout <= 0:
        ap.error("--readable-timeout must be positive")

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

    deadline = OperationDeadline(args.readable_timeout)
    no_retry = oci.retry.NoneRetryStrategy()
    config = oci.config.from_file(profile_name=args.profile)
    initial_timeout = max(deadline.remaining("client setup"), 0.001)
    client_options = {
        "retry_strategy": no_retry,
        "timeout": (min(5.0, initial_timeout), initial_timeout),
    }
    vaults = oci.vault.VaultsClient(config, **client_options)
    kms = oci.key_management.KmsVaultClient(config, **client_options)
    secrets_client = oci.secrets.SecretsClient(config, **client_options)

    def call(label, operation, client=None):
        remaining = deadline.remaining(label)
        if client is not None:
            bounded = max(remaining, 0.001)
            client.base_client.timeout = (min(5.0, bounded), bounded)
        return deadline.call(label, operation)

    compartment_id, key_id = resolve_vault_context(
        kms,
        vaults,
        args.vault_id,
        key_id=args.key_id,
        call=lambda label, operation: call(label, operation, kms if label == "get vault" else vaults),
    )

    content = oci.vault.models.Base64SecretContentDetails(
        content_type="BASE64",
        content=base64.b64encode(value).decode("ascii"),
    )

    existing = find_secret(
        vaults,
        compartment_id,
        args.vault_id,
        args.secret_name,
        call=lambda label, operation: call(label, operation, vaults),
    )
    expected_digest = hashlib.sha256(value).hexdigest()
    version_name = f"acx-{expected_digest[:32]}"
    content.name = version_name

    def read_bundle():
        bundle = secrets_client.get_secret_bundle_by_name(
            secret_name=args.secret_name,
            vault_id=args.vault_id,
            retry_strategy=no_retry,
        ).data
        return base64.b64decode(bundle.secret_bundle_content.content)

    if existing is None:
        details = oci.vault.models.CreateSecretDetails(
            compartment_id=compartment_id,
            secret_name=args.secret_name,
            vault_id=args.vault_id,
            key_id=key_id,
            description=args.description or f"{args.secret_name} (OCIRV-1)",
            secret_content=content,
        )
        retry_token = hashlib.sha256(
            b"acx-vault-create\0" + args.vault_id.encode() + b"\0" + args.secret_name.encode() + b"\0" + value
        ).hexdigest()
        secret = call(
            "create secret",
            lambda: vaults.create_secret(details, opc_retry_token=retry_token, retry_strategy=no_retry),
            vaults,
        ).data
        action = "created"
    else:
        # A rerun after a lost response first checks the consumer-visible active
        # value. If it already matches, do not create a duplicate version.
        active_value = call("read active value before update", read_bundle, secrets_client)
        if hashlib.sha256(active_value).hexdigest() == expected_digest:
            secret = existing
            action = "unchanged"
        else:
            versions = call(
                "list secret versions",
                lambda: vaults.list_secret_versions(existing.id, retry_strategy=no_retry),
                vaults,
            ).data
            if any(getattr(version, "name", None) == version_name for version in versions):
                # A prior identical update was accepted but its response/read
                # readiness was lost. Its deterministic version name is the
                # idempotency key; wait for that version instead of adding one.
                secret = existing
                action = "existing version pending"
            else:
                current = call(
                    "get secret metadata",
                    lambda: vaults.get_secret(existing.id, retry_strategy=no_retry),
                    vaults,
                )
                etag = (getattr(current, "headers", None) or {}).get("etag")
                if not etag:
                    raise RuntimeError("Vault get_secret response omitted etag; refusing an unconditional update")
                secret = call(
                    "update secret",
                    lambda: vaults.update_secret(
                        existing.id,
                        oci.vault.models.UpdateSecretDetails(secret_content=content),
                        if_match=etag,
                        retry_strategy=no_retry,
                    ),
                    vaults,
                ).data
                action = "new version"

    print(f"{action}: {args.secret_name} ({len(value)} bytes)")
    print(f"  secret_id: {secret.id}")

    def prepare_attempt(remaining):
        bounded = max(min(remaining, deadline.remaining("read-back")), 0.001)
        secrets_client.base_client.timeout = (min(5.0, bounded), bounded)

    print(f"  waiting for {args.secret_name} to become readable ...", flush=True)
    wait_until_readable(
        read_bundle,
        args.secret_name,
        expected_digest,
        timeout=deadline.remaining("read-back"),
        prepare_attempt=prepare_attempt,
    )
    print("  readable: value matches what was written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
