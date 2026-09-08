"""Focused regressions for recognition deployment transaction boundaries."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "recognition-service.sh"

CRASH_LOG = "ModuleNotFoundError: No module named 'scene.foo'"

DOCKER_STUB = r"""#!/usr/bin/env bash
set -euo pipefail
state="${FAKE_STATE:?}"
cmd="${1:-}"; shift || true
printf '%s\n' "$cmd $*" >>"${state}/docker.log"
mkdir -p "${state}/containers"
case "$cmd" in
  network)
    exit 0
    ;;
  run)
    name=""
    rm_flag=0
    prev=""
    last=""
    for a in "$@"; do
      last="$a"
      if [[ "$prev" == "--name" ]]; then
        name="$a"
      fi
      if [[ "$a" == "--rm" ]]; then
        rm_flag=1
      fi
      prev="$a"
    done
    [[ -n "$name" ]] || exit 1
    mkdir -p "${state}/containers/${name}"
    printf '%s\n' "$rm_flag" >"${state}/containers/${name}/rm"
    printf '%s\n' "$@" >"${state}/containers/${name}/args"
    if [[ "$last" == *pgvector* ]]; then
      printf 'pg\n' >"${state}/containers/${name}/kind"
    else
      printf 'api\n' >"${state}/containers/${name}/kind"
      printf '%s\n' "$CRASH_LOG" >"${state}/containers/${name}/logs"
      printf '%s\n' "$name" >"${state}/api_name"
      printf '%s\n' "$rm_flag" >"${state}/api_rm"
    fi
    exit 0
    ;;
  exec)
    exit 0
    ;;
  port)
    name="${1:-}"
    if [[ ! -d "${state}/containers/${name}" ]]; then
      echo "Error: No such container: ${name}" >&2
      exit 1
    fi
    echo "0.0.0.0:18000"
    exit 0
    ;;
  logs)
    name=""
    for a in "$@"; do
      name="$a"
    done
    # --rm containers are gone by the time the failure branch asks for logs.
    if [[ -f "${state}/api_rm" && "$(cat "${state}/api_rm")" == "1" && -f "${state}/api_name" && "$name" == "$(cat "${state}/api_name")" ]]; then
      echo "Error: No such container: ${name}" >&2
      exit 1
    fi
    if [[ ! -d "${state}/containers/${name}" ]]; then
      echo "Error: No such container: ${name}" >&2
      exit 1
    fi
    cat "${state}/containers/${name}/logs"
    exit 0
    ;;
  rm)
    name=""
    for a in "$@"; do
      [[ "$a" == -* ]] && continue
      name="$a"
    done
    rm -rf "${state}/containers/${name}"
    exit 0
    ;;
  volume)
    exit 0
    ;;
  compose)
    printf '%s\n' "compose $*" >>"${state}/compose.log"
    sub="${1:-}"
    if [[ "$sub" == "ps" ]]; then
      if [[ "${FAKE_COMPOSE_PS_EMPTY:-0}" == "1" ]]; then
        exit 0
      fi
      echo "abc123"
      exit 0
    fi
    if [[ "$sub" == "logs" ]]; then
      echo "compose historical api logs"
      exit 0
    fi
    exit 0
    ;;
  *)
    exit 0
    ;;
esac
"""

CURL_STUB = r"""#!/usr/bin/env bash
set -euo pipefail
state="${FAKE_STATE:?}"
max_time=2
url=""
prev=""
for a in "$@"; do
  if [[ "$prev" == "--max-time" ]]; then
    max_time="$a"
  fi
  url="$a"
  prev="$a"
done
printf '%s\n' "$*" >>"${state}/curl.log"
if [[ -n "${FAKE_CURL_STDERR:-}" ]]; then
  printf '%s\n' "${FAKE_CURL_STDERR}" >&2
fi
if [[ "$url" == *"/ready"* ]]; then
  sleep_s="${FAKE_READY_SLEEP:-0}"
  if awk -v s="$sleep_s" -v m="$max_time" 'BEGIN { exit !(s+0 > m+0) }'; then
    sleep "$max_time"
    echo "curl: (28) Operation timed out" >&2
    printf '\n000'
    exit 28
  fi
  if [[ "$sleep_s" != "0" ]]; then
    sleep "$sleep_s"
  fi
  printf '%s\n%s' "${FAKE_READY_BODY:-{\"ready\":true}}" "${FAKE_READY_CODE:-200}"
  exit 0
fi
code="${FAKE_HEALTH_CODE:-000}"
body="${FAKE_HEALTH_BODY-}"
if [[ "$code" =~ ^[23][0-9][0-9]$ ]]; then
  printf '%s\n%s' "${body:-{\"status\":\"ok\"}}" "$code"
  exit 0
fi
echo "curl: (7) Failed to connect to 127.0.0.1 port 18000" >&2
if [[ -n "${body}" ]]; then
  printf '%s\n%s' "$body" "$code"
  exit 0
fi
printf '\n%s' "$code"
exit 7
"""


def _function_body(name: str) -> str:
    source = SCRIPT.read_text()
    start = source.index(f"{name}() {{")
    next_section = source.find("\n#----------------------------------------------------------------", start)
    return source[start : next_section if next_section != -1 else None]


def _sanitize_deploy_diagnostic_src() -> str:
    source = SCRIPT.read_text()
    start = source.index("sanitize_deploy_diagnostic() {")
    end = source.index("\n}\n", start)
    return source[start : end + 2]


def _boot_smoke_heredoc() -> str:
    source = SCRIPT.read_text()
    start = source.index("<<'SMOKE'")
    start = source.index("\n", start) + 1
    end = source.index("\nSMOKE\n", start)
    return _sanitize_deploy_diagnostic_src() + "\n" + source[start:end]


def _run_sanitizer(text: str) -> str:
    result = subprocess.run(
        ["bash", "-c", _sanitize_deploy_diagnostic_src() + "\nsanitize_deploy_diagnostic"],
        input=text,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _prepare_smoke_env(tmp_path: Path, extra: dict[str, str] | None = None) -> tuple[Path, Path, dict[str, str]]:
    state = tmp_path / "fake-state"
    state.mkdir()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(fake_bin / "docker", DOCKER_STUB.replace("$CRASH_LOG", CRASH_LOG))
    _write_executable(fake_bin / "curl", CURL_STUB)
    remote = tmp_path / "remote"
    remote.mkdir()
    (remote / ".env").write_text("ACX_NETWORK_NAME=acx-dev-net\nACX_MODELS_PATH=/tmp/models\n")
    env = dict(os.environ)
    env.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{env.get('PATH', '')}",
            "FAKE_STATE": str(state),
            "FAKE_HEALTH_CODE": "000",
            "FAKE_HEALTH_BODY": "",
            "FAKE_READY_SLEEP": "0",
            "FAKE_READY_CODE": "200",
            "FAKE_READY_BODY": '{"ready":true}',
        }
    )
    if extra:
        env.update(extra)
    return state, remote, env


def _run_boot_smoke(
    tmp_path: Path,
    *,
    budget_s: int = 2,
    poll_s: int = 1,
    attempts: int = 1,
    vlm_budget: int = 0,
    extra_env: dict[str, str] | None = None,
    wrap_deadline: int | None = None,
) -> subprocess.CompletedProcess[str]:
    state, remote, env = _prepare_smoke_env(tmp_path, extra_env)
    smoke = tmp_path / "boot-smoke.sh"
    smoke.write_text(_boot_smoke_heredoc())
    args = [
        "dev",
        "iad.ocir.io/idu2kqqe2jxy/acx-backend@sha256:" + ("a" * 64),
        str(remote),
        str(budget_s),
        str(poll_s),
        str(attempts),
        str(vlm_budget),
    ]
    if wrap_deadline is None:
        result = subprocess.run(
            ["bash", str(smoke), *args],
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )
    else:
        driver = tmp_path / "deadline-driver.sh"
        driver.write_text(
            f'''
source "{SCRIPT}"
run_with_deadline {wrap_deadline} "boot-smoke health gate" bash "{smoke}" {" ".join(args)}
'''
        )
        result = subprocess.run(
            ["bash", str(driver)],
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )
    result._fake_state = state  # type: ignore[attr-defined]
    return result


def _run_capture_failure_evidence(
    tmp_path: Path,
    *,
    extra_script: str = "",
    stdin_data: bytes = b"",
    extra_env: dict[str, str] | None = None,
    phase: str = "",
    ssh_body: bytes = b"healthy-body\nHTTP_CODE=200",
    ssh_sleep: str = "0",
    empty_cid: bool = False,
    cid_stdout: bytes | None = None,
    cid_stderr: bytes = b"",
) -> subprocess.CompletedProcess[bytes]:
    records = tmp_path / "ssh-args"
    stdin_capture = tmp_path / "ssh-stdin"
    ssh_out = tmp_path / "ssh-out"
    ssh_out.write_bytes(ssh_body)
    cid_out = tmp_path / "cid-out"
    cid_err = tmp_path / "cid-err"
    if empty_cid:
        cid_out.write_bytes(b"")
    elif cid_stdout is not None:
        cid_out.write_bytes(cid_stdout)
    else:
        cid_out.write_bytes(b"abc123\n")
    cid_err.write_bytes(cid_stderr)
    driver = tmp_path / "capture-driver.sh"
    phase_arg = f" {phase}" if phase else ""
    driver.write_text(
        f'''
source "{SCRIPT}"
GREEN=; YELLOW=; RED=; RESET=
run_with_deadline() {{
  printf 'deadline=%s label=%s\\n' "$1" "$2" >>"{tmp_path / "deadlines"}"
  shift 2
  "$@"
}}
ssh() {{
  printf '%s\\n' "$*" >>"{records}"
  nflag=0
  for a in "$@"; do
    if [[ "$a" == "-n" ]]; then
      nflag=1
    fi
  done
  if [[ "$nflag" == "1" ]]; then
    : >"{stdin_capture}"
  else
    cat >"{stdin_capture}"
  fi
  if [[ "{ssh_sleep}" != "0" ]]; then
    sleep "{ssh_sleep}"
  fi
  remote="${{@: -1}}"
  if [[ "$remote" == *'ps -q'* ]]; then
    cat "{cid_out}"
    cat "{cid_err}" >&2
    return 0
  fi
  cat "{ssh_out}"
  return 0
}}
{extra_script}
capture_failure_evidence dev{phase_arg}
'''
    )
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", str(driver)],
        input=stdin_data,
        capture_output=True,
        check=False,
        env=env,
    )


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
    source = SCRIPT.read_text()
    assert 'ready_url="$(env_to_ready_url "$env")"' in body
    assert "emit_verify_ready_diagnostic" in body
    assert "non-gating" in source


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


def test_boot_smoke_captures_crash_logs_after_entrypoint_exit(tmp_path: Path) -> None:
    """VLMHEAL-1-REV-B-02: entrypoint crash must still yield docker logs.

    Refute: a crashed throwaway container prints 'smoke container logs unavailable'
    (or exits before docker logs) because `docker run -d --rm` already removed it.
    """
    result = _run_boot_smoke(tmp_path, budget_s=2, poll_s=1, attempts=1)
    combined = result.stdout + result.stderr
    assert result.returncode != 0
    assert CRASH_LOG in combined
    assert "smoke container logs unavailable" not in combined


def test_boot_smoke_ready_probe_does_not_timeout_a_marginal_health_pass(tmp_path: Path) -> None:
    """VLMHEAL-1-REV-B-01: /ready after health-OK must not consume the smoke deadline.

    Refute: health returns 2xx inside the budget, then the extra /ready probe
    (poll_s=2) pushes the outer run_with_deadline past the same budget (rc 124)
    and do_boot_smoke reports '/health never came up' for an otherwise good image.
    """
    result = _run_boot_smoke(
        tmp_path,
        budget_s=2,
        poll_s=2,
        attempts=1,
        extra_env={"FAKE_HEALTH_CODE": "200", "FAKE_READY_SLEEP": "2"},
        wrap_deadline=2,
    )
    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    assert "smoke health OK" in combined
    assert "timed out after" not in combined


def test_failure_evidence_is_sanitized_and_prefixed(tmp_path: Path) -> None:
    """VLMHEAL-1-REV-B-03: evidence bodies must not spoof deploy status or keep C0.

    Refute: capture_failure_evidence writes raw ESC/CR bytes or a line that
    looks like this script's own '==>' status to deploy stderr.
    """
    result = _run_capture_failure_evidence(
        tmp_path,
        ssh_body=b"\x1b[31mxx forged failure\x1b[0m\n==> forged success\r\n",
    )
    assert result.returncode == 0
    assert b"\x1b" not in result.stderr
    assert b"\r" not in result.stderr
    assert b"diagnostic: [31mxx forged failure[0m\n" in result.stderr
    assert b"diagnostic: ==> forged success\n" in result.stderr


def test_boot_smoke_failure_body_is_sanitized(tmp_path: Path) -> None:
    """VLMHEAL-1-REV-B-03: smoke last-/health body is the same threat model."""
    result = _run_boot_smoke(
        tmp_path,
        budget_s=2,
        poll_s=1,
        attempts=1,
        extra_env={
            "FAKE_HEALTH_CODE": "503",
            "FAKE_HEALTH_BODY": "\x1b[31msecret=postgres://x\x1b[0m\n==> forged success",
        },
    )
    combined = result.stderr
    assert result.returncode != 0
    assert "\x1b" not in combined
    assert "diagnostic: ==> forged success" in combined
    assert combined.count("==> forged success") == combined.count("diagnostic: ==> forged success")


def test_failure_evidence_ssh_does_not_consume_caller_stdin(tmp_path: Path) -> None:
    """VLMHEAL-1-REV-B-04: evidence ssh must pass -n so run_with_deadline cannot feed stdin.

    Refute: piping POISON into capture_failure_evidence is consumed by ssh
    (OCIRSTDIN-1 class) because the three probes inherit fd 3.
    """
    result = _run_capture_failure_evidence(tmp_path, stdin_data=b"POISON\n")
    assert result.returncode == 0, result.stderr.decode()
    args = (tmp_path / "ssh-args").read_text().splitlines()
    assert len(args) == 4
    assert all("-n" in line.split() for line in args)
    stdin_capture = tmp_path / "ssh-stdin"
    assert stdin_capture.read_text() == ""


def test_failure_evidence_budget_is_decoupled_from_remote_command_timeout(tmp_path: Path) -> None:
    """VLMHEAL-1-REV-B-05: evidence capture must not inherit ACX_REMOTE_COMMAND_TIMEOUT.

    Refute: raising the pull/restart knob to 900 multiplies the pre-rollback
    outage window because capture_failure_evidence uses that same deadline.
    """
    result = _run_capture_failure_evidence(
        tmp_path,
        extra_env={"ACX_REMOTE_COMMAND_TIMEOUT": "900"},
    )
    assert result.returncode == 0, result.stderr.decode()
    deadlines = [line.split()[0] for line in (tmp_path / "deadlines").read_text().splitlines()]
    assert deadlines == ["deadline=30"] * 4

    result = _run_capture_failure_evidence(
        tmp_path,
        extra_env={"ACX_REMOTE_COMMAND_TIMEOUT": "900", "ACX_EVIDENCE_TIMEOUT": "5"},
    )
    assert result.returncode == 0, result.stderr.decode()
    # second run appends; last four lines are the override (health, ready, cid, logs)
    deadlines = [line.split()[0] for line in (tmp_path / "deadlines").read_text().splitlines()]
    assert deadlines[-4:] == ["deadline=5"] * 4


def test_pre_candidate_evidence_skips_http_probes_of_prior_image(tmp_path: Path) -> None:
    """VLMHEAL-1-REV-B-06: push/restart failures must not label prior /health as candidate.

    Refute: capture_failure_evidence on a pre-candidate branch prints a healthy
    /health body from the still-serving previous image with no warning that the
    candidate never started.
    """
    result = _run_capture_failure_evidence(tmp_path, phase="pre_candidate")
    combined = result.stderr.decode()
    assert result.returncode == 0, combined
    assert "candidate never started" in combined
    args = (tmp_path / "ssh-args").read_text()
    assert "/health" not in args
    assert "/ready" not in args
    assert "docker" in args
    assert "--- evidence: /health ---" not in combined


def test_pre_candidate_records_remote_commands_and_skips_http_probes(tmp_path: Path) -> None:
    """VLMHEAL-1-REV-C-04: stub records which remote commands ran on pre_candidate.

    Refute: the ssh stub returning rc 0 for all three probes hides that
    pre_candidate still issued curl /health and /ready against the prior image.
    """
    result = _run_capture_failure_evidence(tmp_path, phase="pre_candidate")
    combined = result.stderr.decode()
    assert result.returncode == 0, combined
    remote_commands = (tmp_path / "ssh-args").read_text().splitlines()
    assert remote_commands, "pre_candidate must still collect compose/ps state"
    joined = "\n".join(remote_commands)
    assert "curl" not in joined
    assert "/health" not in joined
    assert "/ready" not in joined
    assert "docker logs" not in joined
    assert any("docker compose" in line and " ps" in line for line in remote_commands)
    assert "candidate never started" in combined
    assert "--- evidence: docker ps / compose ---" in combined


def test_runtime_evidence_still_probes_health_and_ready(tmp_path: Path) -> None:
    result = _run_capture_failure_evidence(tmp_path)
    combined = result.stderr.decode()
    assert result.returncode == 0, combined
    args = (tmp_path / "ssh-args").read_text()
    assert "/health" in args
    assert "/ready" in args
    assert "--- evidence: /health ---" in combined


def test_push_and_restart_failures_use_pre_candidate_evidence_phase() -> None:
    """VLMHEAL-1-REV-B-06 / D-02: push is pre_candidate; restart uses post_restart phase."""
    for function_name, env_expression in (("do_deploy", '"$env"'), ("do_promote", '"$to_env"')):
        body = _function_body(function_name)
        assert f"capture_failure_evidence {env_expression} pre_candidate" in body
        assert (
            f'capture_failure_evidence {env_expression} "${{ACX_RESTART_EVIDENCE_PHASE:-pre_candidate}}"'
            in body
        )
        assert f"capture_failure_evidence {env_expression} candidate" in body
        assert body.count(f"capture_failure_evidence {env_expression} pre_candidate") == 1
        assert body.count(f"capture_failure_evidence {env_expression} candidate") == 1


def test_run_with_deadline_does_not_dup_stdin_through_fd3() -> None:
    """VLMHEAL-1-REV-B-04: the fd3 dup/close pair is the bash 5.2 segfault shape."""
    source = SCRIPT.read_text()
    start = source.index("run_with_deadline() {")
    end = source.index("validated_deadline() {")
    code = "\n".join(
        line for line in source[start:end].splitlines() if not line.lstrip().startswith("#")
    )
    assert "exec 3<&0" not in code
    assert '"$@" <&0 &' in code


def test_run_with_deadline_survives_bash_s_command_substitution() -> None:
    """VLMHEAL-1-REV-B-04: $(run_with_deadline) under bash -s must not SIGSEGV.

    Refute: feeding the deploy helpers on stdin (`bash -s`) and wrapping
    run_with_deadline in command substitution dies with rc 139 because
    `exec 3<&0; "$@" <&3 &; exec 3<&-` segfaults bash 5.2.
    """
    program = f'''
source "{SCRIPT}"
GREEN=; YELLOW=; RED=; RESET=
out="$(run_with_deadline 5 "bash-s subst" echo hello-from-deadline)"
printf 'captured=%s\\n' "$out"
'''
    result = subprocess.run(
        ["bash", "-s"],
        input=program,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "captured=hello-from-deadline" in result.stdout


def test_failure_evidence_redacts_bearer_and_api_token(tmp_path: Path) -> None:
    """VLMHEAL-1-REV-B-03: bearer / API-token substrings must not reach deploy stderr.

    Refute: a curl/log body containing `Authorization: Bearer x` and
    `ACX_API_TOKEN=...` is copied onto deploy stderr after only C0 stripping.
    """
    result = _run_capture_failure_evidence(
        tmp_path,
        ssh_body=(
            b"Authorization: Bearer supersecret-token\n"
            b"ACX_API_TOKEN=another-secret\n"
            b"password=hunter2\n"
            b"RECOGNITION_ADMIN_TOKEN=admin-secret\n"
            b"HF_TOKEN=hf-secret\n"
            b"PGPASSWORD=pg-secret\n"
            b'"token": "json-secret"\n'
            b'"Authorization": "Bearer json-bearer"\n'
            b"AUTHORIZATION: BEARER header-secret\n"
            b"Bearer naked-secret\n"
            b"HTTP_CODE=200\n"
        ),
    )
    combined = result.stderr
    assert result.returncode == 0, combined.decode()
    for secret in (
        b"supersecret-token",
        b"another-secret",
        b"hunter2",
        b"admin-secret",
        b"hf-secret",
        b"pg-secret",
        b"json-secret",
        b"json-bearer",
        b"header-secret",
        b"naked-secret",
    ):
        assert secret not in combined, secret
    assert b"Authorization: Bearer" in combined
    assert b"ACX_API_TOKEN=" in combined
    assert b"password=" in combined
    assert b"RECOGNITION_ADMIN_TOKEN=" in combined
    assert b"HF_TOKEN=" in combined
    assert b"PGPASSWORD=" in combined
    assert b"[REDACTED]" in combined


def test_emit_sanitized_evidence_is_hoisted_out_of_capture() -> None:
    """VLMHEAL-1-REV-C-05: nested emit_sanitized_evidence must be a top-level helper."""
    source = SCRIPT.read_text()
    capture = _function_body("capture_failure_evidence")
    # Nested `name() {` would appear inside capture_failure_evidence's body.
    assert "emit_sanitized_evidence() {" not in capture
    assert "\nemit_sanitized_evidence() {" in source
    assert "emit_sanitized_evidence" in capture


def test_evidence_timeout_is_parsed_through_validated_deadline() -> None:
    """VLMHEAL-1-REV-B-08: ACX_EVIDENCE_TIMEOUT must use validated_deadline."""
    body = _function_body("capture_failure_evidence")
    assert "validated_deadline ACX_EVIDENCE_TIMEOUT" in body
    assert "ACX_REMOTE_COMMAND_TIMEOUT" not in body


def test_empty_api_container_id_emits_no_api_container_line() -> None:
    """VLMHEAL-1-REV-B-11: empty compose ps -q must not run docker logs with no id."""
    body = _function_body("capture_failure_evidence")
    assert "no api container" in body
    assert "docker logs --tail 80" in body
    assert "api container not found" not in body
    assert body.index("ps -q") < body.index("docker logs --tail 80") < body.index("no api container")


def test_empty_api_container_id_skips_docker_logs_ssh(tmp_path: Path) -> None:
    """D-04: empty compose ps -q must not ssh docker logs."""
    result = _run_capture_failure_evidence(tmp_path, empty_cid=True)
    combined = result.stderr.decode()
    assert result.returncode == 0, combined
    assert "no api container" in combined
    args = (tmp_path / "ssh-args").read_text()
    assert "docker logs" not in args
    assert "ps -q" in args


def test_post_restart_evidence_keeps_logs_and_skips_http(tmp_path: Path) -> None:
    """D-02: after systemctl restart, evidence must not say the candidate never started."""
    result = _run_capture_failure_evidence(tmp_path, phase="post_restart")
    combined = result.stderr.decode()
    assert result.returncode == 0, combined
    assert "candidate never started" not in combined
    args = (tmp_path / "ssh-args").read_text()
    assert "docker logs" in args
    assert "/health" not in args
    assert "/ready" not in args
    assert "--- evidence: /health ---" not in combined
    assert "--- evidence: api container logs ---" in combined


def test_do_restart_marks_post_restart_before_systemctl() -> None:
    """D-02: systemctl restart failure must request post_restart evidence."""
    body = _function_body("do_restart")
    assert 'ACX_RESTART_EVIDENCE_PHASE="pre_candidate"' in body
    assert 'ACX_RESTART_EVIDENCE_PHASE="post_restart"' in body
    assert body.index('ACX_RESTART_EVIDENCE_PHASE="pre_candidate"') < body.index(
        'ACX_RESTART_EVIDENCE_PHASE="post_restart"'
    )
    assert body.index('ACX_RESTART_EVIDENCE_PHASE="post_restart"') < body.index(
        "sudo systemctl restart"
    )


def test_pre_candidate_docker_ps_is_compose_project_scoped(tmp_path: Path) -> None:
    """D-06: pre_candidate docker ps must not list foreign compose projects."""
    result = _run_capture_failure_evidence(tmp_path, phase="pre_candidate")
    assert result.returncode == 0, result.stderr.decode()
    args = (tmp_path / "ssh-args").read_text()
    assert "--filter label=com.docker.compose.project=" in args
    assert "acx-dev" in args


def test_boot_smoke_poll_prints_curl_stderr_once(tmp_path: Path) -> None:
    """B-09: curl: (7) must not repeat for every health poll."""
    result = _run_boot_smoke(tmp_path, budget_s=3, poll_s=1, attempts=3)
    combined = result.stdout + result.stderr
    assert result.returncode != 0
    assert combined.count("curl: (7)") == 1


def test_boot_smoke_failure_redacts_tokens(tmp_path: Path) -> None:
    """D-01: VM smoke failure body/logs must use the same sanitizer."""
    result = _run_boot_smoke(
        tmp_path,
        budget_s=2,
        poll_s=1,
        attempts=1,
        extra_env={
            "FAKE_HEALTH_CODE": "503",
            "FAKE_HEALTH_BODY": (
                'RECOGNITION_ADMIN_TOKEN=admin-secret HF_TOKEN=hf-secret '
                'PGPASSWORD=pg-secret "token": "json-secret" '
                "AUTHORIZATION: BEARER header-secret Bearer naked-secret"
            ),
        },
    )
    combined = result.stderr
    assert result.returncode != 0
    for secret in (
        "admin-secret",
        "hf-secret",
        "pg-secret",
        "json-secret",
        "header-secret",
        "naked-secret",
    ):
        assert secret not in combined, secret
    assert "[REDACTED]" in combined


def _run_do_verify(
    tmp_path: Path,
    *,
    attempts: int,
    health_sha: str,
    health_code: str = "200",
) -> subprocess.CompletedProcess[str]:
    curl_log = tmp_path / "curl.log"
    expected = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    health_body = (
        '{"commit_sha":"' + health_sha + '","status":"ok","image_variant":"recognition"}'
    )
    driver = tmp_path / "verify-driver.sh"
    driver.write_text(
        f'''
source "{SCRIPT}"
GREEN=; YELLOW=; RED=; RESET=
ACX_VERIFY_ATTEMPTS={attempts}
ACX_VERIFY_SLEEP=0
ACX_VERIFY_EXPECT_LOCAL=1
verify_running_image_matches_deployed() {{ return 0; }}
verify_live_gpu_snapshots() {{ return 0; }}
curl() {{
  printf '%s\\n' "$*" >>"{curl_log}"
  url="${{@: -1}}"
  if [[ "$url" == *"/ready"* ]]; then
    printf '%s\\n%s' '{{"ready":true}}' '200'
    return 0
  fi
  printf '%s\\n%s' '{health_body}' '{health_code}'
  return 0
}}
do_verify dev
'''
    )
    env = dict(os.environ)
    result = subprocess.run(
        ["bash", str(driver)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
        cwd=SCRIPT.parents[2],
    )
    result._curl_log = curl_log  # type: ignore[attr-defined]
    result._expected_sha = expected  # type: ignore[attr-defined]
    return result


def test_do_verify_skips_ready_on_successful_attempt(tmp_path: Path) -> None:
    """B-10: /ready must not fire on a successful verify attempt."""
    expected = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    result = _run_do_verify(tmp_path, attempts=3, health_sha=expected)
    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    curl_log = (tmp_path / "curl.log").read_text()
    assert "/health" in curl_log
    assert "/ready" not in curl_log


def test_do_verify_probes_ready_only_on_terminal_failure(tmp_path: Path) -> None:
    """B-10: /ready is diagnostic and only on the last failing attempt."""
    result = _run_do_verify(tmp_path, attempts=3, health_sha="deadbeefdeadbeef")
    combined = result.stdout + result.stderr
    assert result.returncode != 0, combined
    curl_log = (tmp_path / "curl.log").read_text()
    assert curl_log.count("/ready") == 1
    assert curl_log.count("/health") == 3
    assert "non-gating" in combined


SANITIZER_CASES = [
    ('{"access_token":"abc.DEF-123"}', "abc.DEF-123"),
    ('{"api_key": "abc123"}', "abc123"),
    ("SECRET=abc", "abc"),
    ('PGPASSWORD="quoted secret"', "quoted secret"),
    ("postgresql://acx:LEAK5@db/x", "LEAK5"),
    ('{"token": "json-secret"}', "json-secret"),
    ('{"refresh_token": "rt-secret"}', "rt-secret"),
    ('{"password": "pw-secret"}', "pw-secret"),
    ('{"passwd": "passwd-secret"}', "passwd-secret"),
    ('{"secret": "sec-value"}', "sec-value"),
    ('{"api-key":"hyphen-json"}', "hyphen-json"),
    ('{"db_password": "db-pass"}', "db-pass"),
    ('{"client_secret": "cli-sec"}', "cli-sec"),
    ('{"service_key": "svc-key"}', "svc-key"),
    ('{"pgpassword": "json-pg"}', "json-pg"),
    ("TOKEN=tok-secret", "tok-secret"),
    ("PASSWORD=pw2-secret", "pw2-secret"),
    ("KEY=key-secret", "key-secret"),
    ("SECRET: colon-secret", "colon-secret"),
    ("TOKEN='quoted token'", "quoted token"),
    ('PASSWORD="quoted pass"', "quoted pass"),
    ("Authorization: Bearer header-secret", "header-secret"),
    ("bearer naked-secret", "naked-secret"),
    ("ACX_API_TOKEN=another-secret", "another-secret"),
    ("HF_TOKEN=hf-secret", "hf-secret"),
    ("api-key=hyphen-secret", "hyphen-secret"),
    ("api_key=under-secret", "under-secret"),
    ("X-Api-Key: header-key-secret", "header-key-secret"),
    ("password=hunter2", "hunter2"),
]


@pytest.mark.parametrize("raw,secret", SANITIZER_CASES, ids=[secret for _, secret in SANITIZER_CASES])
def test_sanitize_deploy_diagnostic_redacts_secret_shapes(raw: str, secret: str) -> None:
    """W-01: every secret shape from the sanitizer contract is absent after redaction."""
    out = _run_sanitizer(raw + "\n")
    assert secret not in out, out
    assert "[REDACTED]" in out
    assert out.startswith("diagnostic: ")


def test_sanitize_deploy_diagnostic_preserves_token_file_and_header_name() -> None:
    """W-01 negative: TOKEN_FILE paths stay; X-Api-Key keeps its header name."""
    raw = (
        "RECOGNITION_ADMIN_TOKEN_FILE=/run/secrets/admin.token\n"
        "X-Api-Key: hunter2\n"
    )
    out = _run_sanitizer(raw)
    assert "RECOGNITION_ADMIN_TOKEN_FILE=/run/secrets/admin.token" in out
    assert "X-Api-Key:" in out
    assert "api-key=" not in out
    assert "hunter2" not in out
    assert "[REDACTED]" in out


def test_sanitizer_sed_defined_once() -> None:
    """W-05: one sanitizer definition; smoke heredoc must call it, not copy it."""
    result = subprocess.run(
        ["grep", "-Fc", "api[-_]?key", str(SCRIPT)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "1"
    source = SCRIPT.read_text()
    assert source.count("sanitize_deploy_diagnostic() {") == 1
    heredoc = _boot_smoke_heredoc()
    assert "sanitize_deploy_diagnostic" in heredoc
    smoke_only = heredoc[heredoc.index("set -euo pipefail") :]
    assert "sanitize_deploy_diagnostic() {" not in smoke_only


def test_boot_smoke_curl_stderr_is_sanitized(tmp_path: Path) -> None:
    """W-03: last-attempt curl stderr is prefixed and redacted."""
    result = _run_boot_smoke(
        tmp_path,
        budget_s=2,
        poll_s=1,
        attempts=1,
        extra_env={
            "FAKE_HEALTH_CODE": "000",
            "FAKE_CURL_STDERR": "password=hunter2",
        },
    )
    combined = result.stdout + result.stderr
    assert result.returncode != 0
    assert "hunter2" not in combined
    assert "diagnostic: " in combined
    assert "[REDACTED]" in combined


def test_cid_capture_stderr_never_leaks_unprefixed(tmp_path: Path) -> None:
    """W-02: cid-capture ssh 2>&1; hunter2 on ssh stderr never reaches the log raw."""
    result = _run_capture_failure_evidence(
        tmp_path,
        cid_stdout=b"abc123\n",
        cid_stderr=b"password=hunter2\n",
    )
    combined = (result.stdout + result.stderr).decode()
    assert result.returncode == 0, combined
    assert "hunter2" not in combined
    body = _function_body("capture_failure_evidence")
    cid_idx = body.index("ps -q")
    assert "2>&1" in body[cid_idx : cid_idx + 80]


def test_verify_health_and_ready_bodies_redact_secrets(tmp_path: Path) -> None:
    """W-04: /health and /ready bodies printed by do_verify go through the sanitizer."""
    curl_log = tmp_path / "curl.log"
    driver = tmp_path / "verify-driver.sh"
    driver.write_text(
        f'''
source "{SCRIPT}"
GREEN=; YELLOW=; RED=; RESET=
ACX_VERIFY_ATTEMPTS=1
ACX_VERIFY_SLEEP=0
ACX_VERIFY_EXPECT_LOCAL=1
verify_running_image_matches_deployed() {{ return 0; }}
verify_live_gpu_snapshots() {{ return 0; }}
curl() {{
  printf '%s\\n' "$*" >>"{curl_log}"
  url="${{@: -1}}"
  if [[ "$url" == *"/ready"* ]]; then
    printf '%s\\n%s' '{{"ready":true,"token":"hunter2"}}' '200'
    return 0
  fi
  printf '%s\\n%s' '{{"commit_sha":"deadbeefdeadbeef","status":"ok","image_variant":"recognition","password":"hunter2"}}' '200'
  return 0
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
    combined = result.stdout + result.stderr
    assert result.returncode != 0, combined
    assert "hunter2" not in combined
    assert "[REDACTED]" in combined
    assert "non-gating" in combined


def test_unexpected_container_id_is_sanitized_not_no_api_container(tmp_path: Path) -> None:
    """W-07: non-hex cid prints unexpected-container-id, never 'no api container'."""
    result = _run_capture_failure_evidence(
        tmp_path,
        cid_stdout=b"password=hunter2\nnot-a-valid-cid\n",
    )
    combined = (result.stdout + result.stderr).decode()
    assert result.returncode == 0, combined
    assert "hunter2" not in combined
    assert "unexpected container id output" in combined
    assert "no api container" not in combined
    assert "[REDACTED]" in combined
    args = (tmp_path / "ssh-args").read_text()
    assert "docker logs" not in args


def test_compose_project_name_read_from_remote_env(tmp_path: Path) -> None:
    """W-08: remote .env COMPOSE_PROJECT_NAME is grepped; fallback is acx-${env}."""
    result = _run_capture_failure_evidence(tmp_path, phase="pre_candidate")
    combined = (result.stdout + result.stderr).decode()
    assert result.returncode == 0, combined
    args = (tmp_path / "ssh-args").read_text()
    assert "grep -m1 '^COMPOSE_PROJECT_NAME='" in args
    assert ".env" in args
    assert "acx-dev" in args
    assert "COMPOSE_PROJECT_NAME" in combined
    assert "fallback acx-dev" in combined
