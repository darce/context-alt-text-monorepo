"""Regression coverage for failed flips to the next cutover unit."""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "recognition-service.sh"
ROOT = SCRIPT.parents[2]
DIGEST = "iad.ocir.io/idu2kqqe2jxy/acx-backend@sha256:" + ("a" * 64)


def _function_body(name: str) -> str:
    """Slice one top-level function through the next column-0 function."""
    source = SCRIPT.read_text()
    start = source.index(f"{name}() {{")
    consumed = 0
    heredoc_end: str | None = None
    for idx, line in enumerate(source[start:].splitlines(keepends=True)):
        raw = line.rstrip("\n")
        if idx == 0:
            consumed += len(line)
            continue
        if heredoc_end is not None:
            consumed += len(line)
            if raw == heredoc_end:
                heredoc_end = None
            continue
        heredoc = re.search(r"""<<[-]?(['\"]?)(\w+)\1""", raw)
        if heredoc:
            heredoc_end = heredoc.group(2)
            consumed += len(line)
            continue
        if re.match(r"[A-Za-z_][A-Za-z0-9_]*\(\) \{", raw):
            return source[start : start + consumed]
        consumed += len(line)
    return source[start:]


def _run_driver(tmp_path: Path, driver_body: str) -> tuple[str, list[str]]:
    records = tmp_path / "records.log"
    driver = tmp_path / "driver.sh"
    driver.write_text(
        f'''\
source {shlex.quote(str(SCRIPT))}
GREEN=; YELLOW=; RED=; RESET=
RECORD_FILE={shlex.quote(str(records))}
record() {{ printf '%s\\n' "$*" >>"$RECORD_FILE"; }}
log() {{ record "log $*"; }}
warn() {{ record "warn $*"; }}
{driver_body}
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
    record_lines = records.read_text().splitlines() if records.exists() else []
    return result.stdout + result.stderr, record_lines


def _run_recovery(
    tmp_path: Path,
    *,
    inflight_rc: int,
    restore_rc: int = 0,
) -> tuple[str, list[str]]:
    output, records = _run_driver(
        tmp_path,
        f'''\
ACX_CUTOVER_ENV=dev
ACX_TRAFFIC_FLIPPED=0
INFLIGHT_RC={inflight_rc}
RESTORE_RC={restore_rc}
cutover_inflight_present() {{ record "cutover_inflight_present $*"; return "$INFLIGHT_RC"; }}
abort_cutover_candidate() {{ record "abort_cutover_candidate $*"; }}
restore_edge_backups() {{ record "restore_edge_backups $*"; return "$RESTORE_RC"; }}
enable_cutover_candidate() {{ record "enable_cutover_candidate $*"; }}
commit_cutover_state() {{ record "commit_cutover_state $*"; ACX_TRAFFIC_FLIPPED=0; }}
if recover_failed_flip_to_next dev; then driver_rc=0; else driver_rc=$?; fi
printf 'driver_rc=%s\\ntraffic=%s\\n' "$driver_rc" "$ACX_TRAFFIC_FLIPPED"
''',
    )
    return output, records


def test_absent_marker_drains_without_edge_restore(tmp_path: Path) -> None:
    output, records = _run_recovery(tmp_path, inflight_rc=1)
    assert "driver_rc=0" in output
    assert "abort_cutover_candidate dev" in records
    assert not any(line.startswith("restore_edge_backups ") for line in records)


def test_present_marker_restores_edge_before_drain(tmp_path: Path) -> None:
    output, records = _run_recovery(tmp_path, inflight_rc=0)
    assert "driver_rc=0" in output
    assert "traffic=0" in output
    restore_at = records.index("restore_edge_backups dev")
    drain_at = records.index("abort_cutover_candidate dev")
    commit_at = records.index("commit_cutover_state dev")
    assert restore_at < drain_at < commit_at


def test_probe_failure_is_treated_as_possibly_flipped(tmp_path: Path) -> None:
    _, records = _run_recovery(tmp_path, inflight_rc=2)
    assert records.index("restore_edge_backups dev") < records.index("abort_cutover_candidate dev")


def test_failed_edge_restore_keeps_candidate_serving(tmp_path: Path) -> None:
    output, records = _run_recovery(tmp_path, inflight_rc=0, restore_rc=1)
    assert "driver_rc=1" in output
    assert "enable_cutover_candidate dev" in records
    assert not any(line.startswith("abort_cutover_candidate ") for line in records)


def test_flip_next_failure_branches_use_recovery() -> None:
    for function_name in ("do_restart", "staged_rollback_runtime"):
        body = _function_body(function_name)
        flip_at = body.index('if ! flip_edge_alias "$env" next')
        return_at = body.index("return 1", flip_at)
        branch = body[flip_at:return_at]
        assert "recover_failed_flip_to_next" in branch
        assert "abort_cutover_candidate" not in branch


def test_do_restart_flip_failure_after_route_change_restores_edge(tmp_path: Path) -> None:
    output, records = _run_driver(
        tmp_path,
        f'''\
DIGEST={shlex.quote(DIGEST)}
ACX_IMAGE_REPO='iad.ocir.io/idu2kqqe2jxy/acx-backend'
DEPLOY_SHA='{"b" * 40}'
ACX_CUTOVER_ENV=dev
ACX_TRAFFIC_FLIPPED=0
ACX_CUTOVER_COMMITTED=0
env_to_unit() {{ record "env_to_unit $*"; printf 'acx-%s\\n' "$1"; }}
env_to_next_unit() {{ record "env_to_next_unit $*"; printf 'acx-%s-next\\n' "$1"; }}
env_to_remote_dir() {{ record "env_to_remote_dir $*"; printf '/srv/acx/%s\\n' "$1"; }}
env_to_tag() {{ record "env_to_tag $*"; printf '%s\\n' "$1"; }}
pin_deploy_sha() {{ record pin_deploy_sha; DEPLOY_SHA='{"b" * 40}'; }}
validated_deadline() {{ record "validated_deadline $*"; printf '120\\n'; }}
assert_remote_env_image_tag() {{ record "assert_remote_env_image_tag $*"; }}
recover_persisted_cutover() {{ record "recover_persisted_cutover $*"; }}
assert_remote_disk_headroom_for_pull() {{ record assert_remote_disk_headroom_for_pull; }}
preflight_remote_ocir_auth() {{ record preflight_remote_ocir_auth; }}
_pull_ref_remote() {{ record "_pull_ref_remote $*"; }}
remote_image_digest_ref() {{ record "remote_image_digest_ref $*"; printf '%s\\n' "$1"; }}
remote_docker_with_config() {{ record "remote_docker_with_config $*"; }}
repair_blob_volume_ownership() {{ record "repair_blob_volume_ownership $*"; }}
ship_cutover_candidate_units() {{ record "ship_cutover_candidate_units $*"; }}
recreate_cutover_candidate() {{ record "recreate_cutover_candidate $*"; }}
probe_cutover_api_health() {{ record "probe_cutover_api_health $*"; }}
flip_edge_alias() {{ record "flip_edge_alias $*"; [[ "$2" != next ]]; }}
cutover_inflight_present() {{ record "cutover_inflight_present $*"; return 0; }}
restore_edge_backups() {{ record "restore_edge_backups $*"; }}
abort_cutover_candidate() {{ record "abort_cutover_candidate $*"; }}
enable_cutover_candidate() {{ record "enable_cutover_candidate $*"; }}
commit_cutover_state() {{ record "commit_cutover_state $*"; ACX_TRAFFIC_FLIPPED=0; }}
run_with_deadline() {{ record "run_with_deadline $2"; }}
if do_restart dev "$DIGEST"; then driver_rc=0; else driver_rc=$?; fi
printf 'driver_rc=%s\\n' "$driver_rc"
''',
    )
    assert "driver_rc=1" in output
    assert records.index("restore_edge_backups dev") < records.index("abort_cutover_candidate dev")
    assert not any("systemctl restart" in line for line in records)
