"""Regression coverage for VM-owned deployed release receipts."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "recognition-service.sh"
LOCAL_SHA = "a" * 40
RECEIPT_SHA = "b" * 40
RECEIPT_DIGEST = "iad.ocir.io/test/acx-backend@sha256:" + "d" * 64
RUNNING_IMAGE_ID = "sha256:" + "1" * 64
RECEIPT_IMAGE_ID = "sha256:" + "2" * 64


def _receipt(*, sha: str = RECEIPT_SHA, digest_ref: str = RECEIPT_DIGEST) -> str:
    return json.dumps(
        {
            "env": "dev",
            "sha": sha,
            "digest_ref": digest_ref,
            "deployed_at": "2026-01-02T03:04:05Z",
            "transaction": "tx-test",
        }
    )


def _run_standalone_verify(
    tmp_path: Path,
    *,
    health_sha: str,
    receipt: str = _receipt(),
    receipt_mode: str = "present",
    running_image_id: str = RUNNING_IMAGE_ID,
    receipt_image_id: str = RUNNING_IMAGE_ID,
) -> subprocess.CompletedProcess[str]:
    receipt_file = tmp_path / "receipt.json"
    receipt_file.write_text(receipt)
    health_file = tmp_path / "health.json"
    health_file.write_text(
        json.dumps(
            {
                "commit_sha": health_sha,
                "status": "ok",
                "image_variant": "recognition",
            }
        )
    )
    curl_log = tmp_path / "curl.log"
    curl_log.touch()
    ssh_log = tmp_path / "ssh.log"
    driver = tmp_path / "verify-driver.sh"
    driver.write_text(
        f'''
source "{SCRIPT}"
GREEN=; YELLOW=; RED=; RESET=
DEPLOY_SHA="{LOCAL_SHA}"
ACX_VERIFY_ATTEMPTS=1
ACX_VERIFY_SLEEP=0
ACX_IMAGE_VARIANT=recognition
pin_deploy_sha() {{ :; }}
expected_image_variant() {{ printf '%s\\n' recognition; }}
verify_running_image_matches_deployed() {{ return 0; }}
verify_live_gpu_snapshots() {{ return 0; }}
read_running_api_image_id() {{ printf '%s\\n' '{running_image_id}'; }}
remote_image_id_for_digest() {{ printf '%s\\n' '{receipt_image_id}'; }}
run_with_deadline() {{ shift 2; "$@"; }}
ssh() {{
  printf '%s\\n' "$*" >>"{ssh_log}"
  if [[ "$*" == *"deployed-release.json"* ]]; then
    [[ "{receipt_mode}" == "present" ]] || return 1
    cat "{receipt_file}"
    return
  fi
  return 1
}}
curl() {{
  printf '%s\\n' "$*" >>"{curl_log}"
  url="${{@: -1}}"
  if [[ "$url" == *"/ready" ]]; then
    printf '%s\\n%s' '{{"ready":true}}' '200'
    return 0
  fi
  cat "{health_file}"
  printf '\\n%s' '200'
}}
do_verify dev
'''
    )
    result = subprocess.run(
        ["bash", str(driver)],
        text=True,
        capture_output=True,
        check=False,
        env=dict(os.environ),
        cwd=SCRIPT.parents[2],
    )
    result._curl_log = curl_log  # type: ignore[attr-defined]
    result._ssh_log = ssh_log  # type: ignore[attr-defined]
    return result


def test_standalone_verify_uses_vm_receipt_when_local_head_differs(tmp_path: Path) -> None:
    result = _run_standalone_verify(tmp_path, health_sha=RECEIPT_SHA)
    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    assert "Expected release from VM receipt" in combined
    assert (tmp_path / "curl.log").read_text().count("/health") == 1


def test_standalone_verify_rejects_local_head_when_receipt_differs(tmp_path: Path) -> None:
    result = _run_standalone_verify(tmp_path, health_sha=LOCAL_SHA)
    combined = result.stdout + result.stderr
    assert result.returncode != 0, combined
    assert "SKEW" in combined


def test_standalone_verify_fails_closed_without_receipt(tmp_path: Path) -> None:
    result = _run_standalone_verify(
        tmp_path,
        health_sha=LOCAL_SHA,
        receipt_mode="missing",
    )
    combined = result.stdout + result.stderr
    assert result.returncode != 0, combined
    assert "no valid release receipt" in combined
    assert "/health" not in (tmp_path / "curl.log").read_text()


def test_standalone_verify_fails_closed_for_invalid_receipt(tmp_path: Path) -> None:
    result = _run_standalone_verify(
        tmp_path,
        health_sha=LOCAL_SHA,
        receipt=_receipt(sha="short"),
    )
    combined = result.stdout + result.stderr
    assert result.returncode != 0, combined
    assert "no valid release receipt" in combined
    assert "/health" not in (tmp_path / "curl.log").read_text()


def test_standalone_verify_requires_receipt_digest_image_id(tmp_path: Path) -> None:
    result = _run_standalone_verify(
        tmp_path,
        health_sha=RECEIPT_SHA,
        receipt_image_id=RECEIPT_IMAGE_ID,
    )
    combined = result.stdout + result.stderr
    assert result.returncode != 0, combined
    assert "IMMUTABLE IMAGE MISMATCH" in combined


def test_write_deployed_release_receipt_validates_and_atomically_writes(tmp_path: Path) -> None:
    ssh_log = tmp_path / "ssh.log"
    stdin_log = tmp_path / "ssh.stdin"
    driver = tmp_path / "write-driver.sh"
    driver.write_text(
        f'''
source "{SCRIPT}"
GREEN=; YELLOW=; RED=; RESET=
run_with_deadline() {{ shift 2; "$@"; }}
ssh() {{
  printf '%s\\n' "$*" >>"{ssh_log}"
  cat >"{stdin_log}"
}}
if write_deployed_release_receipt dev short "{RECEIPT_DIGEST}"; then exit 91; else bad_sha_rc=$?; fi
if write_deployed_release_receipt dev "{LOCAL_SHA}" bad-digest; then exit 92; else bad_digest_rc=$?; fi
printf '%s\\n%s\\n' "$bad_sha_rc" "$bad_digest_rc"
write_deployed_release_receipt dev "{LOCAL_SHA}" "{RECEIPT_DIGEST}"
'''
    )
    result = subprocess.run(
        ["bash", str(driver)],
        text=True,
        capture_output=True,
        check=False,
        env=dict(os.environ),
        cwd=SCRIPT.parents[2],
    )
    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    assert result.stdout.splitlines()[:2] == ["1", "1"]
    remote_argv = ssh_log.read_text()
    assert "mktemp" in remote_argv
    assert "deployed-release.json" in remote_argv
    assert "mv -f" in remote_argv
    assert "" == stdin_log.read_text()
    assert remote_argv.count("sudo sh -c") == 1


def test_release_receipt_call_sites_follow_verified_runtime_state() -> None:
    source = SCRIPT.read_text()
    restart_start = source.index("do_restart() {")
    restart_end = source.index("\n# Automatic cutover compensation", restart_start)
    restart = source[restart_start:restart_end]
    receipt_write = restart.index("write_deployed_release_receipt")
    assert restart.rfind("abort_cutover_candidate") < receipt_write
    assert receipt_write < restart.rfind("return 0")

    restore_start = source.index("restore_runtime_and_edge() {")
    restore_end = source.index("\n# Restore both the registry env tag", restore_start)
    restore = source[restore_start:restore_end]
    assert restore.index("verify_restored_runtime") < restore.index(
        "write_deployed_release_receipt"
    )
