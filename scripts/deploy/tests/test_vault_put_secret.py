"""Regression tests for the bounded Vault secret writer."""

from __future__ import annotations

import importlib.util
import io
import random
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "_vault_put_secret.py"
SPEC = importlib.util.spec_from_file_location("vault_put_secret", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
vault_put_secret = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(vault_put_secret)


def test_blocking_control_call_is_bounded() -> None:
    started = time.monotonic()

    def stall() -> None:
        time.sleep(1)

    with pytest.raises(vault_put_secret.OperationDeadlineError, match="discovery.*deadline"):
        vault_put_secret.call_with_deadline(stall, 0.02, "discovery")

    assert time.monotonic() - started < 0.5


def test_timed_out_mutation_is_unknown() -> None:
    def stall() -> None:
        time.sleep(1)

    with pytest.raises(vault_put_secret.MutationOutcomeUnknownError, match="UNKNOWN"):
        vault_put_secret.call_with_deadline(stall, 0.02, "update OCIR_AUTH_TOKEN", mutation=True)


def test_identical_existing_value_skips_update() -> None:
    existing = SimpleNamespace(id="ocid1.vaultsecret.test", secret_name="OCIR_AUTH_TOKEN")
    updates: list[bytes] = []

    secret, action = vault_put_secret.write_secret_if_needed(
        existing=existing,
        value=b"same-token",
        read_current=lambda: b"same-token",
        create_secret=lambda: pytest.fail("create must not run"),
        update_secret=lambda: updates.append(b"called"),
    )

    assert secret is existing
    assert action == "already current"
    assert updates == []


def test_main_reconciles_identical_value_with_stubbed_oci(monkeypatch, capsys) -> None:
    existing = SimpleNamespace(
        id="ocid1.vaultsecret.test",
        secret_name="OCIR_AUTH_TOKEN",
        key_id="ocid1.key.test",
        lifecycle_state="ACTIVE",
    )
    updates: list[object] = []

    class Client:
        def __init__(self, *_args, **_kwargs):
            self.base_client = SimpleNamespace(timeout=None)

    class VaultsClient(Client):
        def list_secrets(self, **_kwargs):
            return SimpleNamespace(data=[existing], headers={})

        def create_secret(self, *_args, **_kwargs):
            pytest.fail("create must not run")

        def update_secret(self, *_args, **_kwargs):
            updates.append(object())
            return SimpleNamespace(data=existing)

    class KmsVaultClient(Client):
        def get_vault(self, *_args, **_kwargs):
            return SimpleNamespace(data=SimpleNamespace(compartment_id="ocid1.compartment.test"))

    class SecretsClient(Client):
        def get_secret_bundle_by_name(self, **_kwargs):
            encoded = "c2FtZS10b2tlbg=="
            content = SimpleNamespace(content=encoded)
            return SimpleNamespace(data=SimpleNamespace(secret_bundle_content=content))

    class Details:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    fake_oci = SimpleNamespace(
        config=SimpleNamespace(from_file=lambda **_kwargs: {}),
        retry=SimpleNamespace(NoneRetryStrategy=lambda: object()),
        vault=SimpleNamespace(
            VaultsClient=VaultsClient,
            models=SimpleNamespace(
                Base64SecretContentDetails=Details,
                CreateSecretDetails=Details,
                UpdateSecretDetails=Details,
            ),
        ),
        key_management=SimpleNamespace(KmsVaultClient=KmsVaultClient),
        secrets=SimpleNamespace(SecretsClient=SecretsClient),
    )

    class Stdin:
        buffer = io.BytesIO(b"same-token")

        @staticmethod
        def isatty() -> bool:
            return False

    monkeypatch.setitem(sys.modules, "oci", fake_oci)
    monkeypatch.setattr(sys, "stdin", Stdin())
    monkeypatch.setattr(
        sys,
        "argv",
        ["_vault_put_secret.py", "--secret-name", "OCIR_AUTH_TOKEN", "--readable-timeout", "0"],
    )

    assert vault_put_secret.main() == 0
    assert updates == []
    assert "already current" in capsys.readouterr().out


def _retry_delays(seed: int) -> list[float]:
    now = [0.0]
    delays: list[float] = []
    rng = random.Random(seed)

    def monotonic() -> float:
        return now[0]

    def sleep(delay: float) -> None:
        delays.append(delay)
        # Ensure even a zero jitter draw advances the synthetic clock.
        now[0] += max(delay, 0.01)

    def unavailable() -> bytes:
        raise ConnectionError("not ready")

    with pytest.raises(vault_put_secret.SecretNotReadableError):
        vault_put_secret.wait_until_readable(
            unavailable,
            "OCIR_AUTH_TOKEN",
            "unused",
            timeout=2,
            sleep=sleep,
            monotonic=monotonic,
            random_uniform=rng.uniform,
        )
    return delays


def test_read_back_retries_use_full_jitter() -> None:
    first = _retry_delays(1)
    second = _retry_delays(2)

    assert first != second
    assert all(0 <= delay <= 2 for delay in first + second)
