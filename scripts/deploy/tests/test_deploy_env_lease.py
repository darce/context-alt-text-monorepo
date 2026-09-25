"""Regressions for the fenced deploy environment lease."""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import time
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "recognition-service.sh"


def _lease_path(tmp_path: Path, env: str = "dev") -> Path:
    return tmp_path / "vm-backups" / "locks" / f"deploy-{env}.lease"


def _write_lease(path: Path, transaction: str, holder: str, expires_at: int) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(
        {"transaction": transaction, "holder": holder, "expires_at": expires_at},
        separators=(",", ":"),
    ).encode("ascii")
    path.write_bytes(content)
    return content


def _run_driver(
    tmp_path: Path,
    statements: str,
    *,
    transaction: str = "transaction-a",
    **extra_env: str,
) -> subprocess.CompletedProcess[str]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    sudo = bin_dir / "sudo"
    sudo.write_text('#!/usr/bin/env bash\nexec "$@"\n', encoding="utf-8")
    sudo.chmod(0o755)
    command = f'''
source {shlex.quote(str(SCRIPT))}
GREEN=; YELLOW=; RED=; RESET=
export PATH={shlex.quote(str(bin_dir))}:$PATH
run_with_deadline() {{ shift 2; "$@"; }}
ssh() {{ bash -c "${{@: -1}}"; }}
ACX_DEPLOY_BACKUP_ROOT={shlex.quote(str(tmp_path / "vm-backups"))}
{statements}
'''
    env = os.environ.copy()
    env.update({"ACX_DEPLOY_TRANSACTION_ID": transaction, **extra_env})
    return subprocess.run(
        ["bash", "-c", command],
        text=True,
        capture_output=True,
        env=env,
        check=False,
        timeout=30,
    )


def test_second_transaction_is_refused_while_first_holds(tmp_path: Path) -> None:
    first = _run_driver(tmp_path, "deploy_env_lease acquire dev", transaction="transaction-a")
    assert first.returncode == 0, first.stdout + first.stderr
    path = _lease_path(tmp_path)
    original = path.read_bytes()
    holder = json.loads(original)["holder"]

    second = _run_driver(tmp_path, "deploy_env_lease acquire dev", transaction="transaction-b")

    assert second.returncode == 75, second.stdout + second.stderr
    assert holder in second.stderr
    assert "until " in second.stderr
    assert re.search(r"until \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", second.stderr)
    assert path.read_bytes() == original


def test_same_transaction_with_different_holder_is_refused(tmp_path: Path) -> None:
    first = _run_driver(tmp_path, "deploy_env_lease acquire dev", transaction="transaction-a")
    assert first.returncode == 0, first.stdout + first.stderr
    path = _lease_path(tmp_path)
    original = path.read_bytes()
    original_holder = json.loads(original)["holder"]

    second = _run_driver(tmp_path, "deploy_env_lease acquire dev", transaction="transaction-a")

    assert second.returncode == 75, second.stdout + second.stderr
    assert original_holder in second.stderr
    assert path.read_bytes() == original


def test_same_process_can_reacquire_own_lease(tmp_path: Path) -> None:
    result = _run_driver(
        tmp_path,
        "set -e; deploy_env_lease acquire dev; deploy_env_lease acquire dev",
        transaction="transaction-a",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    record = json.loads(_lease_path(tmp_path).read_bytes())
    assert record["transaction"] == "transaction-a"


def test_ttl_covers_push_timeout_and_margin(tmp_path: Path) -> None:
    result = _run_driver(
        tmp_path,
        "deploy_env_lease acquire dev",
        ACX_DEPLOY_LOCK_TTL_SECONDS="600",
    )

    assert result.returncode != 0, result.stdout + result.stderr
    combined = result.stdout + result.stderr
    assert "ACX_DEPLOY_LOCK_TTL_SECONDS" in combined
    assert "ACX_PUSH_TIMEOUT" in combined
    assert "600" in combined
    assert "900" in combined


def test_ttl_must_reach_exact_push_timeout_margin(tmp_path: Path) -> None:
    below = _run_driver(
        tmp_path,
        "deploy_env_lease acquire dev",
        ACX_DEPLOY_LOCK_TTL_SECONDS="1249",
        ACX_PUSH_TIMEOUT="900",
    )
    assert below.returncode != 0, below.stdout + below.stderr

    exact = _run_driver(
        tmp_path,
        "deploy_env_lease acquire dev",
        ACX_DEPLOY_LOCK_TTL_SECONDS="1250",
        ACX_PUSH_TIMEOUT="900",
    )
    assert exact.returncode == 0, exact.stdout + exact.stderr


def test_ttl_covers_default_restart_budget(tmp_path: Path) -> None:
    result = _run_driver(
        tmp_path,
        "deploy_env_lease acquire dev",
        ACX_DEPLOY_LOCK_TTL_SECONDS="7200",
        ACX_PUSH_TIMEOUT="900",
        ACX_PULL_TIMEOUT="900",
        ACX_CUTOVER_HEALTH_ATTEMPTS="5",
        ACX_CUTOVER_HEALTH_SLEEP="5",
        ACX_CANONICAL_HEALTH_ATTEMPTS="5",
        ACX_CANONICAL_HEALTH_SLEEP="5",
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_ttl_rejects_restart_budget_beyond_default_and_accepts_exact_floor(
    tmp_path: Path,
) -> None:
    budget = {
        "ACX_CUTOVER_HEALTH_ATTEMPTS": "60",
        "ACX_CUTOVER_HEALTH_SLEEP": "120",
        "ACX_CANONICAL_HEALTH_ATTEMPTS": "60",
        "ACX_CANONICAL_HEALTH_SLEEP": "120",
    }
    below = _run_driver(
        tmp_path,
        "deploy_env_lease acquire dev",
        ACX_DEPLOY_LOCK_TTL_SECONDS="7200",
        **budget,
    )
    assert below.returncode != 0, below.stdout + below.stderr
    assert "15600" in below.stdout + below.stderr

    exact = _run_driver(
        tmp_path,
        "deploy_env_lease acquire dev",
        ACX_DEPLOY_LOCK_TTL_SECONDS="15600",
        **budget,
    )
    assert exact.returncode == 0, exact.stdout + exact.stderr


def test_expired_lease_is_taken_over(tmp_path: Path) -> None:
    path = _lease_path(tmp_path)
    _write_lease(path, "transaction-a", "a@example:123", int(time.time()) - 1)

    result = _run_driver(tmp_path, "deploy_env_lease acquire dev", transaction="transaction-b")

    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(path.read_bytes())["transaction"] == "transaction-b"


def test_renew_extends_only_own_lease(tmp_path: Path) -> None:
    path = _lease_path(tmp_path)
    old_expiry = int(time.time()) + 7200

    own = _run_driver(
        tmp_path,
        "deploy_env_lease acquire dev; sleep 1; deploy_env_lease renew dev",
        transaction="transaction-a",
    )
    assert own.returncode == 0, own.stdout + own.stderr
    renewed = path.read_bytes()
    assert json.loads(renewed)["expires_at"] > old_expiry

    other = _run_driver(tmp_path, "deploy_env_lease renew dev", transaction="transaction-b")
    assert other.returncode == 75, other.stdout + other.stderr
    assert path.read_bytes() == renewed


def test_renew_refuses_same_transaction_with_different_holder(tmp_path: Path) -> None:
    path = _lease_path(tmp_path)
    original = _write_lease(path, "transaction-a", "someone@else:1", int(time.time()) + 7200)

    result = _run_driver(tmp_path, "deploy_env_lease renew dev", transaction="transaction-a")

    assert result.returncode == 75, result.stdout + result.stderr
    assert path.read_bytes() == original


def test_release_is_owner_checked(tmp_path: Path) -> None:
    path = _lease_path(tmp_path)
    result = _run_driver(
        tmp_path,
        f"""
deploy_env_lease acquire dev
ACX_DEPLOY_TRANSACTION_ID=transaction-b deploy_env_lease release dev
test -f {shlex.quote(str(path))}
deploy_env_lease release dev
""",
        transaction="transaction-a",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "not released" in result.stderr
    assert not path.exists()


def test_release_refuses_same_transaction_with_different_holder(tmp_path: Path) -> None:
    path = _lease_path(tmp_path)
    original = _write_lease(path, "transaction-a", "someone@else:1", int(time.time()) + 7200)

    result = _run_driver(tmp_path, "deploy_env_lease release dev", transaction="transaction-a")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "not released" in result.stderr
    assert path.read_bytes() == original


def test_break_glass_matches_transaction(tmp_path: Path) -> None:
    first = _run_driver(tmp_path, "deploy_env_lease acquire dev", transaction="transaction-a")
    assert first.returncode == 0, first.stdout + first.stderr

    breaker = _run_driver(
        tmp_path,
        "deploy_env_lease acquire dev",
        transaction="transaction-b",
        ACX_DEPLOY_LOCK_BREAK="transaction-a",
    )
    assert breaker.returncode == 0, breaker.stdout + breaker.stderr
    assert "breaking deploy lease of transaction transaction-a held by" in breaker.stderr
    path = _lease_path(tmp_path)
    assert json.loads(path.read_bytes())["transaction"] == "transaction-b"

    original = _write_lease(path, "transaction-a", "a@example:123", int(time.time()) + 7200)
    refused = _run_driver(
        tmp_path,
        "deploy_env_lease acquire dev",
        transaction="transaction-b",
        ACX_DEPLOY_LOCK_BREAK="other",
    )
    assert refused.returncode == 75, refused.stdout + refused.stderr
    assert path.read_bytes() == original


def test_malformed_lease_fails_closed(tmp_path: Path) -> None:
    path = _lease_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"not json")

    result = _run_driver(tmp_path, "deploy_env_lease acquire dev", transaction="transaction-b")

    assert result.returncode == 1, result.stdout + result.stderr
    assert str(path) in result.stderr
    assert "inspect and remove" in result.stderr
    assert path.read_bytes() == b"not json"


def test_ship_refuses_before_rollback_tag_when_env_is_held(tmp_path: Path) -> None:
    first = _run_driver(tmp_path, "deploy_env_lease acquire dev", transaction="transaction-a")
    assert first.returncode == 0, first.stdout + first.stderr
    path = _lease_path(tmp_path)
    original = path.read_bytes()
    records = tmp_path / "records.log"
    statements = f'''
RECORDS={shlex.quote(str(records))}
record() {{ printf '%s\\n' "$*" >>"$RECORDS"; }}
pin_deploy_sha() {{ DEPLOY_SHA=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa; }}
init_deploy_ocir_docker_config() {{ install_deploy_interrupt_traps; }}
preflight_ssh() {{ :; }}
preflight_remote_face_pipeline_models() {{ :; }}
preflight_git_clean() {{ :; }}
preflight_branch_synced() {{ :; }}
preflight_remote_ocir_auth() {{ :; }}
preserve_rollback_tag() {{ record preserve_rollback_tag "$@"; }}
recover_interrupted_cutover() {{ :; }}
cleanup_remote_build_generation_on_exit() {{ :; }}
_purge_deploy_ocir_docker_config() {{ :; }}
_purge_deploy_snapshot() {{ :; }}
_ship_selected_env dev aggregate
'''

    result = _run_driver(tmp_path, statements, transaction="transaction-b")

    assert result.returncode != 0, result.stdout + result.stderr
    assert not records.exists() or "preserve_rollback_tag" not in records.read_text(encoding="utf-8")
    assert path.read_bytes() == original


def test_exit_trap_releases_own_lease(tmp_path: Path) -> None:
    result = _run_driver(
        tmp_path,
        """
recover_interrupted_cutover() { :; }
cleanup_remote_build_generation_on_exit() { :; }
_purge_deploy_ocir_docker_config() { :; }
_purge_deploy_snapshot() { :; }
install_deploy_interrupt_traps
deploy_env_lease acquire dev
exit 0
""",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert not _lease_path(tmp_path).exists()


def test_lost_lease_before_restart_stops_without_compensation(tmp_path: Path) -> None:
    records = tmp_path / "records.log"
    statements = f'''
RECORDS={shlex.quote(str(records))}
record() {{ printf '%s\\n' "$*" >>"$RECORDS"; }}
pin_deploy_sha() {{ DEPLOY_SHA=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa; }}
init_deploy_ocir_docker_config() {{ install_deploy_interrupt_traps; }}
preflight_ssh() {{ :; }}
preflight_remote_face_pipeline_models() {{ :; }}
preflight_git_clean() {{ :; }}
preflight_branch_synced() {{ :; }}
preflight_remote_ocir_auth() {{ :; }}
preserve_rollback_tag() {{ :; }}
capture_prior_runtime_identity() {{ :; }}
do_build() {{ :; }}
do_push_sha() {{ ACX_CANDIDATE_DIGEST_REF=repo@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa; }}
promote_gate() {{ ACX_DEPLOY_PHASE=repo_shipped; }}
do_push_tag() {{
  record do_push_tag "$@"
  printf '%s' '{{"transaction":"transaction-other","holder":"other@example:123","expires_at":4102444800}}' >"${{ACX_DEPLOY_BACKUP_ROOT}}/locks/deploy-dev.lease"
}}
do_restart() {{ record do_restart "$@"; }}
restore_env_tag_to_rollback() {{ record restore_env_tag_to_rollback "$@"; }}
restore_runtime_topology() {{ record restore_runtime_topology "$@"; }}
recover_interrupted_cutover() {{ :; }}
cleanup_remote_build_generation_on_exit() {{ :; }}
_purge_deploy_ocir_docker_config() {{ :; }}
_purge_deploy_snapshot() {{ :; }}
_ship_selected_env dev aggregate
'''

    result = _run_driver(tmp_path, statements, transaction="transaction-a")

    combined = result.stdout + result.stderr
    assert result.returncode != 0, combined
    assert "lost to" in combined
    assert "do_push_tag" in records.read_text(encoding="utf-8")
    assert "do_restart" not in records.read_text(encoding="utf-8")
    assert "restore_env_tag_to_rollback" not in records.read_text(encoding="utf-8")
    assert "restore_runtime_topology" not in records.read_text(encoding="utf-8")
    assert json.loads(_lease_path(tmp_path).read_bytes())["transaction"] == "transaction-other"


def test_lost_lease_after_promote_gate_stops_before_tag_push(tmp_path: Path) -> None:
    marker = tmp_path / "tag-push-ran"
    lease_path = _lease_path(tmp_path)
    statements = f'''
pin_deploy_sha() {{ DEPLOY_SHA=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa; }}
init_deploy_ocir_docker_config() {{ install_deploy_interrupt_traps; }}
preflight_ssh() {{ :; }}
preflight_remote_face_pipeline_models() {{ :; }}
preflight_git_clean() {{ :; }}
preflight_branch_synced() {{ :; }}
preflight_remote_ocir_auth() {{ :; }}
preserve_rollback_tag() {{ :; }}
capture_prior_runtime_identity() {{ :; }}
do_build() {{ :; }}
do_push_sha() {{ ACX_CANDIDATE_DIGEST_REF=repo@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa; }}
promote_gate() {{ rm -f {shlex.quote(str(lease_path))}; ACX_DEPLOY_PHASE=repo_shipped; }}
do_push_tag() {{ touch {shlex.quote(str(marker))}; }}
recover_interrupted_cutover() {{ :; }}
cleanup_remote_build_generation_on_exit() {{ :; }}
_purge_deploy_ocir_docker_config() {{ :; }}
_purge_deploy_snapshot() {{ :; }}
_ship_selected_env dev aggregate
'''

    result = _run_driver(tmp_path, statements)

    assert result.returncode != 0, result.stdout + result.stderr
    assert "lost to" in result.stdout + result.stderr
    assert not marker.exists()


def test_clear_image_repo_refuses_when_env_is_held(tmp_path: Path) -> None:
    first = _run_driver(tmp_path, "deploy_env_lease acquire dev", transaction="transaction-a")
    assert first.returncode == 0, first.stdout + first.stderr
    marker = tmp_path / "image-repo-clear-ran"
    statements = f'''
preflight_ssh() {{ :; }}
image_repo_resource() {{ touch {shlex.quote(str(marker))}; }}
clear_remote_image_repo_env dev
'''

    result = _run_driver(tmp_path, statements, transaction="transaction-b")

    assert result.returncode != 0, result.stdout + result.stderr
    assert "holder line:" in result.stdout + result.stderr
    assert "refusing to clear the image repository" in result.stdout + result.stderr
    assert not marker.exists()


def test_clear_image_repo_holds_and_releases_lease(tmp_path: Path) -> None:
    marker = tmp_path / "image-repo-clear-ran"
    lease_path = _lease_path(tmp_path)
    statements = f'''
preflight_ssh() {{ :; }}
image_repo_resource() {{
  [[ -f {shlex.quote(str(lease_path))} ]] || return 1
  touch {shlex.quote(str(marker))}
}}
clear_remote_image_repo_env dev
'''

    result = _run_driver(tmp_path, statements)

    assert result.returncode == 0, result.stdout + result.stderr
    assert marker.exists()
    assert not lease_path.exists()


def test_clear_image_repo_exit_trap_releases_lease(tmp_path: Path) -> None:
    lease_path = _lease_path(tmp_path)
    result = _run_driver(
        tmp_path,
        """
preflight_ssh() { :; }
image_repo_resource() { exit 1; }
clear_remote_image_repo_env dev
""",
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert not lease_path.exists()


def test_reset_refuses_with_other_live_transaction_before_ssh_mutation(tmp_path: Path) -> None:
    held = _run_driver(tmp_path, "deploy_env_lease acquire dev", transaction="transaction-a")
    assert held.returncode == 0, held.stdout + held.stderr
    ssh_log = tmp_path / "reset-ssh.log"
    statements = f'''
SSH_LOG={shlex.quote(str(ssh_log))}
ssh() {{
  local remote_command="${{@: -1}}"
  printf '%s\\n' "$remote_command" >>"$SSH_LOG"
  if [[ "$remote_command" == sudo\\ python3\\ -c* ]]; then
    bash -c "$remote_command"
  fi
}}
CONFIRM_REMOTE_RESET=RESET
ACX_RESET_SITE_URL=http://localhost:10010
ACX_RESET_TENANT_ID=11111111-2222-7333-9444-555555555555
preflight_ssh() {{ :; }}
preflight_remote_face_pipeline_models() {{ :; }}
curl() {{ return 0; }}
sleep() {{ :; }}
do_reset dev
'''

    result = _run_driver(tmp_path, statements, transaction="transaction-b")

    assert result.returncode != 0, result.stdout + result.stderr
    assert "refusing reset" in result.stdout + result.stderr
    assert "rm -rf" not in ssh_log.read_text(encoding="utf-8")


def _function_body(name: str) -> str:
    source = SCRIPT.read_text(encoding="utf-8")
    match = re.search(rf"(?ms)^{re.escape(name)}\(\) \{{\n(.*?)^\}}", source)
    assert match, f"could not find function {name}"
    return match.group(1)


def test_acquire_calls_precede_mutations() -> None:
    for name, mutation in (
        ("_ship_selected_env", "preserve_rollback_tag"),
        ("do_promote", "preserve_rollback_tag"),
        ("do_rollback", "_pull_ref_remote"),
    ):
        body = _function_body(name)
        assert "deploy_env_lease acquire" in body
        assert body.index("deploy_env_lease acquire") < body.index(mutation)

    rollback = _function_body("do_rollback")
    assert rollback.index("deploy_env_lease renew") < rollback.index("restore_env_tag_to_rollback")


def test_manual_rollback_stops_if_lease_was_lost_during_pulls(tmp_path: Path) -> None:
    marker = tmp_path / "rollback-mutation-ran"
    lease_path = _lease_path(tmp_path)
    statements = f'''
preflight_ssh() {{ :; }}
preflight_remote_ocir_auth() {{ :; }}
_pull_ref_remote() {{ rm -f {shlex.quote(str(lease_path))}; }}
remote_image_digest_ref() {{ printf '%s@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\\n' "$IMAGE_BASE"; }}
remote_image_id_for_digest() {{ printf 'image-id\\n'; }}
capture_prior_runtime_identity() {{ :; }}
restore_env_tag_to_rollback() {{ touch {shlex.quote(str(marker))}; }}
do_rollback dev aaaaaaaaaaaa
'''

    result = _run_driver(tmp_path, statements)

    assert result.returncode != 0, result.stdout + result.stderr
    assert "lost to" in result.stdout + result.stderr
    assert "refusing rollback" in result.stdout + result.stderr
    assert not marker.exists()


def test_deploy_and_promote_renew_after_gate_before_tag_push() -> None:
    for name in ("_ship_selected_env", "do_promote"):
        body = _function_body(name)
        gate = body.index("promote_gate")
        push = body.index("do_push_tag")
        renew = body.rfind("deploy_env_lease renew", gate, push)
        assert gate < renew < push

    assert '_ship_selected_env "$env" aggregate' in _function_body("do_deploy")
