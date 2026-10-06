"""Tests for GPU Vault key minting without live OCI, SSH, or GPU calls."""

from __future__ import annotations

import base64
import hashlib
import io
import importlib.util
import os
import stat
import subprocess
import sys
import time
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
HELPER_PATH = REPO_ROOT / "scripts/deploy/_gpu_key_manifest.py"
SCRIPT_PATH = REPO_ROOT / "scripts/deploy/gpu-key-mint.sh"
WRITER_PATH = REPO_ROOT / "scripts/deploy/_vault_put_secret.py"
SPEC = importlib.util.spec_from_file_location("gpu_key_manifest", HELPER_PATH)
assert SPEC is not None and SPEC.loader is not None
gpu_key_manifest = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gpu_key_manifest)
WRITER_SPEC = importlib.util.spec_from_file_location("vault_put_secret", WRITER_PATH)
assert WRITER_SPEC is not None and WRITER_SPEC.loader is not None
vault_put_secret = importlib.util.module_from_spec(WRITER_SPEC)
WRITER_SPEC.loader.exec_module(vault_put_secret)

FAKE_OCID = "ocid1.vaultsecret.oc1.iad.fakegpuapikey123"
OTHER_FAKE_OCID = "ocid1.vaultsecret.oc1.iad.otherfakegpuapikey456"
FAKE_KEY = "a" * 64
MANIFEST_LOCK_TIMEOUT_SECONDS = 5
MANIFEST_TEXT = '''version = 1

[[var]]
name = "ACX_GPU_ENDPOINT_API_KEY"
class = "secret"
targets = ["svc-vm"]
secret = { dev = "host:", staging = "host:", prod = "host:" }

[[var]]
name = "RECOGNITION_VAULT_SECRET_MAP"
class = "config"
targets = ["svc-vm"]
derive_vault_map = true

[[var]]
name = "PGPASSWORD"
class = "secret"
targets = ["svc-vm"]
secret = { prod = "vault:ocid1.vaultsecret.oc1.iad.fakepgpassword" }

[[var]]
name = "POSTGRES_DSN"
class = "secret"
targets = ["svc-vm"]
secret = { prod = "vault:ocid1.vaultsecret.oc1.iad.fakepostgresdsn" }

[[var]]
name = "POSTGRES_SYNC_DSN"
class = "secret"
targets = ["svc-vm"]
secret = { prod = "vault:ocid1.vaultsecret.oc1.iad.fakepostgressyncdsn" }

[[var]]
name = "RECOGNITION_ADMIN_TOKEN"
class = "secret"
targets = ["svc-vm"]
secret = { prod = "vault:ocid1.vaultsecret.oc1.iad.fakeadmintoken" }
'''

FRAGMENTED_MANIFEST = {
    "10-service-shared.toml": '''version = 1

[[var]]
name = "RECOGNITION_VAULT_SECRET_MAP"
class = "config"
targets = ["svc-vm", "svc-fir"]
derive_vault_map = true

[[var]]
name = "POSTGRES_DSN"
class = "secret"
targets = ["svc-vm"]
secret = { prod = "vault:ocid1.vaultsecret.oc1.iad.fakepostgresdsn" }

[[var]]
name = "POSTGRES_SYNC_DSN"
class = "secret"
targets = ["svc-vm"]
secret = { prod = "vault:ocid1.vaultsecret.oc1.iad.fakepostgressyncdsn" }
''',
    "20-service-local.toml": '''version = 1

[[var]]
name = "PGPASSWORD"
class = "secret"
targets = ["svc-local", "svc-vm"]
secret = { local = "keychain:acx-local/PGPASSWORD", prod = "vault:ocid1.vaultsecret.oc1.iad.fakepgpassword" }
''',
    "21-service-vm.toml": '''version = 1

[[var]]
name = "RECOGNITION_ADMIN_TOKEN"
class = "secret"
targets = ["svc-vm"]
secret = { prod = "vault:ocid1.vaultsecret.oc1.iad.fakeadmintoken" }

[[var]]
name = "ACX_GPU_ENDPOINT_API_KEY"
class = "secret"
targets = ["svc-vm"]
secret = { dev = "host:", staging = "host:", prod = "host:" }
''',
}


def _write_fragmented_manifest(directory: Path) -> dict[str, Path]:
    paths = {}
    for name, text in FRAGMENTED_MANIFEST.items():
        path = directory / name
        path.write_text(text, encoding="utf-8")
        paths[name] = path
    return paths


def test_manifest_persists_valid_ocid_for_dev_and_prod_only(tmp_path: Path) -> None:
    path = tmp_path / "10-service-shared.toml"
    path.write_text(MANIFEST_TEXT, encoding="utf-8")
    path.chmod(0o640)

    gpu_key_manifest.set_gpu_key_ocid(path, FAKE_OCID)

    document = tomllib.loads(path.read_text(encoding="utf-8"))
    refs = document["var"][0]["secret"]
    assert refs == {
        "dev": f"oci:{FAKE_OCID}",
        "staging": "host:",
        "prod": f"vault:{FAKE_OCID}",
    }
    assert stat.S_IMODE(path.stat().st_mode) == 0o640
    assert "version = 1" in path.read_text(encoding="utf-8")


def test_manifest_refuses_invalid_placeholder_without_changing_file(tmp_path: Path) -> None:
    path = tmp_path / "10-service-shared.toml"
    path.write_text(MANIFEST_TEXT, encoding="utf-8")

    with pytest.raises(ValueError, match="invalid Vault secret OCID"):
        gpu_key_manifest.set_gpu_key_ocid(path, "ocid1.vaultsecret.oc1..REPLACE")

    assert path.read_text(encoding="utf-8") == MANIFEST_TEXT


def test_manifest_must_be_ready_before_any_mint(tmp_path: Path) -> None:
    path = tmp_path / "10-service-shared.toml"
    path.write_text(MANIFEST_TEXT.replace("derive_vault_map = true", "derive_vault_map = false"), encoding="utf-8")

    with pytest.raises(ValueError, match="requires the svc-vm derived Vault secret map"):
        gpu_key_manifest.check_manifest_ready(path)


def test_fragmented_manifest_readiness_and_update_find_gpu_owner(tmp_path: Path, monkeypatch) -> None:
    paths = _write_fragmented_manifest(tmp_path)
    paths["21-service-vm.toml"].chmod(0o640)
    shared_before = paths["10-service-shared.toml"].read_text(encoding="utf-8")
    local_before = paths["20-service-local.toml"].read_text(encoding="utf-8")
    events = []
    real_fsync = gpu_key_manifest.os.fsync
    real_replace = gpu_key_manifest.os.replace

    def record_fsync(descriptor: int) -> None:
        events.append("fsync")
        real_fsync(descriptor)

    def record_replace(source: Path, target: Path) -> None:
        events.append("replace")
        real_replace(source, target)

    monkeypatch.setattr(gpu_key_manifest.os, "fsync", record_fsync)
    monkeypatch.setattr(gpu_key_manifest.os, "replace", record_replace)

    gpu_key_manifest.check_manifest_ready(paths["10-service-shared.toml"])
    gpu_key_manifest.set_gpu_key_ocid(paths["10-service-shared.toml"], FAKE_OCID)

    shared_after = paths["10-service-shared.toml"].read_text(encoding="utf-8")
    local_after = paths["20-service-local.toml"].read_text(encoding="utf-8")
    vm_after = paths["21-service-vm.toml"].read_text(encoding="utf-8")
    assert shared_after == shared_before
    assert local_after == local_before
    assert events == ["fsync", "replace", "fsync"]
    assert "local = \"keychain:acx-local/PGPASSWORD\"" in local_after
    assert stat.S_IMODE(paths["21-service-vm.toml"].stat().st_mode) == 0o640
    gpu = next(row for row in tomllib.loads(vm_after)["var"] if row["name"] == "ACX_GPU_ENDPOINT_API_KEY")
    assert gpu["secret"] == {
        "dev": f"oci:{FAKE_OCID}",
        "staging": "host:",
        "prod": f"vault:{FAKE_OCID}",
    }


def test_fragmented_manifest_refuses_duplicate_gpu_owner_without_changes(tmp_path: Path) -> None:
    paths = _write_fragmented_manifest(tmp_path)
    duplicate = '''
[[var]]
name = "ACX_GPU_ENDPOINT_API_KEY"
class = "secret"
targets = ["svc-vm"]
secret = { dev = "host:", staging = "host:", prod = "host:" }
'''
    paths["10-service-shared.toml"].write_text(
        paths["10-service-shared.toml"].read_text(encoding="utf-8") + duplicate,
        encoding="utf-8",
    )
    before = {name: path.read_text(encoding="utf-8") for name, path in paths.items()}

    with pytest.raises(ValueError, match="exactly one ACX_GPU_ENDPOINT_API_KEY"):
        gpu_key_manifest.set_gpu_key_ocid(paths["10-service-shared.toml"], FAKE_OCID)

    assert {name: path.read_text(encoding="utf-8") for name, path in paths.items()} == before


def test_terraform_input_artifact_contains_only_durable_identifier(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "gpu-api-key.tfvars"
    events = []
    real_fsync = gpu_key_manifest.os.fsync
    real_replace = gpu_key_manifest.os.replace

    def record_fsync(descriptor: int) -> None:
        events.append("fsync")
        real_fsync(descriptor)

    def record_replace(source: Path, target: Path) -> None:
        events.append("replace")
        real_replace(source, target)

    monkeypatch.setattr(gpu_key_manifest.os, "fsync", record_fsync)
    monkeypatch.setattr(gpu_key_manifest.os, "replace", record_replace)

    gpu_key_manifest.write_terraform_input(path, FAKE_OCID)

    assert path.read_text(encoding="utf-8") == (
        '# Generated by scripts/deploy/gpu-key-mint.sh; identifier only.\n'
        f'gpu_api_key_secret_ocid = "{FAKE_OCID}"\n'
    )
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert events == ["fsync", "replace", "fsync"]

    with pytest.raises(ValueError, match="refusing to replace existing Terraform GPU key input"):
        gpu_key_manifest.write_terraform_input(path, "ocid1.vaultsecret.oc1.iad.differentfakekey")


@pytest.mark.parametrize("destination", ["conflict", "invalid-input", "invalid-manifest-owner"])
def test_mint_preflights_output_destinations_before_remote_writer(
    tmp_path: Path,
    destination: str,
) -> None:
    bin_dir = _fake_cli(tmp_path)
    if destination == "invalid-manifest-owner":
        manifest_dir = tmp_path / "manifest.d"
        manifest_dir.mkdir()
        fragments = _write_fragmented_manifest(manifest_dir)
        owner = fragments["21-service-vm.toml"]
        target = tmp_path / "vm-fragment-target.toml"
        target.write_text(owner.read_text(encoding="utf-8"), encoding="utf-8")
        owner.unlink()
        owner.symlink_to(target)
        manifest = fragments["10-service-shared.toml"]
    else:
        manifest = tmp_path / "10-service-shared.toml"
        manifest.write_text(MANIFEST_TEXT, encoding="utf-8")
    if destination == "conflict":
        terraform_input = tmp_path / "gpu-api-key.tfvars"
        terraform_input.write_text(
            'gpu_api_key_secret_ocid = "ocid1.vaultsecret.oc1.iad.conflictingfake"\n',
            encoding="utf-8",
        )
    elif destination == "invalid-input":
        parent_file = tmp_path / "not-a-directory"
        parent_file.write_text("invalid destination", encoding="utf-8")
        terraform_input = parent_file / "gpu-api-key.tfvars"
    else:
        terraform_input = tmp_path / "gpu-api-key.tfvars"
    input_capture = tmp_path / "writer-stdin"
    argument_capture = tmp_path / "writer-arguments"

    result = subprocess.run(
        [
            "bash",
            str(SCRIPT_PATH),
            "--approve-mint",
            "--ssh-target",
            "ubuntu@gpu.example",
            "--manifest",
            str(manifest),
            "--terraform-input",
            str(terraform_input),
        ],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "GPU_KEY_TEST_RANDOM": FAKE_KEY,
            "GPU_KEY_TEST_OCID": FAKE_OCID,
            "GPU_KEY_TEST_STDIN_CAPTURE": str(input_capture),
            "GPU_KEY_TEST_ARGUMENT_CAPTURE": str(argument_capture),
            "TMPDIR": str(tmp_path),
        },
    )

    assert result.returncode != 0
    assert not input_capture.exists()
    assert not argument_capture.exists()
    document, _ = gpu_key_manifest._load_manifest_fragments(manifest)
    assert gpu_key_manifest._current_gpu_key_ocid(document) is None


@pytest.mark.parametrize("rotate", [False, True])
@pytest.mark.parametrize("conflicting_input", [False, True])
def test_inherited_transaction_flag_cannot_skip_preflight_or_identity_binding(
    tmp_path: Path,
    rotate: bool,
    conflicting_input: bool,
) -> None:
    bin_dir = _fake_cli(tmp_path)
    manifest = tmp_path / "10-service-shared.toml"
    manifest_text = _manifest_with_gpu_ocid(FAKE_OCID) if rotate else MANIFEST_TEXT
    manifest.write_text(manifest_text, encoding="utf-8")
    terraform_input = tmp_path / "gpu-api-key.tfvars"
    if conflicting_input:
        terraform_text = 'gpu_api_key_secret_ocid = "ocid1.vaultsecret.oc1.iad.conflictingfake"\n'
    elif rotate:
        terraform_text = (
            "# Generated by scripts/deploy/gpu-key-mint.sh; identifier only.\n"
            f'gpu_api_key_secret_ocid = "{FAKE_OCID}"\n'
        )
    else:
        terraform_text = ""
    if terraform_text:
        terraform_input.write_text(terraform_text, encoding="utf-8")
    argument_capture = tmp_path / "writer-arguments"
    mutations = tmp_path / "remote-mutations"
    args = [
        "bash",
        str(SCRIPT_PATH),
        "--approve-mint",
        "--ssh-target",
        "ubuntu@gpu.example",
        "--manifest",
        str(manifest),
        "--terraform-input",
        str(terraform_input),
    ]
    if rotate:
        args.append("--rotate")

    result = subprocess.run(
        args,
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "GPU_KEY_MINT_TRANSACTION_LOCKED": "1",
            "GPU_KEY_TEST_RANDOM": FAKE_KEY,
            "GPU_KEY_TEST_OCID": FAKE_OCID,
            "GPU_KEY_TEST_ARGUMENT_CAPTURE": str(argument_capture),
            "GPU_KEY_TEST_MUTATIONS": str(mutations),
            "TMPDIR": str(tmp_path),
        },
    )

    assert result.returncode != 0
    assert not argument_capture.exists()
    assert not mutations.exists()
    assert manifest.read_text(encoding="utf-8") == manifest_text
    if terraform_text:
        assert terraform_input.read_text(encoding="utf-8") == terraform_text
    else:
        assert not terraform_input.exists()


def test_internal_handoff_rejects_stale_hash_before_writer_contact(tmp_path: Path) -> None:
    bin_dir = _fake_cli(tmp_path)
    manifest = tmp_path / "10-service-shared.toml"
    manifest.write_text(MANIFEST_TEXT, encoding="utf-8")
    terraform_input = tmp_path / "gpu-api-key.tfvars"
    argument_capture = tmp_path / "writer-arguments"
    lock_descriptor = gpu_key_manifest._open_manifest_write_lock(manifest)
    try:
        result = subprocess.run(
            [
                "bash",
                str(SCRIPT_PATH),
                "--approve-mint",
                "--ssh-target",
                "ubuntu@gpu.example",
                "--manifest",
                str(manifest),
                "--terraform-input",
                str(terraform_input),
                "--expected-owner-sha256",
                "0" * 64,
                "--expected-terraform-input-sha256",
                "missing",
            ],
            check=False,
            capture_output=True,
            text=True,
            pass_fds=(lock_descriptor,),
            env={
                **os.environ,
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "GPU_KEY_MINT_TRANSACTION_LOCKED": "1",
                "GPU_KEY_MINT_TRANSACTION_LOCK_FD": str(lock_descriptor),
                "GPU_KEY_TEST_RANDOM": FAKE_KEY,
                "GPU_KEY_TEST_OCID": FAKE_OCID,
                "GPU_KEY_TEST_ARGUMENT_CAPTURE": str(argument_capture),
                "TMPDIR": str(tmp_path),
            },
        )
    finally:
        os.close(lock_descriptor)

    assert result.returncode != 0
    assert "preimage changed before writer contact" in result.stderr
    assert not argument_capture.exists()
    assert manifest.read_text(encoding="utf-8") == MANIFEST_TEXT
    assert not terraform_input.exists()


def test_inherited_flag_does_not_skip_helper_lock(tmp_path: Path) -> None:
    manifest = tmp_path / "10-service-shared.toml"
    manifest.write_text(MANIFEST_TEXT, encoding="utf-8")
    original = manifest.read_text(encoding="utf-8")
    lock_descriptor = gpu_key_manifest._open_manifest_write_lock(manifest)
    try:
        result = subprocess.run(
            [sys.executable, str(HELPER_PATH), FAKE_OCID, "--manifest", str(manifest)],
            check=False,
            capture_output=True,
            text=True,
            timeout=MANIFEST_LOCK_TIMEOUT_SECONDS + 2,
            env={**os.environ, "GPU_KEY_MINT_TRANSACTION_LOCKED": "1"},
        )
    finally:
        os.close(lock_descriptor)

    assert result.returncode != 0
    assert "timed out acquiring GPU key manifest write lock" in result.stderr
    assert manifest.read_text(encoding="utf-8") == original


def test_late_terraform_publish_failure_restores_manifest_preimage(tmp_path: Path, monkeypatch) -> None:
    manifest = tmp_path / "10-service-shared.toml"
    manifest.write_text(MANIFEST_TEXT, encoding="utf-8")
    terraform_input = tmp_path / "gpu-api-key.tfvars"
    real_replace = gpu_key_manifest.os.replace
    failed = False

    def fail_terraform_publish_once(source: Path, target: Path) -> None:
        nonlocal failed
        if Path(target) == terraform_input and not failed:
            failed = True
            raise OSError("injected late Terraform input publish failure")
        real_replace(source, target)

    monkeypatch.setattr(gpu_key_manifest.os, "replace", fail_terraform_publish_once)

    with pytest.raises(ValueError, match="rolled back"):
        gpu_key_manifest.persist_mint_result(manifest, terraform_input, FAKE_OCID)

    assert failed
    assert manifest.read_text(encoding="utf-8") == MANIFEST_TEXT
    assert not terraform_input.exists()


def test_mint_persistence_is_idempotent_for_matching_manifest_and_tfvars(tmp_path: Path, monkeypatch) -> None:
    manifest = tmp_path / "10-service-shared.toml"
    manifest.write_text(MANIFEST_TEXT, encoding="utf-8")
    terraform_input = tmp_path / "gpu-api-key.tfvars"
    real_replace = gpu_key_manifest.os.replace
    replacements = []

    def record_replace(source: Path, target: Path) -> None:
        replacements.append(Path(target))
        real_replace(source, target)

    monkeypatch.setattr(gpu_key_manifest.os, "replace", record_replace)

    gpu_key_manifest.persist_mint_result(manifest, terraform_input, FAKE_OCID)
    first_manifest = manifest.read_text(encoding="utf-8")
    first_input = terraform_input.read_text(encoding="utf-8")
    first_publish_count = len(replacements)
    gpu_key_manifest.persist_mint_result(manifest, terraform_input, FAKE_OCID)

    assert first_publish_count == 2
    assert len(replacements) == first_publish_count
    assert manifest.read_text(encoding="utf-8") == first_manifest
    assert terraform_input.read_text(encoding="utf-8") == first_input


def test_manifest_refuses_to_change_a_different_minted_ocid(tmp_path: Path) -> None:
    path = tmp_path / "10-service-shared.toml"
    path.write_text(MANIFEST_TEXT, encoding="utf-8")
    gpu_key_manifest.set_gpu_key_ocid(path, FAKE_OCID)
    after_first_mint = path.read_text(encoding="utf-8")

    with pytest.raises(ValueError, match="refusing to replace existing dev GPU key ref"):
        gpu_key_manifest.set_gpu_key_ocid(path, "ocid1.vaultsecret.oc1.iad.anotherfakekey")

    assert path.read_text(encoding="utf-8") == after_first_mint


def test_manifest_write_lock_uses_shared_directory_abi(tmp_path: Path) -> None:
    manifest_dir = tmp_path / "manifest.d"
    manifest_dir.mkdir()
    fragment = manifest_dir / "10-service-shared.toml"
    fragment.write_text(MANIFEST_TEXT, encoding="utf-8")
    canonical_directory = manifest_dir.resolve()
    digest = hashlib.sha256(os.fsencode(str(canonical_directory))).hexdigest()
    expected = Path(f"/tmp/acx-envman-manifest-write-{os.getuid()}-{digest}.lock")

    assert gpu_key_manifest.manifest_write_lock_path(fragment) == expected
    assert gpu_key_manifest.manifest_write_lock_path(manifest_dir) == expected
    descriptor = gpu_key_manifest._open_manifest_write_lock(fragment)
    try:
        lock_stat = os.fstat(descriptor)
        assert stat.S_ISREG(lock_stat.st_mode)
        assert lock_stat.st_uid == os.getuid()
        assert lock_stat.st_nlink == 1
        assert stat.S_IMODE(lock_stat.st_mode) == 0o600
        assert not os.get_inheritable(descriptor)
    finally:
        os.close(descriptor)
    assert expected.is_file()


def test_manifest_lock_contention_times_out_before_remote_writer(tmp_path: Path) -> None:
    bin_dir = _fake_cli(tmp_path)
    manifest = tmp_path / "10-service-shared.toml"
    manifest.write_text(MANIFEST_TEXT, encoding="utf-8")
    terraform_input = tmp_path / "gpu-api-key.tfvars"
    argument_capture = tmp_path / "writer-arguments"
    stdin_capture = tmp_path / "writer-stdin"
    lock_descriptor = gpu_key_manifest._open_manifest_write_lock(manifest)
    process = None
    try:
        process = subprocess.Popen(
            [
                "bash",
                str(SCRIPT_PATH),
                "--approve-mint",
                "--ssh-target",
                "ubuntu@gpu.example",
                "--manifest",
                str(manifest),
                "--terraform-input",
                str(terraform_input),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={
                **os.environ,
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "GPU_KEY_TEST_RANDOM": FAKE_KEY,
                "GPU_KEY_TEST_OCID": FAKE_OCID,
                "GPU_KEY_TEST_ARGUMENT_CAPTURE": str(argument_capture),
                "GPU_KEY_TEST_STDIN_CAPTURE": str(stdin_capture),
                "TMPDIR": str(tmp_path),
            },
        )
        try:
            stdout, stderr = process.communicate(timeout=MANIFEST_LOCK_TIMEOUT_SECONDS + 1)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            pytest.fail("mint transaction waited indefinitely for the manifest lock")
    finally:
        os.close(lock_descriptor)

    assert process is not None and process.returncode != 0
    assert "timed out acquiring GPU key manifest write lock" in stderr
    assert stdout == ""
    assert not argument_capture.exists()
    assert not stdin_capture.exists()
    assert not terraform_input.exists()


def test_manifest_lock_release_allows_transaction_to_reach_fake_writer(tmp_path: Path) -> None:
    bin_dir = _fake_cli(tmp_path)
    manifest = tmp_path / "10-service-shared.toml"
    manifest.write_text(MANIFEST_TEXT, encoding="utf-8")
    terraform_input = tmp_path / "gpu-api-key.tfvars"
    argument_capture = tmp_path / "writer-arguments"
    lock_descriptor = gpu_key_manifest._open_manifest_write_lock(manifest)
    process = subprocess.Popen(
        [
            "bash",
            str(SCRIPT_PATH),
            "--approve-mint",
            "--ssh-target",
            "ubuntu@gpu.example",
            "--manifest",
            str(manifest),
            "--terraform-input",
            str(terraform_input),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "GPU_KEY_TEST_RANDOM": FAKE_KEY,
            "GPU_KEY_TEST_OCID": FAKE_OCID,
            "GPU_KEY_TEST_ARGUMENT_CAPTURE": str(argument_capture),
            "GPU_KEY_TEST_STDIN_CAPTURE": str(tmp_path / "writer-stdin"),
            "TMPDIR": str(tmp_path),
        },
    )
    try:
        time.sleep(0.2)
        waited_for_lock = process.poll() is None
    finally:
        os.close(lock_descriptor)

    stdout, stderr = process.communicate(timeout=MANIFEST_LOCK_TIMEOUT_SECONDS + 5)
    assert waited_for_lock
    assert process.returncode == 0, stderr
    assert stdout == f"{FAKE_OCID} 64\n"
    assert "--secret-name ACX_GPU_ENDPOINT_API_KEY" in argument_capture.read_text(encoding="utf-8")
    assert terraform_input.is_file()


def test_real_vault_writer_parser_binds_existing_secret_identity(monkeypatch, capsys) -> None:
    current_secret = [None]
    current_value = [b"b" * 64]
    writes: list[tuple[str, str]] = []
    sibling = SimpleNamespace(
        id="ocid1.vaultsecret.oc1.iad.fakewriteridentitysibling",
        secret_name="OCIR_USERNAME",
        key_id="ocid1.key.test",
        lifecycle_state="ACTIVE",
    )

    class Client:
        def __init__(self, *_args, **_kwargs):
            self.base_client = SimpleNamespace(timeout=None)

    class VaultsClient(Client):
        def get_vault(self, _vault_id):
            return SimpleNamespace(data=SimpleNamespace(compartment_id="ocid1.compartment.test"))

        def list_secrets(self, **kwargs):
            selected = [sibling, current_secret[0]] if current_secret[0] is not None else [sibling]
            name = kwargs.get("name")
            data = [item for item in selected if name is None or item.secret_name == name]
            return SimpleNamespace(data=data, headers={})

        def list_secret_versions(self, *_args, **_kwargs):
            return SimpleNamespace(data=[], headers={})

        def get_secret(self, _secret_id):
            return SimpleNamespace(data=current_secret[0], headers={"etag": "fake-etag"})

        def create_secret(self, details, **_kwargs):
            value = base64.b64decode(details.secret_content.content)
            writes.append(("create", FAKE_OCID))
            current_value[0] = value
            current_secret[0] = SimpleNamespace(
                id=FAKE_OCID,
                secret_name="ACX_GPU_ENDPOINT_API_KEY",
                key_id="ocid1.key.test",
                lifecycle_state="ACTIVE",
            )
            return SimpleNamespace(data=current_secret[0], headers={"etag": "created-etag"})

        def update_secret(self, secret_id, details, *, if_match=None, **_kwargs):
            assert if_match == "fake-etag"
            writes.append(("update", secret_id))
            current_value[0] = base64.b64decode(details.secret_content.content)
            return SimpleNamespace(data=current_secret[0], headers={"etag": "updated-etag"})

    class KmsVaultClient(Client):
        def get_vault(self, _vault_id):
            return SimpleNamespace(data=SimpleNamespace(compartment_id="ocid1.compartment.test"))

    class SecretsClient(Client):
        def get_secret_bundle_by_name(self, **_kwargs):
            content = SimpleNamespace(content=base64.b64encode(current_value[0]).decode("ascii"))
            return SimpleNamespace(data=SimpleNamespace(secret_bundle_content=content))

    class Details:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    fake_oci = SimpleNamespace(
        auth=SimpleNamespace(signers=SimpleNamespace(InstancePrincipalsSecurityTokenSigner=object)),
        config=SimpleNamespace(from_file=lambda **_kwargs: pytest.fail("instance principal must be used")),
        retry=SimpleNamespace(NoneRetryStrategy=object),
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

    def run_writer(mode: str, secret_id: str | None, candidate: bytes) -> int:
        current_secret[0] = None if secret_id is None else SimpleNamespace(
            id=secret_id,
            secret_name="ACX_GPU_ENDPOINT_API_KEY",
            key_id="ocid1.key.test",
            lifecycle_state="ACTIVE",
        )
        current_value[0] = b"b" * 64
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "_vault_put_secret.py",
                "--secret-name",
                "ACX_GPU_ENDPOINT_API_KEY",
                "--instance-principal",
                mode,
                "--expected-secret-id",
                FAKE_OCID,
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
        return vault_put_secret.main()

    assert run_writer("--bootstrap", FAKE_OCID, b"a" * 64) == 0
    assert capsys.readouterr().out == f"{FAKE_OCID} 64\n"
    assert writes == []

    assert run_writer("--rotate-existing", FAKE_OCID, b"a" * 64) == 0
    assert capsys.readouterr().out == f"{FAKE_OCID} 64\n"
    assert writes == [("update", FAKE_OCID)]

    for mode in ("--bootstrap", "--rotate-existing"):
        for remote_id in (None, OTHER_FAKE_OCID):
            before = list(writes)
            with pytest.raises(RuntimeError, match="expected secret identity"):
                run_writer(mode, remote_id, b"c" * 64)
            assert writes == before


def _manifest_with_gpu_ocid(ocid: str) -> str:
    return MANIFEST_TEXT.replace(
        'dev = "host:", staging = "host:", prod = "host:"',
        f'dev = "oci:{ocid}", staging = "host:", prod = "vault:{ocid}"',
    )


@pytest.mark.parametrize("rotate", [False, True])
@pytest.mark.parametrize("remote_state", ["missing", "recreated"])
def test_bound_remote_identity_conflicts_refuse_bootstrap_and_rotation_without_mutation(
    tmp_path: Path,
    rotate: bool,
    remote_state: str,
) -> None:
    bin_dir = _fake_cli(tmp_path)
    manifest = tmp_path / "10-service-shared.toml"
    original = _manifest_with_gpu_ocid(FAKE_OCID)
    manifest.write_text(original, encoding="utf-8")
    terraform_input = tmp_path / "gpu-api-key.tfvars"
    input_capture = tmp_path / "writer-stdin"
    argument_capture = tmp_path / "writer-arguments"
    mutations = tmp_path / "remote-mutations"
    args = [
        "bash",
        str(SCRIPT_PATH),
        "--approve-mint",
        "--ssh-target",
        "ubuntu@gpu.example",
        "--manifest",
        str(manifest),
        "--terraform-input",
        str(terraform_input),
    ]
    if rotate:
        args.append("--rotate")

    result = subprocess.run(
        args,
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "GPU_KEY_TEST_RANDOM": FAKE_KEY,
            "GPU_KEY_TEST_OCID": FAKE_OCID,
            "GPU_KEY_TEST_EXPECTED_ID": FAKE_OCID,
            "GPU_KEY_TEST_REMOTE_STATE": remote_state,
            "GPU_KEY_TEST_STDIN_CAPTURE": str(input_capture),
            "GPU_KEY_TEST_ARGUMENT_CAPTURE": str(argument_capture),
            "GPU_KEY_TEST_MUTATIONS": str(mutations),
            "TMPDIR": str(tmp_path),
        },
    )

    assert result.returncode != 0
    assert "Vault writer failed" in result.stderr
    assert f"--expected-secret-id {FAKE_OCID}" in argument_capture.read_text(encoding="utf-8")
    assert not mutations.exists()
    assert manifest.read_text(encoding="utf-8") == original
    assert not terraform_input.exists()
    assert FAKE_KEY not in result.stdout + result.stderr


@pytest.mark.parametrize("rotate", [False, True])
def test_matching_remote_identity_is_bound_for_bootstrap_and_rotation(
    tmp_path: Path,
    rotate: bool,
) -> None:
    bin_dir = _fake_cli(tmp_path)
    manifest = tmp_path / "10-service-shared.toml"
    manifest.write_text(_manifest_with_gpu_ocid(FAKE_OCID), encoding="utf-8")
    terraform_input = tmp_path / "gpu-api-key.tfvars"
    argument_capture = tmp_path / "writer-arguments"
    mutations = tmp_path / "remote-mutations"
    args = [
        "bash",
        str(SCRIPT_PATH),
        "--approve-mint",
        "--ssh-target",
        "ubuntu@gpu.example",
        "--manifest",
        str(manifest),
        "--terraform-input",
        str(terraform_input),
    ]
    if rotate:
        args.append("--rotate")

    result = subprocess.run(
        args,
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "GPU_KEY_TEST_RANDOM": FAKE_KEY,
            "GPU_KEY_TEST_OCID": FAKE_OCID,
            "GPU_KEY_TEST_EXPECTED_ID": FAKE_OCID,
            "GPU_KEY_TEST_REMOTE_STATE": "matching",
            "GPU_KEY_TEST_STDIN_CAPTURE": str(tmp_path / "writer-stdin"),
            "GPU_KEY_TEST_ARGUMENT_CAPTURE": str(argument_capture),
            "GPU_KEY_TEST_MUTATIONS": str(mutations),
            "TMPDIR": str(tmp_path),
        },
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == f"{FAKE_OCID} 64\n"
    assert f"--expected-secret-id {FAKE_OCID}" in argument_capture.read_text(encoding="utf-8")
    assert mutations.exists() is rotate


@pytest.mark.parametrize(
    "gpu_refs",
    [
        'dev = "oci:not-an-ocid", staging = "host:", prod = "vault:not-an-ocid"',
        (
            'dev = "oci:ocid1.vaultsecret.oc1.iad.firstfakeid", '
            'staging = "host:", prod = "vault:ocid1.vaultsecret.oc1.iad.secondfakeid"'
        ),
    ],
)
def test_malformed_or_inconsistent_local_identity_refuses_before_writer(
    tmp_path: Path,
    gpu_refs: str,
) -> None:
    bin_dir = _fake_cli(tmp_path)
    manifest = tmp_path / "10-service-shared.toml"
    invalid_manifest = MANIFEST_TEXT.replace(
        'dev = "host:", staging = "host:", prod = "host:"',
        gpu_refs,
    )
    manifest.write_text(invalid_manifest, encoding="utf-8")
    argument_capture = tmp_path / "writer-arguments"
    result = subprocess.run(
        [
            "bash",
            str(SCRIPT_PATH),
            "--approve-mint",
            "--ssh-target",
            "ubuntu@gpu.example",
            "--manifest",
            str(manifest),
            "--terraform-input",
            str(tmp_path / "gpu-api-key.tfvars"),
        ],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "GPU_KEY_TEST_RANDOM": FAKE_KEY,
            "GPU_KEY_TEST_OCID": FAKE_OCID,
            "GPU_KEY_TEST_ARGUMENT_CAPTURE": str(argument_capture),
            "TMPDIR": str(tmp_path),
        },
    )

    assert result.returncode != 0
    assert "GPU key manifest dev/prod refs are inconsistent" in result.stderr
    assert not argument_capture.exists()


def test_stale_manifest_edit_during_remote_write_is_rejected(tmp_path: Path) -> None:
    manifest = tmp_path / "10-service-shared.toml"
    manifest.write_text(MANIFEST_TEXT, encoding="utf-8")
    terraform_input = tmp_path / "gpu-api-key.tfvars"
    expected_secret_id, owner_path, expected_preimages = gpu_key_manifest._preflight_mint_transaction(
        manifest,
        terraform_input,
    )
    assert expected_secret_id is None
    assert owner_path == manifest
    changed = MANIFEST_TEXT.replace('version = 1', 'version = 1\n# external edit')
    manifest.write_text(changed, encoding="utf-8")

    with pytest.raises(ValueError, match="changed during GPU key mint transaction"):
        gpu_key_manifest.persist_mint_result(
            manifest,
            terraform_input,
            FAKE_OCID,
            expected_preimages=expected_preimages,
        )

    assert manifest.read_text(encoding="utf-8") == changed
    assert not terraform_input.exists()


def test_mint_does_not_overwrite_external_manifest_edit_after_writer(tmp_path: Path) -> None:
    bin_dir = _fake_cli(tmp_path)
    manifest = tmp_path / "10-service-shared.toml"
    manifest.write_text(MANIFEST_TEXT, encoding="utf-8")
    terraform_input = tmp_path / "gpu-api-key.tfvars"
    original_gpu_refs = 'secret = { dev = "host:", staging = "host:", prod = "host:" }'
    result = subprocess.run(
        [
            "bash",
            str(SCRIPT_PATH),
            "--approve-mint",
            "--ssh-target",
            "ubuntu@gpu.example",
            "--manifest",
            str(manifest),
            "--terraform-input",
            str(terraform_input),
        ],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "GPU_KEY_TEST_RANDOM": FAKE_KEY,
            "GPU_KEY_TEST_OCID": FAKE_OCID,
            "GPU_KEY_TEST_STDIN_CAPTURE": str(tmp_path / "writer-stdin"),
            "GPU_KEY_TEST_ARGUMENT_CAPTURE": str(tmp_path / "writer-arguments"),
            "GPU_KEY_TEST_MUTATIONS": str(tmp_path / "remote-mutations"),
            "GPU_KEY_TEST_EDIT_MANIFEST": str(manifest),
            "TMPDIR": str(tmp_path),
        },
    )

    assert result.returncode != 0
    assert "changed during GPU key mint transaction" in result.stderr
    assert "# external edit during remote writer" in manifest.read_text(encoding="utf-8")
    assert original_gpu_refs in manifest.read_text(encoding="utf-8")
    assert not terraform_input.exists()
    assert (tmp_path / "remote-mutations").read_text(encoding="utf-8") == "create\n"
    assert FAKE_KEY not in result.stdout + result.stderr


def _fake_cli(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    commands = {
        "timeout": "#!/bin/sh\nwhile [ \"$#\" -gt 0 ]; do\n  case \"$1\" in\n    --kill-after=*) shift ;;\n    *s) shift; break ;;\n    *) exit 97 ;;\n  esac\ndone\nexec \"$@\"\n",
        "openssl": "#!/bin/sh\nprintf '%s' \"$GPU_KEY_TEST_RANDOM\"\n",
        "scp": "#!/bin/sh\nexit 0\n",
        "ssh": (
            "#!/bin/sh\n"
            "while [ \"$#\" -gt 0 ]; do\n"
            "  case \"$1\" in\n"
            "    -T) shift ;;\n"
            "    -o) shift 2 ;;\n"
            "    *) break ;;\n"
            "  esac\n"
            "done\n"
            "[ \"$#\" -ge 2 ] || exit 96\n"
            "target=\"$1\"\n"
            "shift\n"
            "command=\"$1\"\n"
            "case \"$command\" in\n"
            "  *'mktemp -d'*) printf '%s\\n' /tmp/acx-gpu-key-mint.fixture ;;\n"
            "  *'--secret-name ACX_GPU_ENDPOINT_API_KEY'*)\n"
            "    if [ -n \"${GPU_KEY_TEST_ARGUMENT_CAPTURE:-}\" ]; then\n"
            "      printf '%s\\n' \"$command\" >\"$GPU_KEY_TEST_ARGUMENT_CAPTURE\"\n"
            "    fi\n"
            "    if [ -n \"${GPU_KEY_TEST_EXPECTED_ID:-}\" ]; then\n"
            "      case \"$command\" in\n"
            "        *\"--expected-secret-id $GPU_KEY_TEST_EXPECTED_ID\"*) ;;\n"
            "        *) exit 94 ;;\n"
            "      esac\n"
            "    fi\n"
            "    case \"${GPU_KEY_TEST_REMOTE_STATE:-initial}\" in\n"
            "      missing) cat >/dev/null; echo 'expected remote secret is missing' >&2; exit 42 ;;\n"
            "      recreated) cat >/dev/null; echo 'remote secret was recreated under another OCID' >&2; exit 42 ;;\n"
            "    esac\n"
            "    cat >\"$GPU_KEY_TEST_STDIN_CAPTURE\"\n"
            "    if [ -n \"${GPU_KEY_TEST_EDIT_MANIFEST:-}\" ]; then\n"
            "      printf '%s\\n' '# external edit during remote writer' >>\"$GPU_KEY_TEST_EDIT_MANIFEST\"\n"
            "    fi\n"
            "    printf '%s %s\\n' \"$GPU_KEY_TEST_OCID\" 64\n"
            "    if [ -n \"${GPU_KEY_TEST_MUTATIONS:-}\" ]; then\n"
            "      case \"$command\" in\n"
            "        *'--rotate-existing'*) printf '%s\\n' rotate >>\"$GPU_KEY_TEST_MUTATIONS\" ;;\n"
            "        *) if [ \"${GPU_KEY_TEST_REMOTE_STATE:-initial}\" = initial ]; then printf '%s\\n' create >>\"$GPU_KEY_TEST_MUTATIONS\"; fi ;;\n"
            "      esac\n"
            "    fi\n"
            "    ;;\n"
            "  *'rm -rf --'*) exit 0 ;;\n"
            "  *) exit 95 ;;\n"
            "esac\n"
        ),
    }
    for name, content in commands.items():
        path = bin_dir / name
        path.write_text(content, encoding="utf-8")
        path.chmod(0o755)
    return bin_dir


def test_mint_requires_approval_before_contacting_writer(tmp_path: Path) -> None:
    bin_dir = _fake_cli(tmp_path)
    result = subprocess.run(
        ["bash", str(SCRIPT_PATH), "--ssh-target", "ubuntu@gpu.example"],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )

    assert result.returncode != 0
    assert "requires explicit --approve-mint" in result.stderr
    assert "gpu-key-mint.fixture" not in result.stderr


def test_mint_refuses_unready_manifest_before_contacting_writer(tmp_path: Path) -> None:
    bin_dir = _fake_cli(tmp_path)
    manifest = tmp_path / "10-service-shared.toml"
    manifest.write_text(MANIFEST_TEXT.replace("derive_vault_map = true", "derive_vault_map = false"), encoding="utf-8")
    result = subprocess.run(
        [
            "bash",
            str(SCRIPT_PATH),
            "--approve-mint",
            "--ssh-target",
            "ubuntu@gpu.example",
            "--manifest",
            str(manifest),
        ],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )

    assert result.returncode != 0
    assert "requires the svc-vm derived Vault secret map" in result.stderr
    assert "gpu-key-mint.fixture" not in result.stderr


@pytest.mark.parametrize("rotate", [False, True])
@pytest.mark.parametrize("trace", [False, True])
def test_mint_pipes_fake_random_input_and_prints_only_ocid_and_length(
    tmp_path: Path,
    rotate: bool,
    trace: bool,
) -> None:
    bin_dir = _fake_cli(tmp_path)
    manifest = tmp_path / "10-service-shared.toml"
    manifest.write_text(MANIFEST_TEXT, encoding="utf-8")
    terraform_input = tmp_path / "gpu-api-key.tfvars"
    input_capture = tmp_path / "writer-stdin"
    argument_capture = tmp_path / "writer-arguments"
    args = ["bash"]
    if trace:
        args.append("-x")
    args.extend([
        str(SCRIPT_PATH),
        "--approve-mint",
        "--ssh-target",
        "ubuntu@gpu.example",
        "--manifest",
        str(manifest),
        "--terraform-input",
        str(terraform_input),
    ])
    if rotate:
        args.append("--rotate")
    environment = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "GPU_KEY_TEST_RANDOM": FAKE_KEY,
        "GPU_KEY_TEST_OCID": FAKE_OCID,
        "GPU_KEY_TEST_STDIN_CAPTURE": str(input_capture),
        "GPU_KEY_TEST_ARGUMENT_CAPTURE": str(argument_capture),
        "TMPDIR": str(tmp_path),
    }

    result = subprocess.run(args, check=False, capture_output=True, text=True, env=environment)

    assert result.returncode == 0, result.stderr
    assert result.stdout == f"{FAKE_OCID} 64\n"
    assert FAKE_KEY not in result.stdout
    assert FAKE_KEY not in result.stderr
    assert input_capture.read_text(encoding="utf-8") == FAKE_KEY
    remote_args = argument_capture.read_text(encoding="utf-8")
    assert FAKE_KEY not in remote_args
    assert ("--rotate-existing" in remote_args) is rotate
    refs = tomllib.loads(manifest.read_text(encoding="utf-8"))["var"][0]["secret"]
    assert refs["dev"] == f"oci:{FAKE_OCID}"
    assert refs["prod"] == f"vault:{FAKE_OCID}"
    assert refs["staging"] == "host:"
    assert terraform_input.read_text(encoding="utf-8") == (
        '# Generated by scripts/deploy/gpu-key-mint.sh; identifier only.\n'
        f'gpu_api_key_secret_ocid = "{FAKE_OCID}"\n'
    )


def test_mint_checks_fragmented_manifest_and_updates_gpu_owner(tmp_path: Path) -> None:
    bin_dir = _fake_cli(tmp_path)
    manifest_dir = tmp_path / "manifest.d"
    manifest_dir.mkdir()
    paths = _write_fragmented_manifest(manifest_dir)
    terraform_input = tmp_path / "gpu-api-key.tfvars"
    input_capture = tmp_path / "writer-stdin"
    argument_capture = tmp_path / "writer-arguments"
    result = subprocess.run(
        [
            "bash",
            str(SCRIPT_PATH),
            "--approve-mint",
            "--ssh-target",
            "ubuntu@gpu.example",
            "--manifest",
            str(paths["10-service-shared.toml"]),
            "--terraform-input",
            str(terraform_input),
        ],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "GPU_KEY_TEST_RANDOM": FAKE_KEY,
            "GPU_KEY_TEST_OCID": FAKE_OCID,
            "GPU_KEY_TEST_STDIN_CAPTURE": str(input_capture),
            "GPU_KEY_TEST_ARGUMENT_CAPTURE": str(argument_capture),
            "TMPDIR": str(tmp_path),
        },
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == f"{FAKE_OCID} 64\n"
    assert input_capture.read_text(encoding="utf-8") == FAKE_KEY
    gpu = next(
        row
        for row in tomllib.loads(paths["21-service-vm.toml"].read_text(encoding="utf-8"))["var"]
        if row["name"] == "ACX_GPU_ENDPOINT_API_KEY"
    )
    assert gpu["secret"]["dev"] == f"oci:{FAKE_OCID}"
    assert gpu["secret"]["prod"] == f"vault:{FAKE_OCID}"
    assert gpu["secret"]["staging"] == "host:"
    assert (
        f'gpu_api_key_secret_ocid = "{FAKE_OCID}"'
        in terraform_input.read_text(encoding="utf-8")
    )


def test_cloud_init_fetches_key_at_runtime_and_gates_docker() -> None:
    cloud_init = (REPO_ROOT / "infra/oci/gpu-cloud-init.yaml").read_text(encoding="utf-8")
    terraform = (REPO_ROOT / "infra/oci/main.tf").read_text(encoding="utf-8")
    terraform_vars = (REPO_ROOT / "infra/oci/variables.tf").read_text(encoding="utf-8")
    prod_example = (REPO_ROOT / "apps/prototype-description-service/.env.prod.example").read_text(encoding="utf-8")
    runbook = (REPO_ROOT / "docs/runbooks/gpu-key-mint.md").read_text(encoding="utf-8")

    assert "--auth instance_principal secrets secret-bundle get" in cloud_init
    assert "ATTEMPT_TIMEOUT=20" in cloud_init and "ATTEMPTS=5" in cloud_init
    assert "chmod 0600 \"$temporary\"" in cloud_init
    assert "ExecStartPre=/usr/local/bin/acx-gpu-fetch-api-key.sh" in cloud_init
    assert '-v "$KEY_PATH:/run/secrets/acx-gpu-api-key:ro"' in cloud_init
    assert "--api-key-file /run/secrets/acx-gpu-api-key" in cloud_init
    assert "--api-key \"$key\"" not in cloud_init
    assert "gpu_api_key_secret_ocid = var.gpu_api_key_secret_ocid" in terraform
    assert 'default     = ""' in terraform_vars
    assert "make gpu-key-mint" in prod_example
    assert "REPLACE_GPU_ENDPOINT_KEY" not in prod_example
    assert "REPLACE_GPU_ENDPOINT_KEY" not in cloud_init
    assert "gpu-api-key.tfvars" in runbook
    assert "terraform -chdir=infra/oci apply -var-file=terraform.tfvars -var-file=gpu-api-key.tfvars" in runbook
