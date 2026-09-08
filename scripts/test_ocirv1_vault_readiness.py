"""Readiness gate for Vault writes (OCIRV-1).

Regression pin for a live failure on 2026-08-28: `ocir-token-rotate` created
OCIR_AUTH_TOKEN successfully, then verified ~1s later and reported
`secret_missing` -- telling the operator to store a token they had just stored.
Creating an OCI secret is asynchronous: the OCID exists immediately but
`get_secret_bundle_by_name` 404s until the first version reaches ACTIVE. The VM
leg, running a few seconds behind, authenticated against the same secret.

The gate polls the *consumer's* read path rather than lifecycle_state, so a
green result means the deploy preflight will succeed rather than merely that the
control plane finished its bookkeeping.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import io
import sys
import time
import types
from pathlib import Path

import pytest

_MODULE_PATH = Path(__file__).parent / "deploy" / "_vault_put_secret.py"


def _load():
    spec = importlib.util.spec_from_file_location("_vault_put_secret", _MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


vps = _load()


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _assert_bounded_increasing_backoff(delays, timeout):
    """Assert the retry policy without freezing its safe tuning factor.

    `delays` are the jitter *caps*: `_Clock.uniform` returns each draw's upper
    bound, so the recorded sleeps are exactly the schedule the policy would use
    with jitter disabled. The cap schedule is what must grow and stay bounded;
    `_assert_full_jitter` covers the randomisation on top of it.
    """
    assert delays
    assert all(0 < delay <= 5.0 for delay in delays)
    assert len(set(delays)) > 1, "retry delay must not remain constant"
    for previous, current in zip(delays[:-1], delays[1:], strict=True):
        if previous < 5.0:
            assert current > previous
        else:
            assert current == 5.0
    assert sum(delays) <= timeout


def _assert_full_jitter(clock, delays):
    """Assert every wait was drawn from [0, cap] rather than taken at the cap.

    Fleet-synchronised retries (two rotation legs, or a rerun after a failure)
    converge on the same schedule and hammer the control plane in lockstep. Full
    jitter is the defence, so its absence is a regression, not a tuning choice.
    """
    assert clock.draws, "retry sleeps must be drawn from a jitter range"
    assert all(low == 0 for low, _ in clock.draws), clock.draws
    assert [high for _, high in clock.draws] == delays


class _ServiceError(Exception):
    """SDK-shaped error double used to distinguish service from code failures."""

    def __init__(self, status, code):
        super().__init__(f"{status} {code}")
        self.status = status
        self.code = code


class RunawayError(AssertionError):
    """wait_until_readable kept polling past any plausible deadline."""


class _Clock:
    """Deterministic sleep + clock: the double advances time instead of burning it.

    The gate's deadline is checked against `monotonic`, so a fake sleep that does
    not advance a fake clock would spin thousands of times inside a 50ms wall
    deadline and prove nothing. Advancing here makes every test exact.

    Bounded on purpose. Every test drives the gate with a read path that either
    never matches or matches after a fixed number of calls, so if the deadline
    check is ever removed the loop never terminates. A hanging test surfaces as a
    CI timeout with nothing pointing at the cause -- strictly worse than a red
    test. Raising converts that defect into a named failure in the test that
    tripped it.
    """

    MAX_SLEEPS = 200
    # A real attempt costs time even when a full-jitter draw rounds to zero.
    # Without this floor a zero draw would leave the fake clock stationary and
    # spin the gate against its own deadline.
    MIN_TICK = 0.001

    def __init__(self):
        self.slept = []
        self.draws = []
        self.now = 0.0

    def __call__(self, seconds):
        self.slept.append(seconds)
        self.now += max(seconds, self.MIN_TICK)
        if len(self.slept) > self.MAX_SLEEPS:
            raise RunawayError(f"polled {len(self.slept)} times without honouring the deadline")

    def uniform(self, low, high):
        """Deterministic `random.uniform` double: records the range, returns its cap.

        Returning the upper bound keeps every read-count assertion exact while
        still recording what the policy asked for, so the jitter range itself
        stays assertable (`_assert_full_jitter`).
        """
        self.draws.append((low, high))
        return high

    def monotonic(self):
        return self.now


def test_module_imports_without_the_oci_sdk():
    # The gate is pure logic; if `import oci` ever moves back to module scope
    # this test cannot run anywhere the SDK is absent, which is most CI envs.
    assert not hasattr(vps, "oci")
    assert callable(vps.wait_until_readable)


def test_returns_once_the_written_value_reads_back():
    value = b"a-token-value"
    calls = {"n": 0}
    not_ready_reads = 8

    def read_bundle():
        calls["n"] += 1
        if calls["n"] <= not_ready_reads:
            raise _ServiceError(404, "NotAuthorizedOrNotFound")
        return value

    clock = _Clock()
    assert vps.wait_until_readable(
        read_bundle,
        "OCIR_AUTH_TOKEN",
        _digest(value),
        timeout=60,
        sleep=clock,
        monotonic=clock.monotonic,
        random_uniform=clock.uniform,
    )
    assert calls["n"] == not_ready_reads + 1
    # A slow propagation must not become a constant-delay hot loop against the
    # control plane. Assert the operational contract while leaving the safe
    # growth factor free to be tuned.
    _assert_bounded_increasing_backoff(clock.slept, timeout=60)
    _assert_full_jitter(clock, clock.slept)


def test_the_exact_live_failure_no_longer_escapes():
    """The 404 the operator saw must be absorbed, not surfaced."""
    value = b"20-byte-token-xxxxxx"
    seq = iter(
        [
            _ServiceError(404, "NotAuthorizedOrNotFound"),
            value,
        ]
    )

    def read_bundle():
        got = next(seq)
        if isinstance(got, Exception):
            raise got
        return got

    clock = _Clock()
    assert vps.wait_until_readable(
        read_bundle,
        "OCIR_AUTH_TOKEN",
        _digest(value),
        timeout=60,
        sleep=clock,
        monotonic=clock.monotonic,
        random_uniform=clock.uniform,
    )


def test_stale_prior_version_is_not_accepted():
    # Rotation case: the read path answers, but with the *previous* token. A
    # length check would pass here whenever the replacement is the same size,
    # which for fixed-format OCI auth tokens is essentially always -- hence the
    # digest comparison.
    old = b"aaaaaaaaaaaaaaaaaaaa"
    new = b"bbbbbbbbbbbbbbbbbbbb"
    assert len(old) == len(new)

    clock = _Clock()
    with pytest.raises(vps.SecretNotReadableError) as excinfo:
        vps.wait_until_readable(
            lambda: old,
            "OCIR_AUTH_TOKEN",
            _digest(new),
            timeout=1,
            sleep=clock,
            monotonic=clock.monotonic,
            random_uniform=clock.uniform,
        )
    assert "do not match" in str(excinfo.value)


def test_gives_up_with_an_actionable_message():
    def read_bundle():
        raise _ServiceError(404, "NotAuthorizedOrNotFound")

    clock = _Clock()
    with pytest.raises(vps.SecretNotReadableError) as excinfo:
        vps.wait_until_readable(
            lambda: read_bundle(),
            "OCIR_AUTH_TOKEN",
            _digest(b"x"),
            timeout=1,
            sleep=clock,
            monotonic=clock.monotonic,
            random_uniform=clock.uniform,
        )
    message = str(excinfo.value)
    assert "OCIR_AUTH_TOKEN" in message
    assert "did not become readable" in message
    # The last observed cause must survive into the message, or the operator is
    # left with a bare timeout and no lead.
    assert "NotAuthorizedOrNotFound" in message


def test_bounded_so_a_stuck_control_plane_cannot_hang_the_rotation():
    # A stuck control plane answers, but never with our value. The gate must
    # give up on its own deadline; _Clock turns a missing deadline into a
    # RunawayError rather than a hung suite.
    started = time.monotonic()
    clock = _Clock()
    with pytest.raises(vps.SecretNotReadableError):
        vps.wait_until_readable(
            lambda: b"never-matches",
            "S",
            _digest(b"target"),
            timeout=30,
            sleep=clock,
            monotonic=clock.monotonic,
            random_uniform=clock.uniform,
        )
    assert time.monotonic() - started < 5


def test_secret_value_never_appears_in_the_failure_message():
    secret = b"super-secret-token-value"
    clock = _Clock()
    with pytest.raises(vps.SecretNotReadableError) as excinfo:
        vps.wait_until_readable(
            lambda: secret,
            "OCIR_AUTH_TOKEN",
            _digest(b"different"),
            timeout=1,
            sleep=clock,
            monotonic=clock.monotonic,
            random_uniform=clock.uniform,
        )
    message = str(excinfo.value)
    assert secret.decode() not in message
    # Nor may the digest leak: it is a verification oracle for a short,
    # fixed-charset token.
    assert _digest(secret) not in message


def test_zero_timeout_skips_readback_entirely():
    calls = {"n": 0}

    def failing_read():
        calls["n"] += 1
        raise AssertionError("timeout zero must not perform a read")

    assert vps.wait_until_readable(failing_read, "S", _digest(b"target"), timeout=0)
    assert calls["n"] == 0


def test_programming_error_propagates_without_retry():
    calls = {"n": 0}
    clock = _Clock()

    def broken_read():
        calls["n"] += 1
        raise TypeError("programming bug, not transient")

    with pytest.raises(TypeError, match="programming bug"):
        vps.wait_until_readable(
            broken_read,
            "S",
            _digest(b"target"),
            timeout=3,
            sleep=clock,
            monotonic=clock.monotonic,
            random_uniform=clock.uniform,
        )
    assert calls["n"] == 1


def test_503_is_retried():
    value = b"target"
    responses = iter([_ServiceError(503, "ServiceUnavailable"), value])
    clock = _Clock()

    def read_bundle():
        response = next(responses)
        if isinstance(response, Exception):
            raise response
        return response

    assert vps.wait_until_readable(
        read_bundle,
        "S",
        _digest(value),
        timeout=10,
        sleep=clock,
        monotonic=clock.monotonic,
        random_uniform=clock.uniform,
    )
    assert clock.slept == [1.0]
    _assert_full_jitter(clock, [1.0])


def test_blocking_read_cannot_overrun_the_outer_deadline():
    started = time.monotonic()

    def slow_read():
        time.sleep(1)
        return b"too late"

    with pytest.raises(vps.SecretNotReadableError, match="deadline"):
        vps.wait_until_readable(slow_read, "S", _digest(b"target"), timeout=0.05)
    assert time.monotonic() - started < 0.25


# --- main() wiring ------------------------------------------------------------
# The unit tests above pin wait_until_readable's behaviour. They say nothing
# about whether main() actually calls it -- and the live 2026-08-28 failure was
# exactly a missing wait, not a broken one. A mutant that deletes the call site
# from main() leaves every test above green, so the regression is pinned here
# instead: drive main() end to end against a stubbed SDK and assert it does not
# return until the consumer's read path yields the written value.


class _FakeVaultStore:
    """Shared Vault state: submitted versions propagate to the read API later."""

    SECRET_ID = "ocid1.vaultsecret.oc1..target"

    def __init__(self, not_ready_reads, existing_value=None):
        self.not_ready_reads = not_ready_reads
        self.remaining = 0
        self.active_value = existing_value
        self.pending_value = None
        self.existing = None
        if existing_value is not None:
            self.existing = types.SimpleNamespace(
                secret_name="OCIR_AUTH_TOKEN",
                key_id="ocid1.key.oc1..shared",
                id=self.SECRET_ID,
                lifecycle_state="ACTIVE",
            )
        self.create_calls = []
        self.update_calls = []
        self.read_history = []
        self.list_calls = []
        self.version_pages = None
        self.version_calls = []
        # OCI hands back an ETag on every get/create/update and requires the
        # current one as an update precondition, so the double carries it too:
        # a fixture that returns bare payloads cannot catch a lost precondition.
        self.etag = "etag-v0"
        self.etag_history = []
        self.get_secret_calls = []
        self.create_tokens = []
        self.update_if_match = []

    @staticmethod
    def _decode(details):
        return base64.b64decode(details.secret_content.content)

    def _stage(self, value):
        self.pending_value = value
        self.remaining = self.not_ready_reads

    def _rotate_etag(self):
        self.etag_history.append(self.etag)
        self.etag = f"etag-v{len(self.etag_history)}"

    def create(self, details, opc_retry_token=None):
        self.create_calls.append(details)
        self.create_tokens.append(opc_retry_token)
        self.existing = types.SimpleNamespace(
            secret_name=details.secret_name,
            key_id=details.key_id,
            id=self.SECRET_ID,
            lifecycle_state="ACTIVE",
        )
        self._stage(self._decode(details))
        self.version_pages = None
        self._rotate_etag()
        return self.existing

    def update(self, secret_id, details, if_match=None):
        self.update_calls.append((secret_id, details))
        self.update_if_match.append(if_match)
        # The live API rejects a stale precondition; so must the double, or a
        # regression that drops --if-match still shows green here.
        if if_match != self.etag:
            raise _ServiceError(409, "NoEtagMatch")
        self._stage(self._decode(details))
        self.version_pages = None
        self._rotate_etag()
        return self.existing

    def read(self):
        if self.pending_value is not None:
            if self.remaining > 0:
                self.remaining -= 1
                if self.active_value is None:
                    raise _ServiceError(404, "NotAuthorizedOrNotFound")
            else:
                self.active_value = self.pending_value
                self.pending_value = None
        if self.active_value is None:
            raise AssertionError("read attempted before a version was submitted")
        self.read_history.append(self.active_value)
        return self.active_value


class _FakeSecretsClient:
    """Consumer API backed by the content actually submitted to fake Vault."""

    def __init__(self, store, **kwargs):
        self._store = store
        self.reads = 0
        self.init_kwargs = kwargs
        self.read_kwargs = []
        self.request_timeouts = []
        self.base_client = types.SimpleNamespace(timeout=kwargs.get("timeout"))

    def get_secret_bundle_by_name(self, secret_name, vault_id, **kwargs):
        self.reads += 1
        self.read_kwargs.append(kwargs)
        self.request_timeouts.append(self.base_client.timeout)
        value = self._store.read()
        content = types.SimpleNamespace(content=base64.b64encode(value).decode("ascii"))
        return types.SimpleNamespace(data=types.SimpleNamespace(secret_bundle_content=content))


def _install_fake_clock(monkeypatch):
    """Bound every main() test's clock.

    Swaps the module's `time` rather than the stdlib's: main() exposes no clock
    seam, and patching time.monotonic globally would hand pytest's own internals
    a fake clock. Bounded like _Clock, so a mutant that breaks a guard fails
    these tests instead of spinning for the full 120s readable-timeout. Applied
    to *every* main() test, including the ones that should never reach the wait
    -- those are exactly the tests a mutant turns into a 120s hang.
    """
    clock = _Clock()
    monkeypatch.setattr(
        vps,
        "time",
        types.SimpleNamespace(sleep=clock, monotonic=clock.monotonic),
    )
    # Same reason for the jitter source: main() exposes no seam for it, and a
    # live RNG would make every read-count assertion below nondeterministic.
    monkeypatch.setattr(vps, "random", types.SimpleNamespace(uniform=clock.uniform))
    return clock


_DEFAULT_SIBLINGS = object()


def _install_fake_oci(
    monkeypatch,
    not_ready_reads,
    existing_value=None,
    sibling_secrets=_DEFAULT_SIBLINGS,
):
    """Minimal stand-in for the parts of the SDK main() touches."""
    store = _FakeVaultStore(not_ready_reads, existing_value)
    if sibling_secrets is _DEFAULT_SIBLINGS:
        sibling_secrets = [
            types.SimpleNamespace(
                secret_name="POSTGRES_DSN",
                key_id="ocid1.key.oc1..sibling",
                id="s0",
                lifecycle_state="ACTIVE",
            )
        ]
    secrets_clients = []

    class _Vaults:
        def __init__(self, config, **kwargs):
            self.init_kwargs = kwargs
            self.base_client = types.SimpleNamespace(timeout=kwargs.get("timeout"))

        def list_secrets(
            self,
            compartment_id,
            vault_id,
            name=None,
            lifecycle_state=None,
            page=None,
        ):
            store.list_calls.append(
                {
                    "name": name,
                    "lifecycle_state": lifecycle_state,
                    "page": page,
                }
            )
            if name is None:
                return types.SimpleNamespace(data=list(sibling_secrets), headers={})
            matches = []
            if store.existing is not None and store.existing.secret_name == name:
                matches.append(store.existing)
            return types.SimpleNamespace(data=matches, headers={})

        def get_secret(self, secret_id):
            store.get_secret_calls.append(secret_id)
            return types.SimpleNamespace(data=store.existing, headers={"etag": store.etag})

        def create_secret(self, details, opc_retry_token=None):
            secret = store.create(details, opc_retry_token)
            return types.SimpleNamespace(data=secret, headers={"etag": store.etag})

        def update_secret(self, secret_id, details, if_match=None):
            secret = store.update(secret_id, details, if_match)
            return types.SimpleNamespace(data=secret, headers={"etag": store.etag})

        def list_secret_versions(self, secret_id, page=None, **kwargs):
            del secret_id
            store.version_calls.append({"page": page, **kwargs})
            if store.version_pages is None:
                return types.SimpleNamespace(data=[], headers={})
            page_index = 0 if page is None else int(page.rsplit("-", 1)[-1]) - 1
            versions = store.version_pages[page_index]
            headers = {}
            if page_index + 1 < len(store.version_pages):
                headers["opc-next-page"] = f"page-{page_index + 2}"
            return types.SimpleNamespace(data=versions, headers=headers)

    class _Kms:
        def __init__(self, config):
            pass

        def get_vault(self, vault_id):
            return types.SimpleNamespace(data=types.SimpleNamespace(compartment_id="ocid1.compartment.oc1..c"))

    models = types.SimpleNamespace(
        Base64SecretContentDetails=lambda content_type, content, name=None, stage=None: types.SimpleNamespace(
            content_type=content_type, content=content, name=name, stage=stage
        ),
        CreateSecretDetails=lambda **kw: types.SimpleNamespace(**kw),
        UpdateSecretDetails=lambda **kw: types.SimpleNamespace(**kw),
    )
    fake = types.ModuleType("oci")
    fake.config = types.SimpleNamespace(from_file=lambda profile_name: {})
    fake.vault = types.SimpleNamespace(VaultsClient=_Vaults, models=models)
    fake.key_management = types.SimpleNamespace(KmsVaultClient=_Kms)
    no_retry = object()
    fake.retry = types.SimpleNamespace(NoneRetryStrategy=lambda: no_retry)

    def make_secrets_client(config, **kwargs):
        client = _FakeSecretsClient(store, **kwargs)
        secrets_clients.append(client)
        return client

    fake.secrets = types.SimpleNamespace(SecretsClient=make_secrets_client)
    monkeypatch.setitem(sys.modules, "oci", fake)
    monkeypatch.setitem(sys.modules, "oci.vault", fake.vault)
    monkeypatch.setitem(sys.modules, "oci.secrets", fake.secrets)
    monkeypatch.setitem(sys.modules, "oci.key_management", fake.key_management)
    return store, secrets_clients, no_retry


def _run_main(
    monkeypatch,
    token,
    not_ready_reads,
    existing_value=None,
    extra_args=(),
    sibling_secrets=_DEFAULT_SIBLINGS,
):
    store, secrets_clients, no_retry = _install_fake_oci(monkeypatch, not_ready_reads, existing_value, sibling_secrets)
    clock = _install_fake_clock(monkeypatch)
    monkeypatch.setattr(
        sys,
        "argv",
        ["_vault_put_secret.py", "--secret-name", "OCIR_AUTH_TOKEN", *extra_args],
    )
    stdin = types.SimpleNamespace(isatty=lambda: False, buffer=io.BytesIO(token + b"\n"))
    monkeypatch.setattr(sys, "stdin", stdin)
    rc = vps.main()
    secrets_client = secrets_clients[0] if secrets_clients else None
    return rc, store, secrets_client, clock, no_retry


def test_main_does_not_return_until_the_secret_reads_back(monkeypatch, capsys):
    # Two 404s then success: the shape of the live failure. main() must absorb
    # them. If the gate is ever unwired from main(), reads stays at 0 and this
    # goes red -- the unit tests above cannot see that.
    rc, _, secrets_client, _, _ = _run_main(monkeypatch, b"20-byte-token-xxxxxx", 2)
    assert rc == 0
    assert secrets_client.reads == 3
    assert "readable" in capsys.readouterr().out


def test_main_disables_sdk_retries_and_bounds_each_request(monkeypatch):
    rc, _, secrets_client, _, no_retry = _run_main(monkeypatch, b"token", 1)

    assert rc == 0
    assert secrets_client.init_kwargs["retry_strategy"] is no_retry
    assert secrets_client.init_kwargs["timeout"] == (5.0, 120.0)
    assert all(kwargs["retry_strategy"] is no_retry for kwargs in secrets_client.read_kwargs)
    assert all(connect <= read <= 120 for connect, read in secrets_client.request_timeouts)


def test_main_reports_the_byte_count_but_never_the_token(monkeypatch, capsys):
    token = b"super-secret-token-value"
    rc, _, _, _, _ = _run_main(monkeypatch, token, 0)
    assert rc == 0
    out = capsys.readouterr().out
    assert f"({len(token)} bytes)" in out
    assert token.decode() not in out
    assert base64.b64encode(token).decode("ascii") not in out


def test_main_strips_a_trailing_newline_before_storing(monkeypatch):
    # `printf`/`read` and a clipboard paste routinely append one. Stored raw it
    # becomes part of the token and OCIR rejects it as a bad credential --
    # indistinguishable from a revoked token.
    token = b"20-byte-token-xxxxxx"
    _, store, secrets_client, _, _ = _run_main(monkeypatch, token, 0)
    # The gate compares against sha256 of the *stripped* value, so reaching
    # rc == 0 above already proves the strip; assert the stored payload too.
    assert secrets_client.reads >= 1
    assert len(store.create_calls) == 1
    assert _FakeVaultStore._decode(store.create_calls[0]) == token
    # The create carries a value-derived idempotency key, so a retried create
    # after a lost response cannot land a second secret.
    assert store.create_tokens == [vps.mutation_retry_token(vps.DEFAULT_VAULT_OCID, "OCIR_AUTH_TOKEN", token)]


def test_main_rotation_waits_for_the_new_submitted_version(monkeypatch, capsys):
    old = b"old-token-value-00000"
    new = b"new-token-value-11111"
    assert len(old) == len(new)

    rc, store, secrets_client, clock, _ = _run_main(monkeypatch, new, not_ready_reads=3, existing_value=old)

    assert rc == 0
    assert store.create_calls == []
    assert len(store.update_calls) == 1
    secret_id, details = store.update_calls[0]
    assert secret_id == _FakeVaultStore.SECRET_ID
    assert _FakeVaultStore._decode(details) == new
    # One read-before-write (the duplicate-version / precondition check), then
    # three stale propagation reads, then the match.
    assert secrets_client.reads == 5
    assert store.read_history == [old, old, old, old, new]
    _assert_bounded_increasing_backoff(clock.slept, timeout=120)
    _assert_full_jitter(clock, clock.slept)
    # The replacement must be fenced on the ETag read just before it, or a
    # concurrent rotation leg silently loses a version.
    assert store.get_secret_calls == [_FakeVaultStore.SECRET_ID]
    assert store.update_if_match == [store.etag_history[0]]
    out = capsys.readouterr().out
    assert "new version" in out
    assert f"write_etag: {store.etag}" in out


def test_accepted_write_readback_timeout_is_an_unknown_mutation(monkeypatch):
    old = b"old-token-value-00000"
    new = b"new-token-value-11111"

    with pytest.raises(vps.MutationOutcomeUnknownError, match="accepted"):
        _run_main(
            monkeypatch,
            new,
            not_ready_reads=200,
            existing_value=old,
            extra_args=("--readable-timeout", "1"),
        )


def test_lost_update_response_reuses_paginated_pending_version(monkeypatch, capsys):
    old = b"old-active-token"
    new = b"accepted-pending-token"
    store, secrets_clients, _ = _install_fake_oci(monkeypatch, not_ready_reads=2, existing_value=old)
    store.pending_value = new
    store.remaining = 2
    store.version_pages = [
        [types.SimpleNamespace(name="unrelated-version", stages=["DEPRECATED"])],
        [types.SimpleNamespace(name=f"acx-{_digest(new)[:32]}", stages=["CURRENT", "LATEST"])],
    ]
    _install_fake_clock(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["_vault_put_secret.py", "--secret-name", "OCIR_AUTH_TOKEN"])
    monkeypatch.setattr(
        sys,
        "stdin",
        types.SimpleNamespace(isatty=lambda: False, buffer=io.BytesIO(new)),
    )

    assert vps.main() == 0
    assert store.update_calls == []
    assert secrets_clients[0].reads == 3
    assert [call["page"] for call in store.version_calls] == [None, "page-2"]
    assert all(call["sort_by"] == "VERSION_NUMBER" for call in store.version_calls)
    assert all(call["sort_order"] == "DESC" for call in store.version_calls)
    assert "existing version pending" in capsys.readouterr().out


@pytest.mark.parametrize(
    "piped, label",
    [(b"", "empty pipe"), (b"\n", "newline only"), (b"\r\n", "CRLF only")],
)
def test_main_refuses_to_store_an_empty_value(monkeypatch, piped, label):
    # `pbpaste | ocir-token-rotate --stdin` with nothing on the clipboard pipes
    # zero bytes. Stored, that becomes an ACTIVE secret holding an empty token,
    # and the next deploy fails at OCIR with a 401 that looks exactly like a
    # revoked credential -- sending the operator to mint a token they already
    # have. Refuse at the boundary instead.
    _, secrets_clients, _ = _install_fake_oci(monkeypatch, 0)
    _install_fake_clock(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["_vault_put_secret.py", "--secret-name", "OCIR_AUTH_TOKEN"])
    monkeypatch.setattr(sys, "stdin", types.SimpleNamespace(isatty=lambda: False, buffer=io.BytesIO(piped)))
    with pytest.raises(SystemExit) as excinfo:
        vps.main()
    assert "empty" in str(excinfo.value), label
    # Nothing may reach the vault on this path.
    assert secrets_clients == []


def test_main_refuses_to_prompt_when_stdin_is_a_terminal(monkeypatch):
    # Without this, a bare invocation blocks on a read the operator cannot see,
    # which reads as a hang.
    _, secrets_clients, _ = _install_fake_oci(monkeypatch, 0)
    _install_fake_clock(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["_vault_put_secret.py", "--secret-name", "OCIR_AUTH_TOKEN"])
    monkeypatch.setattr(sys, "stdin", types.SimpleNamespace(isatty=lambda: True, buffer=io.BytesIO(b"x")))
    with pytest.raises(SystemExit) as excinfo:
        vps.main()
    assert "stdin" in str(excinfo.value)
    assert secrets_clients == []


# --- Vault context/listing validation ----------------------------------------


def _secret(name, key_id, lifecycle_state="ACTIVE"):
    return types.SimpleNamespace(
        secret_name=name,
        key_id=key_id,
        lifecycle_state=lifecycle_state,
    )


class _FakeKms:
    def get_vault(self, vault_id):
        return types.SimpleNamespace(data=types.SimpleNamespace(compartment_id="ocid1.compartment.oc1..c"))


def test_explicit_key_bootstraps_an_empty_vault(monkeypatch, capsys):
    key_id = "ocid1.key.oc1..explicit"
    rc, store, secrets_client, _, _ = _run_main(
        monkeypatch,
        b"token",
        0,
        sibling_secrets=[],
        extra_args=("--key-id", key_id, "--readable-timeout", "0"),
    )

    assert rc == 0
    assert store.create_calls[0].key_id == key_id
    assert all(call["name"] is not None for call in store.list_calls)
    assert secrets_client is None
    # --readable-timeout 0 skips the read-back, so the report must say the write
    # is unverified rather than imply the value was confirmed readable.
    assert "ACCEPTED-BUT-UNVERIFIED" in capsys.readouterr().out


def test_empty_vault_without_explicit_key_names_the_recovery_flag():
    class EmptyVaults:
        def list_secrets(self, **kwargs):
            return types.SimpleNamespace(data=[], headers={})

    with pytest.raises(SystemExit) as excinfo:
        vps.resolve_vault_context(_FakeKms(), EmptyVaults(), "ocid1.vault.oc1..v")
    assert "--key-id" in str(excinfo.value)


def test_divergent_sibling_keys_are_rejected_explicitly():
    keys = {"ocid1.key.oc1..a", "ocid1.key.oc1..b"}

    class DivergentVaults:
        def list_secrets(self, **kwargs):
            return types.SimpleNamespace(data=[_secret("A", key) for key in keys], headers={})

    with pytest.raises(RuntimeError, match="divergent") as excinfo:
        vps.resolve_vault_context(_FakeKms(), DivergentVaults(), "ocid1.vault.oc1..v")
    assert all(key in str(excinfo.value) for key in keys)


def test_sibling_lookup_follows_every_page():
    calls = []
    key_id = "ocid1.key.oc1..shared"

    class PaginatedVaults:
        def list_secrets(self, **kwargs):
            calls.append(kwargs)
            if kwargs.get("page") is None:
                return types.SimpleNamespace(
                    data=[_secret("A", key_id)],
                    headers={"opc-next-page": "page-2"},
                )
            return types.SimpleNamespace(data=[_secret("B", key_id)], headers={})

    assert vps.resolve_vault_context(_FakeKms(), PaginatedVaults(), "ocid1.vault.oc1..v") == (
        "ocid1.compartment.oc1..c",
        key_id,
    )
    assert [call.get("page") for call in calls] == [None, "page-2"]
    assert all(call["lifecycle_state"] == "ACTIVE" for call in calls)


def test_find_secret_rejects_non_active_name_match():
    calls = []

    class DeletedVaults:
        def list_secrets(self, **kwargs):
            calls.append(kwargs)
            return types.SimpleNamespace(
                data=[_secret("TARGET", "ocid1.key.oc1..k", "DELETED")],
                headers={},
            )

    assert vps.find_secret(DeletedVaults(), "ocid1.compartment.oc1..c", "ocid1.vault.oc1..v", "TARGET") is None
    assert calls[0]["name"] == "TARGET"
    assert calls[0]["lifecycle_state"] == "ACTIVE"
