"""Cutover recovery residuals (CUTOVER80B-R01/R02/R03). Tests-only RED.

Source identity (recognition-service.sh, sha256
af22193ef3c89ab6e00e562b720900edd294b845012e962f970a4c6d98ff9ef1):
- cutover_inflight_present L2822: privileged `sudo test ! -f` prints ABSENT
  for any non-regular path (directory, symlink, fifo) and for stat failure.
- recover_interrupted_cutover L2851/L2874: commit_cutover_state removes the
  inflight marker and writes status=canonical *before* abort_cutover_candidate.
- _ship_selected_env L3786 / do_promote L3891: restore_prior_image_repo_env
  runs only inside the restore_env_tag_to_rollback success branch.

SSH doubles and fail-closed sudo/test/rm shims match test_cutover_recovery_safety.py.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

from test_cutover_recovery_safety import SCRIPT, _install_fail_closed_shims

NONREGULAR_KINDS = (
    "directory",
    "dangling_symlink",
    "symlink_to_file",
    "symlink_to_dir",
    "fifo",
    "stat_error",
)


def _install_commit_capable_shims(tmp_path: Path, **kwargs: object) -> Path:
    """Safety sudo shim plus sandboxed `tee` for real commit_cutover_state."""
    bin_dir = _install_fail_closed_shims(tmp_path, **kwargs)  # type: ignore[arg-type]
    sudo = bin_dir / "sudo"
    body = sudo.read_text(encoding="utf-8")
    tee_case = (
        "  tee)\n"
        '    for arg in "$@"; do\n'
        '      [[ "$arg" == -* ]] && continue\n'
        '      under_allowed "$arg" || { echo "sudo tee: path outside sandbox: $arg" >&2; exit 2; }\n'
        "    done\n"
        '    exec tee "$@"\n'
        "    ;;\n"
    )
    old = '  *)\n    echo "sudo: refused unexpected command: ${cmd:-empty}" >&2\n'
    if old not in body:
        raise AssertionError("safety sudo shim no longer matches residual tee splice")
    sudo.write_text(body.replace(old, tee_case + old, 1), encoding="utf-8")
    return bin_dir


def _prepare_marker(inflight: Path, kind: str) -> None:
    parent = inflight.parent
    parent.mkdir(parents=True, exist_ok=True)
    if inflight.exists() or inflight.is_symlink():
        if inflight.is_dir() and not inflight.is_symlink():
            inflight.rmdir()
        else:
            inflight.unlink()
    if kind == "file":
        inflight.write_text("status=traffic_on_next\n", encoding="utf-8")
    elif kind == "missing_parent":
        parent.rmdir()
    elif kind == "absent":
        return
    elif kind == "directory":
        inflight.mkdir()
    elif kind == "dangling_symlink":
        inflight.symlink_to(parent / "missing-cutover-target")
    elif kind == "symlink_to_file":
        target = parent / "cutover-inflight-target"
        target.write_text("status=traffic_on_next\n", encoding="utf-8")
        inflight.symlink_to(target)
    elif kind == "symlink_to_dir":
        target = parent / "cutover-inflight-dir"
        target.mkdir()
        inflight.symlink_to(target)
    elif kind == "fifo":
        os.mkfifo(inflight)
    elif kind == "stat_error":
        inflight.write_text("status=traffic_on_next\n", encoding="utf-8")
        parent.chmod(0)
    else:
        raise ValueError(kind)


def _run_extracted(
    tmp_path: Path,
    *,
    kind: str,
    caller: str,
    inject: str = "ok",
) -> tuple[subprocess.CompletedProcess[str], str]:
    records = tmp_path / "caller.log"
    inflight_dir = tmp_path / "dev"
    inflight = inflight_dir / "cutover-inflight"
    bin_dir = _install_fail_closed_shims(tmp_path, sudo_fail=(inject == "sudo_fail"))
    try:
        _prepare_marker(inflight, kind)
        command = f'''
source "{SCRIPT}"
GREEN=; YELLOW=; RED=; RESET=
export PATH="{bin_dir}:$PATH"
ACX_DEPLOY_BACKUP_ROOT="{tmp_path}"
ACX_CUTOVER_ENV=dev
ACX_TRAFFIC_FLIPPED=0
ACX_CUTOVER_COMMITTED=0
run_with_deadline() {{ shift 2; "$@"; }}
ssh() {{
  case "{inject}" in
    transport_one) return 1 ;;
    *)
      last="${{@: -1}}"
      bash -c "$last"
      ;;
  esac
}}
restore_edge_backups() {{ printf 'restored\\n' >>"{records}"; ACX_TRAFFIC_FLIPPED=0; return 0; }}
commit_cutover_state() {{ printf 'committed\\n' >>"{records}"; return 0; }}
abort_cutover_candidate() {{ printf 'drained\\n' >>"{records}"; return 0; }}
enable_cutover_candidate() {{ printf 'enabled\\n' >>"{records}"; return 0; }}
{caller}
'''
        result = subprocess.run(["bash", "-c", command], text=True, capture_output=True, check=False)
        logged = records.read_text() if records.exists() else ""
        return result, logged
    finally:
        if inflight_dir.exists():
            inflight_dir.chmod(inflight_dir.stat().st_mode | stat.S_IRWXU)


def test_regular_file_inflight_probe_is_present(tmp_path: Path) -> None:
    result, logged = _run_extracted(tmp_path, kind="file", caller="cutover_inflight_present dev")
    combined = result.stdout + result.stderr + logged
    assert result.returncode == 0, combined


@pytest.mark.parametrize("kind", ["absent", "missing_parent"])
def test_true_absent_inflight_probe_is_absent(tmp_path: Path, kind: str) -> None:
    result, logged = _run_extracted(tmp_path, kind=kind, caller="cutover_inflight_present dev")
    combined = result.stdout + result.stderr + logged
    assert result.returncode == 1, combined


def test_regular_file_recover_may_commit_and_allows_new_candidate(tmp_path: Path) -> None:
    caller = (
        "recover_persisted_cutover dev; rc=$?; "
        'if (( rc == 0 )); then printf "new_candidate\\n" >>"' + str(tmp_path / "caller.log") + '"; fi; exit "$rc"'
    )
    result, logged = _run_extracted(tmp_path, kind="file", caller=caller)
    combined = result.stdout + result.stderr + logged
    assert result.returncode == 0, combined
    assert "committed" in logged.splitlines(), logged + combined
    assert "drained" in logged.splitlines(), logged + combined
    assert "new_candidate" in logged.splitlines(), logged + combined


def test_true_absent_recover_skips_without_restore(tmp_path: Path) -> None:
    caller = (
        "recover_persisted_cutover dev; rc=$?; "
        'if (( rc == 0 )); then printf "new_candidate\\n" >>"' + str(tmp_path / "caller.log") + '"; fi; exit "$rc"'
    )
    result, logged = _run_extracted(tmp_path, kind="absent", caller=caller)
    combined = result.stdout + result.stderr + logged
    assert result.returncode == 0, combined
    assert "committed" not in logged.splitlines()
    assert "drained" not in logged.splitlines()
    assert "new_candidate" in logged.splitlines()


@pytest.mark.parametrize("kind", NONREGULAR_KINDS)
def test_nonregular_inflight_probe_is_unknown_not_absent(tmp_path: Path, kind: str) -> None:
    """CUTOVER80B-R01: directory/symlink/fifo/stat-error must not decode as ABSENT."""
    result, logged = _run_extracted(tmp_path, kind=kind, caller="cutover_inflight_present dev")
    combined = result.stdout + result.stderr + logged
    assert result.returncode == 2, combined


@pytest.mark.parametrize("kind", NONREGULAR_KINDS)
def test_nonregular_inflight_recover_refuses_commitment_and_new_candidate(tmp_path: Path, kind: str) -> None:
    """CUTOVER80B-R01: UNKNOWN marker must not return 0 or start a new candidate."""
    caller = (
        "recover_persisted_cutover dev; rc=$?; "
        'if (( rc == 0 )); then printf "new_candidate\\n" >>"' + str(tmp_path / "caller.log") + '"; fi; exit "$rc"'
    )
    result, logged = _run_extracted(tmp_path, kind=kind, caller=caller)
    combined = result.stdout + result.stderr + logged
    assert result.returncode != 0, combined
    assert "committed" not in logged.splitlines(), logged + combined
    assert "drained" not in logged.splitlines(), logged + combined
    assert "new_candidate" not in logged.splitlines(), logged + combined
    assert "enabled" not in logged.splitlines(), logged + combined


def _run_persisted_replay(tmp_path: Path, *, abort_succeeds: bool = False) -> subprocess.CompletedProcess[str]:
    """Independent recover_persisted_cutover against durable remote marker state."""
    records = tmp_path / "caller.log"
    abort_count = tmp_path / "abort.count"
    bin_dir = _install_commit_capable_shims(tmp_path)
    command = f'''
source "{SCRIPT}"
GREEN=; YELLOW=; RED=; RESET=
export PATH="{bin_dir}:$PATH"
ACX_DEPLOY_BACKUP_ROOT="{tmp_path}"
ACX_CUTOVER_ENV=dev
ACX_TRAFFIC_FLIPPED=0
ACX_CUTOVER_COMMITTED=0
ACX_DEPLOY_TRANSACTION_ID="residual-r02"
run_with_deadline() {{ shift 2; "$@"; }}
ssh() {{
  last="${{@: -1}}"
  bash -c "$last"
}}
restore_edge_backups() {{ printf 'restored\\n' >>"{records}"; ACX_TRAFFIC_FLIPPED=0; return 0; }}
enable_cutover_candidate() {{ printf 'enabled\\n' >>"{records}"; return 0; }}
abort_cutover_candidate() {{
  n=0
  [[ -f "{abort_count}" ]] && n="$(cat "{abort_count}")"
  n=$((n + 1))
  printf '%s\\n' "$n" >"{abort_count}"
  printf 'abort-%s\\n' "$n" >>"{records}"
  return {0 if abort_succeeds else 1}
}}
recover_persisted_cutover dev
'''
    return subprocess.run(["bash", "-c", command], text=True, capture_output=True, check=False)


def test_failed_abort_keeps_durable_pending_and_retries_cleanup(tmp_path: Path) -> None:
    """CUTOVER80B-R02: inflight must stay pending until abort actually drains."""
    inflight = tmp_path / "dev" / "cutover-inflight"
    committed = tmp_path / "dev" / "cutover-committed"
    inflight.parent.mkdir(parents=True)
    inflight.write_text("status=traffic_on_next\n", encoding="utf-8")

    first = _run_persisted_replay(tmp_path)
    first_log = (tmp_path / "caller.log").read_text() if (tmp_path / "caller.log").exists() else ""
    first_combined = first.stdout + first.stderr + first_log
    assert first.returncode != 0, first_combined
    assert "abort-1" in first_log.splitlines(), first_combined
    assert inflight.exists(), first_combined
    committed_text = committed.read_text() if committed.is_file() else ""
    assert "status=canonical" not in committed_text, first_combined

    second = _run_persisted_replay(tmp_path)
    second_log = (tmp_path / "caller.log").read_text() if (tmp_path / "caller.log").exists() else ""
    second_combined = second.stdout + second.stderr + second_log
    assert second.returncode != 0, second_combined
    assert "abort-2" in second_log.splitlines(), second_combined
    assert inflight.exists(), second_combined
    committed_text = committed.read_text() if committed.is_file() else ""
    assert "status=canonical" not in committed_text, second_combined

    third = _run_persisted_replay(tmp_path, abort_succeeds=True)
    assert third.returncode == 0, third.stdout + third.stderr
    assert not inflight.exists()
    assert "status=canonical" in committed.read_text()
    final_log = (tmp_path / "caller.log").read_text()
    assert "abort-3" in final_log.splitlines()
    fourth = _run_persisted_replay(tmp_path, abort_succeeds=True)
    assert fourth.returncode == 0, fourth.stdout + fourth.stderr
    assert (tmp_path / "caller.log").read_text() == final_log


def _run_partial_rollback(
    tmp_path: Path, invoke: str, *, stale_initial_fence: bool = False
) -> tuple[subprocess.CompletedProcess[str], str]:
    records = tmp_path / "caller.log"
    digest = "b" * 64
    command = f'''
source "{SCRIPT}"
GREEN=; YELLOW=; RED=; RESET=
REMOTE_BUILD=0
CONFIRM=PROMOTE
ACX_BOOT_SMOKE=0
record() {{ printf '%s\\n' "$*" >>"{records}"; }}
init_deploy_ocir_docker_config() {{ :; }}
preflight_ssh() {{ :; }}
preflight_remote_face_pipeline_models() {{ :; }}
preflight_git_clean() {{ :; }}
preflight_branch_synced() {{ :; }}
preflight_remote_ocir_auth() {{ :; }}
preflight_remote_docker() {{ :; }}
preflight_docker() {{ :; }}
preflight_ocir_auth() {{ :; }}
assert_remote_disk_headroom_for_pull() {{ :; }}
preserve_rollback_tag() {{
  ACX_ROLLBACK_DIGEST_REF="$IMAGE_BASE@sha256:{"a" * 64}"
  ACX_ROLLBACK_IMAGE_BASE="$IMAGE_BASE"
}}
capture_prior_runtime_identity() {{ return 0; }}
do_build() {{ :; }}
do_build_remote() {{ :; }}
do_push_sha() {{ ACX_CANDIDATE_DIGEST_REF="$IMAGE_BASE@sha256:{digest}"; }}
promote_gate() {{ :; }}
do_push_tag() {{ return 1; }}
_pull_ref() {{ :; }}
image_digest_ref() {{ printf '%s\\n' "$IMAGE_BASE@sha256:{digest}"; }}
capture_failure_evidence() {{ return 0; }}
with_shared_tag_lock() {{ shift; "$@"; }}
{"" if stale_initial_fence else "assert_rollback_fence() { record fence; return 0; }"}
_pull_ref_remote() {{ :; }}
remote_image_digest_ref() {{
  if [[ "$1" == *@sha256:* ]]; then
    printf '%s\\n' "$1"
  else
    printf '%s\\n' "$IMAGE_BASE@sha256:{"c" * 64}"
  fi
}}
restore_registry_env_tag() {{ record registry; return 0; }}
restore_runtime_and_edge() {{ record topology-fail; return 1; }}
restore_prior_image_repo_env() {{ record sticky; return 0; }}
fail() {{ printf 'xx %s\\n' "$*" >&2; exit 1; }}
{invoke}
'''
    result = subprocess.run(["bash", "-c", command], text=True, capture_output=True, check=False)
    logged = records.read_text() if records.exists() else ""
    return result, logged


@pytest.mark.parametrize("invoke", ["do_deploy dev", "do_promote dev staging"])
def test_partial_rollback_restores_prior_sticky_repo_while_preserving_failure(tmp_path: Path, invoke: str) -> None:
    """CUTOVER80B-R03: registry success + topology/edge/abort fail still restores ACX_IMAGE_REPO."""
    result, logged = _run_partial_rollback(tmp_path, invoke)
    combined = result.stdout + result.stderr + logged
    assert result.returncode != 0, combined
    assert "registry" in logged.splitlines(), combined
    assert "topology-fail" in logged.splitlines(), combined
    assert "sticky" in logged.splitlines(), combined


@pytest.mark.parametrize("invoke", ["do_deploy dev", "do_promote dev staging"])
def test_rollback_real_initial_fence_preserves_refusal_without_sticky_cleanup(tmp_path: Path, invoke: str) -> None:
    result, logged = _run_partial_rollback(tmp_path, invoke, stale_initial_fence=True)
    combined = result.stdout + result.stderr + logged
    assert "STALE ROLLBACK REFUSED" in combined, combined
    assert result.returncode == 75, combined
    assert not logged, combined


def test_sticky_same_value_new_owner_refuses_old_compensation(tmp_path: Path) -> None:
    """Execute real ship/restore producers against a sandboxed remote resource."""
    env_file = tmp_path / ".env"
    env_file.write_text("SECRET=preserved\nACX_IMAGE_REPO=example.test/prior\n")
    env_file.chmod(0o640)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    sudo = bin_dir / "sudo"
    sudo.write_text('#!/bin/bash\nexec "$@"\n')
    sudo.chmod(0o755)
    command = f'''
source "{SCRIPT}"
export PATH="{bin_dir}:$PATH"
env_to_remote_dir() {{ printf '%s\\n' "{tmp_path}"; }}
run_with_deadline() {{ shift 2; "$@"; }}
ssh() {{ bash -c "${{@: -1}}"; }}
preflight_ssh() {{ :; }}
ACX_DEPLOY_TRANSACTION_ID=owner-a
ACX_PRIOR_IMAGE_REPO_ENV=dev
ACX_PRIOR_IMAGE_REPO=example.test/prior
ACX_IMAGE_REPO=example.test/shared
ship_remote_image_repo_env "{tmp_path}"
(
  ACX_DEPLOY_TRANSACTION_ID=owner-b
  ship_remote_image_repo_env "{tmp_path}"
)
restore_prior_image_repo_env
'''
    result = subprocess.run(["bash", "-c", command], text=True, capture_output=True, timeout=30)
    combined = result.stdout + result.stderr
    assert result.returncode == 75, combined
    assert env_file.read_text() == "SECRET=preserved\nACX_IMAGE_REPO=example.test/shared\n"
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o640
