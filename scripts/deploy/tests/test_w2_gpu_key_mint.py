"""Tests for GPU Vault key minting without live OCI, SSH, or GPU calls."""

from __future__ import annotations

import importlib.util
import os
import stat
import subprocess
import tomllib
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
HELPER_PATH = REPO_ROOT / "scripts/deploy/_gpu_key_manifest.py"
SCRIPT_PATH = REPO_ROOT / "scripts/deploy/gpu-key-mint.sh"
SPEC = importlib.util.spec_from_file_location("gpu_key_manifest", HELPER_PATH)
assert SPEC is not None and SPEC.loader is not None
gpu_key_manifest = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gpu_key_manifest)

FAKE_OCID = "ocid1.vaultsecret.oc1.iad.fakegpuapikey123"
FAKE_KEY = "a" * 64
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


def test_manifest_refuses_to_change_a_different_minted_ocid(tmp_path: Path) -> None:
    path = tmp_path / "10-service-shared.toml"
    path.write_text(MANIFEST_TEXT, encoding="utf-8")
    gpu_key_manifest.set_gpu_key_ocid(path, FAKE_OCID)
    after_first_mint = path.read_text(encoding="utf-8")

    with pytest.raises(ValueError, match="refusing to replace existing dev GPU key ref"):
        gpu_key_manifest.set_gpu_key_ocid(path, "ocid1.vaultsecret.oc1.iad.anotherfakekey")

    assert path.read_text(encoding="utf-8") == after_first_mint


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
            "    cat >\"$GPU_KEY_TEST_STDIN_CAPTURE\"\n"
            "    printf '%s %s\\n' \"$GPU_KEY_TEST_OCID\" 64\n"
            "    printf '%s\\n' \"$command\" >\"$GPU_KEY_TEST_ARGUMENT_CAPTURE\"\n"
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


def test_cloud_init_fetches_key_at_runtime_and_gates_docker() -> None:
    cloud_init = (REPO_ROOT / "infra/oci/gpu-cloud-init.yaml").read_text(encoding="utf-8")
    terraform = (REPO_ROOT / "infra/oci/main.tf").read_text(encoding="utf-8")
    terraform_vars = (REPO_ROOT / "infra/oci/variables.tf").read_text(encoding="utf-8")
    prod_example = (REPO_ROOT / "apps/prototype-description-service/.env.prod.example").read_text(encoding="utf-8")

    assert "--auth instance_principal secrets secret-bundle get" in cloud_init
    assert "ATTEMPT_TIMEOUT=20" in cloud_init and "ATTEMPTS=5" in cloud_init
    assert "chmod 0600 \"$temporary\"" in cloud_init
    assert "ExecStartPre=/usr/local/bin/acx-gpu-fetch-api-key.sh" in cloud_init
    assert "--api-key \"$key\"" in cloud_init
    assert "gpu_api_key_secret_ocid  = var.gpu_api_key_secret_ocid" in terraform
    assert 'default     = ""' in terraform_vars
    assert "make gpu-key-mint" in prod_example
    assert "REPLACE_GPU_ENDPOINT_KEY" not in prod_example
    assert "REPLACE_GPU_ENDPOINT_KEY" not in cloud_init
