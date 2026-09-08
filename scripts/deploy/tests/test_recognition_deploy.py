"""Focused regressions for recognition deployment transaction boundaries."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

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


def _boot_smoke_heredoc() -> str:
    source = SCRIPT.read_text()
    start = source.index("<<'SMOKE'")
    start = source.index("\n", start) + 1
    end = source.index("\nSMOKE\n", start)
    return source[start:end]


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
) -> subprocess.CompletedProcess[bytes]:
    records = tmp_path / "ssh-args"
    stdin_capture = tmp_path / "ssh-stdin"
    ssh_out = tmp_path / "ssh-out"
    ssh_out.write_bytes(ssh_body)
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
    assert len(args) == 3
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
    assert deadlines == ["deadline=30", "deadline=30", "deadline=30"]

    result = _run_capture_failure_evidence(
        tmp_path,
        extra_env={"ACX_REMOTE_COMMAND_TIMEOUT": "900", "ACX_EVIDENCE_TIMEOUT": "5"},
    )
    assert result.returncode == 0, result.stderr.decode()
    # second run appends; last three lines are the override
    deadlines = [line.split()[0] for line in (tmp_path / "deadlines").read_text().splitlines()]
    assert deadlines[-3:] == ["deadline=5", "deadline=5", "deadline=5"]


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
    """VLMHEAL-1-REV-B-06: do_push_tag / do_restart rollback is pre_candidate."""
    for function_name, env_expression in (("do_deploy", '"$env"'), ("do_promote", '"$to_env"')):
        body = _function_body(function_name)
        assert f"capture_failure_evidence {env_expression} pre_candidate" in body
        assert f"capture_failure_evidence {env_expression} candidate" in body
        assert body.count(f"capture_failure_evidence {env_expression} pre_candidate") == 2
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
    assert result.returncode != 139
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
            b"HTTP_CODE=200\n"
        ),
    )
    combined = result.stderr
    assert result.returncode == 0, combined.decode()
    assert b"supersecret-token" not in combined
    assert b"another-secret" not in combined
    assert b"hunter2" not in combined
    assert b"Authorization: Bearer" in combined
    assert b"ACX_API_TOKEN=" in combined
    assert b"password=" in combined
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
    assert body.index("[ -n") < body.index("docker logs --tail 80") < body.index("no api container")
