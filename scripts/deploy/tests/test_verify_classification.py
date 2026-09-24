"""Regression tests for classifying a healthy deploy SHA mismatch."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "recognition-service.sh"
CANDIDATE_REF = "iad.ocir.io/test/acx-backend@sha256:" + "a" * 64
CANDIDATE_ID = "sha256:" + "1" * 64
OTHER_ID = "sha256:" + "2" * 64


def _run_verify(
    tmp_path: Path,
    *,
    attempts: int = 5,
    local_expectation: bool = True,
    receipt: bool = True,
    running_image_id: str = CANDIDATE_ID,
    candidate_image_id: str = CANDIDATE_ID,
) -> subprocess.CompletedProcess[str]:
    curl_log = tmp_path / "curl.log"
    driver = tmp_path / "verify-driver.sh"
    driver.write_text(
        f'''
source "{SCRIPT}"
GREEN=; YELLOW=; RED=; RESET=
ACX_VERIFY_ATTEMPTS={attempts}
ACX_VERIFY_SLEEP=0
DEPLOY_SHA=1111111111111111111111111111111111111111
pin_deploy_sha() {{ :; }}
verify_running_image_matches_deployed() {{ return 0; }}
verify_live_gpu_snapshots() {{ return 0; }}
read_running_api_image_id() {{ printf '%s\\n' '{running_image_id}'; }}
remote_image_id_for_digest() {{ printf '%s\\n' '{candidate_image_id}'; }}
sleep() {{ :; }}
if [[ "{int(local_expectation)}" == "0" ]]; then
  if [[ "{int(receipt)}" == "1" ]]; then
    read_deployed_release_receipt() {{ printf '%s\\n%s\\n' "$DEPLOY_SHA" '{CANDIDATE_REF}'; }}
  else
    read_deployed_release_receipt() {{ return 1; }}
  fi
fi
if [[ "{int(local_expectation)}" == "1" ]]; then
  ACX_VERIFY_EXPECT_LOCAL=1
  ACX_CANDIDATE_DIGEST_REF="{CANDIDATE_REF}"
else
  unset ACX_VERIFY_EXPECT_LOCAL ACX_CANDIDATE_DIGEST_REF
fi
curl() {{
  printf '%s\\n' "$*" >>"{curl_log}"
  url="${{@: -1}}"
  if [[ "$url" == *"/ready"* ]]; then
    printf '%s\\n%s' '{{"ready":true}}' '200'
  else
    printf '%s\\n%s' '{{"commit_sha":"deadbeefdeadbeef","status":"ok"}}' '200'
  fi
}}
if do_verify dev; then status=0; else status=$?; fi
exit "$status"
'''
    )
    return subprocess.run(
        ["bash", str(driver)],
        text=True,
        capture_output=True,
        check=False,
        env=dict(os.environ),
        cwd=SCRIPT.parents[2],
    )


def test_healthy_candidate_with_version_mismatch_is_expectation_error(tmp_path: Path) -> None:
    result = _run_verify(tmp_path)
    combined = result.stdout + result.stderr
    curl_log = (tmp_path / "curl.log").read_text()
    assert result.returncode == 2, combined
    assert "VERIFY EXPECTATION ERROR" in combined
    assert curl_log.count("/health") == 1
    assert "warm-up" not in combined


def test_healthy_version_skew_with_different_image_is_artifact_mismatch(tmp_path: Path) -> None:
    result = _run_verify(tmp_path, running_image_id=OTHER_ID)
    combined = result.stdout + result.stderr
    curl_log = (tmp_path / "curl.log").read_text()
    assert result.returncode == 1, combined
    assert "ARTIFACT MISMATCH" in combined
    assert CANDIDATE_ID in combined
    assert OTHER_ID in combined
    assert curl_log.count("/health") == 1
    assert curl_log.count("/ready") == 1


def test_unknown_identity_retries_as_transient(tmp_path: Path) -> None:
    result = _run_verify(tmp_path, attempts=3, running_image_id="")
    combined = result.stdout + result.stderr
    curl_log = (tmp_path / "curl.log").read_text()
    assert result.returncode == 1, combined
    assert curl_log.count("/health") == 3
    assert curl_log.count("/ready") == 1


def test_standalone_skew_is_terminal_not_warmup(tmp_path: Path) -> None:
    result = _run_verify(tmp_path, local_expectation=False)
    combined = result.stdout + result.stderr
    curl_log = (tmp_path / "curl.log").read_text()
    assert result.returncode == 1, combined
    assert "Expected release from VM receipt" in combined
    assert curl_log.count("/health") == 1
    assert "warm-up" not in combined


def test_standalone_without_receipt_fails_closed_before_health(tmp_path: Path) -> None:
    result = _run_verify(tmp_path, local_expectation=False, receipt=False)
    combined = result.stdout + result.stderr
    curl_log = (tmp_path / "curl.log").read_text()
    assert result.returncode == 1, combined
    assert "no valid release receipt" in combined
    assert curl_log.count("/health") == 0
    assert curl_log.count("/ready") == 1


def _run_ship(tmp_path: Path, *, verify_status: int, verify_optional: str = "0") -> subprocess.CompletedProcess[str]:
    record_file = tmp_path / "ship-record.log"
    driver = tmp_path / "ship-driver.sh"
    driver.write_text(
        f'''
source "{SCRIPT}"
GREEN=; YELLOW=; RED=; RESET=
REMOTE_BUILD=0
DEPLOY_SHA=1111111111111111111111111111111111111111
VERIFY_STATUS={verify_status}
ACX_VERIFY_OPTIONAL="{verify_optional}"
RECORD_FILE="{record_file}"
unset ACX_ROLLBACK_DIGEST_REF ACX_PRIOR_IMAGE_ID
pin_deploy_sha() {{ :; }}
init_deploy_ocir_docker_config() {{ :; }}
env_to_tag() {{ printf 'dev\\n'; }}
preflight_ssh() {{ :; }}
preflight_remote_face_pipeline_models() {{ :; }}
preflight_git_clean() {{ :; }}
preflight_branch_synced() {{ :; }}
preflight_remote_ocir_auth() {{ :; }}
preserve_rollback_tag() {{ :; }}
do_build() {{ :; }}
do_push_sha() {{ :; }}
promote_gate() {{ :; }}
do_push_tag() {{ :; }}
do_restart() {{ :; }}
do_verify() {{ return "$VERIFY_STATUS"; }}
capture_failure_evidence() {{ printf 'capture:%s:%s\\n' "$1" "$2" >>"$RECORD_FILE"; }}
restore_env_tag_to_rollback() {{ printf 'restore:%s\\n' "$1" >>"$RECORD_FILE"; return 0; }}
rollback_command_hint() {{ printf 'rollback %s\\n' "$1"; }}
_ship_selected_env dev aggregate
'''
    )
    return subprocess.run(
        ["bash", str(driver)],
        text=True,
        capture_output=True,
        check=False,
        env=dict(os.environ),
        cwd=SCRIPT.parents[2],
    )


@pytest.mark.parametrize("verify_optional", ["0", "1"])
def test_ship_expectation_error_exits_2_without_rollback(
    tmp_path: Path, verify_optional: str
) -> None:
    result = _run_ship(tmp_path, verify_status=2, verify_optional=verify_optional)
    combined = result.stdout + result.stderr
    records = (tmp_path / "ship-record.log").read_text()
    assert result.returncode == 2, combined
    assert "VERIFY EXPECTATION ERROR" in combined
    assert "capture:dev:candidate" in records
    assert "restore:dev" not in records


def test_ship_failed_verification_still_rolls_back(tmp_path: Path) -> None:
    result = _run_ship(tmp_path, verify_status=1)
    combined = result.stdout + result.stderr
    records = (tmp_path / "ship-record.log").read_text()
    assert result.returncode != 0, combined
    assert "capture:dev:candidate" in records
    assert "restore:dev" in records


def _function_body(name: str) -> str:
    source = SCRIPT.read_text()
    start = source.index(f"{name}() {{")
    following = re.search(r"(?m)^[A-Za-z_][A-Za-z0-9_]*\(\) \{", source[start + 1 :])
    end = start + 1 + following.start() if following else len(source)
    return source[start:end]


def test_verify_callers_keep_status_classes_separate() -> None:
    for function_name in ("_ship_selected_env", "do_promote"):
        body = _function_body(function_name)
        assert "if ! ACX_VERIFY_EXPECT_LOCAL=1 do_verify" not in body

