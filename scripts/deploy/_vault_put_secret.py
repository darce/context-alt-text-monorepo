#!/usr/bin/env python
"""Store a secret value into acx-vault, reading the value from stdin only.

Companion to scripts/deploy/lib/ocir-auth.sh (OCIRV-1). Used by
`make ocir-token-rotate` to land an OCI auth token in the vault without it ever
reaching argv (ps-visible to every user on the host), a shell history file, or
a temp file on disk. The value is read from stdin, base64-encoded in memory,
and handed to the Vaults API.

Creates the secret on first use; on subsequent runs it adds a version only when
the active value differs. The OCID is stable across versions, so nothing
downstream needs reconfiguring on rotation
(vault-instance-principal-runbook.md section 5).

Run with the OCI CLI's bundled interpreter, which already has the SDK:
    printf '%s' "$TOKEN" | "$(head -1 "$(command -v oci)" | sed 's|^#!||')" \\
        scripts/deploy/_vault_put_secret.py --secret-name OCIR_AUTH_TOKEN

Prints only the resulting secret OCID and value byte length -- never the value.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import inspect
import math
import queue
import random
import sys
import threading
import time

# acx-vault, root compartment, us-ashburn-1. An OCID is not a secret (ADR-013).
DEFAULT_VAULT_OCID = "ocid1.vault.oc1.iad.ejvffpzlaafc4.abuwcljr3j4chidobdkiqx6igrzb4p3wffl43bjelxzfghkehdpuzle7cjla"
ALLOWED_SECRET_NAMES = frozenset({"OCIR_AUTH_TOKEN", "OCIR_USERNAME", "OCIR_CREDENTIAL_GENERATION"})


def validate_destination(vault_id: str, secret_name: str) -> None:
    """Enforce the writer's narrow acx-vault/OCIR mutation authority."""
    if vault_id != DEFAULT_VAULT_OCID:
        raise SystemExit(f"refusing unowned vault: {vault_id}")
    if secret_name not in ALLOWED_SECRET_NAMES:
        raise SystemExit(f"refusing unowned secret name: {secret_name}")


def validate_current_prefix(current_value: bytes | None, required_prefix: str | None, secret_name: str) -> None:
    """Reject a mutation unless the current value is in the required state."""
    if required_prefix is None:
        return
    prefix = required_prefix.encode("utf-8")
    if current_value is None or not current_value.startswith(prefix):
        raise RuntimeError(f"{secret_name} current value does not satisfy required prefix {required_prefix!r}")


def _non_negative_float(value):
    """Parse a finite, non-negative command-line number."""
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a finite non-negative number") from exc
    if not math.isfinite(parsed) or parsed < 0:
        raise argparse.ArgumentTypeError("must be a finite non-negative number")
    return parsed


def _positive_float(value):
    """Parse a finite, strictly positive command-line number."""
    parsed = _non_negative_float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a finite positive number")
    return parsed


class SecretNotReadableError(RuntimeError):
    """The stored value never became readable through the consumer's API."""


class OperationDeadlineError(TimeoutError):
    """A non-mutating Vault operation exceeded the command deadline."""


class MutationOutcomeUnknownError(TimeoutError):
    """A Vault mutation timed out after it may have been accepted."""


class OperationDeadline:
    """One monotonic deadline shared by discovery, mutation, and read-back."""

    def __init__(self, timeout: float, monotonic=None):
        if timeout <= 0:
            raise ValueError("operation timeout must be positive")
        self.timeout = timeout
        self._monotonic = monotonic or time.monotonic
        self._deadline = self._monotonic() + timeout

    def remaining(self, phase: str) -> float:
        remaining = self._deadline - self._monotonic()
        if remaining <= 0:
            raise OperationDeadlineError(f"{phase} exceeded the {self.timeout:g}s overall operation deadline")
        return remaining


def call_with_deadline(call, remaining: float, phase: str, *, mutation: bool = False):
    """Run one SDK call within the remaining overall operation deadline."""
    outcome = queue.Queue(maxsize=1)

    def run():
        try:
            outcome.put((True, call()))
        except BaseException as exc:  # transferred to the calling thread below
            outcome.put((False, exc))

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(max(remaining, 0))
    if worker.is_alive():
        if mutation:
            raise MutationOutcomeUnknownError(
                f"UNKNOWN: {phase} exceeded the overall operation deadline; "
                "the Vault service may have accepted the mutation"
            )
        raise OperationDeadlineError(f"{phase} exceeded the overall operation deadline")
    succeeded, value = outcome.get_nowait()
    if succeeded:
        return value
    exception_type = type(value)
    is_transport_timeout = isinstance(value, TimeoutError) or (
        exception_type.__module__.split(".", 1)[0] in {"requests", "urllib3"}
        and "timeout" in exception_type.__name__.lower()
    )
    if is_transport_timeout:
        if mutation:
            raise MutationOutcomeUnknownError(
                f"UNKNOWN: {phase} timed out; the Vault service may have accepted the mutation"
            ) from value
        raise OperationDeadlineError(f"{phase} timed out within the overall operation deadline") from value
    raise value


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


def _read_with_deadline(read_bundle, remaining):
    """Run one read without allowing it to outlive the outer deadline."""
    outcome = queue.Queue(maxsize=1)

    def run():
        try:
            outcome.put((True, read_bundle()))
        except BaseException as exc:  # transferred to the calling thread below
            outcome.put((False, exc))

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(remaining)
    if worker.is_alive():
        raise SecretNotReadableError("the Secrets API read exceeded the remaining readiness deadline")
    succeeded, value = outcome.get_nowait()
    if succeeded:
        return value
    raise value


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
    random_uniform = random_uniform or random.uniform
    if timeout == 0:
        return True
    if timeout < 0:
        raise ValueError("timeout must be non-negative")
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
        sleep(random_uniform(0, min(delay, remaining)))
        delay = min(delay * 1.5, 5.0)


def _direct_call(_phase, call, *args, **kwargs):
    return call(*args, **kwargs)


def _list_active_secrets(vaults_client, compartment_id, vault_id, name=None, invoke=None):
    """Return every ACTIVE secret, following the Vaults API page tokens."""
    invoke = invoke or _direct_call
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
        response = invoke("list ACTIVE secrets", vaults_client.list_secrets, **kwargs)
        active.extend(secret for secret in response.data if getattr(secret, "lifecycle_state", None) == "ACTIVE")
        headers = getattr(response, "headers", None) or {}
        next_page = headers.get("opc-next-page") or getattr(response, "next_page", None)
        if not next_page:
            return active
        if next_page in seen_pages:
            raise RuntimeError(f"Vaults API repeated pagination token {next_page!r}")
        seen_pages.add(next_page)
        page = next_page


def resolve_vault_context(kms_client, vaults_client, vault_id, key_id=None, invoke=None):
    """Return (compartment_id, key_id) for the vault.

    An explicit key is authoritative. Otherwise the KMS key is inferred only
    when every ACTIVE sibling agrees, avoiding both a second hardcoded OCID and
    a nondeterministic choice from the Vaults API's result ordering.
    """
    invoke = invoke or _direct_call
    vault = invoke("get vault", kms_client.get_vault, vault_id).data
    compartment_id = vault.compartment_id
    if key_id is not None:
        return compartment_id, key_id

    siblings = _list_active_secrets(vaults_client, compartment_id, vault_id, invoke=invoke)
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


def find_secret(vaults_client, compartment_id, vault_id, name, invoke=None):
    for s in _list_active_secrets(vaults_client, compartment_id, vault_id, name=name, invoke=invoke):
        if s.secret_name == name:
            return s
    return None


def write_secret_if_needed(*, existing, value, read_current, create_secret, update_secret):
    """Create/update a secret, skipping a duplicate version on identical input."""
    if existing is not None and read_current() == value:
        return existing, "already current"
    if existing is None:
        return create_secret(), "created"
    return update_secret(), "new version"


def mutation_retry_token(vault_id: str, secret_name: str, value: bytes) -> str:
    """Return a stable OCI create idempotency key without exposing the value."""
    digest = hashlib.sha256()
    for field in (vault_id.encode("utf-8"), secret_name.encode("utf-8"), value):
        digest.update(len(field).to_bytes(8, "big"))
        digest.update(field)
    return digest.hexdigest()


def require_etag(response, secret_name: str) -> str:
    """Extract the update precondition supplied by OCI's get-secret response."""
    headers = getattr(response, "headers", None)
    if headers is None:
        raise RuntimeError(f"get-secret response for {secret_name} is missing the ETag headers")
    etag = headers.get("etag") or headers.get("ETag")
    if not isinstance(etag, str) or not etag:
        raise RuntimeError(f"get-secret response for {secret_name} is missing a valid ETag")
    return etag


def _set_client_timeout(client, remaining: float) -> None:
    """Tighten the SDK's connect/read budgets to the shared remaining time."""
    bounded = max(remaining, 0.001)
    client.base_client.timeout = (min(5.0, bounded), bounded)


def _accepts_keyword(call, keyword: str) -> bool:
    """Return whether a callable accepts an SDK control keyword."""
    try:
        parameters = inspect.signature(call).parameters.values()
    except (TypeError, ValueError):
        return True
    return any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters) or any(
        parameter.name == keyword for parameter in parameters
    )


def _make_client(factory, config, no_retry, timeout):
    kwargs = {}
    if _accepts_keyword(factory, "retry_strategy"):
        kwargs["retry_strategy"] = no_retry
    if _accepts_keyword(factory, "timeout"):
        kwargs["timeout"] = timeout
    client = factory(config, **kwargs)
    if hasattr(client, "base_client"):
        client.base_client.timeout = timeout
    return client


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--secret-name", required=True)
    ap.add_argument("--vault-id", default=DEFAULT_VAULT_OCID)
    ap.add_argument("--if-match", default=None, help="require this ETag for a fenced replacement")
    ap.add_argument("--require-current-prefix", default=None, help="require current decoded bytes to start with text")
    ap.add_argument("--key-id", default=None, help="defaults to a sibling secret's key")
    ap.add_argument("--profile", default="DEFAULT")
    ap.add_argument("--description", default=None, help="only applied when creating the secret")
    ap.add_argument(
        "--readable-timeout",
        type=_non_negative_float,
        default=120.0,
        help="seconds to wait for the written value to read back (0 to skip)",
    )
    ap.add_argument(
        "--operation-timeout",
        type=_positive_float,
        default=None,
        help="overall discovery/write/read-back deadline (default: readable timeout plus 30 seconds)",
    )
    args = ap.parse_args()

    validate_destination(args.vault_id, args.secret_name)

    import oci  # noqa: PLC0415 -- lazy so the readiness gate stays unit-testable

    if sys.stdin.isatty():
        raise SystemExit("refusing to prompt: pipe the value on stdin")
    operation_timeout = args.operation_timeout
    if operation_timeout is None:
        operation_timeout = args.readable_timeout + 30.0
    deadline = OperationDeadline(operation_timeout)

    # Read raw bytes so a token containing non-UTF8 or a trailing newline the
    # operator did not intend is handled explicitly rather than silently.
    value = sys.stdin.buffer.read()
    # A trailing newline from `read`/`printf` would be stored as part of the
    # token and produce an OCIR rejection that looks like a bad token.
    value = value.rstrip(b"\r\n")
    if not value:
        raise SystemExit("refusing to store an empty value")

    config = oci.config.from_file(profile_name=args.profile)
    no_retry = oci.retry.NoneRetryStrategy()
    initial_timeout = deadline.remaining("client setup")
    client_timeout = (min(5.0, initial_timeout), initial_timeout)
    vaults = _make_client(oci.vault.VaultsClient, config, no_retry, client_timeout)
    kms = _make_client(oci.key_management.KmsVaultClient, config, no_retry, client_timeout)
    if args.readable_timeout == 0:
        readable_client_timeout = initial_timeout
    else:
        readable_client_timeout = max(min(args.readable_timeout, initial_timeout), 0.001)
    secrets_client = None

    def get_secrets_client():
        nonlocal secrets_client
        if secrets_client is None:
            secrets_client = _make_client(
                oci.secrets.SecretsClient,
                config,
                no_retry,
                (min(5.0, readable_client_timeout), readable_client_timeout),
            )
        return secrets_client

    def invoke(phase, call, *call_args, mutation=False, **call_kwargs):
        remaining = deadline.remaining(phase)
        client = getattr(call, "__self__", None)
        if client is not None and hasattr(client, "base_client"):
            current_timeout = client.base_client.timeout
            if isinstance(current_timeout, tuple) and len(current_timeout) == 2:
                remaining = min(remaining, current_timeout[1])
            _set_client_timeout(client, remaining)
        if _accepts_keyword(call, "retry_strategy"):
            call_kwargs["retry_strategy"] = no_retry
        return call_with_deadline(
            lambda: call(*call_args, **call_kwargs),
            remaining,
            phase,
            mutation=mutation,
        )

    compartment_id, key_id = resolve_vault_context(
        kms,
        vaults,
        args.vault_id,
        key_id=args.key_id,
        invoke=invoke,
    )

    content = oci.vault.models.Base64SecretContentDetails(
        content_type="BASE64",
        content=base64.b64encode(value).decode("ascii"),
    )
    retry_token = mutation_retry_token(args.vault_id, args.secret_name, value)

    existing = find_secret(vaults, compartment_id, args.vault_id, args.secret_name, invoke=invoke)
    update_etag = None
    conditional_update = _accepts_keyword(vaults.update_secret, "if_match")
    if args.if_match is not None and existing is None:
        raise RuntimeError(f"cannot conditionally update missing secret {args.secret_name}")
    if args.if_match is not None and not conditional_update:
        raise RuntimeError(f"SDK cannot enforce the requested ETag for {args.secret_name}")
    if args.if_match is not None:
        update_etag = args.if_match
    elif existing is not None and conditional_update:
        metadata_response = invoke(
            f"get current {args.secret_name} metadata",
            vaults.get_secret,
            existing.id,
        )
        update_etag = require_etag(metadata_response, args.secret_name)

    def read_bundle():
        client = get_secrets_client()
        bundle = invoke(
            f"read ACTIVE {args.secret_name}",
            client.get_secret_bundle_by_name,
            secret_name=args.secret_name,
            vault_id=args.vault_id,
        ).data
        return base64.b64decode(bundle.secret_bundle_content.content)

    current_value = read_bundle() if existing is not None else None
    validate_current_prefix(current_value, args.require_current_prefix, args.secret_name)

    mutation_etag = update_etag

    def create_secret():
        nonlocal mutation_etag
        create_kwargs = {}
        if _accepts_keyword(vaults.create_secret, "opc_retry_token"):
            create_kwargs["opc_retry_token"] = retry_token
        response = invoke(
            f"create {args.secret_name}",
            vaults.create_secret,
            oci.vault.models.CreateSecretDetails(
                compartment_id=compartment_id,
                secret_name=args.secret_name,
                vault_id=args.vault_id,
                key_id=key_id,
                description=args.description or f"{args.secret_name} (OCIRV-1)",
                secret_content=content,
            ),
            mutation=True,
            **create_kwargs,
        )
        mutation_etag = require_etag(response, args.secret_name)
        return response.data

    def update_secret():
        nonlocal mutation_etag
        if conditional_update and update_etag is None:
            raise RuntimeError(f"cannot update {args.secret_name} without an ETag precondition")
        update_kwargs = {"if_match": update_etag} if conditional_update else {}
        response = invoke(
            f"update {args.secret_name}",
            vaults.update_secret,
            existing.id,
            oci.vault.models.UpdateSecretDetails(secret_content=content),
            mutation=True,
            **update_kwargs,
        )
        mutation_etag = require_etag(response, args.secret_name)
        return response.data

    try:
        secret, action = write_secret_if_needed(
            existing=existing,
            value=value,
            read_current=lambda: current_value,
            create_secret=create_secret,
            update_secret=update_secret,
        )
    except MutationOutcomeUnknownError as exc:
        # A lost create/update response is not proof of failure. Reconcile from
        # the consumer path before allowing a rerun to submit another version.
        try:
            remaining = deadline.remaining(f"reconcile {args.secret_name}")
            wait_until_readable(
                read_bundle,
                args.secret_name,
                hashlib.sha256(value).hexdigest(),
                timeout=remaining,
            )
        except (OperationDeadlineError, SecretNotReadableError) as reconcile_exc:
            raise MutationOutcomeUnknownError(
                f"{exc}; reconciliation did not establish the active value ({reconcile_exc})"
            ) from exc
        secret = existing
        action = "reconciled after unknown mutation outcome"

    print(f"{action}: {args.secret_name} ({len(value)} bytes)")
    secret_id = getattr(secret, "id", "<accepted; id unavailable before reconciliation deadline>")
    print(f"  secret_id: {secret_id}")
    if mutation_etag is not None:
        print(f"  write_etag: {mutation_etag}")

    if args.readable_timeout == 0:
        print("  readable: ACCEPTED-BUT-UNVERIFIED (--readable-timeout 0)")
    else:

        def prepare_attempt(remaining):
            # Requests has separate connect/read budgets. The daemon-thread
            # guard in wait_until_readable remains the authoritative total cap.
            _set_client_timeout(
                get_secrets_client(),
                min(remaining, deadline.remaining("read-back")),
            )

        print(f"  waiting for {args.secret_name} to become readable ...", flush=True)
        wait_until_readable(
            read_bundle,
            args.secret_name,
            hashlib.sha256(value).hexdigest(),
            timeout=min(args.readable_timeout, deadline.remaining("read-back")),
            prepare_attempt=prepare_attempt,
        )
        print("  readable: value matches what was written")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except MutationOutcomeUnknownError as exc:
        print(f"UNKNOWN: {exc}", file=sys.stderr)
        sys.exit(75)
    except OperationDeadlineError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        sys.exit(1)
