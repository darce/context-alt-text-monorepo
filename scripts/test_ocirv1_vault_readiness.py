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
    """Assert the retry policy without freezing its safe tuning factor."""
    assert delays
    assert all(0 < delay <= 5.0 for delay in delays)
    assert len(set(delays)) > 1, "retry delay must not remain constant"
    for previous, current in zip(delays, delays[1:]):
        if previous < 5.0:
            assert current > previous
        else:
            assert current == 5.0
    assert sum(delays) < timeout


class Runaway(AssertionError):
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

    def __init__(self):
        self.slept = []
        self.now = 0.0

    def __call__(self, seconds):
        self.slept.append(seconds)
        self.now += seconds
        if len(self.slept) > self.MAX_SLEEPS:
            raise Runaway(
                f"polled {len(self.slept)} times without honouring the deadline"
            )

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
            raise RuntimeError("404 NotAuthorizedOrNotFound")
        return value

    clock = _Clock()
    assert vps.wait_until_readable(
        read_bundle, "OCIR_AUTH_TOKEN", _digest(value), timeout=60,
        sleep=clock, monotonic=clock.monotonic,
    )
    assert calls["n"] == not_ready_reads + 1
    # A slow propagation must not become a constant-delay hot loop against the
    # control plane. Assert the operational contract while leaving the safe
    # growth factor free to be tuned.
    _assert_bounded_increasing_backoff(clock.slept, timeout=60)


def test_the_exact_live_failure_no_longer_escapes():
    """The 404 the operator saw must be absorbed, not surfaced."""
    value = b"20-byte-token-xxxxxx"
    seq = iter(
        [
            RuntimeError(
                'ServiceError: {"code": "NotAuthorizedOrNotFound", "status": 404, '
                '"operation_name": "get_secret_bundle_by_name"}'
            ),
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
        read_bundle, "OCIR_AUTH_TOKEN", _digest(value), timeout=60,
        sleep=clock, monotonic=clock.monotonic,
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
    with pytest.raises(vps.SecretNotReadable) as excinfo:
        vps.wait_until_readable(
            lambda: old, "OCIR_AUTH_TOKEN", _digest(new), timeout=0,
            sleep=clock, monotonic=clock.monotonic,
        )
    assert "do not match" in str(excinfo.value)


def test_gives_up_with_an_actionable_message():
    def read_bundle():
        raise RuntimeError("404 NotAuthorizedOrNotFound")

    clock = _Clock()
    with pytest.raises(vps.SecretNotReadable) as excinfo:
        vps.wait_until_readable(
            lambda: read_bundle(), "OCIR_AUTH_TOKEN", _digest(b"x"),
            timeout=0, sleep=clock, monotonic=clock.monotonic,
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
    # Runaway rather than a hung suite.
    started = time.monotonic()
    clock = _Clock()
    with pytest.raises(vps.SecretNotReadable):
        vps.wait_until_readable(
            lambda: b"never-matches", "S", _digest(b"target"),
            timeout=30, sleep=clock, monotonic=clock.monotonic,
        )
    assert time.monotonic() - started < 5


def test_secret_value_never_appears_in_the_failure_message():
    secret = b"super-secret-token-value"
    clock = _Clock()
    with pytest.raises(vps.SecretNotReadable) as excinfo:
        vps.wait_until_readable(
            lambda: secret, "OCIR_AUTH_TOKEN", _digest(b"different"),
            timeout=0, sleep=clock, monotonic=clock.monotonic,
        )
    message = str(excinfo.value)
    assert secret.decode() not in message
    # Nor may the digest leak: it is a verification oracle for a short,
    # fixed-charset token.
    assert _digest(secret) not in message


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
            )
        self.create_calls = []
        self.update_calls = []
        self.read_history = []

    @staticmethod
    def _decode(details):
        return base64.b64decode(details.secret_content.content)

    def _stage(self, value):
        self.pending_value = value
        self.remaining = self.not_ready_reads

    def create(self, details):
        self.create_calls.append(details)
        self.existing = types.SimpleNamespace(
            secret_name=details.secret_name,
            key_id=details.key_id,
            id=self.SECRET_ID,
        )
        self._stage(self._decode(details))
        return self.existing

    def update(self, secret_id, details):
        self.update_calls.append((secret_id, details))
        self._stage(self._decode(details))
        return self.existing

    def read(self):
        if self.pending_value is not None:
            if self.remaining > 0:
                self.remaining -= 1
                if self.active_value is None:
                    raise RuntimeError(
                        'ServiceError: {"code": "NotAuthorizedOrNotFound", '
                        '"status": 404, "operation_name": '
                        '"get_secret_bundle_by_name"}'
                    )
            else:
                self.active_value = self.pending_value
                self.pending_value = None
        if self.active_value is None:
            raise AssertionError("read attempted before a version was submitted")
        self.read_history.append(self.active_value)
        return self.active_value


class _FakeSecretsClient:
    """Consumer API backed by the content actually submitted to fake Vault."""

    def __init__(self, store):
        self._store = store
        self.reads = 0

    def get_secret_bundle_by_name(self, secret_name, vault_id):
        self.reads += 1
        value = self._store.read()
        content = types.SimpleNamespace(
            content=base64.b64encode(value).decode("ascii")
        )
        return types.SimpleNamespace(
            data=types.SimpleNamespace(secret_bundle_content=content)
        )


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
    return clock


def _install_fake_oci(monkeypatch, not_ready_reads, existing_value=None):
    """Minimal stand-in for the parts of the SDK main() touches."""
    store = _FakeVaultStore(not_ready_reads, existing_value)
    secrets_client = _FakeSecretsClient(store)

    class _Vaults:
        def __init__(self, config):
            pass

        def list_secrets(self, compartment_id, vault_id, name=None):
            sibling = types.SimpleNamespace(
                secret_name="POSTGRES_DSN", key_id="ocid1.key.oc1..sibling", id="s0"
            )
            if name is None:
                return types.SimpleNamespace(data=[sibling])
            matches = []
            if store.existing is not None and store.existing.secret_name == name:
                matches.append(store.existing)
            return types.SimpleNamespace(data=matches)

        def create_secret(self, details):
            return types.SimpleNamespace(data=store.create(details))

        def update_secret(self, secret_id, details):
            return types.SimpleNamespace(data=store.update(secret_id, details))

    class _Kms:
        def __init__(self, config):
            pass

        def get_vault(self, vault_id):
            return types.SimpleNamespace(
                data=types.SimpleNamespace(compartment_id="ocid1.compartment.oc1..c")
            )

    models = types.SimpleNamespace(
        Base64SecretContentDetails=lambda content_type, content: types.SimpleNamespace(
            content_type=content_type, content=content
        ),
        CreateSecretDetails=lambda **kw: types.SimpleNamespace(**kw),
        UpdateSecretDetails=lambda **kw: types.SimpleNamespace(**kw),
    )
    fake = types.ModuleType("oci")
    fake.config = types.SimpleNamespace(from_file=lambda profile_name: {})
    fake.vault = types.SimpleNamespace(VaultsClient=_Vaults, models=models)
    fake.key_management = types.SimpleNamespace(KmsVaultClient=_Kms)
    fake.secrets = types.SimpleNamespace(SecretsClient=lambda config: secrets_client)
    monkeypatch.setitem(sys.modules, "oci", fake)
    monkeypatch.setitem(sys.modules, "oci.vault", fake.vault)
    monkeypatch.setitem(sys.modules, "oci.secrets", fake.secrets)
    monkeypatch.setitem(sys.modules, "oci.key_management", fake.key_management)
    return store, secrets_client


def _run_main(monkeypatch, token, not_ready_reads, existing_value=None):
    store, secrets_client = _install_fake_oci(
        monkeypatch, not_ready_reads, existing_value
    )
    clock = _install_fake_clock(monkeypatch)
    monkeypatch.setattr(
        sys, "argv", ["_vault_put_secret.py", "--secret-name", "OCIR_AUTH_TOKEN"]
    )
    stdin = types.SimpleNamespace(
        isatty=lambda: False, buffer=io.BytesIO(token + b"\n")
    )
    monkeypatch.setattr(sys, "stdin", stdin)
    return vps.main(), store, secrets_client, clock


def test_main_does_not_return_until_the_secret_reads_back(monkeypatch, capsys):
    # Two 404s then success: the shape of the live failure. main() must absorb
    # them. If the gate is ever unwired from main(), reads stays at 0 and this
    # goes red -- the unit tests above cannot see that.
    rc, _, secrets_client, _ = _run_main(
        monkeypatch, b"20-byte-token-xxxxxx", 2
    )
    assert rc == 0
    assert secrets_client.reads == 3
    assert "readable" in capsys.readouterr().out


def test_main_reports_the_byte_count_but_never_the_token(monkeypatch, capsys):
    token = b"super-secret-token-value"
    rc, _, _, _ = _run_main(monkeypatch, token, 0)
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
    _, store, secrets_client, _ = _run_main(monkeypatch, token, 0)
    # The gate compares against sha256 of the *stripped* value, so reaching
    # rc == 0 above already proves the strip; assert the stored payload too.
    assert secrets_client.reads >= 1
    assert len(store.create_calls) == 1
    assert _FakeVaultStore._decode(store.create_calls[0]) == token


def test_main_rotation_waits_for_the_new_submitted_version(monkeypatch, capsys):
    old = b"old-token-value-00000"
    new = b"new-token-value-11111"
    assert len(old) == len(new)

    rc, store, secrets_client, clock = _run_main(
        monkeypatch, new, not_ready_reads=3, existing_value=old
    )

    assert rc == 0
    assert store.create_calls == []
    assert len(store.update_calls) == 1
    secret_id, details = store.update_calls[0]
    assert secret_id == _FakeVaultStore.SECRET_ID
    assert _FakeVaultStore._decode(details) == new
    assert secrets_client.reads == 4
    assert store.read_history == [old, old, old, new]
    _assert_bounded_increasing_backoff(clock.slept, timeout=120)
    assert "new version" in capsys.readouterr().out


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
    _, secrets_client = _install_fake_oci(monkeypatch, 0)
    _install_fake_clock(monkeypatch)
    monkeypatch.setattr(
        sys, "argv", ["_vault_put_secret.py", "--secret-name", "OCIR_AUTH_TOKEN"]
    )
    monkeypatch.setattr(
        sys, "stdin", types.SimpleNamespace(isatty=lambda: False, buffer=io.BytesIO(piped))
    )
    with pytest.raises(SystemExit) as excinfo:
        vps.main()
    assert "empty" in str(excinfo.value), label
    # Nothing may reach the vault on this path.
    assert secrets_client.reads == 0


def test_main_refuses_to_prompt_when_stdin_is_a_terminal(monkeypatch):
    # Without this, a bare invocation blocks on a read the operator cannot see,
    # which reads as a hang.
    _, secrets_client = _install_fake_oci(monkeypatch, 0)
    _install_fake_clock(monkeypatch)
    monkeypatch.setattr(
        sys, "argv", ["_vault_put_secret.py", "--secret-name", "OCIR_AUTH_TOKEN"]
    )
    monkeypatch.setattr(
        sys, "stdin", types.SimpleNamespace(isatty=lambda: True, buffer=io.BytesIO(b"x"))
    )
    with pytest.raises(SystemExit) as excinfo:
        vps.main()
    assert "stdin" in str(excinfo.value)
