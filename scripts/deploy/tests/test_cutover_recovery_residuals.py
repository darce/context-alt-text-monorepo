"""Executable cutover recovery and sticky repository ownership regressions."""

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
    tmp_path: Path, invoke: str, *, stale_initial_fence: bool = False, cleanup_rc: int = 0
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
restore_prior_image_repo_env() {{ record sticky; return {cleanup_rc}; }}
fail() {{ printf 'xx %s\\n' "$*" >&2; exit 1; }}
{invoke}
'''
    result = subprocess.run(["bash", "-c", command], text=True, capture_output=True, check=False)
    logged = records.read_text() if records.exists() else ""
    return result, logged


@pytest.mark.parametrize("invoke", ["do_deploy dev", "do_promote dev staging"])
@pytest.mark.parametrize("cleanup_rc", [0, 1])
def test_partial_rollback_restores_prior_sticky_repo_while_preserving_failure(
    tmp_path: Path, invoke: str, cleanup_rc: int
) -> None:
    """CUTOVER80B-R03: registry success + topology/edge/abort fail still restores ACX_IMAGE_REPO."""
    result, logged = _run_partial_rollback(tmp_path, invoke, cleanup_rc=cleanup_rc)
    combined = result.stdout + result.stderr + logged
    assert result.returncode == 1, combined
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
ACX_IMAGE_REPO_OWNER_ID="$(image_repo_resource claim "{tmp_path}" "" "")"
ACX_PRIOR_IMAGE_REPO_ENV=dev
ACX_PRIOR_IMAGE_REPO=example.test/prior
ACX_IMAGE_REPO=example.test/shared
ship_remote_image_repo_env "{tmp_path}"
(
  ACX_IMAGE_REPO_OWNER_ID="$(image_repo_resource claim "{tmp_path}" "" "")"
  ship_remote_image_repo_env "{tmp_path}"
)
restore_prior_image_repo_env
'''
    result = subprocess.run(["bash", "-c", command], text=True, capture_output=True, timeout=30)
    combined = result.stdout + result.stderr
    assert result.returncode == 75, combined
    assert env_file.read_text().startswith("SECRET=preserved\nACX_IMAGE_REPO=example.test/shared\n")
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o640


def _sticky_shell(tmp_path: Path, command: str) -> str:
    """Use the real producer and deadline wrapper; SSH only redirects to a local host."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    sudo = bin_dir / "sudo"
    sudo.write_text('#!/bin/bash\nexec "$@"\n')
    sudo.chmod(0o755)
    return f'''
source "{SCRIPT}"
export PATH="{bin_dir}:$PATH"
env_to_remote_dir() {{ printf '%s\\n' "{tmp_path}"; }}
ssh() {{ bash -c "${{@: -1}}"; }}
preflight_ssh() {{ :; }}
ACX_PRIOR_IMAGE_REPO_ENV=dev
{command}
'''


def _sticky_run(tmp_path: Path, command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", "-c", _sticky_shell(tmp_path, command)], text=True, capture_output=True, timeout=10)


def _sticky_claim(tmp_path: Path) -> str:
    result = _sticky_run(tmp_path, f'image_repo_resource claim "{tmp_path}" "" ""')
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip()


def _sticky_ship(tmp_path: Path, owner: str) -> subprocess.CompletedProcess[str]:
    return _sticky_run(
        tmp_path,
        f'ACX_IMAGE_REPO_OWNER_ID={owner}; ACX_IMAGE_REPO=example.test/shared; ship_remote_image_repo_env "{tmp_path}"',
    )


@pytest.mark.parametrize("prior", ["", "ACX_IMAGE_REPO=example.test/prior\n"])
def test_sticky_owned_cleanup_is_idempotent_and_preserves_secrets(tmp_path: Path, prior: str) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("SECRET=do-not-log\n" + prior)
    env_file.chmod(0o640)
    owner = _sticky_claim(tmp_path)
    assert _sticky_ship(tmp_path, owner).returncode == 0
    command = f"ACX_IMAGE_REPO_OWNER_ID={owner}; restore_prior_image_repo_env"
    result = _sticky_run(tmp_path, command)
    assert result.returncode == 0, result.stderr
    after = env_file.read_bytes()
    result = _sticky_run(tmp_path, command)
    assert result.returncode == 0, result.stderr
    assert env_file.read_bytes() == after
    assert after.startswith(("SECRET=do-not-log\n" + prior).encode())
    assert "do-not-log" not in result.stdout + result.stderr
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o640
    assert _sticky_ship(tmp_path, owner).returncode == 75


@pytest.mark.parametrize("action", ["ship", "restore"])
def test_sticky_clear_invalidates_prior_owner(tmp_path: Path, action: str) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("SECRET=preserved\n")
    owner = _sticky_claim(tmp_path)
    assert _sticky_ship(tmp_path, owner).returncode == 0
    result = _sticky_run(tmp_path, "clear_remote_image_repo_env dev")
    assert result.returncode == 0, result.stderr
    cleared = env_file.read_bytes()
    result = _sticky_run(tmp_path, f'image_repo_resource {action} "{tmp_path}" {owner} example.test/shared')
    assert result.returncode == 75, result.stderr
    assert env_file.read_bytes() == cleared
    assert b"ACX_IMAGE_REPO=" not in cleared


@pytest.mark.parametrize("corruption", ["missing", "malformed", "changed_repo", "symlink", "directory"])
def test_sticky_unknown_resource_refuses_cleanup(tmp_path: Path, corruption: str) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("SECRET=preserved\n")
    owner = _sticky_claim(tmp_path)
    assert _sticky_ship(tmp_path, owner).returncode == 0
    if corruption == "missing":
        env_file.write_text("SECRET=preserved\nACX_IMAGE_REPO=example.test/shared\n")
    elif corruption == "malformed":
        env_file.write_text("SECRET=preserved\n# ACX_IMAGE_REPO_OWNER={bad}\n")
    elif corruption == "changed_repo":
        env_file.write_text(env_file.read_text().replace("ACX_IMAGE_REPO=example.test/shared", "ACX_IMAGE_REPO=other"))
    else:
        env_file.rename(tmp_path / "original")
        if corruption == "symlink":
            env_file.symlink_to(tmp_path / "original")
        else:
            env_file.mkdir()
    before = env_file.read_bytes() if env_file.is_file() else None
    result = _sticky_run(tmp_path, f"ACX_IMAGE_REPO_OWNER_ID={owner}; restore_prior_image_repo_env")
    assert result.returncode == 1, result.stdout + result.stderr
    assert (env_file.read_bytes() if env_file.is_file() else None) == before
    assert "SECRET" not in result.stdout + result.stderr


@pytest.mark.parametrize("action", ["ship", "restore"])
def test_sticky_waiting_writer_rechecks_owner_inside_resource_lock(tmp_path: Path, action: str) -> None:
    """Pause before actual flock; a new real owner writes before the waiter enters."""
    import fcntl
    import time

    env_file = tmp_path / ".env"
    env_file.write_text("SECRET=preserved\n")
    owner = _sticky_claim(tmp_path)
    assert _sticky_ship(tmp_path, owner).returncode == 0
    # SSH signals that the old request was sent, before running the real producer.
    ready = tmp_path / "ready"
    release = tmp_path / "release"
    command = f'''
ssh() {{
  touch "{ready}"
  while [[ ! -e "{release}" ]]; do sleep 0.01; done
  bash -c "${{@: -1}}"
}}
image_repo_resource {action} "{tmp_path}" {owner} example.test/shared
'''
    process = subprocess.Popen(
        ["bash", "-c", _sticky_shell(tmp_path, command)], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    try:
        deadline = time.monotonic() + 5
        while not ready.exists():
            assert time.monotonic() < deadline
            time.sleep(0.01)
        new_owner = _sticky_claim(tmp_path)
        assert new_owner != owner
        assert _sticky_ship(tmp_path, new_owner).returncode == 0
        newer = env_file.read_bytes()
        # Also prove no mutation can enter while another process holds the lock.
        with (tmp_path / ".env.acx-image-repo.lock").open("rb") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            release.touch()
            time.sleep(0.15)
            assert process.poll() is None
            assert env_file.read_bytes() == newer
        stdout, stderr = process.communicate(timeout=5)
        assert process.returncode == 75, stdout + stderr
        assert env_file.read_bytes() == newer
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)


def test_sticky_resource_lock_wait_is_bounded(tmp_path: Path) -> None:
    import fcntl

    (tmp_path / ".env").write_text("SECRET=preserved\n")
    owner = _sticky_claim(tmp_path)
    before = (tmp_path / ".env").read_bytes()
    with (tmp_path / ".env.acx-image-repo.lock").open("rb") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        result = _sticky_run(
            tmp_path,
            f'ACX_REMOTE_COMMAND_TIMEOUT=1; image_repo_resource ship "{tmp_path}" {owner} example.test/shared',
        )
    assert result.returncode in (1, 124), result.stdout + result.stderr
    assert (tmp_path / ".env").read_bytes() == before


def test_sticky_owner_check_and_mutation_share_lock(tmp_path: Path) -> None:
    """Pause the real guard at replace, after validation; a clear must wait."""
    import sys
    import time

    env_file = tmp_path / ".env"
    env_file.write_text("SECRET=preserved\n")
    owner = _sticky_claim(tmp_path)
    ready = tmp_path / "checked"
    release = tmp_path / "replace"
    shim = tmp_path / "bin" / "python3"
    shim.write_text(
        f"#!{sys.executable}\n"
        "import os, sys, time\n"
        "replace = os.replace\n"
        "def paused_replace(source, target):\n"
        f"    open({str(ready)!r}, 'w').close()\n"
        "    deadline = time.monotonic() + 5\n"
        f"    while not os.path.exists({str(release)!r}):\n"
        "        if time.monotonic() >= deadline: raise TimeoutError()\n"
        "        time.sleep(0.01)\n"
        "    replace(source, target)\n"
        "if sys.argv[4] == 'ship': os.replace = paused_replace\n"
        "program = sys.argv[2]\n"
        "sys.argv = ['-c'] + sys.argv[3:]\n"
        "exec(compile(program, '<real-sticky-producer>', 'exec'))\n"
    )
    shim.chmod(0o755)
    ship = subprocess.Popen(
        ["bash", "-c", _sticky_shell(tmp_path, f'image_repo_resource ship "{tmp_path}" {owner} example.test/shared')],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    clear = None
    try:
        deadline = time.monotonic() + 5
        while not ready.exists():
            assert time.monotonic() < deadline
            time.sleep(0.01)
        clear = subprocess.Popen(
            ["bash", "-c", _sticky_shell(tmp_path, "clear_remote_image_repo_env dev")],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        time.sleep(0.15)
        assert clear.poll() is None
        assert b"ACX_IMAGE_REPO=example.test/shared" not in env_file.read_bytes()
        release.touch()
        stdout, stderr = ship.communicate(timeout=5)
        assert ship.returncode == 0, stdout + stderr
        stdout, stderr = clear.communicate(timeout=5)
        assert clear.returncode == 0, stdout + stderr
        cleared = env_file.read_bytes()
        assert b"ACX_IMAGE_REPO=" not in cleared
        result = _sticky_run(tmp_path, f"ACX_IMAGE_REPO_OWNER_ID={owner}; restore_prior_image_repo_env")
        assert result.returncode == 75, result.stderr
        assert env_file.read_bytes() == cleared
    finally:
        release.touch()
        for process in (ship, clear):
            if process is not None:
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=5)


def test_sticky_real_owned_cleanup_survives_downstream_rollback_failure(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("SECRET=preserved\nACX_IMAGE_REPO=example.test/prior\n")
    owner = _sticky_claim(tmp_path)
    assert _sticky_ship(tmp_path, owner).returncode == 0
    result = _sticky_run(
        tmp_path,
        f"""
ACX_IMAGE_REPO_OWNER_ID={owner}
restore_topology_backups() {{ return 1; }}
restore_runtime_and_edge dev 1
""",
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert env_file.read_text().startswith("SECRET=preserved\nACX_IMAGE_REPO=example.test/prior\n")
