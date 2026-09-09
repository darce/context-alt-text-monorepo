"""Regression tests for the bounded Vault secret writer."""

from __future__ import annotations

import base64
import importlib.util
import io
import random
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

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


def test_mutation_retry_token_is_stable_and_value_specific() -> None:
    first = vault_put_secret.mutation_retry_token(
        "ocid1.vault.test",
        "OCIR_AUTH_TOKEN",
        b"token-one",
    )
    repeated = vault_put_secret.mutation_retry_token(
        "ocid1.vault.test",
        "OCIR_AUTH_TOKEN",
        b"token-one",
    )
    changed = vault_put_secret.mutation_retry_token(
        "ocid1.vault.test",
        "OCIR_AUTH_TOKEN",
        b"token-two",
    )

    assert first == repeated
    assert first != changed
    assert len(first) == 64


def test_missing_update_etag_is_rejected_explicitly() -> None:
    with pytest.raises(RuntimeError, match="missing.*ETag"):
        vault_put_secret.require_etag(SimpleNamespace(headers={}), "OCIR_AUTH_TOKEN")


@pytest.mark.parametrize("name", ["POSTGRES_DSN", "RECOGNITION_ADMIN_TOKEN"])
def test_writer_rejects_unowned_secret_names(name) -> None:
    with pytest.raises(SystemExit, match="refusing unowned secret name"):
        vault_put_secret.validate_destination(vault_put_secret.DEFAULT_VAULT_OCID, name)


def test_writer_rejects_non_acx_vault() -> None:
    with pytest.raises(SystemExit, match="refusing unowned vault"):
        vault_put_secret.validate_destination("ocid1.vault.oc1.iad.attacker", "OCIR_AUTH_TOKEN")


def test_generation_lock_rejects_non_stable_current_value() -> None:
    with pytest.raises(RuntimeError, match="required prefix"):
        vault_put_secret.validate_current_prefix(
            b"UPDATING:other-rotation",
            "STABLE:",
            "OCIR_CREDENTIAL_GENERATION",
        )


def test_main_uses_idempotency_controls_with_stubbed_oci(monkeypatch, capsys) -> None:
    existing = SimpleNamespace(
        id="ocid1.vaultsecret.test",
        secret_name="OCIR_AUTH_TOKEN",
        key_id="ocid1.key.test",
        lifecycle_state="ACTIVE",
    )
    current_value = [b"same-token"]
    existing_present = [True]
    creates: list[tuple[object, dict[str, object]]] = []
    updates: list[tuple[tuple[object, ...], dict[str, object]]] = []

    class Client:
        def __init__(self, *_args, **_kwargs):
            self.base_client = SimpleNamespace(timeout=None)

    class VaultsClient(Client):
        def list_secrets(self, **_kwargs):
            return SimpleNamespace(data=[existing] if existing_present[0] else [], headers={})

        def list_secret_versions(self, *_args, **_kwargs):
            return SimpleNamespace(data=[], headers={})

        def get_secret(self, *_args, **_kwargs):
            return SimpleNamespace(data=existing, headers={"etag": "etag-current"})

        def create_secret(self, details, **kwargs):
            creates.append((details, kwargs))
            current_value[0] = base64.b64decode(details.secret_content.content)
            existing_present[0] = True
            return SimpleNamespace(data=existing, headers={"etag": "etag-created"})

        def update_secret(self, *args, **kwargs):
            updates.append((args, kwargs))
            current_value[0] = base64.b64decode(args[1].secret_content.content)
            return SimpleNamespace(data=existing, headers={"etag": "etag-updated"})

    class KmsVaultClient(Client):
        def get_vault(self, *_args, **_kwargs):
            return SimpleNamespace(data=SimpleNamespace(compartment_id="ocid1.compartment.test"))

    class SecretsClient(Client):
        def get_secret_bundle_by_name(self, **_kwargs):
            encoded = base64.b64encode(current_value[0]).decode("ascii")
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

    monkeypatch.setitem(sys.modules, "oci", fake_oci)
    monkeypatch.setattr(
        sys,
        "argv",
        ["_vault_put_secret.py", "--secret-name", "OCIR_AUTH_TOKEN", "--readable-timeout", "0"],
    )

    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(b"same-token"), isatty=lambda: False))
    assert vault_put_secret.main() == 0
    assert updates == []
    assert "already current" in capsys.readouterr().out

    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(b"new-token"), isatty=lambda: False))
    assert vault_put_secret.main() == 0
    assert updates[0][1]["if_match"] == "etag-current"

    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(b"fenced-token"), isatty=lambda: False))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "_vault_put_secret.py",
            "--secret-name",
            "OCIR_AUTH_TOKEN",
            "--if-match",
            "etag-owned-write",
            "--readable-timeout",
            "0",
        ],
    )
    assert vault_put_secret.main() == 0
    assert updates[-1][1]["if_match"] == "etag-owned-write"

    existing_present[0] = False
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(b"first-token"), isatty=lambda: False))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "_vault_put_secret.py",
            "--secret-name",
            "OCIR_AUTH_TOKEN",
            "--key-id",
            "ocid1.key.test",
            "--readable-timeout",
            "0",
        ],
    )
    assert vault_put_secret.main() == 0
    assert creates[0][1]["opc_retry_token"] == vault_put_secret.mutation_retry_token(
        vault_put_secret.DEFAULT_VAULT_OCID,
        "OCIR_AUTH_TOKEN",
        b"first-token",
    )


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


@pytest.mark.parametrize("flag", ["--readable-timeout", "--operation-timeout"])
@pytest.mark.parametrize("timeout", ["-1", "nan", "inf", "-inf", "abc"])
def test_invalid_timeout_is_rejected_before_vault_mutation(monkeypatch, flag, timeout) -> None:
    vaults_client = Mock()
    fake_oci = SimpleNamespace(
        vault=SimpleNamespace(VaultsClient=Mock(return_value=vaults_client)),
    )
    monkeypatch.setitem(sys.modules, "oci", fake_oci)
    monkeypatch.setattr(
        sys,
        "argv",
        ["_vault_put_secret.py", "--secret-name", "OCIR_AUTH_TOKEN", flag, timeout],
    )

    with pytest.raises(SystemExit) as exc_info:
        vault_put_secret.main()

    assert exc_info.value.code == 2
    vaults_client.create_secret.assert_not_called()
    vaults_client.update_secret.assert_not_called()
