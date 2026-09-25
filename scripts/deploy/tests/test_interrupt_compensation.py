"""Regressions for deploy state left behind when an interrupted transaction exits."""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "recognition-service.sh"


def _run_driver(tmp_path: Path, statements: str, **extra_env: str) -> subprocess.CompletedProcess[str]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    records = tmp_path / "records.log"
    command = f'''
source {shlex.quote(str(SCRIPT))}
GREEN=; YELLOW=; RED=; RESET=
RECORDS={shlex.quote(str(records))}
record() {{ printf '%s\\n' "$*" >>"$RECORDS"; }}
restore_runtime_topology() {{ record restore_runtime_topology "$@"; }}
restore_prior_image_repo_env() {{ record restore_prior_image_repo_env "$@"; }}
restore_env_tag_to_rollback() {{ record restore_env_tag_to_rollback "$@"; return "${{RESTORE_ENV_RC:-0}}"; }}
recover_interrupted_cutover() {{ record recover_interrupted_cutover "$@"; }}
cleanup_remote_build_generation_on_exit() {{ record cleanup_remote_build_generation_on_exit "$@"; }}
_purge_deploy_ocir_docker_config() {{ record _purge_deploy_ocir_docker_config "$@"; }}
_purge_deploy_snapshot() {{ record _purge_deploy_snapshot "$@"; }}
rollback_command_hint() {{ printf 'make deploy-rollback-%s' "$1"; }}
{statements}
'''
    env = os.environ.copy()
    env.update({"RECORDS": str(records), **extra_env})
    result = subprocess.run(["bash", "-c", command], text=True, capture_output=True, env=env, check=False)
    if records.exists():
        result.records = records.read_text(encoding="utf-8").splitlines()  # type: ignore[attr-defined]
    else:
        result.records = []  # type: ignore[attr-defined]
    return result


def _function_body(name: str) -> str:
    source = SCRIPT.read_text(encoding="utf-8")
    match = re.search(rf"(?ms)^{re.escape(name)}\(\) \{{\n(.*?)^\}}", source)
    assert match, f"could not find function {name}"
    return match.group(1)


def test_interrupt_after_repo_ship_restores_topology_and_repo(tmp_path: Path) -> None:
    result = _run_driver(
        tmp_path,
        'ACX_DEPLOY_ENV=dev ACX_DEPLOY_PHASE=repo_shipped; deploy_interrupt_cleanup 130',
    )
    assert result.returncode == 130, result.stdout + result.stderr
    records = result.records  # type: ignore[attr-defined]
    assert records.index("restore_runtime_topology dev") < records.index("restore_prior_image_repo_env")
    assert records.index("restore_prior_image_repo_env") < records.index("_purge_deploy_ocir_docker_config")


def test_interrupt_after_tag_push_restores_env_tag(tmp_path: Path) -> None:
    result = _run_driver(
        tmp_path,
        'ACX_DEPLOY_ENV=dev ACX_DEPLOY_PHASE=tag_promoted; deploy_interrupt_cleanup 130',
    )
    assert result.returncode == 130, result.stdout + result.stderr
    records = result.records  # type: ignore[attr-defined]
    assert records.index("restore_env_tag_to_rollback dev 0") < records.index("restore_prior_image_repo_env")
    assert records.index("restore_prior_image_repo_env") < records.index("_purge_deploy_ocir_docker_config")

    refused = _run_driver(
        tmp_path / "owner-refused",
        'ACX_DEPLOY_ENV=dev ACX_DEPLOY_PHASE=tag_promoted; deploy_interrupt_cleanup 130',
        RESTORE_ENV_RC="75",
    )
    assert refused.returncode == 130, refused.stdout + refused.stderr
    refused_records = refused.records  # type: ignore[attr-defined]
    assert "restore_env_tag_to_rollback dev 0" in refused_records
    assert "restore_prior_image_repo_env" not in refused_records


def test_interrupt_after_live_disruption_only_warns(tmp_path: Path) -> None:
    result = _run_driver(
        tmp_path,
        'ACX_DEPLOY_ENV=dev ACX_DEPLOY_PHASE=tag_promoted ACX_LIVE_DISRUPTED=1; deploy_interrupt_cleanup 130',
    )
    assert result.returncode == 130, result.stdout + result.stderr
    output = result.stdout + result.stderr
    assert "not rolling back from a signal handler" in output
    records = result.records  # type: ignore[attr-defined]
    assert "restore_env_tag_to_rollback dev 0" not in records
    assert "_purge_deploy_ocir_docker_config" in records


def test_no_phase_is_a_noop(tmp_path: Path) -> None:
    result = _run_driver(tmp_path, 'ACX_DEPLOY_ENV=dev ACX_DEPLOY_PHASE=""; deploy_interrupt_cleanup 130')
    assert result.returncode == 130, result.stdout + result.stderr
    output = result.stdout + result.stderr
    assert "compensating" not in output
    records = result.records  # type: ignore[attr-defined]
    assert not any(name.startswith("restore_") for name in records)
    assert "_purge_deploy_ocir_docker_config" in records


def test_restarted_and_compensating_only_warn(tmp_path: Path) -> None:
    for phase, warning in (
        ("restarted", "serves unverified"),
        ("compensating", "during rollback"),
    ):
        result = _run_driver(
            tmp_path / phase,
            f'ACX_DEPLOY_ENV=dev ACX_DEPLOY_PHASE={phase} ACX_CANDIDATE_DIGEST_REF=repo@sha256:abc; deploy_interrupt_cleanup 130',
        )
        assert result.returncode == 130, result.stdout + result.stderr
        assert warning in result.stdout + result.stderr
        records = result.records  # type: ignore[attr-defined]
        assert not any(name.startswith("restore_") for name in records)
        assert "_purge_deploy_ocir_docker_config" in records


def test_compensation_runs_once(tmp_path: Path) -> None:
    result = _run_driver(
        tmp_path,
        'ACX_DEPLOY_ENV=dev ACX_DEPLOY_PHASE=tag_promoted; deploy_interrupt_cleanup; trap deploy_interrupt_cleanup EXIT',
    )
    assert result.returncode == 0, result.stdout + result.stderr
    records = result.records  # type: ignore[attr-defined]
    assert records.count("restore_env_tag_to_rollback dev 0") == 1


def test_ship_interrupt_between_push_and_restart(tmp_path: Path) -> None:
    result = _run_driver(
        tmp_path,
        r'''
pin_deploy_sha() { DEPLOY_SHA=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa; }
init_deploy_ocir_docker_config() { install_deploy_interrupt_traps; }
preflight_ssh() { :; }
preflight_remote_face_pipeline_models() { :; }
preflight_git_clean() { :; }
preflight_branch_synced() { :; }
preflight_remote_ocir_auth() { :; }
preserve_rollback_tag() { :; }
capture_prior_runtime_identity() { :; }
do_build() { :; }
do_push_sha() { ACX_CANDIDATE_DIGEST_REF=repo@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa; }
promote_gate() { ACX_DEPLOY_PHASE=repo_shipped; }
do_push_tag() { record do_push_tag "$@"; kill -INT "$$"; }
do_restart() { record do_restart "$@"; }
_ship_selected_env dev aggregate
''',
    )
    assert result.returncode == 130, result.stdout + result.stderr
    records = result.records  # type: ignore[attr-defined]
    assert "restore_env_tag_to_rollback dev 0" in records
    assert "do_restart dev repo@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" not in records


def test_phase_boundaries_are_recorded() -> None:
    gate = _function_body("promote_gate")
    claim = gate.index('ACX_IMAGE_REPO_OWNER_ID="$(image_repo_resource claim')
    assert gate.index("ACX_DEPLOY_PHASE=repo_shipped") < claim

    for name in ("_ship_selected_env", "do_promote"):
        body = _function_body(name)
        push = body.index("if do_push_tag")
        assert body.index("ACX_DEPLOY_PHASE=tag_promoted", push) > push
