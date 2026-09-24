"""Regression tests for independent deploy health probe budgets."""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "recognition-service.sh"


def _run_shell(tmp_path: Path, driver: str) -> subprocess.CompletedProcess[str]:
    driver_path = tmp_path / "probe-driver.sh"
    driver_path.write_text(f"source {shlex.quote(str(SCRIPT))}\n" + driver)
    return subprocess.run(
        ["bash", str(driver_path)],
        capture_output=True,
        check=False,
        env=dict(os.environ),
        cwd=SCRIPT.parents[2],
        text=True,
        timeout=20,
    )


def test_health_probe_budgets_are_independent(tmp_path: Path) -> None:
    attempts_log = tmp_path / "attempts.log"
    result = _run_shell(
        tmp_path,
        f'''
GREEN=; YELLOW=; RED=; RESET=
DEPLOY_SHA=1111111111111111111111111111111111111111
ACX_CANDIDATE_DIGEST_REF="iad.ocir.io/test/acx-backend@sha256:{'a' * 64}"
ACX_ROLLBACK_DIGEST_REF="$ACX_CANDIDATE_DIGEST_REF"
ACX_CUTOVER_HEALTH_ATTEMPTS=2
ACX_CUTOVER_HEALTH_SLEEP=0
ACX_CANONICAL_HEALTH_ATTEMPTS=3
ACX_CANONICAL_HEALTH_SLEEP=0
ACX_VERIFY_ATTEMPTS=9
ACX_VERIFY_SLEEP=0
ACX_ROLLBACK_VERIFY_ATTEMPTS=5
ACX_ROLLBACK_VERIFY_SLEEP=0
pin_deploy_sha() {{ :; }}
verify_retry_sleep() {{ :; }}
health_probe_program() {{ printf 'pass'; }}
env_to_remote_dir() {{ printf '/srv/%s' "$1"; }}
env_to_compose_files() {{ printf '%s' '-f docker-compose.env.yml'; }}
validated_deadline() {{ printf '30\\n'; }}
remote_image_id_for_digest() {{ printf 'sha256:%s\\n' '{'1' * 64}'; }}
run_with_deadline() {{ shift 2; "$@"; }}
ssh() {{
  case "$*" in
    *acx-dev-next*) printf 'cutover\\n' >>{shlex.quote(str(attempts_log))} ;;
    *) printf 'canonical\\n' >>{shlex.quote(str(attempts_log))} ;;
  esac
  printf 'remote probe failed\\n'
  return 1
}}
env_to_health_url() {{ printf 'https://%s/health' "$1"; }}
env_to_ready_url() {{ printf 'https://%s/ready' "$1"; }}
read_deployed_release_receipt() {{ printf '%s\\n%s\\n' "$DEPLOY_SHA" "$ACX_CANDIDATE_DIGEST_REF"; }}
verify_running_image_matches_deployed() {{ return 0; }}
verify_running_image_digest() {{ return 0; }}
verify_live_gpu_snapshots() {{ return 0; }}
emit_verify_ready_diagnostic() {{ :; }}
curl() {{
  if [[ "$*" == *--write-out* ]]; then
    printf 'verify\\n' >>{shlex.quote(str(attempts_log))}
    printf '%s\\n%s' '{{"commit_sha":"deadbeefdeadbeef","status":"ok"}}' '503'
  else
    printf 'rollback\\n' >>{shlex.quote(str(attempts_log))}
    return 22
  fi
}}
probe_cutover_api_health dev "$ACX_CANDIDATE_DIGEST_REF" "$DEPLOY_SHA" || :
probe_canonical_api_health dev || :
verify_restored_runtime dev "$ACX_ROLLBACK_DIGEST_REF" || :
ACX_VERIFY_ATTEMPTS=4
do_verify dev || :
''',
    )

    combined = result.stdout + result.stderr
    attempts = attempts_log.read_text().splitlines()
    assert result.returncode == 0, combined
    assert attempts.count("cutover") == 2
    assert attempts.count("canonical") == 3
    assert attempts.count("verify") == 4
    assert attempts.count("rollback") == 5
    budget_lines = [line for line in combined.splitlines() if "budget:" in line]
    for prefix in (
        "ACX_CUTOVER_HEALTH",
        "ACX_CANONICAL_HEALTH",
        "ACX_VERIFY",
        "ACX_ROLLBACK_VERIFY",
    ):
        assert sum(prefix in line for line in budget_lines) == 1


def test_gpu_snapshot_gate_has_its_own_budget(tmp_path: Path) -> None:
    health_log = tmp_path / "health.log"
    gpu_log = tmp_path / "gpu.log"
    result = _run_shell(
        tmp_path,
        f'''
GREEN=; YELLOW=; RED=; RESET=
DEPLOY_SHA=1111111111111111111111111111111111111111
ACX_VERIFY_EXPECT_LOCAL=1
ACX_CANDIDATE_DIGEST_REF="iad.ocir.io/test/acx-backend@sha256:{'a' * 64}"
ACX_VERIFY_ATTEMPTS=6
ACX_VERIFY_SLEEP=0
ACX_GPU_SNAPSHOT_GATE_ATTEMPTS=2
ACX_GPU_SNAPSHOT_GATE_SLEEP=0
pin_deploy_sha() {{ :; }}
env_to_health_url() {{ printf 'https://dev/health'; }}
env_to_ready_url() {{ printf 'https://dev/ready'; }}
read_deployed_release_receipt() {{ printf '%s\\n%s\\n' "$DEPLOY_SHA" "$ACX_CANDIDATE_DIGEST_REF"; }}
verify_running_image_matches_deployed() {{ return 0; }}
verify_running_image_digest() {{ return 0; }}
verify_live_gpu_snapshots() {{ printf 'gpu\\n' >>{shlex.quote(str(gpu_log))}; return 1; }}
emit_verify_ready_diagnostic() {{ :; }}
verify_retry_sleep() {{ :; }}
curl() {{
  url="${{@: -1}}"
  if [[ "$url" == *"/ready"* ]]; then
    printf '%s\\n%s' '{{"ready":true}}' '200'
    return 0
  fi
  printf 'health\\n' >>{shlex.quote(str(health_log))}
  printf '%s\\n%s' '{{"commit_sha":"1111111111111111111111111111111111111111","status":"ok","image_variant":"recognition"}}' '200'
}}
do_verify dev
''',
    )

    combined = result.stdout + result.stderr
    assert result.returncode != 0, combined
    assert health_log.read_text().splitlines().count("health") == 1
    assert gpu_log.read_text().splitlines().count("gpu") == 2
    assert "GPU snapshot gate budget:" in combined
    assert "ACX_GPU_SNAPSHOT_GATE_*" in combined


def test_invalid_cutover_budget_warns_and_makes_no_ssh_calls(tmp_path: Path) -> None:
    attempts_log = tmp_path / "ssh.log"
    result = _run_shell(
        tmp_path,
        f'''
GREEN=; YELLOW=; RED=; RESET=
DEPLOY_SHA=1111111111111111111111111111111111111111
ACX_CUTOVER_HEALTH_ATTEMPTS=0
ACX_CUTOVER_HEALTH_SLEEP=0
ACX_CANDIDATE_DIGEST_REF="iad.ocir.io/test/acx-backend@sha256:{'a' * 64}"
pin_deploy_sha() {{ :; }}
verify_retry_sleep() {{ :; }}
health_probe_program() {{ printf 'pass'; }}
env_to_remote_dir() {{ printf '/srv/%s' "$1"; }}
validated_deadline() {{ printf '30\\n'; }}
remote_docker_with_config() {{ printf 'called\\n' >>{shlex.quote(str(attempts_log))}; return 1; }}
run_with_deadline() {{ shift 2; "$@"; }}
ssh() {{ printf 'called\\n' >>{shlex.quote(str(attempts_log))}; return 1; }}
if probe_cutover_api_health dev "$ACX_CANDIDATE_DIGEST_REF" "$DEPLOY_SHA"; then rc=0; else rc=$?; fi
printf 'rc=%s\\n' "$rc"
''',
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "rc=1" in result.stdout
    assert "ACX_CUTOVER_HEALTH_ATTEMPTS must be a positive integer (got: 0)" in result.stderr
    assert not attempts_log.exists()
