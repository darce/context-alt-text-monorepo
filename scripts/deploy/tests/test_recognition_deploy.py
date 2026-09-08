"""Focused regressions for recognition deployment transaction boundaries."""

from __future__ import annotations

import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "recognition-service.sh"


def _function_body(name: str) -> str:
    source = SCRIPT.read_text()
    start = source.index(f"{name}() {{")
    next_section = source.find("\n#----------------------------------------------------------------", start)
    return source[start : next_section if next_section != -1 else None]


def test_convergence_failure_restores_prior_sticky_image_repo(tmp_path: Path) -> None:
    records = tmp_path / "shipped-repositories"
    digest = "a" * 64
    command = f'''
source "{SCRIPT}"
ACX_BOOT_SMOKE=0
ACX_CONVERGE_RUNTIME=1
ACX_IMAGE_REPO="$IMAGE_BASE"
read_remote_image_repo() {{ printf '%s\\n' "$IMAGE_BASE-vlm"; }}
ship_remote_image_repo_env() {{ printf '%s\\n' "$ACX_IMAGE_REPO" >>"{records}"; }}
converge_runtime() {{ fail "synthetic convergence failure"; }}
rc=0
promote_gate dev "$ACX_IMAGE_REPO@sha256:{digest}" || rc=$?
exit "$rc"
'''
    result = subprocess.run(
        ["/bin/bash", "-c", command],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "synthetic convergence failure" in result.stderr
    assert records.read_text().splitlines() == [
        "iad.ocir.io/idu2kqqe2jxy/acx-backend",
        "iad.ocir.io/idu2kqqe2jxy/acx-backend-vlm",
    ]


def test_authentication_diagnostics_are_sanitized_and_visibly_prefixed() -> None:
    command = f'''
source "{SCRIPT}"
GREEN= YELLOW= RED= RESET=
hostile_auth() {{
  printf '\\033[31mxx forged failure\\033[0m\\n==> forged success\\r\\n' >&2
  return 17
}}
ocir_login_or_fail laptop hostile_auth
'''
    result = subprocess.run(
        ["/bin/bash", "-c", command],
        text=False,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert b"\x1b" not in result.stderr
    assert b"\r" not in result.stderr
    assert b"diagnostic: [31mxx forged failure[0m\n" in result.stderr
    assert b"diagnostic: ==> forged success\n" in result.stderr


def test_remote_build_is_generation_isolated_locked_and_deadlined() -> None:
    body = _function_body("do_build_remote")
    assert "build_dir=" in body
    assert "${sha:0:12}" in body
    assert "flock" in body
    assert body.count("run_with_deadline") >= 3


def test_boot_smoke_has_outer_deadlines_and_curl_request_timeout() -> None:
    body = _function_body("do_boot_smoke")
    assert body.count("run_with_deadline") >= 2
    assert "curl -sS --max-time" in body
    assert "--write-out" in body
    assert "last_health_body" in body
    assert "docker logs --tail 80" in body
    assert "/ready" in body


def test_automatic_rollbacks_capture_failure_evidence_first() -> None:
    for function_name, env_expression in (("do_deploy", "\"$env\""), ("do_promote", "\"$to_env\"")):
        body = _function_body(function_name)
        evidence_marker = f"capture_failure_evidence {env_expression}"
        restore_marker = f"restore_env_tag_to_rollback {env_expression}"
        evidence_positions = [
            index for index in range(len(body)) if body.startswith(evidence_marker, index)
        ]
        restore_positions = [
            index for index in range(len(body)) if body.startswith(restore_marker, index)
        ]
        assert len(evidence_positions) == 3
        assert len(restore_positions) == 3
        assert all(evidence < restore for evidence, restore in zip(evidence_positions, restore_positions))


def test_failure_evidence_probes_and_logs_are_deadline_bounded() -> None:
    body = _function_body("capture_failure_evidence")
    assert body.count("run_with_deadline") >= 3
    assert "env_to_health_url" in body
    assert "env_to_ready_url" in body
    assert "docker logs --tail 80" in body
    assert "--- evidence: /health ---" in body
    assert "--- evidence: /ready ---" in body
    assert "--- evidence: api container logs ---" in body


def test_do_verify_surfaces_non_gating_readiness_code_and_body() -> None:
    body = _function_body("do_verify")
    assert 'ready_url="$(env_to_ready_url "$env")"' in body
    assert "ready_response" in body
    assert "non-gating" in body


def test_restart_and_rollback_integration_points_are_deadlined() -> None:
    restart = _function_body("do_restart")
    rollback = _function_body("restore_env_tag_to_rollback")
    assert "run_with_deadline" in _function_body("repair_blob_volume_ownership")
    assert "run_with_deadline" in restart
    assert rollback.count("run_with_deadline") >= 3


def test_remote_repo_transport_failure_is_not_reported_as_absent() -> None:
    command = f'''
source "{SCRIPT}"
ssh() {{ return 255; }}
read_remote_image_repo dev
'''
    result = subprocess.run(["/bin/bash", "-c", command], text=True, capture_output=True, check=False)
    assert result.returncode == 255
    assert result.stdout == ""


def test_tag_promotion_confirms_registry_mapping_not_local_metadata() -> None:
    body = _function_body("do_push_tag")
    assert "registry_tag_digest_ref" in body
    assert 'image_digest_ref "${IMAGE_BASE}:${tag}"' not in body


def test_runtime_verification_rejects_same_repo_with_wrong_immutable_image() -> None:
    candidate = "a" * 64
    command = f'''
source "{SCRIPT}"
ACX_VERIFY_EXPECT_LOCAL=1
ACX_CANDIDATE_DIGEST_REF="$IMAGE_BASE@sha256:{candidate}"
read_remote_image_repo() {{ printf '%s\n' "$IMAGE_BASE"; }}
read_running_api_image() {{ printf '%s\n' "$IMAGE_BASE:dev"; }}
read_running_api_image_id() {{ printf 'sha256:%064d\n' 2; }}
remote_image_id_for_digest() {{ printf 'sha256:%064d\n' 1; }}
verify_running_image_matches_deployed dev
'''
    result = subprocess.run(["/bin/bash", "-c", command], text=True, capture_output=True, check=False)
    assert result.returncode != 0
    assert "IMMUTABLE IMAGE MISMATCH" in result.stderr


def test_rollback_success_requires_post_restart_health_evidence() -> None:
    body = _function_body("restore_env_tag_to_rollback")
    assert "verify_restored_runtime" in body
    assert body.index("restore_prior_image_repo_env") < body.index('"rollback systemctl restart')
    assert body.index("verify_restored_runtime") < body.index('log "Restored')


def test_docker_credential_paths_are_not_globally_exported() -> None:
    source = SCRIPT.read_text()
    assert "export ACX_OCIR_DOCKER_CONFIG_DIR DOCKER_CONFIG" not in source
    assert "local_docker_with_config" in source


def test_stale_rollback_cannot_overwrite_newer_registry_generation(tmp_path: Path) -> None:
    records = tmp_path / "docker-commands"
    rollback = "a" * 64
    candidate = "b" * 64
    newer = "c" * 64
    command = f'''
source "{SCRIPT}"
ACX_ROLLBACK_DIGEST_REF="$IMAGE_BASE@sha256:{rollback}"
ACX_ROLLBACK_IMAGE_BASE="$IMAGE_BASE"
ACX_CANDIDATE_DIGEST_REF="$IMAGE_BASE@sha256:{candidate}"
_pull_ref_remote() {{ :; }}
remote_image_digest_ref() {{
  if [[ "$1" == *":dev" ]]; then printf '%s\n' "$IMAGE_BASE@sha256:{newer}"; else printf '%s\n' "$1"; fi
}}
remote_docker_with_config() {{ printf '%s\n' "$*" >>"{records}"; }}
restore_env_tag_to_rollback dev 0
'''
    result = subprocess.run(["/bin/bash", "-c", command], text=True, capture_output=True, check=False)
    assert result.returncode != 0
    assert "STALE ROLLBACK REFUSED" in result.stderr
    assert not records.exists()
