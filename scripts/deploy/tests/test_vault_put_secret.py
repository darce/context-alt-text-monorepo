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
    existing = SimpleNamespace(
        id="ocid1.vaultsecret.oc1.iad.FAKE_OCIR_AUTH_TOKEN_TEST_000000000001",
        secret_name="OCIR_AUTH_TOKEN",
    )
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


def test_writer_allows_gpu_endpoint_key_only_in_owned_vault() -> None:
    vault_put_secret.validate_destination(
        vault_put_secret.DEFAULT_VAULT_OCID,
        "ACX_GPU_ENDPOINT_API_KEY",
    )
    with pytest.raises(SystemExit, match="refusing unowned vault"):
        vault_put_secret.validate_destination(
            "ocid1.vault.oc1.iad.attacker",
            "ACX_GPU_ENDPOINT_API_KEY",
        )


def test_writer_requires_a_64_byte_hex_gpu_key() -> None:
    vault_put_secret.validate_gpu_endpoint_key(b"a" * 64)
    with pytest.raises(ValueError, match="64 hexadecimal bytes"):
        vault_put_secret.validate_gpu_endpoint_key(b"not-a-credential")


@pytest.mark.parametrize(
    "secret_id",
    [
        "ocid1.vault.oc1.iad." + "a" * 40,
        "ocid1.vaultsecret.oc1..fakegpuapikey123",
        "ocid1.vaultsecret.oc1.iad.fakegpuapikey123",
        "ocid1.vaultsecret.oc1.iad.fakegpuapikey123\nextra",
        "ocid1.vaultsecret.oc1.iad.fakegpuapikey123/extra",
        'ocid1.vaultsecret.oc1.iad.fakegpuapikey123"suffix0123456789',
        "ocid1.vaultsecret.oc1.iad.fakegpuapikey123 suffix0123456789",
        "ocid1.vaultsecret.oc1.iad.",
    ],
)
def test_expected_gpu_secret_id_requires_a_full_vault_secret_ocid(monkeypatch, secret_id) -> None:
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "_vault_put_secret.py",
            "--secret-name",
            "ACX_GPU_ENDPOINT_API_KEY",
            "--expected-secret-id",
            secret_id,
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        vault_put_secret.main()

    assert exc_info.value.code == 2


@pytest.mark.parametrize(
    "secret_id",
    [
        "ocid1.vaultsecret.oc1.iad.FAKE_GPU_KEY_0123456789_abcd-efgh.ijkl",
        "ocid1.vaultsecret.oc22..Fake_Global_Secret.Part-0123456789",
    ],
)
def test_expected_gpu_secret_id_accepts_the_complete_vault_grammar(secret_id) -> None:
    assert vault_put_secret._vault_secret_ocid(secret_id) == secret_id


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
        id="ocid1.vaultsecret.oc1.iad.FAKE_OCIR_AUTH_TOKEN_TEST_000000000001",
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


def test_instance_principal_option_is_rejected_by_argparse(monkeypatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["_vault_put_secret.py", "--secret-name", "ACX_GPU_ENDPOINT_API_KEY", "--instance-principal"],
    )

    with pytest.raises(SystemExit) as exc_info:
        vault_put_secret.main()

    assert exc_info.value.code == 2


def test_gpu_bootstrap_reuses_existing_key_and_rotation_reuses_its_ocid(monkeypatch, capsys) -> None:
    existing = SimpleNamespace(
        id="ocid1.vaultsecret.oc22..FAKE_GPU_API_KEY_TEST_000000000001",
        secret_name="ACX_GPU_ENDPOINT_API_KEY",
        key_id="ocid1.key.test",
        lifecycle_state="ACTIVE",
    )
    sibling = SimpleNamespace(
        id="ocid1.vaultsecret.oc1.iad.FAKE_SIBLING_SECRET_TEST_000000000001",
        secret_name="OCIR_USERNAME",
        key_id="ocid1.key.test",
        lifecycle_state="ACTIVE",
    )
    current_value = [b"b" * 64]
    existing_present = [True]
    create_response_id: list[str | None] = [None]
    updates: list[str] = []
    created_values: list[bytes] = []
    profile_config = {"profile": "DEFAULT"}
    loaded_profiles: list[str] = []
    passed_configs: list[object] = []

    class Client:
        def __init__(self, config, **_kwargs):
            passed_configs.append(config)
            self.base_client = SimpleNamespace(timeout=None)

    class VaultsClient(Client):
        def list_secrets(self, **kwargs):
            if existing_present[0]:
                data = [existing]
            elif kwargs.get("name") == "ACX_GPU_ENDPOINT_API_KEY":
                data = []
            else:
                data = [sibling]
            return SimpleNamespace(data=data, headers={})

        def list_secret_versions(self, *_args, **_kwargs):
            return SimpleNamespace(data=[], headers={})

        def get_secret(self, *_args, **_kwargs):
            return SimpleNamespace(data=existing, headers={"etag": "etag-current"})

        def create_secret(self, details, **_kwargs):
            created_values.append(base64.b64decode(details.secret_content.content))
            current_value[0] = created_values[-1]
            existing_present[0] = True
            created = existing
            if create_response_id[0] is not None:
                created = SimpleNamespace(id=create_response_id[0], secret_name=existing.secret_name)
            return SimpleNamespace(data=created, headers={"etag": "etag-created"})

        def update_secret(self, secret_id, details, **_kwargs):
            updates.append(secret_id)
            current_value[0] = base64.b64decode(details.secret_content.content)
            return SimpleNamespace(data=existing, headers={"etag": "etag-updated"})

    class KmsVaultClient(Client):
        def get_vault(self, *_args, **_kwargs):
            return SimpleNamespace(data=SimpleNamespace(compartment_id="ocid1.compartment.test"))

    class SecretsClient(Client):
        def get_secret_bundle_by_name(self, **_kwargs):
            content = SimpleNamespace(content=base64.b64encode(current_value[0]).decode("ascii"))
            return SimpleNamespace(data=SimpleNamespace(secret_bundle_content=content))

    class Details:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    def from_file(*, profile_name):
        loaded_profiles.append(profile_name)
        return profile_config

    fake_oci = SimpleNamespace(
        config=SimpleNamespace(from_file=from_file),
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
    monkeypatch.setattr(sys, "argv", [
        "_vault_put_secret.py",
        "--secret-name",
        "ACX_GPU_ENDPOINT_API_KEY",
        "--bootstrap",
        "--result-only",
        "--readable-timeout",
        "0",
    ])
    monkeypatch.setattr(
        sys,
        "stdin",
        SimpleNamespace(buffer=io.BytesIO(b"unused-bootstrap-candidate"), isatty=lambda: False),
    )

    assert vault_put_secret.main() == 0
    assert capsys.readouterr().out == f"{existing.id} {len(current_value[0])}\n"
    assert updates == []
    assert loaded_profiles == ["DEFAULT"]
    assert len(passed_configs) >= 2
    assert all(config is profile_config for config in passed_configs)

    monkeypatch.setattr(sys, "argv", [
        "_vault_put_secret.py",
        "--secret-name",
        "ACX_GPU_ENDPOINT_API_KEY",
        "--rotate-existing",
        "--result-only",
        "--readable-timeout",
        "0",
    ])
    monkeypatch.setattr(
        sys,
        "stdin",
        SimpleNamespace(buffer=io.BytesIO(b"c" * 64), isatty=lambda: False),
    )

    assert vault_put_secret.main() == 0
    assert capsys.readouterr().out == f"{existing.id} 64\n"
    assert updates == [existing.id]

    expected_id = existing.id

    def run_with_expected_id(mode: str, remote_id: str | None, candidate: bytes) -> None:
        existing_present[0] = remote_id is not None
        if remote_id is not None:
            existing.id = remote_id
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "_vault_put_secret.py",
                "--secret-name",
                "ACX_GPU_ENDPOINT_API_KEY",
                mode,
                "--expected-secret-id",
                expected_id,
                "--result-only",
                "--readable-timeout",
                "0",
            ],
        )
        monkeypatch.setattr(
            sys,
            "stdin",
            SimpleNamespace(buffer=io.BytesIO(candidate), isatty=lambda: False),
        )

    # An expected identity binds the name-selected secret before any write.
    # Missing and recreated secrets are refusals in both modes.
    for mode in ("--bootstrap", "--rotate-existing"):
        before = (len(created_values), len(updates))
        run_with_expected_id(mode, None, b"g" * 64)
        with pytest.raises(RuntimeError, match="expected secret identity"):
            vault_put_secret.main()
        assert (len(created_values), len(updates)) == before

        run_with_expected_id(mode, "ocid1.vaultsecret.oc1.iad.RECREATED_GPU_API_KEY_TEST_000000000001", b"h" * 64)
        with pytest.raises(RuntimeError, match="expected secret identity"):
            vault_put_secret.main()
        assert (len(created_values), len(updates)) == before

    # A matching identity permits bootstrap and explicitly requested rotation.
    run_with_expected_id("--bootstrap", expected_id, b"i" * 64)
    assert vault_put_secret.main() == 0
    assert capsys.readouterr().out == f"{expected_id} 64\n"
    assert updates == [expected_id]

    run_with_expected_id("--rotate-existing", expected_id, b"f" * 64)
    assert vault_put_secret.main() == 0
    assert capsys.readouterr().out == f"{expected_id} 64\n"
    assert updates == [expected_id, expected_id]

    existing_present[0] = False
    monkeypatch.setattr(sys, "argv", [
        "_vault_put_secret.py",
        "--secret-name",
        "ACX_GPU_ENDPOINT_API_KEY",
        "--key-id",
        "ocid1.key.test",
        "--result-only",
        "--readable-timeout",
        "0",
    ])
    monkeypatch.setattr(
        sys,
        "stdin",
        SimpleNamespace(buffer=io.BytesIO(b"e" * 64), isatty=lambda: False),
    )

    assert vault_put_secret.main() == 0
    assert capsys.readouterr().out == f"{existing.id} 64\n"
    assert created_values == [b"e" * 64]
    assert updates == [existing.id, existing.id]

    # A GPU write without an explicit mode is a safe bootstrap: it may create
    # an absent key, but an existing key is read and left unchanged.
    monkeypatch.setattr(sys, "argv", [
        "_vault_put_secret.py",
        "--secret-name",
        "ACX_GPU_ENDPOINT_API_KEY",
        "--result-only",
        "--readable-timeout",
        "0",
    ])
    monkeypatch.setattr(
        sys,
        "stdin",
        SimpleNamespace(buffer=io.BytesIO(b"d" * 64), isatty=lambda: False),
    )

    assert vault_put_secret.main() == 0
    assert capsys.readouterr().out == f"{existing.id} 64\n"
    assert updates == [existing.id, existing.id]

    # A malformed discovered identity must fail before either bootstrap or an
    # explicitly requested rotation can create or update a secret.
    for malformed_id in (
        "ocid1.vaultsecret.oc1.iad.short",
        "ocid1.vaultsecret.oc1.iad.invalid/secret-id-0123456789",
    ):
        existing.id = malformed_id
        for mode in ("--bootstrap", "--rotate-existing"):
            before = (len(created_values), len(updates))
            monkeypatch.setattr(sys, "argv", [
                "_vault_put_secret.py",
                "--secret-name",
                "ACX_GPU_ENDPOINT_API_KEY",
                mode,
                "--result-only",
                "--readable-timeout",
                "0",
            ])
            monkeypatch.setattr(
                sys,
                "stdin",
                SimpleNamespace(buffer=io.BytesIO(b"z" * 64), isatty=lambda: False),
            )
            with pytest.raises(RuntimeError, match="invalid Vault secret OCID"):
                vault_put_secret.main()
            assert (len(created_values), len(updates)) == before

    existing.id = expected_id
    existing_present[0] = False
    create_response_id[0] = "ocid1.vaultsecret.oc1.iad.malformed/secret-id-0123456789"
    monkeypatch.setattr(sys, "argv", [
        "_vault_put_secret.py",
        "--secret-name",
        "ACX_GPU_ENDPOINT_API_KEY",
        "--result-only",
        "--readable-timeout",
        "0",
    ])
    monkeypatch.setattr(
        sys,
        "stdin",
        SimpleNamespace(buffer=io.BytesIO(b"f" * 64), isatty=lambda: False),
    )
    before_creates = len(created_values)
    with pytest.raises(RuntimeError, match="did not return a valid secret OCID"):
        vault_put_secret.main()
    assert len(created_values) == before_creates + 1
    assert created_values[-1] == b"f" * 64
    assert capsys.readouterr().out == ""
    assert loaded_profiles and all(profile == "DEFAULT" for profile in loaded_profiles)
    assert len(passed_configs) >= 2 * len(loaded_profiles)
    assert all(config is profile_config for config in passed_configs)


def test_profile_config_constructs_real_sdk_clients_without_network() -> None:
    import oci
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_key_content = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("ascii")
    profile_config = {
        "user": "ocid1.user.oc1..aaaaaaaa",
        "tenancy": "ocid1.tenancy.oc1..aaaaaaaa",
        "fingerprint": "00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00",
        "key_file": "/unused/test-key.pem",
        "key_content": private_key_content,
        "region": "us-ashburn-1",
    }
    no_retry = oci.retry.NoneRetryStrategy()
    timeout = (1.0, 1.0)
    clients = (
        (oci.vault.VaultsClient, oci.vault.VaultsClient),
        (oci.key_management.KmsVaultClient, oci.key_management.KmsVaultClient),
        (oci.secrets.SecretsClient, oci.secrets.SecretsClient),
    )

    for factory, client_type in clients:
        client = vault_put_secret._make_client(factory, profile_config, no_retry, timeout)
        assert isinstance(client, client_type)
        assert client.base_client.config == profile_config


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
