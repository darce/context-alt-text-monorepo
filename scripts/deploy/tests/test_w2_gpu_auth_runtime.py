from __future__ import annotations

import base64
import json
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[3]
OCI_ROOT = REPO_ROOT / "infra" / "oci"
FAKE_SECRET_OCID = "ocid1.vaultsecret.oc1.iad.FAKE_GPU_API_KEY_RUNTIME_0001"
FAKE_KEY = b"a" * 64


def _gpu_secret_ocid_variable_block() -> str:
    variables_tf = (OCI_ROOT / "variables.tf").read_text()
    match = re.search(
        r'(?ms)^variable "gpu_api_key_secret_ocid" \{\n.*?^\}', variables_tf
    )
    assert match is not None, "expected the committed GPU Vault OCID variable block"
    return match.group(0)


def _plan_gpu_secret_ocid_fixture(
    tmp_path: Path, *, name: str, identifier: str | None
) -> subprocess.CompletedProcess[str]:
    terraform = shutil.which("terraform")
    if terraform is None:
        pytest.skip("Terraform is required for the provider-free variable plan check")

    fixture = tmp_path / name
    fixture.mkdir()
    (fixture / "main.tf").write_text(_gpu_secret_ocid_variable_block() + "\n")
    var_file_arg: list[str] = []
    if identifier is not None:
        # This is the identifier-only artifact shape emitted by the mint helper.
        var_file = fixture / "gpu-api-key-secret.tfvars"
        var_file.write_text(
            "gpu_api_key_secret_ocid = " + json.dumps(identifier) + "\n"
        )
        var_file_arg = [f"-var-file={var_file}"]

    return subprocess.run(
        [
            terraform,
            f"-chdir={fixture}",
            "plan",
            "-input=false",
            "-no-color",
            *var_file_arg,
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def _cloud_init_files() -> dict[str, str]:
    document = yaml.safe_load((OCI_ROOT / "gpu-cloud-init.yaml").read_text())
    return {entry["path"]: entry["content"] for entry in document["write_files"]}


def test_gpu_runtime_reads_key_with_instance_principal_and_keeps_it_out_of_argv(
    tmp_path: Path,
) -> None:
    files = _cloud_init_files()
    fetch = files["/usr/local/bin/acx-gpu-fetch-api-key.sh"]
    start = files["/usr/local/bin/acx-gpu-vlm-start.sh"]

    assert "--auth instance_principal secrets secret-bundle get" in fetch
    assert "--secret-id \"$SECRET_ID\"" in fetch
    assert 'install -d -o root -g root -m 0700 "$RUNTIME_DIR"' in fetch
    assert 'chown root:root "$temporary"' in fetch
    assert 'chmod 0600 "$temporary"' in fetch
    assert "readonly ATTEMPTS=5" in fetch
    assert 'readonly ATTEMPT_TIMEOUT=20' in fetch
    assert 'readonly RETRY_DELAY=2' in fetch

    runtime_dir = tmp_path / "runtime"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_oci = fake_bin / "oci"
    fake_oci.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' \"$@\" > \"$FAKE_OCI_ARGV\"\n"
        "printf '%s\\n' \"$FAKE_SECRET_BASE64\"\n"
    )
    fake_oci.chmod(0o755)

    docker_args = tmp_path / "docker-argv"
    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' \"$@\" > \"$FAKE_DOCKER_ARGV\"\n"
    )
    fake_docker.chmod(0o755)

    fetch = fetch.replace("$${", "${")
    fetch = fetch.replace(
        "${gpu_api_key_secret_ocid}", FAKE_SECRET_OCID
    )
    fetch = fetch.replace(
        "readonly OCI_BIN=/usr/bin/oci",
        f"readonly OCI_BIN={shlex.quote(str(fake_oci))}",
    )
    fetch = fetch.replace("/run/acx-gpu-vlm", str(runtime_dir))
    # Keep this fixture runnable as an unprivileged developer while retaining
    # static and resulting-mode assertions for the production ownership step.
    fetch = fetch.replace(
        'install -d -o root -g root -m 0700 "$RUNTIME_DIR"',
        'mkdir -p "$RUNTIME_DIR" && chmod 0700 "$RUNTIME_DIR"',
    )
    fetch = fetch.replace('chown root:root "$temporary"', ":")
    fetch_path = tmp_path / "fetch-api-key.sh"
    fetch_path.write_text(fetch)
    fetch_path.chmod(0o750)

    env = {
        **os.environ,
        "FAKE_OCI_ARGV": str(tmp_path / "oci-argv"),
        "FAKE_DOCKER_ARGV": str(docker_args),
        "FAKE_SECRET_BASE64": base64.b64encode(FAKE_KEY).decode("ascii"),
    }
    fetched = subprocess.run(
        ["/bin/bash", str(fetch_path)], env=env, capture_output=True, text=True, check=False
    )
    assert fetched.returncode == 0, fetched.stderr

    key_path = runtime_dir / "api-key"
    assert key_path.read_bytes() == FAKE_KEY
    assert runtime_dir.stat().st_mode & 0o777 == 0o700
    assert key_path.stat().st_mode & 0o777 == 0o600

    start = start.replace("/run/acx-gpu-vlm/api-key", str(key_path))
    start = start.replace("/usr/bin/docker", shlex.quote(str(fake_docker)))
    start_path = tmp_path / "start-vlm.sh"
    start_path.write_text(start)
    start_path.chmod(0o750)
    started = subprocess.run(
        ["/bin/bash", str(start_path)],
        env={key: value for key, value in env.items() if key != "FAKE_SECRET_BASE64"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert started.returncode == 0, started.stderr

    docker_argv = docker_args.read_bytes()
    assert FAKE_KEY not in docker_argv
    docker_words = docker_argv.decode("utf-8").splitlines()
    assert "--api-key-file" in docker_words
    key_flag = docker_words.index("--api-key-file")
    assert docker_words[key_flag + 1] == "/run/secrets/acx-gpu-api-key"
    assert f"{key_path}:/run/secrets/acx-gpu-api-key:ro" in docker_words
    assert "--api-key" not in docker_words
    assert FAKE_KEY.decode("ascii") not in (
        fetched.stdout + fetched.stderr + started.stdout + started.stderr
    )

    oci_argv = Path(env["FAKE_OCI_ARGV"]).read_text().splitlines()
    assert ["--auth", "instance_principal"] == oci_argv[:2]
    assert FAKE_SECRET_OCID in oci_argv
    assert FAKE_KEY.decode("ascii") not in "\n".join(oci_argv)


def test_gpu_secret_read_policy_is_root_scoped_to_one_configured_secret() -> None:
    watchdog = (OCI_ROOT / "watchdog.tf").read_text()
    main_tf = (OCI_ROOT / "main.tf").read_text()
    policy = re.search(
        r'resource\s+"oci_identity_policy"\s+"acx_gpu_secret_read"\s*\{(?P<body>.*?)\n\}',
        watchdog,
        re.DOTALL,
    )
    assert policy is not None
    body = policy.group("body")

    assert "compartment_id = var.tenancy_ocid" in body
    assert re.search(
        r'count\s*=\s*var\.gpu_api_key_secret_ocid\s*==\s*""\s*\?\s*0\s*:\s*1',
        body,
    )
    assert re.search(
        r"gpu_api_key_secret_ocid\s*=\s*var\.gpu_api_key_secret_ocid", main_tf
    )
    assert (
        "to read secret-bundles in tenancy where target.secret.id = "
        "'${var.gpu_api_key_secret_ocid}'"
    ) in body
    assert "secret-family" not in body
    assert not re.search(r"\b(?:create|update|manage)\s+(?:secret|secret-family)", body)


def test_gpu_secret_ocid_variable_accepts_agreed_identifier_artifacts(
    tmp_path: Path,
) -> None:
    # The omitted value preserves the empty bootstrap default. Each explicit
    # value is written as a generated identifier-only tfvars artifact.
    cases = {
        "bootstrap": None,
        "standard-region": "ocid1.vaultsecret.oc1.iad.FAKE_GPU_API_KEY_ID_0001",
        "global": "ocid1.vaultsecret.oc1..FAKE_GPU_API_KEY_ID_0002",
        "broad-grammar": (
            "ocid1.vaultsecret.oc123.eu-fr_1.XY.z-FAKE_GPU_API_KEY_ID.0003"
        ),
    }

    for name, identifier in cases.items():
        planned = _plan_gpu_secret_ocid_fixture(
            tmp_path, name=name, identifier=identifier
        )
        assert planned.returncode == 0, f"{name}: {planned.stdout}\n{planned.stderr}"


def test_gpu_secret_ocid_variable_rejects_invalid_identifier_artifacts(
    tmp_path: Path,
) -> None:
    cases = {
        "malformed": "not-an-ocid",
        "wrong-kind": "ocid1.vault.oc1.iad.FAKE_GPU_API_KEY_ID_0004",
        "bad-realm": "ocid1.vaultsecret.ocx.iad.FAKE_GPU_API_KEY_ID_0005",
        "short-unique-part": "ocid1.vaultsecret.oc1.iad.abcdefghijklmnopqrs",
        "whitespace": "ocid1.vaultsecret.oc1.iad.FAKE_GPU_API_KEY_ID 0006",
        "slash": "ocid1.vaultsecret.oc1.iad.FAKE/GPU/API/KEY/ID/0007",
        "quote": 'ocid1.vaultsecret.oc1.iad.FAKE_GPU_API_KEY_ID_0008"',
        "injection": (
            'ocid1.vaultsecret.oc1.iad.FAKE_GPU_API_KEY_ID_0009"\n'
            'ssh_allowed_cidrs = ["0.0.0.0/0"] #'
        ),
    }

    for name, identifier in cases.items():
        planned = _plan_gpu_secret_ocid_fixture(
            tmp_path, name=name, identifier=identifier
        )
        output = planned.stdout + planned.stderr
        assert planned.returncode != 0, f"{name} unexpectedly planned successfully"
        assert "gpu_api_key_secret_ocid must be empty or a valid OCI Vault secret OCID" in output


def test_generated_secret_var_file_must_follow_stale_operator_file(
    tmp_path: Path,
) -> None:
    terraform = shutil.which("terraform")
    if terraform is None:
        pytest.skip("Terraform is required for the provider-free variable plan check")

    fixture = tmp_path / "var-file-precedence"
    fixture.mkdir()
    (fixture / "main.tf").write_text(
        _gpu_secret_ocid_variable_block()
        + '\noutput "effective_gpu_api_key_secret_ocid" {\n'
        + "  value = var.gpu_api_key_secret_ocid\n}\n"
    )

    stale_identifier = "ocid1.vaultsecret.oc1.iad.FAKE_GPU_API_KEY_STALE_0020"
    generated_identifier = FAKE_SECRET_OCID
    stale_file = fixture / "operator.tfvars"
    stale_file.write_text(
        "gpu_api_key_secret_ocid = " + json.dumps(stale_identifier) + "\n"
    )
    generated_file = fixture / "gpu-api-key-secret.tfvars"
    generated_file.write_text(
        "gpu_api_key_secret_ocid = " + json.dumps(generated_identifier) + "\n"
    )

    def plan_with(*var_files: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                terraform,
                f"-chdir={fixture}",
                "plan",
                "-input=false",
                "-no-color",
                *(f"-var-file={path}" for path in var_files),
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    generated_last = plan_with(stale_file, generated_file)
    generated_output = generated_last.stdout + generated_last.stderr
    assert generated_last.returncode == 0, generated_output
    assert f'"{generated_identifier}"' in generated_output
    assert stale_identifier not in generated_output

    stale_last = plan_with(generated_file, stale_file)
    stale_output = stale_last.stdout + stale_last.stderr
    assert stale_last.returncode == 0, stale_output
    assert f'"{stale_identifier}"' in stale_output
    assert generated_identifier not in stale_output


def test_gpu_key_fetch_fails_closed_after_five_instance_principal_attempts(
    tmp_path: Path,
) -> None:
    fetch = _cloud_init_files()["/usr/local/bin/acx-gpu-fetch-api-key.sh"]
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_oci = fake_bin / "oci"
    fake_oci.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' attempt >> \"$FAKE_OCI_CALLS\"\n"
        "printf '%s\\n' \"$@\" >> \"$FAKE_OCI_ARGV\"\n"
        "exit 1\n"
    )
    fake_oci.chmod(0o755)

    runtime_dir = tmp_path / "runtime"
    fetch = fetch.replace("$${", "${")
    fetch = fetch.replace("${gpu_api_key_secret_ocid}", FAKE_SECRET_OCID)
    fetch = fetch.replace(
        "readonly OCI_BIN=/usr/bin/oci",
        f"readonly OCI_BIN={shlex.quote(str(fake_oci))}",
    )
    fetch = fetch.replace("/run/acx-gpu-vlm", str(runtime_dir))
    fetch = fetch.replace(
        'install -d -o root -g root -m 0700 "$RUNTIME_DIR"',
        'mkdir -p "$RUNTIME_DIR" && chmod 0700 "$RUNTIME_DIR"',
    )
    fetch = fetch.replace('chown root:root "$temporary"', ":")
    fetch = fetch.replace("readonly RETRY_DELAY=2", "readonly RETRY_DELAY=0")
    fetch_path = tmp_path / "fetch-api-key.sh"
    fetch_path.write_text(fetch)
    fetch_path.chmod(0o750)

    calls = tmp_path / "oci-calls"
    argv_path = tmp_path / "oci-argv"
    failed = subprocess.run(
        ["/bin/bash", str(fetch_path)],
        env={**os.environ, "FAKE_OCI_CALLS": str(calls), "FAKE_OCI_ARGV": str(argv_path)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert failed.returncode != 0
    assert "fetch failed after bounded retries" in failed.stderr
    assert calls.read_text().splitlines() == ["attempt"] * 5
    failed_argv = argv_path.read_text()
    assert "--auth\ninstance_principal" in failed_argv
    assert FAKE_KEY.decode("ascii") not in failed_argv
    assert not (runtime_dir / "api-key").exists()
    assert FAKE_KEY.decode("ascii") not in failed.stdout + failed.stderr


def test_gpu_server_fails_closed_for_missing_or_invalid_key_file(tmp_path: Path) -> None:
    files = _cloud_init_files()
    start = files["/usr/local/bin/acx-gpu-vlm-start.sh"]
    service = files["/etc/systemd/system/acx-gpu-vlm.service"]
    assert service.index("ExecStartPre=/usr/local/bin/acx-gpu-fetch-api-key.sh") < service.index(
        "ExecStart=/usr/local/bin/acx-gpu-vlm-start.sh"
    )

    key_path = tmp_path / "api-key"
    docker_called = tmp_path / "docker-called"
    fake_docker = tmp_path / "docker"
    fake_docker.write_text(f"#!/bin/sh\nprintf called > {shlex.quote(str(docker_called))}\n")
    fake_docker.chmod(0o755)
    start = start.replace("/run/acx-gpu-vlm/api-key", str(key_path))
    start = start.replace("/usr/bin/docker", shlex.quote(str(fake_docker)))
    start_path = tmp_path / "start-vlm.sh"
    start_path.write_text(start)
    start_path.chmod(0o750)

    missing = subprocess.run(
        ["/bin/bash", str(start_path)], capture_output=True, text=True, check=False
    )
    assert missing.returncode != 0
    assert "key file is missing" in missing.stderr
    assert not docker_called.exists()

    key_path.write_text("fake-invalid-key")
    invalid = subprocess.run(
        ["/bin/bash", str(start_path)], capture_output=True, text=True, check=False
    )
    assert invalid.returncode != 0
    assert "key file is invalid" in invalid.stderr
    assert not docker_called.exists()
