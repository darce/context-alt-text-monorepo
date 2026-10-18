"""Tests for GPU Vault key minting without live OCI or GPU calls."""

from __future__ import annotations

import base64
import hashlib
import http.client
import io
import importlib.util
import os
import re
import shlex
import shutil
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

FAKE_OCID = "ocid1.vaultsecret.oc1.iad." + "f" * 24
OTHER_FAKE_OCID = "ocid1.vaultsecret.oc1.iad." + "e" * 24
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
secret = { prod = "vault:ocid1.vaultsecret.oc1.iad.fakepgpasswordaaaaaaaaaa" }

[[var]]
name = "POSTGRES_DSN"
class = "secret"
targets = ["svc-vm"]
secret = { prod = "vault:ocid1.vaultsecret.oc1.iad.fakepostgresdsnaaaaaaaaa" }

[[var]]
name = "POSTGRES_SYNC_DSN"
class = "secret"
targets = ["svc-vm"]
secret = { prod = "vault:ocid1.vaultsecret.oc1.iad.fakepostgressyncdsnaaaaa" }

[[var]]
name = "RECOGNITION_ADMIN_TOKEN"
class = "secret"
targets = ["svc-vm"]
secret = { prod = "vault:ocid1.vaultsecret.oc1.iad.fakeadmintokenaaaaaaaaaa" }
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
secret = { prod = "vault:ocid1.vaultsecret.oc1.iad.fakepostgresdsnaaaaaaaaa" }

[[var]]
name = "POSTGRES_SYNC_DSN"
class = "secret"
targets = ["svc-vm"]
secret = { prod = "vault:ocid1.vaultsecret.oc1.iad.fakepostgressyncdsnaaaaa" }
''',
    "20-service-local.toml": '''version = 1

[[var]]
name = "PGPASSWORD"
class = "secret"
targets = ["svc-local", "svc-vm"]
secret = { local = "keychain:acx-local/PGPASSWORD", prod = "vault:ocid1.vaultsecret.oc1.iad.fakepgpasswordaaaaaaaaaa" }
''',
    "21-service-vm.toml": '''version = 1

[[var]]
name = "RECOGNITION_ADMIN_TOKEN"
class = "secret"
targets = ["svc-vm"]
secret = { prod = "vault:ocid1.vaultsecret.oc1.iad.fakeadmintokenaaaaaaaaaa" }

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
    for name in (
        "22-service-fir.toml",
        "30-portal-backend.toml",
        "40-demo.toml",
        "50-wp-e2e.toml",
        "60-app-portal.toml",
        "targets.toml",
    ):
        (directory / name).write_text("version = 1\n", encoding="utf-8")
    return paths


def _write_fake_committed_manifest(directory: Path) -> dict[str, Path]:
    """Copy the fragment layout with fake identifiers and an unminted GPU key.

    Bound/retry/rotation tests must establish their fake GPU identity explicitly,
    independently of whether the checked-in deployment has already minted a key.
    """
    source_dir = REPO_ROOT / "config/env/manifest.d"

    def bootstrap_gpu_refs(match: re.Match[str]) -> str:
        block = match.group(0)
        variable = tomllib.loads(block)["var"][0]
        if variable.get("name") != "ACX_GPU_ENDPOINT_API_KEY":
            return block
        secret_line = re.search(r"(?m)^secret\s*=.*$", block)
        assert secret_line is not None
        refs = secret_line.group(0)
        for env in ("dev", "prod"):
            refs, count = re.subn(rf'(\b{env}\s*=\s*)"[^"\n]*"', r'\1"host:"', refs, count=1)
            assert count == 1
        return block[: secret_line.start()] + refs + block[secret_line.end() :]

    fake_ids: dict[str, str] = {}
    paths = {}
    for source in sorted(source_dir.glob("*.toml")):
        text = source.read_text(encoding="utf-8")
        text = re.sub(r"(?ms)^\[\[var\]\].*?(?=^\[\[|\Z)", bootstrap_gpu_refs, text)

        def replace_ocid(match: re.Match[str]) -> str:
            original = match.group(0)
            if original not in fake_ids:
                fake_ids[original] = "ocid1.vaultsecret.oc1.iad.f" + f"{len(fake_ids) + 1:02d}" + "a" * 20
            return fake_ids[original]

        text = re.sub(
            r"ocid1\.vaultsecret\.oc1\.[a-z0-9-]*\.[a-z0-9]{20,}",
            replace_ocid,
            text,
        )
        target = directory / source.name
        shutil.copy2(source, target)
        target.write_text(text, encoding="utf-8")
        paths[source.name] = target
    return paths


def _replace_var_field(path: Path, var_name: str, field: str, value: str) -> None:
    text = path.read_text(encoding="utf-8")
    marker = f'name = "{var_name}"'
    marker_index = text.index(marker)
    start = text.rfind("[[var]]", 0, marker_index)
    end = text.find("\n[[", marker_index)
    if end == -1:
        end = len(text)
    block = text[start:end]
    updated, count = re.subn(rf"(?m)^{re.escape(field)}\s*=.*$", value, block, count=1)
    assert count == 1
    path.write_text(text[:start] + updated + text[end:], encoding="utf-8")


@pytest.mark.parametrize(
    "source_ocid",
    [None, OTHER_FAKE_OCID, "ocid1.vaultsecret.oc12.iad.AbCdEfGhIjKlMnOpQrStUvWx"],
    ids=["unminted", "previously-minted", "previously-minted-original-case"],
)
def test_fake_committed_manifest_establishes_bootstrap_independent_of_source(
    tmp_path: Path,
    monkeypatch,
    source_ocid: str | None,
) -> None:
    source_root = tmp_path / "source"
    source_dir = source_root / "config/env/manifest.d"
    source_dir.mkdir(parents=True)
    sources = _write_fragmented_manifest(source_dir)
    source_owner = sources["21-service-vm.toml"]
    staging_ref = "keychain:fixture-staging/ACX_GPU_ENDPOINT_API_KEY"
    source_refs = (
        f'dev = "oci:{source_ocid}", prod = "vault:{source_ocid}"'
        if source_ocid is not None
        else 'dev = "host:", prod = "host:"'
    )
    _replace_var_field(
        source_owner,
        "ACX_GPU_ENDPOINT_API_KEY",
        "secret",
        f'secret = {{ {source_refs}, staging = "{staging_ref}", local = "host:" }}',
    )
    source_before = {path.name: path.read_bytes() for path in source_dir.glob("*.toml")}
    monkeypatch.setattr(sys.modules[__name__], "REPO_ROOT", source_root)
    manifest_dir = tmp_path / "manifest.d"
    manifest_dir.mkdir()

    paths = _write_fake_committed_manifest(manifest_dir)

    assert set(paths) == set(source_before)
    assert {path.name: path.read_bytes() for path in source_dir.glob("*.toml")} == source_before
    source_gpu = next(
        row
        for row in tomllib.loads(source_owner.read_text(encoding="utf-8"))["var"]
        if row["name"] == "ACX_GPU_ENDPOINT_API_KEY"
    )
    owner = paths[source_owner.name]
    fixture_gpu = next(
        row
        for row in tomllib.loads(owner.read_text(encoding="utf-8"))["var"]
        if row["name"] == "ACX_GPU_ENDPOINT_API_KEY"
    )
    assert fixture_gpu == {**source_gpu, "secret": {**source_gpu["secret"], "dev": "host:", "prod": "host:"}}
    source_secret_line = next(
        line
        for line in source_owner.read_text(encoding="utf-8").splitlines()
        if line.startswith("secret =") and staging_ref in line
    )
    expected_secret_line = f'secret = {{ dev = "host:", prod = "host:", staging = "{staging_ref}", local = "host:" }}'
    for name, original in source_before.items():
        original_text = original.decode("utf-8")
        if name == source_owner.name:
            original_text = original_text.replace(source_secret_line, expected_secret_line)
        fixture_text = paths[name].read_text(encoding="utf-8")
        assert re.sub(r"ocid1\.vaultsecret[^\"]+", "FAKE_REF", fixture_text) == re.sub(
            r"ocid1\.vaultsecret[^\"]+",
            "FAKE_REF",
            original_text,
        )
        for original_ref in re.findall(r"ocid1\.vaultsecret[^\"]+", original.decode("utf-8")):
            assert original_ref not in fixture_text
    expected_id, actual_owner, _ = gpu_key_manifest._preflight_mint_transaction(
        paths["10-service-shared.toml"],
        tmp_path / "gpu-api-key.tfvars",
    )
    assert expected_id is None
    assert actual_owner == owner


@pytest.mark.parametrize("rotate", [False, True], ids=["bound-bootstrap", "rotation"])
def test_fake_committed_manifest_explicit_binding_rejects_writer_identity_mismatch(
    tmp_path: Path,
    monkeypatch,
    rotate: bool,
) -> None:
    source_root = tmp_path / "source"
    source_dir = source_root / "config/env/manifest.d"
    source_dir.mkdir(parents=True)
    _write_fragmented_manifest(source_dir)
    monkeypatch.setattr(sys.modules[__name__], "REPO_ROOT", source_root)
    manifest_dir = tmp_path / "manifest.d"
    manifest_dir.mkdir()
    paths = _write_fake_committed_manifest(manifest_dir)
    _replace_var_field(
        paths["21-service-vm.toml"],
        "ACX_GPU_ENDPOINT_API_KEY",
        "secret",
        f'secret = {{ dev = "oci:{OTHER_FAKE_OCID}", staging = "host:", prod = "vault:{OTHER_FAKE_OCID}" }}',
    )
    before = {path: path.read_bytes() for path in paths.values()}
    terraform_input = tmp_path / "gpu-api-key.tfvars"
    terraform_input.write_text(
        "# Generated by scripts/deploy/gpu-key-mint.sh; identifier only.\n"
        f'gpu_api_key_secret_ocid = "{OTHER_FAKE_OCID}"\n',
        encoding="utf-8",
    )
    before_terraform_input = terraform_input.read_bytes()
    bin_dir = _fake_cli(tmp_path)
    argument_capture = tmp_path / "writer-arguments"
    stdin_capture = tmp_path / "writer-stdin"
    args = [
        "bash",
        str(SCRIPT_PATH),
        "--approve-mint",
        "--manifest",
        str(paths["10-service-shared.toml"]),
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
            "ACX_OCI_PYTHON": str(bin_dir / "oci-python"),
            "GPU_KEY_TEST_OCID": FAKE_OCID,
            "GPU_KEY_TEST_EXPECTED_ID": OTHER_FAKE_OCID,
            "GPU_KEY_TEST_ARGUMENT_CAPTURE": str(argument_capture),
            "GPU_KEY_TEST_STDIN_CAPTURE": str(stdin_capture),
            "TMPDIR": str(tmp_path),
        },
    )

    assert result.returncode != 0
    assert "Vault writer returned a different GPU key secret identity" in result.stderr
    assert result.stdout == ""
    writer_arguments = argument_capture.read_text(encoding="utf-8")
    assert f"--expected-secret-id {OTHER_FAKE_OCID}" in writer_arguments
    assert ("--rotate-existing" in writer_arguments) is rotate
    assert {path: path.read_bytes() for path in paths.values()} == before
    assert terraform_input.read_bytes() == before_terraform_input
    _assert_key_only_in_stdin(tmp_path, stdin_capture)
    assert FAKE_KEY not in result.stdout + result.stderr


@pytest.mark.parametrize("rotate", [False, True], ids=["bootstrap", "rotate"])
@pytest.mark.parametrize(
    "invalid_declaration",
    [
        "derived-map-values",
        "derived-map-secret",
        "derived-map-derive",
        "derived-map-secret-refs",
        "pgpassword-config-class",
    ],
)
def test_mint_rejects_invalid_required_declarations_before_writer(
    tmp_path: Path,
    rotate: bool,
    invalid_declaration: str,
) -> None:
    manifest_dir = tmp_path / "manifest.d"
    manifest_dir.mkdir()
    paths = _write_fake_committed_manifest(manifest_dir)
    shared = paths["10-service-shared.toml"]
    owner = paths["21-service-vm.toml"]
    map_source_fields = {
        "derived-map-values": 'values = { prod = "obvious-fake-config" }',
        "derived-map-secret": 'secret = { prod = "host:" }',
        "derived-map-derive": 'derive = "obvious-fake-derived-source"',
        "derived-map-secret-refs": 'secret_refs = { prod = "obvious-fake-secret-ref" }',
    }
    if invalid_declaration in map_source_fields:
        text = shared.read_text(encoding="utf-8")
        text, count = re.subn(
            r"(?m)^(derive_vault_map = true)$",
            lambda match: f"{match.group(1)}\n{map_source_fields[invalid_declaration]}",
            text,
            count=1,
        )
        assert count == 1
        shared.write_text(text, encoding="utf-8")
    else:
        _replace_var_field(paths["20-service-local.toml"], "PGPASSWORD", "class", 'class = "config"')

    terraform_input = tmp_path / "gpu-api-key.tfvars"
    if rotate:
        _replace_var_field(
            owner,
            "ACX_GPU_ENDPOINT_API_KEY",
            "secret",
            f'secret = {{ dev = "oci:{FAKE_OCID}", staging = "host:", prod = "vault:{FAKE_OCID}" }}',
        )
        terraform_input.write_text(
            '# Generated by scripts/deploy/gpu-key-mint.sh; identifier only.\n'
            f'gpu_api_key_secret_ocid = "{FAKE_OCID}"\n',
            encoding="utf-8",
        )

    before_fragments = {path: path.read_bytes() for path in manifest_dir.glob("*.toml")}
    before_terraform_input = terraform_input.read_bytes() if rotate else None
    bin_dir = _fake_cli(tmp_path)
    stdin_capture = tmp_path / "writer-stdin"
    argument_capture = tmp_path / "writer-arguments"
    mutations = tmp_path / "vault-mutations"
    args = [
        "bash",
        str(SCRIPT_PATH),
        "--approve-mint",
        "--manifest",
        str(shared),
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
            "ACX_OCI_PYTHON": str(bin_dir / "oci-python"),
            "GPU_KEY_TEST_OCID": OTHER_FAKE_OCID,
            "GPU_KEY_TEST_STDIN_CAPTURE": str(stdin_capture),
            "GPU_KEY_TEST_ARGUMENT_CAPTURE": str(argument_capture),
            "GPU_KEY_TEST_MUTATIONS": str(mutations),
            "TMPDIR": str(tmp_path),
        },
    )

    assert result.returncode != 0
    assert not argument_capture.exists()
    assert not stdin_capture.exists()
    assert not mutations.exists()
    assert {path: path.read_bytes() for path in manifest_dir.glob("*.toml")} == before_fragments
    if rotate:
        assert terraform_input.read_bytes() == before_terraform_input
    else:
        assert not terraform_input.exists()


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


@pytest.mark.parametrize(
    ("var_name", "target_value"),
    [
        (name, value)
        for name in ("ACX_GPU_ENDPOINT_API_KEY", "RECOGNITION_VAULT_SECRET_MAP", "PGPASSWORD")
        for value in ('targets = "svc-vm"', 'targets = "prefix-svc-vm-suffix"', 'targets = [17, "svc-vm"]')
    ],
    ids=[
        f"{name.lower().replace('_', '-')}-{case}"
        for name in ("gpu", "map", "pgpassword")
        for case in ("scalar", "substring", "non-string-element")
    ],
)
def test_mint_rejects_malformed_fragment_targets_before_writer(
    tmp_path: Path,
    var_name: str,
    target_value: str,
) -> None:
    manifest_dir = tmp_path / "manifest.d"
    manifest_dir.mkdir()
    paths = _write_fake_committed_manifest(manifest_dir)
    owner = paths["21-service-vm.toml"]
    _replace_var_field(paths["21-service-vm.toml"] if var_name == "ACX_GPU_ENDPOINT_API_KEY" else (
        paths["10-service-shared.toml"] if var_name == "RECOGNITION_VAULT_SECRET_MAP" else paths["20-service-local.toml"]
    ), var_name, "targets", target_value)
    terraform_input = tmp_path / "gpu-api-key.tfvars"
    fragments_before = {path: path.read_text(encoding="utf-8") for path in manifest_dir.glob("*.toml")}
    bin_dir = _fake_cli(tmp_path)
    input_capture = tmp_path / "writer-stdin"
    argument_capture = tmp_path / "writer-arguments"
    mutations = tmp_path / "vault-mutations"

    result = subprocess.run(
        [
            "bash", str(SCRIPT_PATH), "--approve-mint",
            "--manifest", str(paths["10-service-shared.toml"]),
            "--terraform-input", str(terraform_input),
        ],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "ACX_OCI_PYTHON": str(bin_dir / "oci-python"),
            "GPU_KEY_TEST_OCID": FAKE_OCID,
            "GPU_KEY_TEST_STDIN_CAPTURE": str(input_capture),
            "GPU_KEY_TEST_ARGUMENT_CAPTURE": str(argument_capture),
            "GPU_KEY_TEST_MUTATIONS": str(mutations),
            "TMPDIR": str(tmp_path),
        },
    )

    assert result.returncode != 0
    assert not argument_capture.exists()
    assert not input_capture.exists()
    assert not mutations.exists()
    assert {path: path.read_text(encoding="utf-8") for path in manifest_dir.glob("*.toml")} == fragments_before
    assert not terraform_input.exists()


@pytest.mark.parametrize(
    ("environment", "reference"),
    [
        (environment, reference)
        for environment in ("dev", "staging", "prod")
        for reference in (17, "bogus:obviousfake", "keychain:", "env:", "vault:not-an-ocid", "oci:not-an-ocid")
    ],
    ids=[
        f"{environment}-{case}"
        for environment in ("dev", "staging", "prod")
        for case in ("number", "unknown-scheme", "empty-keychain", "empty-env", "bad-vault-ocid", "bad-oci-ocid")
    ],
)
def test_mint_rejects_malformed_gpu_refs_before_writer(
    tmp_path: Path,
    environment: str,
    reference: object,
) -> None:
    manifest_dir = tmp_path / "manifest.d"
    manifest_dir.mkdir()
    paths = _write_fake_committed_manifest(manifest_dir)
    owner = paths["21-service-vm.toml"]
    secret_line = next(line for line in owner.read_text(encoding="utf-8").splitlines() if line.startswith("secret = "))
    current_refs = tomllib.loads(f"{secret_line}\n")["secret"]
    current_refs[environment] = reference
    serialized_refs = ", ".join(f'{key} = {value!r}' for key, value in current_refs.items())
    # Use TOML double-quoted strings for the valid refs while leaving the malformed number numeric.
    serialized_refs = re.sub(r"= '([^']*)'(?=,|$)", lambda match: '= "' + match.group(1) + '"', serialized_refs)
    _replace_var_field(owner, "ACX_GPU_ENDPOINT_API_KEY", "secret", f"secret = {{ {serialized_refs} }}")
    terraform_input = tmp_path / "gpu-api-key.tfvars"
    fragments_before = {path: path.read_text(encoding="utf-8") for path in manifest_dir.glob("*.toml")}
    bin_dir = _fake_cli(tmp_path)
    input_capture = tmp_path / "writer-stdin"
    argument_capture = tmp_path / "writer-arguments"
    mutations = tmp_path / "vault-mutations"

    result = subprocess.run(
        [
            "bash", str(SCRIPT_PATH), "--approve-mint",
            "--manifest", str(paths["10-service-shared.toml"]),
            "--terraform-input", str(terraform_input),
        ],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "ACX_OCI_PYTHON": str(bin_dir / "oci-python"),
            "GPU_KEY_TEST_OCID": FAKE_OCID,
            "GPU_KEY_TEST_STDIN_CAPTURE": str(input_capture),
            "GPU_KEY_TEST_ARGUMENT_CAPTURE": str(argument_capture),
            "GPU_KEY_TEST_MUTATIONS": str(mutations),
            "TMPDIR": str(tmp_path),
        },
    )

    assert result.returncode != 0
    assert not argument_capture.exists()
    assert not input_capture.exists()
    assert not mutations.exists()
    assert {path: path.read_text(encoding="utf-8") for path in manifest_dir.glob("*.toml")} == fragments_before
    assert not terraform_input.exists()


def test_readiness_accepts_valid_staging_keychain_and_bound_oci_refs(tmp_path: Path) -> None:
    manifest_dir = tmp_path / "manifest.d"
    manifest_dir.mkdir()
    paths = _write_fake_committed_manifest(manifest_dir)
    _replace_var_field(
        paths["21-service-vm.toml"],
        "ACX_GPU_ENDPOINT_API_KEY",
        "secret",
        f'secret = {{ dev = "oci:{FAKE_OCID}", staging = "keychain:acx-gpu/staging", prod = "vault:{FAKE_OCID}" }}',
    )

    gpu_key_manifest.check_manifest_ready(paths["10-service-shared.toml"])

    document, _, _, _ = gpu_key_manifest._manifest_gpu_owner(paths["10-service-shared.toml"])
    gpu = next(row for row in document["var"] if row["name"] == "ACX_GPU_ENDPOINT_API_KEY")
    assert gpu["secret"]["dev"] == f"oci:{FAKE_OCID}"
    assert gpu["secret"]["staging"] == "keychain:acx-gpu/staging"


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
        gpu_key_manifest.write_terraform_input(path, OTHER_FAKE_OCID)


@pytest.mark.parametrize("destination", ["conflict", "invalid-input", "invalid-manifest-owner"])
def test_mint_preflights_output_destinations_before_local_writer(
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
            "ACX_OCI_PYTHON": str(bin_dir / "oci-python"),
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
def test_mint_rejects_unpublishable_gpu_owner_before_local_writer(
    tmp_path: Path,
    rotate: bool,
) -> None:
    manifest_dir = tmp_path / "manifest.d"
    manifest_dir.mkdir()
    paths = _write_fragmented_manifest(manifest_dir)
    owner = paths["21-service-vm.toml"]
    gpu_refs = 'secret = { dev = "host:", staging = "host:", prod = "host:" }'
    expected_refs = (
        'secret = { dev = "oci:' + FAKE_OCID + '", staging = "host:", prod = "vault:' + FAKE_OCID + '" }'
        if rotate
        else gpu_refs
    )
    owner_text = owner.read_text(encoding="utf-8").replace(gpu_refs, expected_refs)
    owner_text = owner_text.replace(expected_refs, expected_refs + " # valid TOML trailing comment", 1)
    assert tomllib.loads(owner_text)["var"][-1]["secret"]["staging"] == "host:"
    owner.write_text(owner_text, encoding="utf-8")
    with pytest.raises(ValueError, match="GPU key manifest var must contain one inline secret map"):
        gpu_key_manifest.check_manifest_ready(paths["10-service-shared.toml"])

    terraform_input = tmp_path / "gpu-api-key.tfvars"
    terraform_before = None
    if rotate:
        terraform_before = (
            "# Generated by scripts/deploy/gpu-key-mint.sh; identifier only.\n"
            f'gpu_api_key_secret_ocid = "{FAKE_OCID}"\n'
        )
        terraform_input.write_text(terraform_before, encoding="utf-8")
    fragments_before = {path: path.read_text(encoding="utf-8") for path in manifest_dir.glob("*.toml")}
    assert {path.name for path in fragments_before} == {
        "10-service-shared.toml",
        "20-service-local.toml",
        "21-service-vm.toml",
        "22-service-fir.toml",
        "30-portal-backend.toml",
        "40-demo.toml",
        "50-wp-e2e.toml",
        "60-app-portal.toml",
        "targets.toml",
    }

    bin_dir = _fake_cli(tmp_path)
    input_capture = tmp_path / "writer-stdin"
    argument_capture = tmp_path / "writer-arguments"
    mutations = tmp_path / "vault-mutations"
    args = [
        "bash",
        str(SCRIPT_PATH),
        "--approve-mint",
        "--manifest",
        str(paths["10-service-shared.toml"]),
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
            "ACX_OCI_PYTHON": str(bin_dir / "oci-python"),
            "GPU_KEY_TEST_OCID": FAKE_OCID,
            "GPU_KEY_TEST_STDIN_CAPTURE": str(input_capture),
            "GPU_KEY_TEST_ARGUMENT_CAPTURE": str(argument_capture),
            "GPU_KEY_TEST_MUTATIONS": str(mutations),
            "TMPDIR": str(tmp_path),
        },
    )

    assert result.returncode != 0
    assert "GPU key manifest var must contain one inline secret map" in result.stderr
    assert not argument_capture.exists()
    assert not input_capture.exists()
    assert not mutations.exists()
    assert {path: path.read_text(encoding="utf-8") for path in manifest_dir.glob("*.toml")} == fragments_before
    assert "gpukeypreflightprobe" not in result.stdout + result.stderr
    if terraform_before is None:
        assert not terraform_input.exists()
    else:
        assert terraform_input.read_text(encoding="utf-8") == terraform_before


@pytest.mark.parametrize("quote", ['"""', "'''"])
def test_mint_rejects_multiline_gpu_ref_quotes_before_local_writer(
    tmp_path: Path,
    quote: str,
) -> None:
    manifest_dir = tmp_path / "manifest.d"
    manifest_dir.mkdir()
    paths = _write_fragmented_manifest(manifest_dir)
    owner = paths["21-service-vm.toml"]
    owner_text = owner.read_text(encoding="utf-8").replace(
        'dev = "host:"',
        f"dev = {quote}host:{quote}",
        1,
    )
    assert tomllib.loads(owner_text)["var"][-1]["secret"]["dev"] == "host:"
    owner.write_text(owner_text, encoding="utf-8")
    fragments_before = {path: path.read_text(encoding="utf-8") for path in manifest_dir.glob("*.toml")}
    terraform_input = tmp_path / "gpu-api-key.tfvars"
    input_capture = tmp_path / "writer-stdin"
    argument_capture = tmp_path / "writer-arguments"
    mutations = tmp_path / "vault-mutations"
    bin_dir = _fake_cli(tmp_path)

    result = subprocess.run(
        [
            "bash",
            str(SCRIPT_PATH),
            "--approve-mint",
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
            "ACX_OCI_PYTHON": str(bin_dir / "oci-python"),
            "GPU_KEY_TEST_OCID": FAKE_OCID,
            "GPU_KEY_TEST_STDIN_CAPTURE": str(input_capture),
            "GPU_KEY_TEST_ARGUMENT_CAPTURE": str(argument_capture),
            "GPU_KEY_TEST_MUTATIONS": str(mutations),
            "TMPDIR": str(tmp_path),
        },
    )

    assert result.returncode != 0
    assert "exactly one dev secret ref" in result.stderr
    assert not input_capture.exists()
    assert not argument_capture.exists()
    assert not mutations.exists()
    assert {path: path.read_text(encoding="utf-8") for path in manifest_dir.glob("*.toml")} == fragments_before
    assert not terraform_input.exists()
    assert "gpukeypreflightprobe" not in result.stdout + result.stderr


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
    mutations = tmp_path / "vault-mutations"
    args = [
        "bash",
        str(SCRIPT_PATH),
        "--approve-mint",
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
            "ACX_OCI_PYTHON": str(bin_dir / "oci-python"),
            "GPU_KEY_MINT_TRANSACTION_LOCKED": "1",
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
                "ACX_OCI_PYTHON": str(bin_dir / "oci-python"),
                "GPU_KEY_MINT_TRANSACTION_LOCKED": "1",
                "GPU_KEY_MINT_TRANSACTION_LOCK_FD": str(lock_descriptor),
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
        gpu_key_manifest.set_gpu_key_ocid(path, OTHER_FAKE_OCID)

    assert path.read_text(encoding="utf-8") == after_first_mint


def test_manifest_write_lock_uses_shared_directory_abi(tmp_path: Path) -> None:
    manifest_dir = tmp_path / "manifest.d"
    manifest_dir.mkdir()
    fragment = manifest_dir / "10-service-shared.toml"
    fragment.write_text(MANIFEST_TEXT, encoding="utf-8")
    canonical_directory = tmp_path.resolve()
    digest = hashlib.sha256(os.fsencode(str(canonical_directory))).hexdigest()
    expected = Path(f"/tmp/acx-envman-manifest-write-{os.getuid()}-{digest}.lock")
    alias_directory = tmp_path / "manifest-alias"
    alias_directory.symlink_to(manifest_dir, target_is_directory=True)

    assert gpu_key_manifest.manifest_write_lock_path(fragment) == expected
    assert gpu_key_manifest.manifest_write_lock_path(manifest_dir) == expected
    assert gpu_key_manifest.manifest_write_lock_path(alias_directory / fragment.name) == expected
    assert gpu_key_manifest.manifest_write_lock_path(alias_directory) == expected
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


def test_harvest_cli_waits_for_mint_publication_across_canonical_symlink_lock(
    tmp_path: Path,
) -> None:
    env_root = tmp_path / "env"
    manifest_dir = env_root / "manifest.d"
    manifest_dir.mkdir(parents=True)
    paths = _write_fake_committed_manifest(manifest_dir)
    alias_dir = tmp_path / "manifest-alias"
    alias_dir.symlink_to(manifest_dir, target_is_directory=True)
    alias_manifest = alias_dir / "10-service-shared.toml"

    canonical_lock = gpu_key_manifest.manifest_write_lock_path(paths["10-service-shared.toml"])
    assert gpu_key_manifest.manifest_write_lock_path(alias_manifest) == canonical_lock
    assert gpu_key_manifest.manifest_write_lock_path(alias_dir) == canonical_lock

    subprocess.run(["git", "-C", str(env_root), "init", "--quiet"], check=True)
    subprocess.run(["git", "-C", str(env_root), "add", "manifest.d"], check=True)
    subprocess.run(
        [
            "git", "-C", str(env_root), "-c", "user.name=Fixture",
            "-c", "user.email=fixture@example.invalid", "commit", "--quiet", "-m", "fixture",
        ],
        check=True,
    )

    terraform_input = tmp_path / "gpu-api-key.tfvars"
    writer_started = tmp_path / "writer-started"
    release_writer = tmp_path / "release-writer"
    writer_stdin = tmp_path / "writer-stdin"
    writer_arguments = tmp_path / "writer-arguments"
    mutations = tmp_path / "vault-mutations"
    bin_dir = _fake_cli(tmp_path)
    mint_environment = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "ACX_OCI_PYTHON": str(bin_dir / "oci-python"),
        "GPU_KEY_TEST_OCID": FAKE_OCID,
        "GPU_KEY_TEST_STDIN_CAPTURE": str(writer_stdin),
        "GPU_KEY_TEST_ARGUMENT_CAPTURE": str(writer_arguments),
        "GPU_KEY_TEST_MUTATIONS": str(mutations),
        "GPU_KEY_TEST_WRITER_STARTED": str(writer_started),
        "GPU_KEY_TEST_WRITER_RELEASE": str(release_writer),
        "TMPDIR": str(tmp_path),
    }
    mint = subprocess.Popen(
        [
            "bash", str(SCRIPT_PATH), "--approve-mint",
            "--manifest", str(alias_manifest), "--terraform-input", str(terraform_input),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=mint_environment,
    )

    probe_dir = tmp_path / "harvest-probe"
    probe_dir.mkdir()
    (probe_dir / "sitecustomize.py").write_text(
        "import os\n"
        "from contextlib import contextmanager\n"
        "from pathlib import Path\n"
        "from env import harvest_apply\n"
        "_original_lock = harvest_apply._manifest_write_lock\n"
        "@contextmanager\n"
        "def _tracked_lock(path):\n"
        "    Path(os.environ['HARVEST_LOCK_ATTEMPT']).touch()\n"
        "    with _original_lock(path):\n"
        "        yield\n"
        "harvest_apply._manifest_write_lock = _tracked_lock\n"
        "_original_load = harvest_apply.load_manifest\n"
        "def _tracked_load(root):\n"
        "    Path(os.environ['HARVEST_LOAD_ENTERED']).touch()\n"
        "    return _original_load(root)\n"
        "harvest_apply.load_manifest = _tracked_load\n",
        encoding="utf-8",
    )
    harvest_lock_attempt = tmp_path / "harvest-lock-attempt"
    harvest_load_entered = tmp_path / "harvest-load-entered"
    harvest_input = tmp_path / "harvest.json"
    harvest_input.write_text(
        '{"version":1,"target":"svc-vm","env":"prod",'
        '"values":{"DB_POOL_SIZE":"16"},'
        '"withheld":{"secret":[],"derived":[],"unmanaged":[],"missing":[],'
        '"secret_looking":[],"unparsed":[]}}',
        encoding="utf-8",
    )
    harvest_environment = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": os.pathsep.join((str(REPO_ROOT / "scripts"), str(probe_dir))),
        "HARVEST_LOCK_ATTEMPT": str(harvest_lock_attempt),
        "HARVEST_LOAD_ENTERED": str(harvest_load_entered),
    }
    harvest = None
    try:
        deadline = time.monotonic() + 10
        while not writer_started.exists() and mint.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert writer_started.exists(), "fake Vault writer did not reach the pause point"

        harvest = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "from env import harvest_apply; raise SystemExit(harvest_apply.main())",
                "--root",
                str(env_root),
                str(harvest_input),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=harvest_environment,
        )
        deadline = time.monotonic() + 10
        while (
            not harvest_lock_attempt.exists()
            and harvest.poll() is None
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)
        assert harvest_lock_attempt.exists(), "harvest did not attempt the shared lock"
        time.sleep(0.1)
        assert harvest.poll() is None, "harvest should wait while mint owns the lock"
        assert not harvest_load_entered.exists(), "harvest loaded stale fragments before locking"

        release_writer.touch()
        mint_stdout, mint_stderr = mint.communicate(timeout=20)
        harvest_stdout, harvest_stderr = harvest.communicate(timeout=20)
    finally:
        release_writer.touch()
        if mint.poll() is None:
            mint.kill()
            mint.communicate(timeout=5)
        if harvest is not None and harvest.poll() is None:
            harvest.kill()
            harvest.communicate(timeout=5)

    assert mint.returncode == 0, mint_stderr
    _assert_key_only_in_stdin(tmp_path, writer_stdin)
    assert mint_stdout == f"{FAKE_OCID} 64\n"
    assert FAKE_KEY not in mint_stdout + mint_stderr
    assert writer_stdin.read_text(encoding="utf-8") == "True\n"
    assert writer_arguments.exists()
    assert mutations.read_text(encoding="utf-8") == "create\n"
    assert harvest.returncode == 0, harvest_stderr
    assert harvest_load_entered.exists()
    assert "set\tDB_POOL_SIZE\tprod\n" == harvest_stdout

    scripts_dir = str(REPO_ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    from env.manifest import load_manifest, vault_secret_map

    manifest = load_manifest(env_root)
    gpu = next(var for var in manifest.vars if var.name == "ACX_GPU_ENDPOINT_API_KEY")
    assert gpu.secret == {
        "dev": f"oci:{FAKE_OCID}",
        "staging": "host:",
        "prod": f"vault:{FAKE_OCID}",
    }
    assert vault_secret_map(manifest, "svc-vm", "prod")["ACX_GPU_ENDPOINT_API_KEY"] == FAKE_OCID
    assert terraform_input.read_text(encoding="utf-8") == (
        '# Generated by scripts/deploy/gpu-key-mint.sh; identifier only.\n'
        f'gpu_api_key_secret_ocid = "{FAKE_OCID}"\n'
    )
    assert stat.S_IMODE(terraform_input.stat().st_mode) == 0o600
    shared_doc = tomllib.loads(paths["10-service-shared.toml"].read_text(encoding="utf-8"))
    harvested = next(var for var in shared_doc["var"] if var["name"] == "DB_POOL_SIZE")
    assert harvested["values"]["prod"] == "16"


def test_manifest_lock_contention_times_out_before_local_writer(tmp_path: Path) -> None:
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
                "ACX_OCI_PYTHON": str(bin_dir / "oci-python"),
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
            "ACX_OCI_PYTHON": str(bin_dir / "oci-python"),
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
    _assert_key_only_in_stdin(tmp_path, tmp_path / "writer-stdin")
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
        def __init__(self, config, **_kwargs):
            assert config is not operator_config
            assert config == {**operator_config, "log_requests": False}
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

    operator_config = {"user": "fake-operator", "tenancy": "fake-tenancy", "log_requests": True}
    config_calls = []
    original_http_debuglevel = http.client.HTTPConnection.debuglevel
    http_log_calls: list[bool] = []

    def is_http_log_enabled(enabled: bool) -> None:
        http_log_calls.append(enabled)
        http.client.HTTPConnection.debuglevel = int(enabled)

    def from_file(*, profile_name):
        config_calls.append(profile_name)
        return operator_config

    fake_oci = SimpleNamespace(
        config=SimpleNamespace(from_file=from_file),
        base_client=SimpleNamespace(
            is_http_log_enabled=is_http_log_enabled,
        ),
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

    with monkeypatch.context() as restore_http_debuglevel:
        restore_http_debuglevel.setattr(
            http.client.HTTPConnection,
            "debuglevel",
            1,
        )

        assert run_writer("--bootstrap", FAKE_OCID, b"a" * 64) == 0
        assert http.client.HTTPConnection.debuglevel == 0
        assert http_log_calls == [False, False]
        assert capsys.readouterr().out == f"{FAKE_OCID} 64\n"
        assert writes == []

        restore_http_debuglevel.setattr(http.client.HTTPConnection, "debuglevel", 1)
        http_log_calls.clear()
        assert run_writer("--rotate-existing", FAKE_OCID, b"a" * 64) == 0
        assert http.client.HTTPConnection.debuglevel == 0
        assert http_log_calls == [False, False]
        assert capsys.readouterr().out == f"{FAKE_OCID} 64\n"
        assert writes == [("update", FAKE_OCID)]
        assert config_calls == ["DEFAULT", "DEFAULT"]

        for mode in ("--bootstrap", "--rotate-existing"):
            for vault_id in (None, OTHER_FAKE_OCID):
                before = list(writes)
                with pytest.raises(RuntimeError, match="expected secret identity"):
                    run_writer(mode, vault_id, b"c" * 64)
                assert writes == before

    assert http.client.HTTPConnection.debuglevel == original_http_debuglevel


def _manifest_with_gpu_ocid(ocid: str) -> str:
    return MANIFEST_TEXT.replace(
        'dev = "host:", staging = "host:", prod = "host:"',
        f'dev = "oci:{ocid}", staging = "host:", prod = "vault:{ocid}"',
    )


@pytest.mark.parametrize("rotate", [False, True])
@pytest.mark.parametrize("vault_state", ["missing", "recreated"])
def test_bound_vault_identity_conflicts_refuse_bootstrap_and_rotation_without_mutation(
    tmp_path: Path,
    rotate: bool,
    vault_state: str,
) -> None:
    bin_dir = _fake_cli(tmp_path)
    manifest = tmp_path / "10-service-shared.toml"
    original = _manifest_with_gpu_ocid(FAKE_OCID)
    manifest.write_text(original, encoding="utf-8")
    terraform_input = tmp_path / "gpu-api-key.tfvars"
    input_capture = tmp_path / "writer-stdin"
    argument_capture = tmp_path / "writer-arguments"
    mutations = tmp_path / "vault-mutations"
    args = [
        "bash",
        str(SCRIPT_PATH),
        "--approve-mint",
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
            "ACX_OCI_PYTHON": str(bin_dir / "oci-python"),
            "GPU_KEY_TEST_OCID": FAKE_OCID,
            "GPU_KEY_TEST_EXPECTED_ID": FAKE_OCID,
            "GPU_KEY_TEST_VAULT_STATE": vault_state,
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
def test_matching_vault_identity_is_bound_for_bootstrap_and_rotation(
    tmp_path: Path,
    rotate: bool,
) -> None:
    bin_dir = _fake_cli(tmp_path)
    manifest = tmp_path / "10-service-shared.toml"
    manifest.write_text(_manifest_with_gpu_ocid(FAKE_OCID), encoding="utf-8")
    terraform_input = tmp_path / "gpu-api-key.tfvars"
    argument_capture = tmp_path / "writer-arguments"
    mutations = tmp_path / "vault-mutations"
    args = [
        "bash",
        str(SCRIPT_PATH),
        "--approve-mint",
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
            "ACX_OCI_PYTHON": str(bin_dir / "oci-python"),
            "GPU_KEY_TEST_OCID": FAKE_OCID,
            "GPU_KEY_TEST_EXPECTED_ID": FAKE_OCID,
            "GPU_KEY_TEST_VAULT_STATE": "matching",
            "GPU_KEY_TEST_STDIN_CAPTURE": str(tmp_path / "writer-stdin"),
            "GPU_KEY_TEST_ARGUMENT_CAPTURE": str(argument_capture),
            "GPU_KEY_TEST_MUTATIONS": str(mutations),
            "TMPDIR": str(tmp_path),
        },
    )

    assert result.returncode == 0, result.stderr
    _assert_key_only_in_stdin(tmp_path, tmp_path / "writer-stdin")
    assert result.stdout == f"{FAKE_OCID} 64\n"
    assert f"--expected-secret-id {FAKE_OCID}" in argument_capture.read_text(encoding="utf-8")
    assert mutations.exists() is rotate


@pytest.mark.parametrize(
    ("gpu_refs", "expected_error"),
    [
        (
            'dev = "oci:not-an-ocid", staging = "host:", prod = "vault:not-an-ocid"',
            "GPU key manifest contains an invalid secret ref",
        ),
        (
            'dev = "oci:ocid1.vaultsecret.oc1.iad.' + "a" * 24 + '", '
            'staging = "host:", prod = "vault:ocid1.vaultsecret.oc1.iad.' + "b" * 24 + '"',
            "GPU key manifest dev/prod refs are inconsistent",
        ),
        (
            'dev = "oci:ocid1.vaultsecret.oc12.iad.' + "a" * 19 + '", '
            'staging = "host:", prod = "vault:ocid1.vaultsecret.oc12.iad.' + "a" * 19 + '"',
            "GPU key manifest contains an invalid secret ref",
        ),
    ],
)
def test_malformed_or_inconsistent_local_identity_refuses_before_writer(
    tmp_path: Path,
    gpu_refs: str,
    expected_error: str,
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
            "ACX_OCI_PYTHON": str(bin_dir / "oci-python"),
            "GPU_KEY_TEST_OCID": FAKE_OCID,
            "GPU_KEY_TEST_ARGUMENT_CAPTURE": str(argument_capture),
            "TMPDIR": str(tmp_path),
        },
    )

    assert result.returncode != 0
    assert expected_error in result.stderr
    assert not argument_capture.exists()


def test_stale_manifest_edit_during_vault_write_is_rejected(tmp_path: Path) -> None:
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


def test_run_locked_rotation_without_recorded_ocid_refuses_before_writer(tmp_path: Path) -> None:
    manifest_dir = tmp_path / "manifest.d"
    manifest_dir.mkdir()
    paths = _write_fake_committed_manifest(manifest_dir)
    before = {path: path.read_bytes() for path in paths.values()}
    terraform_input = tmp_path / "gpu-api-key.tfvars"
    writer_capture = tmp_path / "writer-contact"
    argument_capture = tmp_path / "writer-arguments"
    stdin_capture = tmp_path / "writer-stdin"
    mutations = tmp_path / "vault-mutations"
    bin_dir = _fake_cli(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            str(HELPER_PATH),
            "--run-locked",
            "--approve-mint",
            "--manifest",
            str(paths["10-service-shared.toml"]),
            "--terraform-input",
            str(terraform_input),
            "--rotate",
        ],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "ACX_OCI_PYTHON": str(bin_dir / "oci-python"),
            "GPU_KEY_TEST_OCID": FAKE_OCID,
            "GPU_KEY_TEST_WRITER_CAPTURE": str(writer_capture),
            "GPU_KEY_TEST_ARGUMENT_CAPTURE": str(argument_capture),
            "GPU_KEY_TEST_STDIN_CAPTURE": str(stdin_capture),
            "GPU_KEY_TEST_MUTATIONS": str(mutations),
            "TMPDIR": str(tmp_path),
        },
    )

    assert result.returncode != 0
    assert "rotation requires a recorded GPU secret OCID" in result.stderr
    assert not writer_capture.exists()
    assert not argument_capture.exists()
    assert not stdin_capture.exists()
    assert not mutations.exists()
    assert {path: path.read_bytes() for path in paths.values()} == before
    assert not terraform_input.exists()


def test_locked_shell_rotation_without_recorded_ocid_refuses_before_writer(tmp_path: Path) -> None:
    manifest_dir = tmp_path / "manifest.d"
    manifest_dir.mkdir()
    paths = _write_fake_committed_manifest(manifest_dir)
    before = {path: path.read_bytes() for path in paths.values()}
    manifest = paths["10-service-shared.toml"]
    terraform_input = tmp_path / "gpu-api-key.tfvars"
    expected_secret_id, owner, preimages = gpu_key_manifest._preflight_mint_transaction(
        manifest,
        terraform_input,
    )
    assert expected_secret_id is None
    writer_capture = tmp_path / "writer-contact"
    argument_capture = tmp_path / "writer-arguments"
    stdin_capture = tmp_path / "writer-stdin"
    mutations = tmp_path / "vault-mutations"
    bin_dir = _fake_cli(tmp_path)
    descriptor = gpu_key_manifest._open_manifest_write_lock(manifest)
    try:
        result = subprocess.run(
            [
                "bash",
                str(SCRIPT_PATH),
                "--approve-mint",
                "--manifest",
                str(manifest),
                "--terraform-input",
                str(terraform_input),
                "--expected-owner-sha256",
                preimages[owner] or "missing",
                "--expected-terraform-input-sha256",
                preimages[terraform_input] or "missing",
                "--rotate",
            ],
            check=False,
            capture_output=True,
            text=True,
            pass_fds=(descriptor,),
            env={
                **os.environ,
                "GPU_KEY_MINT_TRANSACTION_LOCKED": "1",
                "GPU_KEY_MINT_TRANSACTION_LOCK_FD": str(descriptor),
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "ACX_OCI_PYTHON": str(bin_dir / "oci-python"),
                "GPU_KEY_TEST_OCID": FAKE_OCID,
                "GPU_KEY_TEST_WRITER_CAPTURE": str(writer_capture),
                "GPU_KEY_TEST_ARGUMENT_CAPTURE": str(argument_capture),
                "GPU_KEY_TEST_STDIN_CAPTURE": str(stdin_capture),
                "GPU_KEY_TEST_MUTATIONS": str(mutations),
                "TMPDIR": str(tmp_path),
            },
        )
    finally:
        os.close(descriptor)

    assert result.returncode != 0
    assert "rotation requires a recorded GPU secret OCID" in result.stderr
    assert not writer_capture.exists()
    assert not argument_capture.exists()
    assert not stdin_capture.exists()
    assert not mutations.exists()
    assert {path: path.read_bytes() for path in paths.values()} == before
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
            "ACX_OCI_PYTHON": str(bin_dir / "oci-python"),
            "GPU_KEY_TEST_OCID": FAKE_OCID,
            "GPU_KEY_TEST_STDIN_CAPTURE": str(tmp_path / "writer-stdin"),
            "GPU_KEY_TEST_ARGUMENT_CAPTURE": str(tmp_path / "writer-arguments"),
            "GPU_KEY_TEST_MUTATIONS": str(tmp_path / "vault-mutations"),
            "GPU_KEY_TEST_EDIT_MANIFEST": str(manifest),
            "TMPDIR": str(tmp_path),
        },
    )

    assert result.returncode != 0
    assert "changed during GPU key mint transaction" in result.stderr
    assert "# external edit during local writer" in manifest.read_text(encoding="utf-8")
    assert original_gpu_refs in manifest.read_text(encoding="utf-8")
    assert not terraform_input.exists()
    assert (tmp_path / "vault-mutations").read_text(encoding="utf-8") == "create\n"
    assert FAKE_KEY not in result.stdout + result.stderr


def _fake_cli(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    commands = {
        "timeout": '''#!/bin/sh
while [ "$#" -gt 0 ]; do
  case "$1" in
    --kill-after=*) shift ;;
    *s) shift; break ;;
    *) exit 97 ;;
  esac
done
exec "$@"
''',
        "openssl": '''#!/bin/sh
# Generate the fixed fake value without storing it in env or this script.
printf '%064d' 0 | tr '0' 'a'
''',
        "oci": f"#!{bin_dir / 'oci-python'}\n",
        "writer-probe": f"#!{sys.executable}\n" + '''import os
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
key = b"a" * 64
value = sys.stdin.buffer.read()
# Check credentials in memory; persist only boolean observations.
environment_contains_key = any(key.decode("ascii") in item for pair in os.environ.items() for item in pair)
(root / "writer-environment").write_text(str(environment_contains_key) + "\\n")
Path(os.environ["GPU_KEY_TEST_STDIN_CAPTURE"]).write_text(str(value == key) + "\\n")
# The writer still owns the pipe, so the mint has not run its EXIT cleanup.
files_contain_key = any(key in path.read_bytes() for path in root.rglob("*") if path.is_file())
(root / "writer-files-before-cleanup").write_text(str(files_contain_key) + "\\n")
''',
        "oci-python": """#!/bin/sh
if [ "$1" = -c ] && [ "$2" = 'import oci' ]; then exit 0; fi
case "$1" in
  */_vault_put_secret.py) ;;
  *) exit 95 ;;
esac
if [ -n "${GPU_KEY_TEST_WRITER_CAPTURE:-}" ]; then
    printf '%s\\n' "$*" >>"$GPU_KEY_TEST_WRITER_CAPTURE"
fi
command="$*"
if [ -n "${GPU_KEY_TEST_ARGUMENT_CAPTURE:-}" ]; then
    printf '%s\\n' "$command" >"$GPU_KEY_TEST_ARGUMENT_CAPTURE"
fi
if [ -n "${GPU_KEY_TEST_EXPECTED_ID:-}" ]; then
    case "$command" in
        *"--expected-secret-id $GPU_KEY_TEST_EXPECTED_ID"*) ;;
        *) exit 94 ;;
    esac
fi
case "${GPU_KEY_TEST_VAULT_STATE:-initial}" in
    missing) cat >/dev/null; echo 'expected Vault secret is missing' >&2; exit 42 ;;
    recreated) cat >/dev/null; echo 'Vault secret was recreated under another OCID' >&2; exit 42 ;;
esac
""" + shlex.quote(sys.executable) + """ "$(dirname "$0")/writer-probe"
if [ -n "${GPU_KEY_TEST_WRITER_STARTED:-}" ]; then
    : >"$GPU_KEY_TEST_WRITER_STARTED"
    while [ ! -e "$GPU_KEY_TEST_WRITER_RELEASE" ]; do sleep 0.01; done
fi
if [ -n "${GPU_KEY_TEST_EDIT_MANIFEST:-}" ]; then
    printf '%s\\n' '# external edit during local writer' >>"$GPU_KEY_TEST_EDIT_MANIFEST"
fi
printf '%s %s\\n' "$GPU_KEY_TEST_OCID" 64
if [ -n "${GPU_KEY_TEST_MUTATIONS:-}" ]; then
    case "$command" in
        *'--rotate-existing'*) printf '%s\\n' rotate >>"$GPU_KEY_TEST_MUTATIONS" ;;
        *) if [ "${GPU_KEY_TEST_VAULT_STATE:-initial}" = initial ]; then printf '%s\\n' create >>"$GPU_KEY_TEST_MUTATIONS"; fi ;;
    esac
fi
""",
    }
    for name, content in commands.items():
        path = bin_dir / name
        path.write_text(content, encoding="utf-8")
        path.chmod(0o755)
    return bin_dir


def _assert_key_only_in_stdin(tmp_path: Path, stdin_capture: Path) -> None:
    environment_capture = tmp_path / "writer-environment"
    assert environment_capture.is_file()
    assert environment_capture.read_text(encoding="utf-8") == "False\n", "key leaked to writer environment"
    assert (tmp_path / "writer-files-before-cleanup").read_text(encoding="utf-8") == "False\n", (
        "key leaked to a file before mint cleanup"
    )
    assert stdin_capture.read_text(encoding="utf-8") == "True\n", "writer did not receive the fake key on stdin"
    for path in sorted(tmp_path.rglob("*")):
        if path.is_file():
            file_contains_key = FAKE_KEY.encode("ascii") in path.read_bytes()
            assert not file_contains_key, f"key leaked to {path}"


def test_mint_requires_approval_before_contacting_writer(tmp_path: Path) -> None:
    bin_dir = _fake_cli(tmp_path)
    result = subprocess.run(
        ["bash", str(SCRIPT_PATH)],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "ACX_OCI_PYTHON": str(bin_dir / "oci-python")},
    )

    assert result.returncode != 0
    assert "requires explicit --approve-mint" in result.stderr
    assert not (tmp_path / "writer-arguments").exists()


@pytest.mark.parametrize("prerequisite", ["oci-cli", "oci-sdk"])
@pytest.mark.parametrize("existing_input", [False, True])
def test_mint_refuses_missing_oci_prerequisite_before_lock_or_writer(
    tmp_path: Path,
    prerequisite: str,
    existing_input: bool,
) -> None:
    bin_dir = _fake_cli(tmp_path)
    manifest = tmp_path / "10-service-shared.toml"
    original = _manifest_with_gpu_ocid(FAKE_OCID) if existing_input else MANIFEST_TEXT
    manifest.write_text(original, encoding="utf-8")
    terraform_input = tmp_path / "gpu-api-key.tfvars"
    if existing_input:
        terraform_input.write_text(f'gpu_api_key_secret_ocid = "{FAKE_OCID}"\n', encoding="utf-8")
    before_input = terraform_input.read_bytes() if existing_input else None
    argument_capture = tmp_path / "writer-arguments"
    stdin_capture = tmp_path / "writer-stdin"
    environment = {
        **os.environ,
        "PATH": str(bin_dir),
        "GPU_KEY_TEST_ARGUMENT_CAPTURE": str(argument_capture),
        "GPU_KEY_TEST_STDIN_CAPTURE": str(stdin_capture),
        "GPU_KEY_TEST_OCID": FAKE_OCID,
    }
    environment.pop("ACX_OCI_PYTHON", None)
    # Only these local commands may run before the prerequisite check. Do not
    # expose an ambient oci executable when checking the missing-CLI path.
    dirname = shutil.which("dirname")
    assert dirname is not None
    (bin_dir / "dirname").symlink_to(dirname)
    if prerequisite == "oci-cli":
        (bin_dir / "oci").unlink()
        message = "oci CLI not found in PATH. brew install oci-cli"
    else:
        interpreter = bin_dir / "oci-python"
        interpreter.write_text(
            '#!/bin/sh\nif [ "$1" = -c ]; then exit 1; fi\n'
            ': >"$GPU_KEY_TEST_ARGUMENT_CAPTURE"\nexit 99\n',
            encoding="utf-8",
        )
        environment["ACX_OCI_PYTHON"] = str(interpreter)
        message = f"no OCI SDK in {interpreter}; set ACX_OCI_PYTHON"

    bash = shutil.which("bash")
    assert bash is not None
    lock_path = gpu_key_manifest.manifest_write_lock_path(manifest)
    assert not lock_path.exists()
    result = subprocess.run(
        [
            bash, str(SCRIPT_PATH), "--approve-mint",
            "--manifest", str(manifest), "--terraform-input", str(terraform_input),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode != 0
    assert message in result.stderr
    assert result.stdout == ""
    assert not argument_capture.exists() and not stdin_capture.exists()
    assert not lock_path.exists()
    assert manifest.read_text(encoding="utf-8") == original
    assert (terraform_input.read_bytes() if terraform_input.exists() else None) == before_input
    assert FAKE_KEY not in result.stdout + result.stderr


def test_mint_rejects_obsolete_ssh_target_as_unknown_argument(tmp_path: Path) -> None:
    bin_dir = _fake_cli(tmp_path)
    argument_capture = tmp_path / "writer-arguments"
    result = subprocess.run(
        ["bash", str(SCRIPT_PATH), "--approve-mint", "--ssh-target", "x@y"],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "ACX_OCI_PYTHON": str(bin_dir / "oci-python"),
            "GPU_KEY_TEST_ARGUMENT_CAPTURE": str(argument_capture),
        },
    )

    assert result.returncode != 0
    assert "unknown argument: --ssh-target" in result.stderr
    assert result.stdout == ""
    assert not argument_capture.exists()


@pytest.mark.parametrize("rotate", [False, True])
def test_run_locked_helper_requires_explicit_approval_before_writer(
    tmp_path: Path,
    rotate: bool,
) -> None:
    manifest_dir = tmp_path / "manifest.d"
    manifest_dir.mkdir()
    paths = _write_fake_committed_manifest(manifest_dir)
    owner = paths["21-service-vm.toml"]
    if rotate:
        _replace_var_field(
            owner,
            "ACX_GPU_ENDPOINT_API_KEY",
            "secret",
            f'secret = {{ dev = "oci:{FAKE_OCID}", staging = "host:", prod = "vault:{FAKE_OCID}" }}',
        )
    before = {path: path.read_bytes() for path in paths.values()}
    terraform_input = tmp_path / "gpu-api-key.tfvars"
    argument_capture = tmp_path / "writer-arguments"
    stdin_capture = tmp_path / "writer-stdin"
    mutations = tmp_path / "vault-mutations"
    bin_dir = _fake_cli(tmp_path)
    environment = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "ACX_OCI_PYTHON": str(bin_dir / "oci-python"),
        "GPU_KEY_TEST_OCID": FAKE_OCID,
        "GPU_KEY_TEST_ARGUMENT_CAPTURE": str(argument_capture),
        "GPU_KEY_TEST_STDIN_CAPTURE": str(stdin_capture),
        "GPU_KEY_TEST_MUTATIONS": str(mutations),
        "TMPDIR": str(tmp_path),
    }
    if rotate:
        environment["GPU_KEY_TEST_EXPECTED_ID"] = FAKE_OCID
    args = [
        sys.executable,
        str(HELPER_PATH),
        "--run-locked",
        "--manifest",
        str(paths["10-service-shared.toml"]),
        "--terraform-input",
        str(terraform_input),
    ]
    if rotate:
        args.append("--rotate")

    result = subprocess.run(args, check=False, capture_output=True, text=True, env=environment)

    assert not mutations.exists()
    assert not argument_capture.exists()
    assert not stdin_capture.exists()
    assert {path: path.read_bytes() for path in paths.values()} == before
    assert not terraform_input.exists()
    assert result.returncode != 0
    assert "requires explicit --approve-mint" in result.stderr


@pytest.mark.parametrize("rotate", [False, True])
def test_run_locked_helper_with_approval_publishes_complete_fragments(
    tmp_path: Path,
    rotate: bool,
) -> None:
    manifest_dir = tmp_path / "manifest.d"
    manifest_dir.mkdir()
    paths = _write_fake_committed_manifest(manifest_dir)
    owner = paths["21-service-vm.toml"]
    if rotate:
        _replace_var_field(
            owner,
            "ACX_GPU_ENDPOINT_API_KEY",
            "secret",
            f'secret = {{ dev = "oci:{FAKE_OCID}", staging = "host:", prod = "vault:{FAKE_OCID}" }}',
        )
    before = {path: path.read_bytes() for path in paths.values()}
    terraform_input = tmp_path / "gpu-api-key.tfvars"
    argument_capture = tmp_path / "writer-arguments"
    stdin_capture = tmp_path / "writer-stdin"
    mutations = tmp_path / "vault-mutations"
    bin_dir = _fake_cli(tmp_path)
    environment = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "ACX_OCI_PYTHON": str(bin_dir / "oci-python"),
        "GPU_KEY_TEST_OCID": FAKE_OCID,
        "GPU_KEY_TEST_ARGUMENT_CAPTURE": str(argument_capture),
        "GPU_KEY_TEST_STDIN_CAPTURE": str(stdin_capture),
        "GPU_KEY_TEST_MUTATIONS": str(mutations),
        "TMPDIR": str(tmp_path),
    }
    if rotate:
        environment["GPU_KEY_TEST_EXPECTED_ID"] = FAKE_OCID
    args = [
        sys.executable,
        str(HELPER_PATH),
        "--run-locked",
        "--approve-mint",
        "--manifest",
        str(paths["10-service-shared.toml"]),
        "--terraform-input",
        str(terraform_input),
    ]
    if rotate:
        args.append("--rotate")

    result = subprocess.run(args, check=False, capture_output=True, text=True, env=environment)

    assert result.returncode == 0, result.stderr
    _assert_key_only_in_stdin(tmp_path, stdin_capture)
    assert result.stdout == f"{FAKE_OCID} 64\n"
    assert FAKE_KEY not in result.stdout + result.stderr
    assert stdin_capture.read_text(encoding="utf-8") == "True\n"
    assert mutations.read_text(encoding="utf-8") == ("rotate\n" if rotate else "create\n")
    writer_arguments = argument_capture.read_text(encoding="utf-8")
    assert FAKE_KEY not in writer_arguments
    assert (f"--rotate-existing" in writer_arguments) is rotate
    assert (f"--expected-secret-id {FAKE_OCID}" in writer_arguments) is rotate
    assert stat.S_IMODE(terraform_input.stat().st_mode) == 0o600
    assert terraform_input.read_text(encoding="utf-8") == (
        '# Generated by scripts/deploy/gpu-key-mint.sh; identifier only.\n'
        f'gpu_api_key_secret_ocid = "{FAKE_OCID}"\n'
    )

    after = {path: path.read_bytes() for path in paths.values()}
    assert all(after[path] == before[path] for path in paths.values() if path != owner)
    assert after[owner] == gpu_key_manifest._update_gpu_key_text(
        before[owner].decode("utf-8"), FAKE_OCID
    ).encode("utf-8")
    gpu = next(
        row
        for row in tomllib.loads(after[owner].decode("utf-8"))["var"]
        if row["name"] == "ACX_GPU_ENDPOINT_API_KEY"
    )
    assert gpu["secret"] == {
        "dev": f"oci:{FAKE_OCID}",
        "staging": "host:",
        "prod": f"vault:{FAKE_OCID}",
    }


def test_mint_refuses_unready_manifest_before_contacting_writer(tmp_path: Path) -> None:
    bin_dir = _fake_cli(tmp_path)
    manifest = tmp_path / "10-service-shared.toml"
    manifest.write_text(MANIFEST_TEXT.replace("derive_vault_map = true", "derive_vault_map = false"), encoding="utf-8")
    result = subprocess.run(
        [
            "bash",
            str(SCRIPT_PATH),
            "--approve-mint",
            "--manifest",
            str(manifest),
        ],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "ACX_OCI_PYTHON": str(bin_dir / "oci-python")},
    )

    assert result.returncode != 0
    assert "requires the svc-vm derived Vault secret map" in result.stderr
    assert not (tmp_path / "writer-arguments").exists()


@pytest.mark.parametrize("rotate", [False, True])
@pytest.mark.parametrize("trace", [False, True])
@pytest.mark.parametrize("interpreter_source", ["override", "cli-shebang"])
def test_mint_pipes_fake_random_input_and_prints_only_ocid_and_length(
    tmp_path: Path,
    rotate: bool,
    trace: bool,
    interpreter_source: str,
) -> None:
    inherited_credential = "fake-inherited-credential-" + "z" * 32
    bin_dir = _fake_cli(tmp_path)
    manifest = tmp_path / "10-service-shared.toml"
    manifest.write_text(_manifest_with_gpu_ocid(FAKE_OCID) if rotate else MANIFEST_TEXT, encoding="utf-8")
    terraform_input = tmp_path / "gpu-api-key.tfvars"
    input_capture = tmp_path / "writer-stdin"
    argument_capture = tmp_path / "writer-arguments"
    args = ["bash"]
    if trace:
        args.append("-x")
    args.extend([
        str(SCRIPT_PATH),
        "--approve-mint",
        "--manifest",
        str(manifest),
        "--terraform-input",
        str(terraform_input),
    ])
    if rotate:
        args.append("--rotate")
    environment = {
        **os.environ,
        "GPU_KEY_TEST_INHERITED_CREDENTIAL": inherited_credential,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "ACX_OCI_PYTHON": str(bin_dir / "oci-python"),
        "GPU_KEY_TEST_OCID": FAKE_OCID,
        "GPU_KEY_TEST_STDIN_CAPTURE": str(input_capture),
        "GPU_KEY_TEST_ARGUMENT_CAPTURE": str(argument_capture),
        "TMPDIR": str(tmp_path),
    }
    if interpreter_source == "cli-shebang":
        environment.pop("ACX_OCI_PYTHON")
    if trace:
        environment["SHELLOPTS"] = "xtrace"
        # set +x updates exported SHELLOPTS, so re-enable xtrace at every Bash
        # entry, including the locked script and its nested writer shell.
        bash_startup = tmp_path / "bash-startup"
        bash_startup.write_text("set -x\n", encoding="utf-8")
        environment["BASH_ENV"] = str(bash_startup)
    if rotate:
        environment["GPU_KEY_TEST_EXPECTED_ID"] = FAKE_OCID

    result = subprocess.run(args, check=False, capture_output=True, text=True, env=environment)

    assert result.returncode == 0, result.stderr
    _assert_key_only_in_stdin(tmp_path, input_capture)
    for path in tmp_path.rglob("*"):
        if path.is_file():
            contains_inherited_credential = inherited_credential.encode("ascii") in path.read_bytes()
            assert not contains_inherited_credential, "test persisted an inherited credential"
    assert result.stdout == f"{FAKE_OCID} 64\n"
    assert FAKE_KEY not in result.stdout
    assert FAKE_KEY not in result.stderr
    if trace:
        # The outer script, locked script, and writer shell each disable tracing.
        assert result.stderr.count("+ set +x\n") >= 3
    assert input_capture.read_text(encoding="utf-8") == "True\n"
    vault_args = argument_capture.read_text(encoding="utf-8")
    assert FAKE_KEY not in vault_args
    assert "--result-only" in vault_args
    assert "--instance-principal" not in vault_args
    assert "sudo" not in vault_args and "ssh" not in vault_args
    assert "--readable-timeout 90" in vault_args
    assert "--operation-timeout 150" in vault_args
    assert ("--bootstrap" in vault_args) is not rotate
    assert ("--rotate-existing" in vault_args) is rotate
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
            "ACX_OCI_PYTHON": str(bin_dir / "oci-python"),
            "GPU_KEY_TEST_OCID": FAKE_OCID,
            "GPU_KEY_TEST_STDIN_CAPTURE": str(input_capture),
            "GPU_KEY_TEST_ARGUMENT_CAPTURE": str(argument_capture),
            "TMPDIR": str(tmp_path),
        },
    )

    assert result.returncode == 0, result.stderr
    _assert_key_only_in_stdin(tmp_path, input_capture)
    assert result.stdout == f"{FAKE_OCID} 64\n"
    assert input_capture.read_text(encoding="utf-8") == "True\n"
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


@pytest.mark.parametrize("newline_style", ["lf", "crlf"])
@pytest.mark.parametrize("rotate", [False, True])
def test_mint_persists_complete_fragmented_manifest_with_original_newlines(
    tmp_path: Path,
    newline_style: str,
    rotate: bool,
) -> None:
    manifest_dir = tmp_path / "manifest.d"
    manifest_dir.mkdir()
    paths = _write_fake_committed_manifest(manifest_dir)
    owner = paths["21-service-vm.toml"]
    if rotate:
        _replace_var_field(
            owner,
            "ACX_GPU_ENDPOINT_API_KEY",
            "secret",
            f'secret = {{ dev = "oci:{FAKE_OCID}", staging = "host:", prod = "vault:{FAKE_OCID}" }}',
        )
    if newline_style == "crlf":
        for fragment in paths.values():
            fragment.write_bytes(fragment.read_bytes().replace(b"\n", b"\r\n"))

    before_fragments = {path: path.read_bytes() for path in paths.values()}
    before_owner_text = before_fragments[owner].decode("utf-8")
    before_owner_document = tomllib.loads(before_owner_text)
    terraform_input = tmp_path / "gpu-api-key.tfvars"
    input_capture = tmp_path / "writer-stdin"
    argument_capture = tmp_path / "writer-arguments"
    mutations = tmp_path / "vault-mutations"
    bin_dir = _fake_cli(tmp_path)
    args = [
        "bash",
        str(SCRIPT_PATH),
        "--approve-mint",
        "--manifest",
        str(paths["10-service-shared.toml"]),
        "--terraform-input",
        str(terraform_input),
    ]
    if rotate:
        args.append("--rotate")
    environment = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "ACX_OCI_PYTHON": str(bin_dir / "oci-python"),
        "GPU_KEY_TEST_OCID": FAKE_OCID,
        "GPU_KEY_TEST_STDIN_CAPTURE": str(input_capture),
        "GPU_KEY_TEST_ARGUMENT_CAPTURE": str(argument_capture),
        "GPU_KEY_TEST_MUTATIONS": str(mutations),
        "TMPDIR": str(tmp_path),
    }
    if rotate:
        environment["GPU_KEY_TEST_EXPECTED_ID"] = FAKE_OCID

    result = subprocess.run(args, check=False, capture_output=True, text=True, env=environment)

    assert result.returncode == 0, result.stderr
    _assert_key_only_in_stdin(tmp_path, input_capture)
    assert result.stdout == f"{FAKE_OCID} 64\n"
    assert input_capture.read_text(encoding="utf-8") == "True\n"
    assert mutations.read_text(encoding="utf-8") == ("rotate\n" if rotate else "create\n")
    vault_arguments = argument_capture.read_text(encoding="utf-8")
    assert (f"--expected-secret-id {FAKE_OCID}" in vault_arguments) == rotate
    assert stat.S_IMODE(terraform_input.stat().st_mode) == 0o600
    assert terraform_input.read_text(encoding="utf-8") == (
        '# Generated by scripts/deploy/gpu-key-mint.sh; identifier only.\n'
        f'gpu_api_key_secret_ocid = "{FAKE_OCID}"\n'
    )

    after_fragments = {path: path.read_bytes() for path in paths.values()}
    for fragment, before_content in before_fragments.items():
        if fragment != owner:
            assert after_fragments[fragment] == before_content
    expected_owner = gpu_key_manifest._update_gpu_key_text(before_owner_text, FAKE_OCID).encode("utf-8")
    assert after_fragments[owner] == expected_owner
    if newline_style == "crlf":
        assert after_fragments[owner].count(b"\r\n") == after_fragments[owner].count(b"\n")

    before_gpu = next(
        row for row in before_owner_document["var"] if row["name"] == "ACX_GPU_ENDPOINT_API_KEY"
    )
    after_gpu = next(
        row
        for row in tomllib.loads(after_fragments[owner].decode("utf-8"))["var"]
        if row["name"] == "ACX_GPU_ENDPOINT_API_KEY"
    )
    assert {key: value for key, value in after_gpu.items() if key != "secret"} == {
        key: value for key, value in before_gpu.items() if key != "secret"
    }
    assert after_gpu["secret"]["dev"] == f"oci:{FAKE_OCID}"
    assert after_gpu["secret"]["prod"] == f"vault:{FAKE_OCID}"
    assert after_gpu["secret"]["staging"] == before_gpu["secret"]["staging"] == "host:"


@pytest.mark.parametrize(
    "secret_ocid",
    [
        "ocid1.vaultsecret.oc12.iad." + "AbCdEfGhIjKlMnOpQrStUvWx",
        "ocid1.vaultsecret.oc3.us_ashburn_1." + "ab_cd.ef-gh_ij.kl-mn_op.qr-st_uv",
    ],
    ids=["uppercase-numbered-realm", "underscore-and-dotted-unique-part"],
)
def test_mint_publishes_writer_supported_ocids_through_bootstrap_retry_and_rotation(
    tmp_path: Path,
    secret_ocid: str,
) -> None:
    bin_dir = _fake_cli(tmp_path)
    manifest_dir = tmp_path / "manifest.d"
    manifest_dir.mkdir()
    paths = _write_fake_committed_manifest(manifest_dir)
    before = {path: path.read_bytes() for path in paths.values()}
    terraform_input = tmp_path / "gpu-api-key.tfvars"
    input_capture = tmp_path / "writer-stdin"
    argument_capture = tmp_path / "writer-arguments"
    mutations = tmp_path / "vault-mutations"
    base_args = [
        "bash",
        str(SCRIPT_PATH),
        "--approve-mint",
        "--manifest",
        str(paths["10-service-shared.toml"]),
        "--terraform-input",
        str(terraform_input),
    ]

    for state, rotate in (("initial", False), ("existing", False), ("existing", True)):
        environment = {
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "ACX_OCI_PYTHON": str(bin_dir / "oci-python"),
            "GPU_KEY_TEST_OCID": secret_ocid,
            "GPU_KEY_TEST_STDIN_CAPTURE": str(input_capture),
            "GPU_KEY_TEST_ARGUMENT_CAPTURE": str(argument_capture),
            "GPU_KEY_TEST_MUTATIONS": str(mutations),
            "GPU_KEY_TEST_VAULT_STATE": state,
            "TMPDIR": str(tmp_path),
        }
        if state == "existing":
            environment["GPU_KEY_TEST_EXPECTED_ID"] = secret_ocid
        args = list(base_args)
        if rotate:
            args.append("--rotate")

        result = subprocess.run(args, check=False, capture_output=True, text=True, env=environment)

        assert result.returncode == 0, result.stderr
        _assert_key_only_in_stdin(tmp_path, input_capture)
        assert result.stdout == f"{secret_ocid} 64\n"
        assert FAKE_KEY not in result.stdout + result.stderr

    assert input_capture.read_text(encoding="utf-8") == "True\n"
    assert mutations.read_text(encoding="utf-8") == "create\nrotate\n"
    assert f"--expected-secret-id {secret_ocid}" in argument_capture.read_text(encoding="utf-8")
    assert stat.S_IMODE(terraform_input.stat().st_mode) == 0o600
    assert terraform_input.read_text(encoding="utf-8") == (
        "# Generated by scripts/deploy/gpu-key-mint.sh; identifier only.\n"
        f'gpu_api_key_secret_ocid = "{secret_ocid}"\n'
    )
    owner = paths["21-service-vm.toml"]
    for path, original in before.items():
        if path != owner:
            assert path.read_bytes() == original
    gpu = next(
        row
        for row in tomllib.loads(owner.read_text(encoding="utf-8"))["var"]
        if row["name"] == "ACX_GPU_ENDPOINT_API_KEY"
    )
    assert gpu["secret"] == {
        "dev": f"oci:{secret_ocid}",
        "staging": "host:",
        "prod": f"vault:{secret_ocid}",
    }


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
