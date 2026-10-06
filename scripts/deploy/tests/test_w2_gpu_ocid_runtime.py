from __future__ import annotations

import base64
import os
import shlex
import subprocess
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[3]
OCI_ROOT = REPO_ROOT / "infra" / "oci"
FAKE_KEY = b"a" * 64


def _fetch_script() -> str:
    document = yaml.safe_load((OCI_ROOT / "gpu-cloud-init.yaml").read_text())
    return next(
        entry["content"]
        for entry in document["write_files"]
        if entry["path"] == "/usr/local/bin/acx-gpu-fetch-api-key.sh"
    )


def _render_fetch_script(secret_id: str, tmp_path: Path) -> tuple[Path, Path, Path]:
    """Run the committed fetch script with a safely supplied Terraform value."""
    script = _fetch_script()
    terraform_assignment = "readonly SECRET_ID='${gpu_api_key_secret_ocid}'"
    assert script.count(terraform_assignment) == 1
    script = script.replace(
        terraform_assignment,
        f"readonly SECRET_ID={shlex.quote(secret_id)}",
    )
    script = script.replace("$${", "${")

    fake_oci = tmp_path / "fake-oci"
    fake_oci.write_text(
        "#!/bin/sh\n"
        "printf 'contact\\n' >> \"$FAKE_OCI_CONTACTS\"\n"
        "printf '%s\\n' \"$@\" > \"$FAKE_OCI_ARGUMENTS\"\n"
        "printf '%s\\n' \"$FAKE_SECRET_BASE64\"\n"
    )
    fake_oci.chmod(0o755)

    runtime_dir = tmp_path / "runtime"
    script = script.replace(
        "readonly OCI_BIN=/usr/bin/oci",
        f"readonly OCI_BIN={shlex.quote(str(fake_oci))}",
    )
    script = script.replace(
        "readonly RUNTIME_DIR=/run/acx-gpu-vlm",
        f"readonly RUNTIME_DIR={shlex.quote(str(runtime_dir))}",
    )
    script = script.replace(
        "readonly KEY_PATH=/run/acx-gpu-vlm/api-key",
        f"readonly KEY_PATH={shlex.quote(str(runtime_dir / 'api-key'))}",
    )
    # Keep the script executable by an unprivileged test runner. The production
    # ownership and mode steps are unchanged in the committed cloud-init file.
    script = script.replace(
        'install -d -o root -g root -m 0700 "$RUNTIME_DIR"',
        'mkdir -p "$RUNTIME_DIR" && chmod 0700 "$RUNTIME_DIR"',
    )
    script = script.replace('chown root:root "$temporary"', ":")

    script_path = tmp_path / "fetch-api-key.sh"
    script_path.write_text(script)
    return script_path, fake_oci, runtime_dir


@pytest.mark.parametrize(
    "secret_id",
    [
        "ocid1.vaultsecret.oc1.iad.abcdefghijklmnopqrstuvwxyz1234",
        "ocid1.vaultsecret.oc1..aaaaaaaaaaaaaaaaaaaa",
        "ocid1.vaultsecret.oc1.eu-frankfurt-1.Ab_C.d-Ef_0123456789.abcdefghijkl",
        "ocid1.vaultsecret.oc21.phx.0123456789abcdefghijklmnopqrstuv",
    ],
)
def test_fetch_guard_accepts_complete_vault_secret_ocids(
    secret_id: str, tmp_path: Path
) -> None:
    script_path, _, runtime_dir = _render_fetch_script(secret_id, tmp_path)
    contacts = tmp_path / "oci-contacts"
    arguments = tmp_path / "oci-arguments"
    result = subprocess.run(
        ["/bin/bash", str(script_path)],
        env={
            **os.environ,
            "FAKE_OCI_CONTACTS": str(contacts),
            "FAKE_OCI_ARGUMENTS": str(arguments),
            "FAKE_SECRET_BASE64": base64.b64encode(FAKE_KEY).decode("ascii"),
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert contacts.read_text().splitlines() == ["contact"]
    argv = arguments.read_text().splitlines()
    assert argv[:2] == ["--auth", "instance_principal"]
    assert argv[argv.index("--secret-id") + 1] == secret_id
    assert (runtime_dir / "api-key").read_bytes() == FAKE_KEY


@pytest.mark.parametrize(
    "secret_id",
    [
        "",
        "ocid1.vaultsecret.oc1.iad.short",
        "ocid1.vault.oc1.iad.abcdefghijklmnopqrstuvwxyz1234",
        "ocid1.vaultsecret.oc1x.iad.abcdefghijklmnopqrstuvwxyz1234",
        "ocid1.vaultsecret.oc1.iad.abcdefghijklmnopqrstuvwxy z",
        "ocid1.vaultsecret.oc1.iad.abcdefghijklmnopqrstuv/xyz",
        "ocid1.vaultsecret.oc1.iad.abcdefghijklmnopqrstuv'; touch INJECTED; #",
        "ocid1.vaultsecret.oc1.iad.abcdefghijklmnopqrstuv\ntouch INJECTED",
    ],
)
def test_fetch_guard_rejects_invalid_ids_before_contact_or_mutation(
    secret_id: str, tmp_path: Path
) -> None:
    script_path, _, runtime_dir = _render_fetch_script(secret_id, tmp_path)
    contacts = tmp_path / "oci-contacts"
    arguments = tmp_path / "oci-arguments"

    result = subprocess.run(
        ["/bin/bash", str(script_path)],
        env={
            **os.environ,
            "FAKE_OCI_CONTACTS": str(contacts),
            "FAKE_OCI_ARGUMENTS": str(arguments),
            "FAKE_SECRET_BASE64": base64.b64encode(FAKE_KEY).decode("ascii"),
        },
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "OCID is missing or invalid" in result.stderr
    assert not contacts.exists()
    assert not arguments.exists()
    assert not runtime_dir.exists()
    assert not (tmp_path / "INJECTED").exists()
