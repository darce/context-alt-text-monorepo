"""Regression coverage for staged rollback recovery."""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "recognition-service.sh"
ROOT = SCRIPT.parents[2]
ROLLBACK_DIGEST = "iad.ocir.io/idu2kqqe2jxy/acx-backend@sha256:" + ("a" * 64)


def _run_rollback(
    tmp_path: Path,
    *,
    flipped: int,
    inflight_rc: int = 1,
    fail_candidate: int = 0,
    fail_canonical: int = 0,
    fail_digest: int = 0,
) -> tuple[int, str, list[str]]:
    records = tmp_path / "records.log"
    driver = tmp_path / "rollback-driver.sh"
    driver.write_text(
        f'''\
source {shlex.quote(str(SCRIPT))}
GREEN=; YELLOW=; RED=; RESET=
RECORD_FILE={shlex.quote(str(records))}
ROLLBACK_DIGEST={shlex.quote(ROLLBACK_DIGEST)}
ROLLBACK_SHA={shlex.quote("b" * 40)}
INFLIGHT_RC={inflight_rc}
FAIL_CANDIDATE={fail_candidate}
FAIL_CANONICAL={fail_canonical}
FAIL_DIGEST={fail_digest}
ACX_ROLLBACK_DIGEST_REF="$ROLLBACK_DIGEST"
ACX_TRAFFIC_FLIPPED={flipped}
ACX_LIVE_DISRUPTED=0
record() {{ printf '%s\\n' "$*" >>"$RECORD_FILE"; }}
restore_prior_image_repo_env() {{ record restore_prior_image_repo_env; }}
restore_topology_backups() {{ record "restore_topology_backups $*"; }}
assert_remote_env_image_tag() {{ record "assert_remote_env_image_tag $*"; }}
cutover_inflight_present() {{ record "cutover_inflight_present $*"; return "$INFLIGHT_RC"; }}
ship_cutover_candidate_units() {{ record "ship_cutover_candidate_units $*"; }}
recreate_cutover_candidate() {{ record "recreate_cutover_candidate $*"; }}
probe_cutover_api_health() {{ record "probe_cutover_api_health $*"; return "$FAIL_CANDIDATE"; }}
flip_edge_alias() {{ record "flip_edge_alias $*"; }}
enable_cutover_candidate() {{ record "enable_cutover_candidate $*"; }}
run_with_deadline() {{ record "run_with_deadline $2"; }}
probe_canonical_api_health() {{ record "probe_canonical_api_health $*"; return "$FAIL_CANONICAL"; }}
verify_running_image_digest() {{ record "verify_running_image_digest $*"; return "$FAIL_DIGEST"; }}
restore_edge_backups() {{ record "restore_edge_backups $* flipped=$ACX_TRAFFIC_FLIPPED"; ACX_TRAFFIC_FLIPPED=0; }}
abort_cutover_candidate() {{ record "abort_cutover_candidate $*"; }}
verify_restored_runtime() {{ record "verify_restored_runtime $*"; }}
remote_image_commit_sha() {{ record "remote_image_commit_sha $*"; printf '%s\\n' "$ROLLBACK_SHA"; }}
write_deployed_release_receipt() {{ record "write_deployed_release_receipt $*"; }}
if restore_runtime_and_edge prod 1; then driver_rc=0; else driver_rc=$?; fi
printf 'driver_rc=%s\\n' "$driver_rc"
'''
    )
    result = subprocess.run(
        ["bash", str(driver)],
        text=True,
        capture_output=True,
        check=False,
        env=dict(os.environ),
        cwd=ROOT,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    driver_rc = int(result.stdout.rsplit("driver_rc=", 1)[1].splitlines()[0])
    record_lines = records.read_text().splitlines() if records.exists() else []
    return driver_rc, result.stdout + result.stderr, record_lines


def _index(records: list[str], prefix: str) -> int:
    return next(i for i, line in enumerate(records) if line.startswith(prefix))


def _assert_in_order(records: list[str], prefixes: list[str]) -> None:
    positions = [_index(records, prefix) for prefix in prefixes]
    assert positions == sorted(positions)


def _assert_receipt_last(records: list[str]) -> None:
    receipts = [line for line in records if line.startswith("write_deployed_release_receipt ")]
    assert len(receipts) == 1
    assert records[-1] == receipts[0]


def test_canonical_side_rollback_stages_before_restart(tmp_path: Path) -> None:
    rc, _, records = _run_rollback(tmp_path, flipped=0, inflight_rc=1)
    assert rc == 0
    _assert_in_order(
        records,
        [
            "restore_edge_backups ",
            "recreate_cutover_candidate ",
            f"probe_cutover_api_health prod {ROLLBACK_DIGEST} --image-only",
            f"flip_edge_alias prod next {ROLLBACK_DIGEST}",
            "run_with_deadline rollback systemctl restart ",
            "probe_canonical_api_health prod",
            f"verify_running_image_digest prod {ROLLBACK_DIGEST}",
            "flip_edge_alias prod canonical",
            "abort_cutover_candidate prod",
            "verify_restored_runtime prod",
        ],
    )
    _assert_receipt_last(records)


def test_unhealthy_rollback_candidate_never_restarts_canonical(tmp_path: Path) -> None:
    rc, _, records = _run_rollback(tmp_path, flipped=0, fail_candidate=1)
    assert rc == 1
    assert not any(line.startswith("run_with_deadline rollback systemctl restart ") for line in records)
    assert not any(line.startswith("flip_edge_alias ") for line in records)
    assert any(line.startswith("abort_cutover_candidate prod") for line in records)
    assert not any(line.startswith("write_deployed_release_receipt ") for line in records)


def test_unhealthy_canonical_stays_behind_next_route(tmp_path: Path) -> None:
    rc, output, records = _run_rollback(tmp_path, flipped=0, fail_canonical=1)
    restart_at = _index(records, "run_with_deadline rollback systemctl restart ")
    assert rc == 1
    assert not any(line.startswith("flip_edge_alias prod canonical") for line in records)
    assert not any(line.startswith("abort_cutover_candidate ") for line in records[restart_at + 1 :])
    assert "traffic remains on" in output
    assert not any(line.startswith("write_deployed_release_receipt ") for line in records)


def test_next_side_rollback_probes_canonical_before_edge_restore(tmp_path: Path) -> None:
    rc, _, records = _run_rollback(tmp_path, flipped=1)
    assert rc == 0
    _assert_in_order(
        records,
        [
            "run_with_deadline rollback systemctl restart ",
            "probe_canonical_api_health prod",
            f"verify_running_image_digest prod {ROLLBACK_DIGEST}",
            "restore_edge_backups ",
            "abort_cutover_candidate prod",
            "verify_restored_runtime prod",
        ],
    )
    assert not any(line.startswith("recreate_cutover_candidate ") for line in records)
    _assert_receipt_last(records)


def test_unknown_traffic_side_refuses_rollback_restart(tmp_path: Path) -> None:
    rc, _, records = _run_rollback(tmp_path, flipped=0, inflight_rc=2)
    assert rc == 1
    assert not any(line.startswith("run_with_deadline rollback systemctl restart ") for line in records)
    assert not any(line.startswith("write_deployed_release_receipt ") for line in records)


def test_inflight_marker_selects_next_side_for_rollback(tmp_path: Path) -> None:
    rc, _, records = _run_rollback(tmp_path, flipped=0, inflight_rc=0)
    assert rc == 0
    assert "restore_edge_backups prod flipped=1" in records
    assert any(line.startswith("run_with_deadline rollback systemctl restart ") for line in records)
    assert not any(line.startswith("recreate_cutover_candidate ") for line in records)
    _assert_receipt_last(records)


def test_cutover_health_image_only_keeps_image_identity_without_sha(tmp_path: Path) -> None:
    deploy_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    image_id = "sha256:" + ("c" * 64)
    digest = ROLLBACK_DIGEST

    def run_probe(third_arg: str, name: str) -> str:
        records = tmp_path / f"{name}.log"
        driver = tmp_path / f"{name}.sh"
        driver.write_text(
            f'''\
source {shlex.quote(str(SCRIPT))}
GREEN=; YELLOW=; RED=; RESET=
DEPLOY_SHA={shlex.quote(deploy_sha)}
ACX_CUTOVER_HEALTH_ATTEMPTS=1
ACX_CUTOVER_HEALTH_SLEEP=0
RECORD_FILE={shlex.quote(str(records))}
record() {{ printf '%s\\n' "$*" >>"$RECORD_FILE"; }}
remote_image_id_for_digest() {{ printf '%s\\n' {shlex.quote(image_id)}; }}
run_with_deadline() {{ local remote_command="${{!#}}"; record "$remote_command"; }}
probe_cutover_api_health prod {shlex.quote(digest)} {shlex.quote(third_arg)}
'''
        )
        result = subprocess.run(
            ["bash", str(driver)],
            text=True,
            capture_output=True,
            check=False,
            env=dict(os.environ),
            cwd=ROOT,
            timeout=20,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return records.read_text()

    image_only_command = run_probe("--image-only", "image-only")
    assert "image_id" in image_only_command
    assert f"= '{image_id}'" in image_only_command
    assert deploy_sha not in image_only_command

    sha_command = run_probe(deploy_sha, "sha")
    assert f"'{deploy_sha}'" in sha_command
