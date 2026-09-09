"""Focused regressions for recognition deployment transaction boundaries."""

from __future__ import annotations

import os
import re
import shutil
import signal
import stat
import subprocess
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "recognition-service.sh"

CRASH_LOG = "ModuleNotFoundError: No module named 'scene.foo'"
VALID_CID = "ab" * 32

DOCKER_STUB = r"""#!/usr/bin/env bash
set -euo pipefail
state="${FAKE_STATE:?}"
cmd="${1:-}"; shift || true
printf '%s\n' "$cmd $*" >>"${state}/docker.log"
mkdir -p "${state}/containers"
case "$cmd" in
  network)
    sub="${1:-}"; shift || true
    net_name=""
    for a in "$@"; do
      net_name="$a"
    done
    case "$sub" in
      inspect)
        format=0
        prev=""
        for a in "$@"; do
          if [[ "$prev" == "--format" ]]; then
            format=1
          fi
          prev="$a"
        done
        if [[ -n "$net_name" && -d "${state}/networks/${net_name}" ]]; then
          if (( format )); then
            cat "${state}/networks/${net_name}/owner" 2>/dev/null || true
          fi
          exit 0
        fi
        if [[ "${FAKE_NET_EXISTS:-1}" == "1" ]]; then
          if (( format )); then
            printf '%s\n' "${FAKE_NET_OWNER:-}"
          fi
          exit 0
        fi
        exit 1
        ;;
      create)
        owner=""
        prev=""
        for a in "$@"; do
          if [[ "$prev" == "--label" && "$a" == acx.smoke.owner=* ]]; then
            owner="${a#acx.smoke.owner=}"
          fi
          prev="$a"
        done
        mkdir -p "${state}/networks/${net_name}"
        printf '%s\n' "$owner" >"${state}/networks/${net_name}/owner"
        if [[ -n "${FAKE_NET_CREATE_SLEEP:-}" ]]; then
          sleep "${FAKE_NET_CREATE_SLEEP}"
        fi
        exit 0
        ;;
      rm)
        rm -rf "${state}/networks/${net_name}"
        printf '%s\n' "$net_name" >>"${state}/network_rm"
        exit 0
        ;;
      *)
        exit 0
        ;;
    esac
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
    if [[ -n "${FAKE_PG_EXEC_SLEEP:-}" ]]; then
      sleep "${FAKE_PG_EXEC_SLEEP}"
    fi
    if [[ "${FAKE_PG_READY:-1}" != "1" ]]; then
      exit 1
    fi
    exit 0
    ;;
  port)
    if [[ -n "${FAKE_PORT_SLEEP:-}" ]]; then
      sleep "${FAKE_PORT_SLEEP}"
    fi
    name="${1:-}"
    if [[ ! -d "${state}/containers/${name}" ]]; then
      echo "Error: No such container: ${name}" >&2
      exit 1
    fi
    if [[ "${FAKE_PORT_EMPTY:-0}" == "1" ]]; then
      exit 0
    fi
    echo "0.0.0.0:18000"
    exit 0
    ;;
  logs)
    date +%s.%N >"${state}/logs_started"
    if [[ -n "${FAKE_LOGS_SLEEP:-}" ]]; then
      sleep "${FAKE_LOGS_SLEEP}"
    fi
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
    if [[ ! -f "${state}/first_rm" ]]; then
      date +%s.%N >"${state}/first_rm"
    fi
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
if [[ -n "${FAKE_HEALTH_SLEEP:-}" ]]; then
  sleep_s="${FAKE_HEALTH_SLEEP}"
  if awk -v s="$sleep_s" -v m="$max_time" 'BEGIN { exit !(s+0 > m+0) }'; then
    sleep "$max_time"
    echo "curl: (28) Operation timed out" >&2
    printf '\n000'
    exit 28
  fi
  if [[ "$sleep_s" != "0" ]]; then
    sleep "$sleep_s"
  fi
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
    """Slice one top-level `name() {` through the next column-0 `fn() {`.

    Nested helpers inside remote heredocs are not the next top-level function.
    """
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


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _path_without_timeout(prepend: Path, tmp_path: Path) -> str:
    """PATH with stubs plus essential bins, but no `timeout` binary."""
    stripped = tmp_path / "path-no-timeout"
    stripped.mkdir(exist_ok=True)
    needed = (
        "bash",
        "sleep",
        "rm",
        "cat",
        "mkdir",
        "mktemp",
        "grep",
        "cut",
        "tr",
        "head",
        "sed",
        "awk",
        "mv",
        "cp",
        "ls",
        "chmod",
        "kill",
        "ps",
        "date",
        "env",
        "true",
        "false",
        "uname",
        "sort",
        "basename",
        "dirname",
        "touch",
        "wc",
        "tee",
        "id",
        "printf",
        "echo",
        "ln",
        "od",
        "tail",
        "xargs",
        "locale",
        "getconf",
        "which",
    )
    for name in needed:
        found = shutil.which(name)
        if found is None:
            continue
        dest = stripped / name
        if not dest.exists():
            dest.symlink_to(found)
    return f"{prepend}{os.pathsep}{stripped}"


def _prepare_smoke_env(
    tmp_path: Path,
    extra: dict[str, str] | None = None,
    *,
    hide_timeout: bool = False,
) -> tuple[Path, Path, dict[str, str]]:
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
    if hide_timeout:
        env["PATH"] = _path_without_timeout(fake_bin, tmp_path)
    return state, remote, env


def _docker_log(result: subprocess.CompletedProcess[str]) -> str:
    state = result._fake_state  # type: ignore[attr-defined]
    return Path(state).joinpath("docker.log").read_text()


def _run_bash_with_unread_fifo(
    driver: Path,
    tmp_path: Path,
    env: dict[str, str],
    *,
    alarm_s: int = 5,
) -> subprocess.CompletedProcess[str]:
    """Attach stdin to a FIFO nobody writes; alarm out if a child consumes it."""
    fifo = tmp_path / "unread.fifo"
    os.mkfifo(fifo)
    fd = os.open(fifo, os.O_RDWR)
    try:
        return subprocess.run(
            ["bash", str(driver)],
            text=True,
            capture_output=True,
            check=False,
            env=env,
            cwd=SCRIPT.parents[2],
            stdin=fd,
            timeout=alarm_s,
        )
    finally:
        os.close(fd)


def _run_boot_smoke(
    tmp_path: Path,
    *,
    budget_s: int | str = 2,
    poll_s: int | str = 1,
    attempts: int = 1,
    vlm_budget: int | str = 0,
    pg_budget: int | str = 30,
    setup_slack: int | str = 30,
    net_create_cap: int | str = 10,
    port_cap: int | str = 5,
    trap_docker_s: int | str = 10,
    extra_env: dict[str, str] | None = None,
    wrap_deadline: int | None = None,
    hide_timeout: bool = False,
    close_stderr: bool = False,
) -> subprocess.CompletedProcess[str]:
    del attempts  # LR-04: wrapper/body no longer take a dead attempts positional.
    state, remote, env = _prepare_smoke_env(tmp_path, extra_env, hide_timeout=hide_timeout)
    smoke = tmp_path / "boot-smoke.sh"
    smoke.write_text(_boot_smoke_heredoc())
    args = [
        "dev",
        "iad.ocir.io/idu2kqqe2jxy/acx-backend@sha256:" + ("a" * 64),
        str(remote),
        str(budget_s),
        str(poll_s),
        str(vlm_budget),
        str(pg_budget),
        str(setup_slack),
        str(net_create_cap),
        str(port_cap),
        str(trap_docker_s),
    ]
    if wrap_deadline is None:
        cmd = ["bash", str(smoke), *args]
        if close_stderr:
            wrapper = tmp_path / "closed-stderr.sh"
            _write_executable(
                wrapper,
                f'#!/usr/bin/env bash\nexec 2>&-\nexec bash "{smoke}" "$@"\n',
            )
            cmd = ["bash", str(wrapper), *args]
        result = subprocess.run(
            cmd,
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
        cid_out.write_bytes((VALID_CID + "\n").encode())
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
restore_runtime_topology() {{ printf 'topology\\n' >>"{records}"; }}
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
        "topology",
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


def test_remote_build_does_not_stage_mutable_environment_tag(tmp_path: Path) -> None:
    calls = tmp_path / "commands.txt"
    driver = f'''
source "{SCRIPT}"
preflight_ssh() {{ :; }}
preflight_remote_docker() {{ :; }}
preflight_rsync() {{ :; }}
assert_remote_build_free_space() {{ :; }}
run_with_deadline() {{
  printf '%s\\n' "$@" >> "{calls}"
  if [[ "$2" == *"setup/bootstrap/prune/build"* ]]; then cat >> "{calls}"; fi
}}
do_build_remote dev
'''
    result = subprocess.run(
        ["bash", "-c", driver], text=True, capture_output=True, cwd=SCRIPT.parents[2], env=dict(os.environ), timeout=10
    )
    assert result.returncode == 0, result.stdout + result.stderr
    commands = calls.read_text()
    assert "buildx build" in commands
    assert "--load" in commands
    assert '-t "${acx_image}:${acx_sha}" .' in commands
    assert ":dev" not in commands


def test_boot_smoke_has_outer_deadlines_and_curl_request_timeout() -> None:
    body = _function_body("do_boot_smoke")
    assert body.count("run_with_deadline") >= 2
    assert "repair_blob_volume_ownership() {" not in body
    assert "do_restart() {" not in body
    assert "capture_failure_evidence() {" not in body
    smoke = _boot_smoke_heredoc()
    assert "curl -sS --max-time" in smoke
    assert "--write-out" in smoke
    assert "last_health_body" in smoke
    assert "docker logs --tail 80" in smoke
    assert "sanitize_deploy_diagnostic" in smoke
    assert not re.search(r"curl[^\n]*/ready", smoke)
    assert "SECONDS" in smoke
    assert 'seq 1 "${pg_budget}"' not in smoke
    assert 'seq 1 "${attempts}"' not in smoke
    assert re.search(r"^SMOKE_TIMEOUT_DEFAULT=24$", SCRIPT.read_text(), re.M)
    assert re.search(r"^SMOKE_PG_READY_TIMEOUT=30$", SCRIPT.read_text(), re.M)


@pytest.mark.parametrize("budget_s", [16, 24])
def test_boot_smoke_computed_health_loop_budget(tmp_path: Path, budget_s: int) -> None:
    """GR-37 / GR-38: health window is budget minus trap reserve plus last-curl guard."""
    poll_s = 2
    trap_docker_s = 10  # logs+rm+rm+volume+network, each timeout 2
    diag_reserve = trap_docker_s + poll_s
    health_budget = max(1, budget_s - diag_reserve)
    started = time.monotonic()
    result = _run_boot_smoke(
        tmp_path,
        budget_s=budget_s,
        poll_s=poll_s,
        pg_budget=1,
        extra_env={"FAKE_HEALTH_CODE": "000"},
    )
    elapsed = time.monotonic() - started
    combined = result.stdout + result.stderr
    assert result.returncode != 0, combined
    # GR-05 stops the last curl when remaining <= poll_s, so elapsed is
    # health_budget minus about one poll, never the full outer budget.
    assert elapsed >= max(0, health_budget - poll_s) - 1
    assert elapsed < budget_s + 4


def test_automatic_rollbacks_capture_failure_evidence_first() -> None:
    helper = _function_body("handle_failed_verification")
    helper_evidence = 'capture_failure_evidence "$env"'
    helper_restore = 'restore_env_tag_to_rollback "$env"'
    assert helper_evidence in helper
    assert helper_restore in helper
    assert helper.index(helper_evidence) < helper.index(helper_restore)
    for function_name, env_expression in (("_ship_selected_env", '"$env"'), ("do_promote", '"$to_env"')):
        body = _function_body(function_name)
        evidence_marker = f"capture_failure_evidence {env_expression}"
        restore_marker = f"restore_env_tag_to_rollback {env_expression}"
        evidence_positions = [index for index in range(len(body)) if body.startswith(evidence_marker, index)]
        restore_positions = [index for index in range(len(body)) if body.startswith(restore_marker, index)]
        assert len(evidence_positions) == 2
        assert len(restore_positions) == 2
        assert all(evidence < restore for evidence, restore in zip(evidence_positions, restore_positions))
        assert f"handle_failed_verification {env_expression}" in body


def test_failure_evidence_probes_and_logs_are_deadline_bounded() -> None:
    body = _function_body("capture_failure_evidence")
    assert body.count("run_with_deadline") >= 3
    assert "env_to_health_url" in body
    assert "env_to_ready_url" in body
    assert "docker logs --tail 80" in body
    assert "--- evidence: /health ---" in body
    assert "--- evidence: /ready ---" in body
    assert "--- evidence: api container logs ---" in body


def test_do_verify_surfaces_non_gating_readiness_code_and_body(tmp_path: Path) -> None:
    """X-08: emit_verify_ready_diagnostic runs once on terminal failure, never on success."""
    expected = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    success_dir = tmp_path / "success"
    success_dir.mkdir()
    success = _run_do_verify(success_dir, attempts=3, health_sha=expected)
    assert success.returncode == 0, success.stdout + success.stderr
    assert "/ready" not in (success_dir / "curl.log").read_text()

    fail_dir = tmp_path / "fail"
    fail_dir.mkdir()
    failed = _run_do_verify(fail_dir, attempts=3, health_sha="deadbeefdeadbeef")
    assert failed.returncode != 0, failed.stdout + failed.stderr
    curl_log = (fail_dir / "curl.log").read_text()
    assert curl_log.count("/ready") == 1
    assert curl_log.count("/health") == 3


def test_restart_and_rollback_integration_points_are_deadlined() -> None:
    restart = _function_body("do_restart")
    registry = _function_body("restore_registry_env_tag")
    runtime = _function_body("restore_runtime_and_edge")
    assert "run_with_deadline" in _function_body("repair_blob_volume_ownership")
    assert "run_with_deadline" in restart
    assert registry.count("run_with_deadline") >= 2
    assert runtime.count("run_with_deadline") >= 1


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
    orchestrator = _function_body("restore_env_tag_to_rollback")
    body = _function_body("restore_runtime_and_edge")
    assert "assert_rollback_fence" in orchestrator
    assert "restore_registry_env_tag" in orchestrator
    assert "restore_runtime_and_edge" in orchestrator
    assert orchestrator.index("assert_rollback_fence") < orchestrator.index("restore_registry_env_tag")
    assert orchestrator.index("restore_registry_env_tag") < orchestrator.index("restore_runtime_and_edge")
    assert "verify_restored_runtime" in body
    assert "restore_topology_backups" in body
    assert "restore_edge_backups" in body
    assert "abort_cutover_candidate" in body
    assert body.index("restore_topology_backups") < body.index("restore_prior_image_repo_env")
    assert body.index("restore_prior_image_repo_env") < body.index('"rollback systemctl restart')
    assert body.index('"rollback systemctl restart') < body.index("restore_edge_backups")
    assert body.index("restore_edge_backups") < body.index("abort_cutover_candidate")
    assert body.index("verify_restored_runtime") > body.index("abort_cutover_candidate")
    assert 'log "Restored' in orchestrator


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
with_shared_tag_lock() {{ shift; "$@"; }}
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


def test_rollback_push_cas_refuses_generation_changed_after_fence(tmp_path: Path) -> None:
    """R-07: a newer shared-tag mapping between fence and push must not be overwritten."""
    records = tmp_path / "docker-commands"
    rollback = "a" * 64
    candidate = "b" * 64
    newer = "c" * 64
    command = f'''
source "{SCRIPT}"
ACX_ROLLBACK_DIGEST_REF="$IMAGE_BASE@sha256:{rollback}"
ACX_ROLLBACK_IMAGE_BASE="$IMAGE_BASE"
ACX_CANDIDATE_DIGEST_REF="$IMAGE_BASE@sha256:{candidate}"
with_shared_tag_lock() {{ shift; "$@"; }}
_pull_ref_remote() {{ :; }}
restore_runtime_and_edge() {{ return 0; }}
remote_image_digest_ref() {{
  if [[ "$1" == *":dev" ]]; then
    printf 'inspect\\n' >>"{records}.inspects"
    if [[ "$(wc -l < "{records}.inspects")" -eq 1 ]]; then
      printf '%s\\n' "$IMAGE_BASE@sha256:{candidate}"
    else
      printf '%s\\n' "$IMAGE_BASE@sha256:{newer}"
    fi
  else
    printf '%s\\n' "$1"
  fi
}}
remote_docker_with_config() {{ printf '%s\\n' "$*" >>"{records}"; return 0; }}
restore_env_tag_to_rollback dev-fir 0
'''
    result = subprocess.run(["/bin/bash", "-c", command], text=True, capture_output=True, check=False)
    logged = records.read_text() if records.exists() else ""
    combined = result.stdout + result.stderr
    assert result.returncode != 0, combined
    assert "ROLLBACK CAS REFUSED" in result.stderr
    assert "dev-fir" in result.stderr
    assert candidate in result.stderr
    assert newer in result.stderr
    assert "push " not in logged


def test_rollback_push_cas_happy_path_pushes_when_tag_unchanged(tmp_path: Path) -> None:
    """R-07: compare-and-swap must push when the shared env tag is still the planned digest."""
    records = tmp_path / "docker-commands"
    rollback = "a" * 64
    candidate = "b" * 64
    command = f'''
source "{SCRIPT}"
ACX_ROLLBACK_DIGEST_REF="$IMAGE_BASE@sha256:{rollback}"
ACX_ROLLBACK_IMAGE_BASE="$IMAGE_BASE"
ACX_CANDIDATE_DIGEST_REF="$IMAGE_BASE@sha256:{candidate}"
with_shared_tag_lock() {{ shift; "$@"; }}
_pull_ref_remote() {{ :; }}
restore_runtime_and_edge() {{ return 0; }}
remote_image_digest_ref() {{
  if [[ "$1" == *":dev" ]]; then
    printf '%s\\n' "$IMAGE_BASE@sha256:{candidate}"
  else
    printf '%s\\n' "$1"
  fi
}}
remote_docker_with_config() {{ printf '%s\\n' "$*" >>"{records}"; return 0; }}
restore_env_tag_to_rollback dev-fir 0
'''
    result = subprocess.run(["/bin/bash", "-c", command], text=True, capture_output=True, check=False)
    logged = records.read_text() if records.exists() else ""
    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    assert "ROLLBACK CAS REFUSED" not in combined
    assert "tag " in logged
    assert "push " in logged


def test_restore_and_promote_serialize_on_shared_env_tag() -> None:
    """R-07: dev and dev-fir share :dev, so rollback and promote must lock that tag."""
    restore = _function_body("restore_env_tag_to_rollback")
    registry = _function_body("restore_registry_env_tag")
    promote = _function_body("do_push_tag")
    lock = _function_body("with_shared_tag_lock")
    assert "with_shared_tag_lock" in restore
    assert "with_shared_tag_lock" in promote
    assert "flock" in lock
    assert "tag-${tag}.lock" in lock
    assert "remote_image_digest_ref" in registry
    assert restore.index("with_shared_tag_lock") < restore.index("assert_rollback_fence")
    assert registry.index("remote_image_digest_ref") < registry.index("remote_docker_with_config tag")


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
    assert "diagnostic: smoke health OK" in combined
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
    helper = _function_body("handle_failed_verification")
    assert 'capture_failure_evidence "$env" candidate' in helper
    for function_name, env_expression in (("_ship_selected_env", '"$env"'), ("do_promote", '"$to_env"')):
        body = _function_body(function_name)
        assert f"capture_failure_evidence {env_expression} pre_candidate" in body
        assert f'capture_failure_evidence {env_expression} "${{ACX_RESTART_EVIDENCE_PHASE:-pre_candidate}}"' in body
        assert f"handle_failed_verification {env_expression}" in body
        assert f"capture_failure_evidence {env_expression} candidate" not in body
        assert body.count(f"capture_failure_evidence {env_expression} pre_candidate") == 1


def test_run_with_deadline_does_not_dup_stdin_through_fd3() -> None:
    """VLMHEAL-1-REV-B-04: the fd3 dup/close pair is the bash 5.2 segfault shape."""
    source = SCRIPT.read_text()
    start = source.index("run_with_deadline() {")
    end = source.index("validated_deadline() {")
    code = "\n".join(line for line in source[start:end].splitlines() if not line.lstrip().startswith("#"))
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
    """D-02: candidate unit start failure must request post_restart evidence."""
    body = _function_body("do_restart")
    assert 'ACX_RESTART_EVIDENCE_PHASE="pre_candidate"' in body
    assert 'ACX_RESTART_EVIDENCE_PHASE="post_restart"' in body
    assert body.index('ACX_RESTART_EVIDENCE_PHASE="pre_candidate"') < body.index(
        'ACX_RESTART_EVIDENCE_PHASE="post_restart"'
    )
    recreate_at = body.index("recreate_cutover_candidate")
    candidate = _function_body("recreate_cutover_candidate")
    assert body.index('ACX_RESTART_EVIDENCE_PHASE="post_restart"') < recreate_at
    assert "sudo systemctl start" in candidate
    assert recreate_at < body.index("systemctl restart")
    assert body.index("ACX_LIVE_DISRUPTED=1") < body.index("systemctl restart ${unit}")
    assert recreate_at < body.index("ACX_LIVE_DISRUPTED=1")
    assert body.rindex("ACX_LIVE_DISRUPTED=0") > body.index("ACX_LIVE_DISRUPTED=1")


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
                "RECOGNITION_ADMIN_TOKEN=admin-secret HF_TOKEN=hf-secret "
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
    health_body = '{"commit_sha":"' + health_sha + '","status":"ok","image_variant":"recognition"}'
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


@pytest.mark.parametrize("health_code", ["302", "404", "500", "503"])
def test_do_verify_non_2xx_matching_sha_fails_and_probes_ready(tmp_path: Path, health_code: str) -> None:
    """GR-261: matching commit_sha on non-2xx /health must not verify; /ready is non-gating."""
    expected = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    result = _run_do_verify(tmp_path, attempts=1, health_sha=expected, health_code=health_code)
    combined = result.stdout + result.stderr
    assert result.returncode != 0, combined
    assert "Verified:" not in combined
    curl_log = (tmp_path / "curl.log").read_text()
    assert "/health" in curl_log
    assert "/ready" in curl_log
    assert curl_log.count("/ready") == 1


def test_do_verify_non_2xx_matching_sha_retries_then_probes_ready(tmp_path: Path) -> None:
    """GR-261: a baked SHA on HTTP 503 must not skip warm-up retries."""
    expected = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    result = _run_do_verify(tmp_path, attempts=3, health_sha=expected, health_code="503")
    combined = result.stdout + result.stderr
    assert result.returncode != 0, combined
    assert "Verified:" not in combined
    curl_log = (tmp_path / "curl.log").read_text()
    assert curl_log.count("/health") == 3
    assert curl_log.count("/ready") == 1
    assert "non-gating" in combined


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
    """W-02: hunter2 on ssh stderr never reaches the log raw; stdout cid stays usable."""
    result = _run_capture_failure_evidence(
        tmp_path,
        cid_stdout=(VALID_CID + "\n").encode(),
        cid_stderr=b"password=hunter2\n",
    )
    combined = (result.stdout + result.stderr).decode()
    assert result.returncode == 0, combined
    assert "hunter2" not in combined
    assert "[REDACTED]" in combined
    args = (tmp_path / "ssh-args").read_text()
    assert "docker logs" in args
    body = _function_body("capture_failure_evidence")
    cid_idx = body.index("ps -q")
    snippet = body[cid_idx : cid_idx + 160]
    assert "2>&1" not in snippet
    assert '2>"${cid_err}"' in body


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


def test_function_body_does_not_overcapture_boot_smoke() -> None:
    """Slice do_boot_smoke at the next top-level fn, not the next section header."""
    body = _function_body("do_boot_smoke")
    assert "do_boot_smoke() {" in body
    assert "repair_blob_volume_ownership() {" not in body
    assert "do_restart() {" not in body
    assert "capture_failure_evidence() {" not in body
    restart = _function_body("do_restart")
    assert "restore_env_tag_to_rollback() {" not in restart


def test_boot_smoke_deadline_kill_still_emits_health_body(tmp_path: Path) -> None:
    """EXIT trap must print last_health_body even when the outer deadline fires."""
    result = _run_boot_smoke(
        tmp_path,
        budget_s=10,
        poll_s=2,
        attempts=6,
        extra_env={
            "FAKE_HEALTH_CODE": "503",
            "FAKE_HEALTH_BODY": '{"status":"fail","note":"deadline-kill-body","password":"hunter2"}',
        },
        wrap_deadline=2,
    )
    combined = result.stdout + result.stderr
    assert result.returncode != 0
    assert "deadline-kill-body" in combined
    assert "hunter2" not in combined
    assert CRASH_LOG in combined
    assert "smoke container logs unavailable" not in combined


def test_cid_stdout_hex_collects_logs_when_stderr_warns(tmp_path: Path) -> None:
    """Stderr after a valid cid must not skip docker logs."""
    result = _run_capture_failure_evidence(
        tmp_path,
        cid_stdout=(VALID_CID + "\n").encode(),
        cid_stderr=b"WARNING: password=hunter2\n",
    )
    combined = (result.stdout + result.stderr).decode()
    assert result.returncode == 0, combined
    assert "hunter2" not in combined
    assert "unexpected container id output" not in combined
    assert "no api container" not in combined
    args = (tmp_path / "ssh-args").read_text()
    assert "docker logs" in args
    assert VALID_CID in args


def test_do_verify_failure_warn_sanitizes_body(tmp_path: Path) -> None:
    """X-04: do_verify fetch-failure warn must not leak secrets or raw C0 bytes."""
    driver = tmp_path / "verify-fail-driver.sh"
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
  printf '%s' $'password=hunter2\\001'
  return 7
}}
do_verify dev
'''
    )
    result = subprocess.run(
        ["bash", str(driver)],
        capture_output=True,
        check=False,
        env=dict(os.environ),
        cwd=SCRIPT.parents[2],
    )
    combined = result.stdout + result.stderr
    assert result.returncode != 0
    assert b"hunter2" not in combined
    assert b"\x01" not in combined
    assert b"diagnostic:" in combined
    assert b"Health check fetch failed" in combined


def test_verify_restored_runtime_warn_sanitizes_body(tmp_path: Path) -> None:
    """X-04: rollback health warn must not leak secrets or raw C0 bytes."""
    driver = tmp_path / "restore-driver.sh"
    digest = "iad.ocir.io/idu2kqqe2jxy/acx-backend@sha256:" + ("a" * 64)
    driver.write_text(
        f'''
source "{SCRIPT}"
GREEN=; YELLOW=; RED=; RESET=
ACX_VERIFY_ATTEMPTS=1
ACX_VERIFY_SLEEP=0
curl() {{
  printf '%s' $'password=hunter2\\001'
  return 7
}}
verify_running_image_digest() {{ return 1; }}
verify_restored_runtime dev "{digest}"
'''
    )
    result = subprocess.run(
        ["bash", str(driver)],
        capture_output=True,
        check=False,
        env=dict(os.environ),
        cwd=SCRIPT.parents[2],
    )
    combined = result.stdout + result.stderr
    assert result.returncode != 0
    assert b"hunter2" not in combined
    assert b"\x01" not in combined
    assert b"diagnostic:" in combined
    assert b"Rollback health/digest verification failed" in combined


def test_compose_project_dequotes_remote_env_value(tmp_path: Path) -> None:
    """X-05: quoted COMPOSE_PROJECT_NAME must become an unquoted docker ps filter."""
    remote = tmp_path / "opt"
    remote.mkdir()
    (remote / ".env").write_text('COMPOSE_PROJECT_NAME="acx-prod"\n')
    docker_log = tmp_path / "docker.log"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(
        fake_bin / "docker",
        f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >>"{docker_log}"
exit 0
""",
    )
    driver = tmp_path / "compose-driver.sh"
    driver.write_text(
        f'''
source "{SCRIPT}"
GREEN=; YELLOW=; RED=; RESET=
env_to_remote_dir() {{ printf '%s\\n' "{remote}"; }}
run_with_deadline() {{ shift 2; "$@"; }}
ssh() {{
  remote_cmd="${{@: -1}}"
  PATH="{fake_bin}:$PATH" bash -c "$remote_cmd"
}}
capture_failure_evidence dev pre_candidate
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
    assert result.returncode == 0, result.stderr
    logged = docker_log.read_text()
    assert "label=com.docker.compose.project=acx-prod" in logged
    assert 'label=com.docker.compose.project="acx-prod"' not in logged
    assert "label=com.docker.compose.project='acx-prod'" not in logged


def test_do_verify_continues_when_sanitizer_pipeline_fails(tmp_path: Path) -> None:
    """X-06: a failing sanitizer sed must print fallback and not abort verify."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    state = tmp_path / "sed-state"
    state.mkdir()
    _write_executable(
        fake_bin / "sed",
        f"""#!/usr/bin/env bash
if [[ ! -f "{state}/failed" ]]; then
  touch "{state}/failed"
  exit 1
fi
exec /usr/bin/sed "$@"
""",
    )
    expected = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    health_body = '{"commit_sha":"' + expected + '","status":"ok","image_variant":"recognition"}'
    driver = tmp_path / "sed-fail-driver.sh"
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
  url="${{@: -1}}"
  if [[ "$url" == *"/ready"* ]]; then
    printf '%s\\n%s' '{{"ready":true}}' '200'
    return 0
  fi
  printf '%s\\n%s' '{health_body}' '200'
  return 0
}}
do_verify dev
'''
    )
    env = dict(os.environ)
    env["PATH"] = f"{fake_bin}{os.pathsep}{env.get('PATH', '')}"
    result = subprocess.run(
        ["bash", str(driver)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
        cwd=SCRIPT.parents[2],
    )
    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    assert "diagnostic:" in combined
    assert "unavailable" in combined


def _run_do_boot_smoke_wrapper(
    tmp_path: Path,
    *,
    extra_script: str = "",
    unread_fifo: bool = False,
) -> subprocess.CompletedProcess[str]:
    payload = tmp_path / "smoke-wrap"
    ssh_args = tmp_path / "ssh-args"
    image = "iad.ocir.io/idu2kqqe2jxy/acx-backend@sha256:" + ("a" * 64)
    driver = tmp_path / "wrap-driver.sh"
    driver.write_text(
        f'''
source "{SCRIPT}"
GREEN=; YELLOW=; RED=; RESET=
preflight_remote_ocir_auth() {{ return 0; }}
assert_remote_disk_headroom_for_pull() {{ return 0; }}
_pull_ref_remote() {{ return 0; }}
remote_image_digest_ref() {{ printf '%s\\n' "$1"; }}
run_with_deadline() {{
  shift 2
  "$@"
}}
ssh() {{
  printf '%s\\n' "$*" >>"{ssh_args}"
  if [[ "$*" == *"bash -s"* ]]; then
    cat >"{payload}"
  fi
  return 0
}}
{extra_script}
do_boot_smoke dev "{image}"
'''
    )
    env = dict(os.environ)
    if unread_fifo:
        result = _run_bash_with_unread_fifo(driver, tmp_path, env)
    else:
        result = subprocess.run(
            ["bash", str(driver)],
            text=True,
            capture_output=True,
            check=False,
            env=env,
            cwd=SCRIPT.parents[2],
        )
    result._payload = payload  # type: ignore[attr-defined]
    result._ssh_args = ssh_args  # type: ignore[attr-defined]
    return result


def test_do_boot_smoke_wrap_payload_includes_sanitizer_and_parses(tmp_path: Path) -> None:
    """X-07: composed SMOKE_WRAP payload includes sanitizer + set -euo and bash -n."""
    result = _run_do_boot_smoke_wrapper(tmp_path, unread_fifo=True)
    payload = (tmp_path / "smoke-wrap").read_text()
    assert result.returncode == 0, result.stderr
    assert "sanitize_deploy_diagnostic ()" in payload or "sanitize_deploy_diagnostic()" in payload
    assert "set -euo pipefail" in payload
    parsed = subprocess.run(["bash", "-n"], input=payload, text=True, capture_output=True, check=False)
    assert parsed.returncode == 0, parsed.stderr


def test_do_boot_smoke_passes_pg_ready_budget_as_eighth_arg(tmp_path: Path) -> None:
    """LR-04: wrapper bash -s arg list carries pg_ready_budget after dropping attempts."""
    result = _run_do_boot_smoke_wrapper(tmp_path, unread_fifo=True)
    assert result.returncode == 0, result.stderr
    args_text = (tmp_path / "ssh-args").read_text()
    bash_s_line = next(line for line in args_text.splitlines() if "bash -s" in line)
    remote = bash_s_line.split("bash -s", 1)[1].strip()
    wrap_args = remote.split()
    # env image remote_dir timeout poll vlm_budget pg_ready_budget setup_slack
    assert wrap_args[5] == "0"
    assert wrap_args[6] == "30"
    assert wrap_args[7] == "30"
    assert "pgvector/pgvector:pg17" in args_text


def test_boot_smoke_health_loop_uses_full_wall_clock(tmp_path: Path) -> None:
    """SB-01: instant ECONNREFUSED still polls for health_budget minus last-curl guard."""
    budget_s = 24
    poll_s = 2
    trap_docker_s = 10
    health_budget = max(1, budget_s - (trap_docker_s + poll_s))
    started = time.monotonic()
    result = _run_boot_smoke(
        tmp_path,
        budget_s=budget_s,
        poll_s=poll_s,
        attempts=6,
        pg_budget=1,
        extra_env={"FAKE_HEALTH_CODE": "000"},
    )
    elapsed = time.monotonic() - started
    combined = result.stdout + result.stderr
    assert result.returncode != 0, combined
    assert elapsed >= max(0, health_budget - poll_s) - 1
    assert elapsed < budget_s + 4


def test_boot_smoke_pg_wait_is_seconds_bounded(tmp_path: Path) -> None:
    """SB-02: pg ready-wait is SECONDS-bounded, not seq-iteration bounded."""
    started = time.monotonic()
    result = _run_boot_smoke(
        tmp_path,
        budget_s=2,
        poll_s=1,
        attempts=1,
        pg_budget=3,
        extra_env={"FAKE_PG_READY": "0", "FAKE_PG_EXEC_SLEEP": "2"},
    )
    elapsed = time.monotonic() - started
    combined = result.stdout + result.stderr
    assert result.returncode != 0, combined
    assert "postgres failed to become ready" in combined
    assert elapsed >= 2
    assert elapsed < 7


def test_boot_smoke_deadline_reports_phase_unknown(tmp_path: Path) -> None:
    """SB-03: smoke_rc 124 reports composite deadline and phase unknown."""
    image = "iad.ocir.io/idu2kqqe2jxy/acx-backend@sha256:" + ("a" * 64)
    driver = tmp_path / "timeout-driver.sh"
    driver.write_text(
        f'''
source "{SCRIPT}"
GREEN=; YELLOW=; RED=; RESET=
preflight_remote_ocir_auth() {{ return 0; }}
assert_remote_disk_headroom_for_pull() {{ return 0; }}
_pull_ref_remote() {{ return 0; }}
remote_image_digest_ref() {{ printf '%s\\n' "$1"; }}
run_with_deadline() {{
  local label="$2"
  shift 2
  if [[ "$label" == *"health gate"* ]]; then
    "$@" >/dev/null
    return 124
  fi
  "$@" >/dev/null
  return 0
}}
ssh() {{
  if [[ "$*" == *"bash -s"* ]]; then
    cat >/dev/null
  fi
  return 0
}}
do_boot_smoke dev "{image}"
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
    assert result.returncode != 0
    assert "phase unknown" in combined
    assert "composite deadline" in combined
    assert "/health never came up" not in combined


def test_short_hex_container_id_is_rejected(tmp_path: Path) -> None:
    """SB-05: 7-hex stdout is unexpected container id output, not a usable cid."""
    result = _run_capture_failure_evidence(tmp_path, cid_stdout=b"deadbee\n")
    combined = (result.stdout + result.stderr).decode()
    assert result.returncode == 0, combined
    assert "unexpected container id output" in combined
    args = (tmp_path / "ssh-args").read_text()
    assert "docker logs" not in args
    assert "deadbee" not in args


def test_boot_smoke_trap_handles_term_and_int(tmp_path: Path) -> None:
    """GR-37: SIGTERM the smoke process group; trap still rm -f both containers."""
    state, remote, env = _prepare_smoke_env(tmp_path, {"FAKE_HEALTH_CODE": "000"})
    smoke = tmp_path / "boot-smoke.sh"
    smoke.write_text(_boot_smoke_heredoc())
    image = "iad.ocir.io/idu2kqqe2jxy/acx-backend@sha256:" + ("a" * 64)
    proc = subprocess.Popen(
        [
            "bash",
            str(smoke),
            "dev",
            image,
            str(remote),
            "30",
            "2",
            "0",
            "1",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        start_new_session=True,
    )
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if (state / "docker.log").exists() and "run " in (state / "docker.log").read_text():
            break
        if proc.poll() is not None:
            break
        time.sleep(0.05)
    time.sleep(1)
    if proc.poll() is None:
        os.killpg(proc.pid, signal.SIGTERM)
    stdout, stderr = proc.communicate(timeout=10)
    combined = (stdout or "") + (stderr or "")
    assert proc.returncode in (143, 124), combined
    log = (state / "docker.log").read_text()
    assert re.search(r"rm -f acx-smoke-dev-\d+", log), log
    assert re.search(r"rm -f acx-smoke-pg-dev-\d+", log), log


def test_do_boot_smoke_prepull_failure_skips_health_gate(tmp_path: Path) -> None:
    """GR-31 / GR-06: failed pgvector pre-pull must not send the smoke-body payload."""
    extra = """
run_with_deadline() {
  local label="$2"
  shift 2
  if [[ "$label" == *"pgvector pull"* ]]; then
    return 1
  fi
  "$@"
}
"""
    result = _run_do_boot_smoke_wrapper(tmp_path, extra_script=extra, unread_fifo=True)
    combined = result.stdout + result.stderr
    payload = tmp_path / "smoke-wrap"
    ssh_args = (tmp_path / "ssh-args").read_text()
    assert result.returncode == 1, combined
    assert "pre-pull of pgvector/pgvector:pg17 failed" in combined
    assert "will retry" not in combined
    assert "bash -s" not in ssh_args
    assert (not payload.exists()) or payload.read_text() == ""


def test_boot_smoke_pg_run_uses_pull_never(tmp_path: Path) -> None:
    """GR-31: inner pg docker run must not pull; pre-pull is fail-closed."""
    result = _run_boot_smoke(tmp_path, budget_s=2, poll_s=1, pg_budget=1)
    log = _docker_log(result)
    run_lines = [line for line in log.splitlines() if line.startswith("run ")]
    pg_run = next(line for line in run_lines if "pgvector" in line)
    assert "--pull=never" in pg_run


def test_boot_smoke_trap_still_rms_when_logs_hang(tmp_path: Path) -> None:
    """GR-32 / GR-04: timeout-bounded logs must not skip rm/volume cleanup."""
    result = _run_boot_smoke(
        tmp_path,
        budget_s=2,
        poll_s=1,
        pg_budget=1,
        extra_env={"FAKE_LOGS_SLEEP": "5", "FAKE_HEALTH_CODE": "000"},
        # GR-262: outer KILL grace is 1s; timeout -k 1 on logs needs wrap > health+2+1.
        wrap_deadline=12,
    )
    log = _docker_log(result)
    assert re.search(r"rm -f acx-smoke-dev-\d+", log), log
    assert re.search(r"rm -f acx-smoke-pg-dev-\d+", log), log
    assert "volume rm -f" in log
    assert result.returncode != 0


def test_boot_smoke_pg_exec_per_call_timeout(tmp_path: Path) -> None:
    """GR-33 / GR-04: hung pg_isready must not consume the whole pg budget twice."""
    started = time.monotonic()
    result = _run_boot_smoke(
        tmp_path,
        budget_s=2,
        poll_s=1,
        pg_budget=3,
        extra_env={"FAKE_PG_READY": "0", "FAKE_PG_EXEC_SLEEP": "30"},
    )
    elapsed = time.monotonic() - started
    combined = result.stdout + result.stderr
    assert result.returncode != 0, combined
    assert "postgres failed to become ready" in combined
    assert elapsed < 2 * 3
    log = _docker_log(result)
    assert re.search(r"rm -f acx-smoke-pg-dev-\d+", log), log


def test_boot_smoke_port_timeout_fails_setup_explicitly(tmp_path: Path) -> None:
    """GR-39: hung docker port must fail with 'smoke setup timed out' and still clean up."""
    result = _run_boot_smoke(
        tmp_path,
        budget_s=2,
        poll_s=1,
        pg_budget=1,
        extra_env={"FAKE_PORT_SLEEP": "10"},
    )
    combined = result.stdout + result.stderr
    assert result.returncode != 0, combined
    assert "smoke setup timed out" in combined
    log = _docker_log(result)
    assert re.search(r"rm -f acx-smoke-dev-\d+", log), log
    assert re.search(r"rm -f acx-smoke-pg-dev-\d+", log), log


def test_boot_smoke_removes_network_only_on_failure(tmp_path: Path) -> None:
    """GR-34: trap removes a smoke-created network on failure, not on success."""
    fail_dir = tmp_path / "fail"
    fail_dir.mkdir()
    fail = _run_boot_smoke(
        fail_dir,
        budget_s=2,
        poll_s=1,
        pg_budget=1,
        extra_env={"FAKE_NET_EXISTS": "0", "FAKE_HEALTH_CODE": "000"},
    )
    fail_log = _docker_log(fail)
    assert "network create" in fail_log
    assert "network rm" in fail_log
    create_at = fail_log.index("network create")
    rm_at = fail_log.index("network rm")
    assert create_at < rm_at

    ok_dir = tmp_path / "ok"
    ok_dir.mkdir()
    ok = _run_boot_smoke(
        ok_dir,
        budget_s=2,
        poll_s=1,
        pg_budget=1,
        extra_env={"FAKE_NET_EXISTS": "0", "FAKE_HEALTH_CODE": "200"},
    )
    ok_log = _docker_log(ok)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    assert "network create" in ok_log
    assert "network rm" not in ok_log


def test_cid_capture_uses_last_64_hex_line(tmp_path: Path) -> None:
    """GR-35 / GR-36: last 64-hex wins; trim; lowercase; reject short hex."""
    cid = "a" * 64
    fixtures = [
        f"WARNING: x\ncafebabeface\n{cid}\n".encode(),
        f"1700000000000\n{cid}\n".encode(),
        f"{cid} \n".encode(),
        f"{'A' * 64}\n".encode(),
    ]
    for stdout in fixtures:
        case_dir = tmp_path / str(abs(hash(stdout)))
        case_dir.mkdir()
        result = _run_capture_failure_evidence(case_dir, cid_stdout=stdout)
        combined = (result.stdout + result.stderr).decode()
        assert result.returncode == 0, combined
        args = (case_dir / "ssh-args").read_text()
        assert f"docker logs --tail 80 {cid}" in args, args


def test_boot_smoke_last_curl_does_not_eat_diag_reserve(tmp_path: Path) -> None:
    """GR-05: do not start a health curl that would overrun the diag reserve."""
    poll_s = 2
    budget_s = 16  # health_budget = 16 - 12 = 4; second curl would eat the reserve
    started = time.monotonic()
    result = _run_boot_smoke(
        tmp_path,
        budget_s=budget_s,
        poll_s=poll_s,
        pg_budget=1,
        extra_env={"FAKE_HEALTH_CODE": "000", "FAKE_HEALTH_SLEEP": str(poll_s)},
    )
    elapsed = time.monotonic() - started
    combined = result.stdout + result.stderr
    assert result.returncode != 0, combined
    assert "smoke container logs" in combined
    # One curl of poll_s plus setup/trap, not a second curl of poll_s.
    assert elapsed < (poll_s * 2) + 2


def test_emit_sanitized_evidence_survives_sed_failure(tmp_path: Path) -> None:
    """GR-03: a failing sanitizer pipeline must not abort emit_sanitized_evidence."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    state = tmp_path / "sed-state"
    state.mkdir()
    _write_executable(
        fake_bin / "sed",
        f"""#!/usr/bin/env bash
if [[ ! -f "{state}/failed" ]]; then
  touch "{state}/failed"
  exit 1
fi
exec /usr/bin/sed "$@"
""",
    )
    driver = tmp_path / "emit-driver.sh"
    driver.write_text(
        f'''
source "{SCRIPT}"
GREEN=; YELLOW=; RED=; RESET=
emit_sanitized_evidence "password=hunter2"
'''
    )
    env = dict(os.environ)
    env["PATH"] = f"{fake_bin}{os.pathsep}{env.get('PATH', '')}"
    result = subprocess.run(
        ["bash", str(driver)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
        cwd=SCRIPT.parents[2],
    )
    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    assert "unavailable" in combined
    assert "hunter2" not in combined


def test_do_boot_smoke_import_and_prepull_ssh_use_n_flag(tmp_path: Path) -> None:
    """LR-03: import-gate and pre-pull ssh must pass -n so they cannot eat stdin."""
    result = _run_do_boot_smoke_wrapper(tmp_path, unread_fifo=True)
    assert result.returncode == 0, result.stderr
    lines = (tmp_path / "ssh-args").read_text().splitlines()
    non_payload = [line for line in lines if "bash -s" not in line]
    assert non_payload, lines
    for line in non_payload:
        assert " -n " in f" {line} " or line.split()[0:2] == ["-n"] or "-n" in line.split()


def _curl_max_times(result: subprocess.CompletedProcess[str]) -> list[int]:
    state = Path(result._fake_state)  # type: ignore[attr-defined]
    log = state.joinpath("curl.log")
    if not log.exists():
        return []
    values: list[int] = []
    for line in log.read_text().splitlines():
        parts = line.split()
        for i, part in enumerate(parts):
            if part == "--max-time" and i + 1 < len(parts):
                values.append(int(parts[i + 1]))
    return values


def test_boot_smoke_composite_deadline_covers_inner_caps(tmp_path: Path) -> None:
    """H2E-01: outer deadline must not fire before an explicit inner failure."""
    setup_slack = 1
    pg_ready = 1
    smoke_timeout = 2
    poll_interval = 2
    net_create_cap = 10
    port_cap = 5
    trap_docker_s = 10
    margin = 5
    inner_sum = (
        net_create_cap + setup_slack + pg_ready + setup_slack + port_cap + smoke_timeout + trap_docker_s + poll_interval
    )
    expected_deadline = inner_sum + margin
    old_composite = pg_ready + smoke_timeout + setup_slack
    fake_sleep = old_composite + 2
    image = "iad.ocir.io/idu2kqqe2jxy/acx-backend@sha256:" + ("a" * 64)
    driver = tmp_path / "composite-driver.sh"
    driver.write_text(
        f'''
source "{SCRIPT}"
GREEN=; YELLOW=; RED=; RESET=
SMOKE_SETUP_SLACK={setup_slack}
SMOKE_PG_READY_TIMEOUT={pg_ready}
ACX_SMOKE_TIMEOUT={smoke_timeout}
preflight_remote_ocir_auth() {{ return 0; }}
assert_remote_disk_headroom_for_pull() {{ return 0; }}
_pull_ref_remote() {{ return 0; }}
remote_image_digest_ref() {{ printf '%s\\n' "$1"; }}
eval "$(declare -f run_with_deadline | sed '1s/run_with_deadline/run_with_deadline_impl/')"
run_with_deadline() {{
  local deadline="$1" label="$2"
  if [[ "$label" == *"health gate"* ]]; then
    printf 'CAPTURED_COMPOSITE_DEADLINE=%s\\n' "$deadline" >&2
  fi
  run_with_deadline_impl "$@"
}}
ssh() {{
  if [[ "$*" == *"bash -s"* ]]; then
    cat >/dev/null
    sleep {fake_sleep}
    echo "smoke setup timed out" >&2
    return 1
  fi
  return 0
}}
do_boot_smoke dev "{image}"
'''
    )
    result = subprocess.run(
        ["bash", str(driver)],
        text=True,
        capture_output=True,
        check=False,
        env=dict(os.environ),
        cwd=SCRIPT.parents[2],
        timeout=expected_deadline + 10,
    )
    combined = result.stdout + result.stderr
    captured = re.search(r"CAPTURED_COMPOSITE_DEADLINE=(\d+)", combined)
    assert captured, combined
    assert int(captured.group(1)) >= expected_deadline, combined
    assert result.returncode != 124, combined
    assert "smoke setup timed out" in combined, combined
    assert "phase unknown" not in combined, combined


def test_boot_smoke_composite_deadline_covers_trap_kill_grace(tmp_path: Path) -> None:
    """GR-262: hung docker ignoring TERM lasts timeout+1s; 6 trap ops plus setup grace."""
    setup_slack = 1
    pg_ready = 1
    smoke_timeout = 2
    poll_interval = 2
    net_create_cap = 10
    port_cap = 5
    kill_grace = 1
    trap_op_s = 2
    trap_op_count = 6  # logs, rm api, rm pg, volume, inspect, network rm
    margin = 5
    trap_wall = trap_op_count * (trap_op_s + kill_grace)
    setup_kill_grace = 4 * kill_grace
    expected_deadline = (
        net_create_cap
        + setup_slack
        + pg_ready
        + setup_slack
        + port_cap
        + smoke_timeout
        + trap_wall
        + poll_interval
        + margin
        + setup_kill_grace
    )
    image = "iad.ocir.io/idu2kqqe2jxy/acx-backend@sha256:" + ("a" * 64)
    driver = tmp_path / "kill-grace-driver.sh"
    driver.write_text(
        f'''
source "{SCRIPT}"
GREEN=; YELLOW=; RED=; RESET=
SMOKE_SETUP_SLACK={setup_slack}
SMOKE_PG_READY_TIMEOUT={pg_ready}
ACX_SMOKE_TIMEOUT={smoke_timeout}
preflight_remote_ocir_auth() {{ return 0; }}
assert_remote_disk_headroom_for_pull() {{ return 0; }}
_pull_ref_remote() {{ return 0; }}
remote_image_digest_ref() {{ printf '%s\\n' "$1"; }}
eval "$(declare -f run_with_deadline | sed '1s/run_with_deadline/run_with_deadline_impl/')"
run_with_deadline() {{
  local deadline="$1" label="$2"
  if [[ "$label" == *"health gate"* ]]; then
    printf 'CAPTURED_COMPOSITE_DEADLINE=%s\\n' "$deadline" >&2
  fi
  run_with_deadline_impl "$@"
}}
ssh() {{
  if [[ "$*" == *"bash -s"* ]]; then
    cat >/dev/null
    return 1
  fi
  return 0
}}
do_boot_smoke dev "{image}"
'''
    )
    result = subprocess.run(
        ["bash", str(driver)],
        text=True,
        capture_output=True,
        check=False,
        env=dict(os.environ),
        cwd=SCRIPT.parents[2],
        timeout=30,
    )
    combined = result.stdout + result.stderr
    captured = re.search(r"CAPTURED_COMPOSITE_DEADLINE=(\d+)", combined)
    assert captured, combined
    assert int(captured.group(1)) >= expected_deadline, (
        f"composite {captured.group(1)} < hung-daemon budget {expected_deadline}: {combined}"
    )


def test_boot_smoke_owned_net_rm_on_create_timeout(tmp_path: Path) -> None:
    """GR-81 / A10: timed-out network create still rms a net labeled with this run's nonce."""
    result = _run_boot_smoke(
        tmp_path,
        budget_s=2,
        poll_s=1,
        pg_budget=1,
        extra_env={
            "FAKE_NET_EXISTS": "0",
            "FAKE_NET_CREATE_SLEEP": "12",
            "FAKE_HEALTH_CODE": "000",
        },
    )
    combined = result.stdout + result.stderr
    log = _docker_log(result)
    assert result.returncode != 0, combined
    assert "network create" in log, log
    assert "acx.smoke.owner=" in log, log
    assert "network rm acx-dev-net" in log, log
    state = Path(result._fake_state)  # type: ignore[attr-defined]
    assert (state / "network_rm").read_text().strip() == "acx-dev-net"


def test_boot_smoke_foreign_net_not_removed(tmp_path: Path) -> None:
    """GR-81: trap must not rm a net whose ownership label is absent or foreign."""
    result = _run_boot_smoke(
        tmp_path,
        budget_s=2,
        poll_s=1,
        pg_budget=1,
        extra_env={
            "FAKE_NET_EXISTS": "1",
            "FAKE_NET_OWNER": "compose-owned",
            "FAKE_HEALTH_CODE": "000",
        },
    )
    combined = result.stdout + result.stderr
    log = _docker_log(result)
    assert result.returncode != 0, combined
    assert "network rm" not in log, log
    state = Path(result._fake_state)  # type: ignore[attr-defined]
    assert not (state / "network_rm").exists()


def test_boot_smoke_first_probe_max_time_capped_by_remaining(tmp_path: Path) -> None:
    """GR-82 / A5: first health curl --max-time is remaining budget, not a full poll_s."""
    budget_s = 5
    poll_s = 2
    trap_docker_s = 10
    health_budget = max(1, budget_s - (trap_docker_s + poll_s))
    started = time.monotonic()
    result = _run_boot_smoke(
        tmp_path,
        budget_s=budget_s,
        poll_s=poll_s,
        pg_budget=1,
        extra_env={"FAKE_HEALTH_CODE": "000", "FAKE_HEALTH_SLEEP": str(poll_s)},
    )
    elapsed = time.monotonic() - started
    combined = result.stdout + result.stderr
    assert result.returncode != 0, combined
    max_times = _curl_max_times(result)
    assert max_times, combined
    assert all(mt <= health_budget for mt in max_times), max_times
    assert elapsed < budget_s + 4


def test_boot_smoke_timeout_fallback_bounds_logs_then_rms(tmp_path: Path) -> None:
    """GR-83 / A13: without GNU timeout, hung logs must not delay rm past the 2s bound."""
    result = _run_boot_smoke(
        tmp_path,
        budget_s=2,
        poll_s=1,
        pg_budget=1,
        extra_env={"FAKE_LOGS_SLEEP": "5", "FAKE_HEALTH_CODE": "000"},
        hide_timeout=True,
    )
    combined = result.stdout + result.stderr
    log = _docker_log(result)
    state = Path(result._fake_state)  # type: ignore[attr-defined]
    assert result.returncode != 0, combined
    assert re.search(r"rm -f acx-smoke-dev-\d+", log), log
    logs_started = float((state / "logs_started").read_text().strip())
    first_rm = float((state / "first_rm").read_text().strip())
    assert first_rm - logs_started < 2.8, first_rm - logs_started
    logs_at = log.index("logs ")
    rm_at = log.index("rm -f")
    assert logs_at < rm_at, log


def test_boot_smoke_logs_still_emitted_after_bounded_cleanup(tmp_path: Path) -> None:
    """GR-83: a normal logs stub's output still appears in stderr after cleanup."""
    result = _run_boot_smoke(
        tmp_path,
        budget_s=2,
        poll_s=1,
        pg_budget=1,
        hide_timeout=True,
    )
    combined = result.stdout + result.stderr
    log = _docker_log(result)
    assert result.returncode != 0, combined
    assert CRASH_LOG in combined
    assert "smoke container logs unavailable" not in combined
    assert log.index("logs ") < log.index("rm -f"), log


def test_boot_smoke_invalid_setup_slack_fails_closed(tmp_path: Path) -> None:
    """GR-84: $8=abc fails with smoke setup_slack invalid (rc 2) before any docker call."""
    result = _run_boot_smoke(
        tmp_path,
        budget_s=2,
        poll_s=1,
        pg_budget=1,
        setup_slack="abc",
        extra_env={"FAKE_HEALTH_CODE": "200"},
    )
    combined = result.stdout + result.stderr
    assert result.returncode == 2, combined
    assert "smoke setup_slack invalid" in combined, combined
    state = Path(result._fake_state)  # type: ignore[attr-defined]
    docker_log = state / "docker.log"
    assert (not docker_log.exists()) or docker_log.read_text() == ""


def test_boot_smoke_vlm_flag_zero_is_not_a_budget(tmp_path: Path) -> None:
    """GR-84: $6 is the vlm flag (0/1), not a positive-integer budget."""
    result = _run_boot_smoke(
        tmp_path,
        budget_s=2,
        poll_s=1,
        pg_budget=1,
        vlm_budget=0,
        extra_env={"FAKE_HEALTH_CODE": "200"},
    )
    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    assert "invalid" not in combined


def test_boot_smoke_health_302_is_not_success(tmp_path: Path) -> None:
    """VLMHEA-L-06: 3xx must not set smoke_passed; stderr names the code."""
    result = _run_boot_smoke(
        tmp_path,
        budget_s=2,
        poll_s=1,
        pg_budget=1,
        extra_env={"FAKE_HEALTH_CODE": "302", "FAKE_HEALTH_BODY": '{"status":"redir"}'},
    )
    combined = result.stdout + result.stderr
    assert result.returncode != 0, combined
    assert "smoke health OK" not in combined, combined
    assert "302" in combined, combined


def test_boot_smoke_trap_cleans_up_when_stderr_closed(tmp_path: Path) -> None:
    """S3B-01: EXIT trap still rm/volume/network when stderr is EPIPE under set -e."""
    result = _run_boot_smoke(
        tmp_path,
        budget_s=2,
        poll_s=1,
        pg_budget=1,
        extra_env={"FAKE_HEALTH_CODE": "000", "FAKE_NET_EXISTS": "0"},
        close_stderr=True,
    )
    log = _docker_log(result)
    assert re.search(r"rm -f acx-smoke-dev-\d+", log), log
    assert "volume rm -f" in log, log
    assert "network rm" in log, log


def test_boot_smoke_empty_docker_port_fails_setup(tmp_path: Path) -> None:
    """S3B-02: empty `docker port` must not curl :80; fail setup and still collect logs."""
    result = _run_boot_smoke(
        tmp_path,
        budget_s=2,
        poll_s=1,
        pg_budget=1,
        extra_env={"FAKE_PORT_EMPTY": "1", "FAKE_HEALTH_CODE": "200"},
    )
    combined = result.stdout + result.stderr
    state = Path(result._fake_state)  # type: ignore[attr-defined]
    curl_path = state / "curl.log"
    curl_text = curl_path.read_text() if curl_path.exists() else ""
    log = _docker_log(result)
    assert result.returncode != 0, combined
    assert "smoke setup failed: no published port" in combined, combined
    assert "logs --tail" in log, log
    assert "127.0.0.1:/health" not in curl_text, curl_text
    assert re.search(r"rm -f acx-smoke-dev-\d+", log), log


def _run_verify_optional_after_verify_failure(
    tmp_path: Path,
    *,
    invoke: str,
    rollback_rc: int,
    restart_failure_phase: str | None = None,
    live_disrupted: int = 0,
    traffic_flipped: int = 0,
) -> subprocess.CompletedProcess[str]:
    """Source recognition-service.sh and reach the post-verify rollback branch."""
    fail_log = tmp_path / "fail.log"
    driver = tmp_path / "verify-optional-driver.sh"
    driver.write_text(
        f'''
source "{SCRIPT}"
GREEN=; YELLOW=; RED=; RESET=
ACX_VERIFY_OPTIONAL=1
init_deploy_ocir_docker_config() {{ return 0; }}
preflight_ssh() {{ return 0; }}
preflight_remote_face_pipeline_models() {{ return 0; }}
preflight_git_clean() {{ return 0; }}
preflight_branch_synced() {{ return 0; }}
preflight_remote_ocir_auth() {{ return 0; }}
preflight_remote_docker() {{ return 0; }}
preflight_docker() {{ return 0; }}
preflight_ocir_auth() {{ return 0; }}
assert_remote_disk_headroom_for_pull() {{ return 0; }}
preserve_rollback_tag() {{ return 0; }}
do_build() {{ return 0; }}
do_build_remote() {{ return 0; }}
do_push_sha() {{ return 0; }}
do_push_tag() {{ return 0; }}
do_restart() {{
  ACX_RESTART_EVIDENCE_PHASE={restart_failure_phase or "pre_candidate"}
  ACX_LIVE_DISRUPTED={live_disrupted}
  ACX_TRAFFIC_FLIPPED={traffic_flipped}
  return {1 if restart_failure_phase else 0}
}}
promote_gate() {{ return 0; }}
_pull_ref() {{ return 0; }}
image_digest_ref() {{
  printf '%s\\n' "$IMAGE_BASE@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
}}
do_verify() {{ return 1; }}
capture_failure_evidence() {{ return 0; }}
restore_env_tag_to_rollback() {{ printf 'rollback-runtime=%s\\n' "$2"; return {rollback_rc}; }}
fail() {{
  printf 'xx %s\\n' "$*" >&2
  printf '%s\\n' "$*" >>"{fail_log}"
  exit 1
}}
{invoke}
'''
    )
    return subprocess.run(
        ["bash", str(driver)],
        text=True,
        capture_output=True,
        check=False,
        env=dict(os.environ),
        cwd=SCRIPT.parents[2],
        timeout=30,
    )


@pytest.mark.parametrize("invoke", ["do_deploy dev", "do_promote dev prod"])
@pytest.mark.parametrize(
    "phase,live_disrupted,traffic_flipped,runtime",
    [
        ("pre_candidate", 0, 0, "0"),
        ("post_restart", 0, 0, "0"),
        ("post_restart", 1, 0, "1"),
        ("post_restart", 0, 1, "1"),
    ],
)
def test_restart_failure_recovers_runtime_only_after_live_disruption(
    tmp_path, monkeypatch, invoke, phase, live_disrupted, traffic_flipped, runtime
):
    monkeypatch.setenv("CONFIRM", "PROMOTE")
    result = _run_verify_optional_after_verify_failure(
        tmp_path,
        invoke=invoke,
        rollback_rc=0,
        restart_failure_phase=phase,
        live_disrupted=live_disrupted,
        traffic_flipped=traffic_flipped,
    )
    assert result.returncode != 0
    assert f"rollback-runtime={runtime}" in result.stdout, result.stdout + result.stderr


@pytest.mark.parametrize(
    "invoke",
    ("do_deploy dev", "do_promote dev staging"),
    ids=("do_deploy", "do_promote"),
)
def test_acx_verify_optional_fails_closed_when_rollback_fails(tmp_path: Path, invoke: str) -> None:
    """VLMHEAL-1-HARM-01: ACX_VERIFY_OPTIONAL=1 must not exit 0 after a failed rollback."""
    result = _run_verify_optional_after_verify_failure(tmp_path, invoke=invoke, rollback_rc=1)
    combined = result.stdout + result.stderr
    assert result.returncode != 0, combined
    assert "rollback failed" in combined, combined
    assert "previous image restored" not in combined, combined


@pytest.mark.parametrize(
    "invoke",
    ("do_deploy dev", "do_promote dev staging"),
    ids=("do_deploy", "do_promote"),
)
def test_acx_verify_optional_downgrades_when_rollback_succeeds(tmp_path: Path, invoke: str) -> None:
    """VLMHEAL-1-HARM-01: a verified rollback may still warn-and-exit-0 under ACX_VERIFY_OPTIONAL=1."""
    result = _run_verify_optional_after_verify_failure(tmp_path, invoke=invoke, rollback_rc=0)
    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    assert "previous image restored" in combined, combined
    assert not (tmp_path / "fail.log").exists()


def _run_actual_restart_failure_transaction(
    tmp_path: Path,
    *,
    invoke: str,
    runtime_mode: str = "candidate",
    health_code: str = "200",
    fail_at: str = "next_start",
) -> subprocess.CompletedProcess[str]:
    """Run a real deploy/promote restart failure through fake SSH and Docker."""
    state = tmp_path / "rollback-state"
    state.mkdir()
    fake_bin = tmp_path / "rollback-bin"
    fake_bin.mkdir()
    base = "iad.ocir.io/idu2kqqe2jxy/acx-backend"
    env_name = "staging" if "staging" in invoke else "dev"
    project = "acx-" + env_name
    rollback_digest = base + "@sha256:" + ("a" * 64)
    candidate_digest = base + "@sha256:" + ("b" * 64)
    rollback_id = "sha256:" + ("1" * 64)
    candidate_id = "sha256:" + ("2" * 64)
    candidate_commit = subprocess.check_output(
        ["git", "-C", str(SCRIPT.parents[2]), "rev-parse", "HEAD"], text=True
    ).strip()
    prior_cid = "5" * 64
    stopped_cid = "3" * 64
    rollback_cid = "4" * 64
    remote_dir = state / "remote"
    remote_dir.mkdir()
    (remote_dir / "docker-compose.cutover.yml").write_text("# fake cutover compose\n")
    if invoke.startswith("do_rollback"):
        (state / "prior-stopped").write_text("")
    else:
        (state / "running-cid").write_text(prior_cid + "\n")

    docker = r"""#!/usr/bin/env bash
set -euo pipefail
state="${FAKE_ROLLBACK_STATE:?}"
base="__BASE__"
env_tag="__ENV_TAG__"
project="__PROJECT__"
runtime_mode="__RUNTIME_MODE__"
rollback_digest="__ROLLBACK_DIGEST__"
candidate_digest="__CANDIDATE_DIGEST__"
rollback_id="__ROLLBACK_ID__"
candidate_id="__CANDIDATE_ID__"
candidate_commit="__CANDIDATE_COMMIT__"
stopped_cid="__STOPPED_CID__"
rollback_cid="__ROLLBACK_CID__"
prior_cid="__PRIOR_CID__"
wrong_id="sha256:3333333333333333333333333333333333333333333333333333333333333333"
printf '%s\n' "$*" >>"${state}/docker.log"

if [[ "${1:-}" == "compose" ]]; then
  ps=0
  all=0
  compose_project="$project"
  prev=""
  for arg in "$@"; do
    [[ "$arg" == "ps" ]] && ps=1
    [[ "$arg" == "-a" || "$arg" == "-aq" || "$arg" == "--all" ]] && all=1
    if [[ "$prev" == "-p" || "$prev" == "--project-name" ]]; then
      compose_project="$arg"
    fi
    prev="$arg"
  done
  next_project="${project}-next"
  if (( ps )); then
    if [[ "$compose_project" == "$next_project" ]]; then
      if (( all )); then
        [[ "$runtime_mode" == "unknown" ]] && exit 1
        if [[ -f "${state}/candidate-stopped" || -f "${state}/next-running-cid" ]]; then
          printf '%s\n' "$stopped_cid"
        fi
      elif [[ -f "${state}/next-running-cid" ]]; then
        cat "${state}/next-running-cid"
      fi
      exit 0
    fi
    if (( all )); then
      [[ "$runtime_mode" == "unknown" ]] && exit 1
      if [[ -f "${state}/prior-stopped" ]]; then
        printf '%s\n' "$prior_cid"
      fi
    elif [[ -f "${state}/running-cid" ]]; then
      cat "${state}/running-cid"
    fi
    exit 0
  fi
  exit 0
fi

if [[ "${1:-}" == "exec" ]]; then
  if [[ "$*" == *"urllib.request"* ]]; then
    printf '{"commit_sha":"%s","status":"ok"}\n' "$candidate_commit"
  fi
  exit 0
fi

if [[ "${1:-}" == "inspect" || ( "${1:-}" == "image" && "${2:-}" == "inspect" ) ]]; then
  format=""
  previous=""
  for arg in "$@"; do
    if [[ "$previous" == "--format" ]]; then
      format="$arg"
    fi
    previous="$arg"
  done
  target="${@: -1}"
  if [[ "$format" == *"RepoDigests"* ]]; then
    case "$target" in
      "$base:rollback-"*) printf '%s\n' "$rollback_digest" ;;
      "$base:$env_tag") printf '%s\n' "$candidate_digest" ;;
      "$candidate_digest") printf '%s\n' "$candidate_digest" ;;
      "$rollback_digest") printf '%s\n' "$rollback_digest" ;;
      *) printf '%s\n' "$target" ;;
    esac
    exit 0
  fi
  if [[ "$format" == *"State.Status"* && "$format" == *"Config.Labels"* ]]; then
    next_project="${project}-next"
    if [[ "$target" == "$prior_cid" ]]; then
      prior_state="running"
      [[ -f "${state}/prior-stopped" ]] && prior_state="exited"
      printf 'RUNTIME|%s|%s|%s|%s|api|prior-generation\n' "$prior_cid" "$rollback_id" "$prior_state" "$project"
    elif [[ "$target" == "$stopped_cid" ]]; then
      stopped_image_id="$candidate_id"
      [[ "$runtime_mode" == "wrong" ]] && stopped_image_id="$wrong_id"
      if [[ -f "${state}/next-running-cid" && ! -f "${state}/candidate-stopped" ]]; then
        printf 'RUNTIME|%s|%s|running|%s|api|candidate-generation\n' "$stopped_cid" "$stopped_image_id" "$next_project"
      else
        printf 'RUNTIME|%s|%s|exited|%s|api|candidate-generation\n' "$stopped_cid" "$stopped_image_id" "$next_project"
      fi
    elif [[ "$target" == "$rollback_cid" ]]; then
      printf 'RUNTIME|%s|%s|running|%s|api|rollback-generation\n' "$rollback_cid" "$rollback_id" "$project"
    else
      exit 1
    fi
    exit 0
  fi
  if [[ "$format" == *"State.Status"* ]]; then
    [[ "$target" == "$prior_cid" && -f "${state}/prior-stopped" ]] && printf '%s\n' exited
    [[ "$target" == "$stopped_cid" ]] && printf '%s\n' exited
    [[ "$target" == "$rollback_cid" ]] && printf '%s\n' running
    exit 0
  fi
  if [[ "$format" == *".Image"* ]]; then
    [[ "$target" == "$prior_cid" ]] && printf '%s\n' "$rollback_id"
    [[ "$target" == "$stopped_cid" ]] && printf '%s\n' "$candidate_id"
    [[ "$target" == "$rollback_cid" ]] && printf '%s\n' "$rollback_id"
    exit 0
  fi
  if [[ "$format" == *".Id"* ]]; then
    case "$target" in
      "$rollback_digest") printf '%s\n' "$rollback_id" ;;
      "$candidate_digest") printf '%s\n' "$candidate_id" ;;
      *) printf '%s\n' "$target" ;;
    esac
    exit 0
  fi
fi

case "${1:-}" in
  pull)
    exit 0
    ;;
  tag)
    exit 0
    ;;
  push)
    if [[ "${2:-}" == "$base:$env_tag" ]]; then
      : >"${state}/rollback-pushed"
    fi
    exit 0
    ;;
  *)
    exit 0
    ;;
esac
"""
    docker = (
        docker.replace("__BASE__", base)
        .replace("__ENV_TAG__", env_name)
        .replace("__PROJECT__", project)
        .replace("__RUNTIME_MODE__", runtime_mode)
        .replace("__ROLLBACK_DIGEST__", rollback_digest)
        .replace("__CANDIDATE_DIGEST__", candidate_digest)
        .replace("__ROLLBACK_ID__", rollback_id)
        .replace("__CANDIDATE_ID__", candidate_id)
        .replace("__CANDIDATE_COMMIT__", candidate_commit)
        .replace("__STOPPED_CID__", stopped_cid)
        .replace("__ROLLBACK_CID__", rollback_cid)
        .replace("__PRIOR_CID__", prior_cid)
    )
    _write_executable(fake_bin / "docker", docker)

    ssh = (
        r"""#!/usr/bin/env bash
set -euo pipefail
state="${FAKE_ROLLBACK_STATE:?}"
runtime_mode="__RUNTIME_MODE__"
fail_at="__FAIL_AT__"
stopped_cid="__STOPPED_CID__"
cat >/dev/null || true
remote="${@: -1}"
printf '%s\n' "$remote" >>"${state}/ssh.log"
if [[ "$remote" == *"cutover-inflight"* ]]; then
  if [[ -f "${state}/cutover-inflight" ]]; then
    cat "${state}/cutover-inflight"
    exit 0
  fi
  exit 1
fi
if [[ "$remote" == *"flock"* || "$remote" == *"/locks/tag-"* ]]; then
  printf 'LOCKED\n'
  exit 0
fi
if [[ "$remote" == *"systemctl start"* && "$remote" == *"-next"* ]]; then
  if [[ "$fail_at" == "next_start" ]]; then
    if [[ "$runtime_mode" == "prior" ]]; then
      : >"${state}/prior-stopped"
    elif [[ "$runtime_mode" == "candidate" || "$runtime_mode" == "wrong" ]]; then
      : >"${state}/candidate-stopped"
    fi
    exit 1
  fi
  if [[ "$remote" == *"docker compose"* && "$remote" == *"rm -fs api"* ]]; then
    : >"${state}/candidate-recreated"
  fi
  printf '%s\n' "$stopped_cid" >"${state}/next-running-cid"
  exit 0
fi
if [[ "$remote" == *"systemctl restart"* ]]; then
  if [[ -f "${state}/rollback-pushed" ]]; then
    printf '%s\n' "__ROLLBACK_CID__" >"${state}/running-cid"
    exit 0
  fi
  if [[ "$fail_at" == "canonical_health" ]]; then
    printf '%s\n' "$stopped_cid" >"${state}/running-cid"
    exit 0
  fi
  if [[ "$fail_at" == "live_restart" ]]; then
    rm -f "${state}/running-cid"
    if [[ "$runtime_mode" == "absent" || "$runtime_mode" == "unknown" ]]; then
      rm -f "${state}/next-running-cid"
    fi
    exit 1
  fi
  rm -f "${state}/running-cid"
  if [[ "$runtime_mode" == "prior" ]]; then
    : >"${state}/prior-stopped"
  elif [[ "$runtime_mode" == "candidate" || "$runtime_mode" == "wrong" ]]; then
    : >"${state}/candidate-stopped"
  fi
  exit 1
fi
remote="${remote//\/opt\/acx-backend\/dev/${state}/remote}"
remote="${remote//\/opt\/acx-backend\/staging/${state}/remote}"
remote="${remote//\/opt\/acx-backend\/prod/${state}/remote}"
# Edge/topology sudo scripts must not run on the host. Match them before the
# compose-ps executor: a flip script contains both "docker compose" and the
# substring "ps" inside "snapshot", which used to leak `sudo` to the operator.
if [[ "$fail_at" == "canonical_health" && "$remote" == *"docker-compose.env.yml"* \
     && "$remote" == *"/health"* && "$remote" != *"cutover"* ]]; then
  exit 1
fi
if [[ "$remote" == "bash -s" || "$remote" == *"Caddyfile"* \
     || "$remote" == *"sudo test"* || "$remote" == *"sudo awk"* \
     || "$remote" == *"sudo install"* || "$remote" == *"sudo sed"* \
     || "$remote" == *"sudo mv"* || "$remote" == *"sudo tee"* ]]; then
  exit 0
fi
if [[ "$remote" == *"docker compose"* ]] && \
   [[ "$remote" == *" ps -q"* || "$remote" == *" ps -a"* \
      || "$remote" == *" ps;"* || "$remote" == *" ps" \
      || "$remote" == *" ps "* ]]; then
  bash -c "$remote"
  exit $?
fi
if [[ "$remote" == *"systemctl"* || "$remote" == *"daemon-reload"* \
     || "$remote" == *".bak"* || "$remote" == *"cutover"* \
     || "$remote" == *"sudo cp"* ]]; then
  exit 0
fi
if [[ "$remote" == cd\ *" && "* ]]; then
  remote="${remote#* && }"
fi
bash -c "$remote"
""".replace("__ROLLBACK_CID__", rollback_cid)
        .replace("__RUNTIME_MODE__", runtime_mode)
        .replace("__FAIL_AT__", fail_at)
        .replace("__STOPPED_CID__", stopped_cid)
    )
    _write_executable(fake_bin / "ssh", ssh)

    curl = r"""#!/usr/bin/env bash
set -euo pipefail
code="${FAKE_HEALTH_CODE:-200}"
if [[ "$code" =~ ^2[0-9][0-9]$ ]]; then
  printf '%s\n' '{"status":"ok"}'
  exit 0
fi
printf '%s\n%s\n' '{"status":"unhealthy"}' "$code"
exit 22
"""
    _write_executable(fake_bin / "curl", curl)

    driver = f'''\
source "{SCRIPT}"
GREEN=; YELLOW=; RED=; RESET=
ACX_REMOTE_INSPECT_TIMEOUT=5
ACX_REMOTE_COMMAND_TIMEOUT=5
ACX_PULL_TIMEOUT=5
ACX_PUSH_TIMEOUT=5
ACX_VERIFY_ATTEMPTS=1
ACX_VERIFY_SLEEP=0
ACX_IMAGE_REPO="$IMAGE_BASE"
init_deploy_ocir_docker_config() {{ ACX_DEPLOY_OCIR_CONFIG_DIR="{tmp_path / "docker-config"}"; mkdir -p "$ACX_DEPLOY_OCIR_CONFIG_DIR"; return 0; }}
preflight_ssh() {{ return 0; }}
preflight_remote_face_pipeline_models() {{ return 0; }}
preflight_git_clean() {{ return 0; }}
preflight_branch_synced() {{ return 0; }}
preflight_remote_ocir_auth() {{ return 0; }}
preflight_remote_docker() {{ return 0; }}
preflight_docker() {{ return 0; }}
preflight_ocir_auth() {{ return 0; }}
assert_remote_disk_headroom_for_pull() {{ return 0; }}
preserve_rollback_tag() {{
  ACX_ROLLBACK_DIGEST_REF="$IMAGE_BASE@sha256:{"a" * 64}"
  ACX_ROLLBACK_IMAGE_BASE="$IMAGE_BASE"
  ACX_ROLLBACK_TAG="rollback-{"a" * 12}"
  ACX_PRIOR_IMAGE_ID="sha256:{"1" * 64}"
}}
do_build() {{ return 0; }}
do_build_remote() {{ return 0; }}
do_push_sha() {{ ACX_CANDIDATE_DIGEST_REF="$IMAGE_BASE@sha256:{"b" * 64}"; }}
promote_gate() {{ return 0; }}
do_push_tag() {{ return 0; }}
repair_blob_volume_ownership() {{ return 0; }}
restore_prior_image_repo_env() {{ return 0; }}
_pull_ref() {{ return 0; }}
image_digest_ref() {{ printf '%s\\n' "$IMAGE_BASE@sha256:{"b" * 64}"; }}
do_verify() {{ return 1; }}
fail() {{ printf 'xx %s\\n' "$*" >&2; exit 1; }}
{invoke}
'''
    driver_path = tmp_path / "actual-rollback-driver.sh"
    driver_path.write_text(driver)
    env = dict(os.environ)
    env.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{env.get('PATH', '')}",
            "FAKE_ROLLBACK_STATE": str(state),
            "FAKE_HEALTH_CODE": health_code,
            "CONFIRM": "PROMOTE",
        }
    )
    return subprocess.run(
        ["bash", str(driver_path)],
        text=True,
        capture_output=True,
        check=False,
        cwd=SCRIPT.parents[2],
        env=env,
        timeout=30,
    )


@pytest.mark.parametrize("invoke", ["do_deploy dev", "do_promote dev staging"])
def test_actual_restart_failure_restores_after_confirmed_stopped_candidate(tmp_path: Path, invoke: str) -> None:
    """A failed live restart fences the next-project candidate before bouncing live."""
    result = _run_actual_restart_failure_transaction(tmp_path, invoke=invoke, fail_at="live_restart")
    combined = result.stdout + result.stderr
    state = tmp_path / "rollback-state"
    env_name = "staging" if "staging" in invoke else "dev"
    unit = "acx-" + env_name
    base = "iad.ocir.io/idu2kqqe2jxy/acx-backend"
    rollback_digest = base + "@sha256:" + "a" * 64
    docker_log = (state / "docker.log").read_text()
    ssh_log = (state / "ssh.log").read_text()
    assert result.returncode != 0, combined
    assert "Rollback verified healthy" in combined, combined
    assert f"in acx-{env_name}-next" in combined, combined
    assert docker_log.count(f"tag {rollback_digest} {base}:{env_name}") == 1
    assert docker_log.count(f"push {base}:{env_name}") == 1
    assert ssh_log.count(f"systemctl start {unit}-next") == 1, ssh_log
    assert (state / "candidate-recreated").is_file(), ssh_log
    assert ssh_log.index(f"systemctl stop {unit}-next") < ssh_log.index("rm -fs api") < ssh_log.index(
        f"systemctl start {unit}-next"
    )
    assert ssh_log.count(f"systemctl restart {unit}") == 2, ssh_log
    assert "-p acx-" + env_name + "-next" in docker_log, docker_log
    assert (state / "running-cid").read_text().strip() == "4" * 64
    assert "STALE ROLLBACK REFUSED" not in combined


@pytest.mark.parametrize("invoke", ["do_deploy dev", "do_promote dev staging"])
def test_failed_next_unit_start_does_not_restart_live(tmp_path: Path, invoke: str) -> None:
    """A failed additive start restores the env tag without bouncing the live unit."""
    result = _run_actual_restart_failure_transaction(tmp_path, invoke=invoke, fail_at="next_start")
    combined = result.stdout + result.stderr
    state = tmp_path / "rollback-state"
    env_name = "staging" if "staging" in invoke else "dev"
    unit = "acx-" + env_name
    base = "iad.ocir.io/idu2kqqe2jxy/acx-backend"
    rollback_digest = base + "@sha256:" + "a" * 64
    docker_log = (state / "docker.log").read_text()
    ssh_log = (state / "ssh.log").read_text()

    assert result.returncode != 0, combined
    assert docker_log.count(f"tag {rollback_digest} {base}:{env_name}") == 1
    assert docker_log.count(f"push {base}:{env_name}") == 1
    assert ssh_log.count(f"systemctl start {unit}-next") == 1, ssh_log
    assert ssh_log.count(f"systemctl restart {unit}") == 0, ssh_log
    assert (state / "running-cid").read_text().strip() == "5" * 64
    assert "Rollback verified healthy" not in combined
    assert "STALE ROLLBACK REFUSED" not in combined


def test_manual_rollback_captures_stopped_current_generation(tmp_path: Path) -> None:
    """Manual rollback must fence the stopped generation before retagging."""
    result = _run_actual_restart_failure_transaction(
        tmp_path,
        invoke="do_rollback dev " + "a" * 12,
        runtime_mode="prior",
    )
    combined = result.stdout + result.stderr
    state = tmp_path / "rollback-state"
    docker_log = (state / "docker.log").read_text()
    ssh_log = (state / "ssh.log").read_text()
    base = "iad.ocir.io/idu2kqqe2jxy/acx-backend"
    rollback_digest = base + "@sha256:" + "a" * 64

    assert result.returncode == 0, combined
    assert "Confirmed stopped prior api container" in combined, combined
    assert "Rollback verified healthy" in combined, combined
    assert docker_log.count(f"tag {rollback_digest} {base}:dev") == 1
    assert docker_log.count(f"push {base}:dev") == 1
    assert ssh_log.count("systemctl restart acx-dev") == 1, ssh_log
    assert (state / "running-cid").read_text().strip() == "4" * 64


def test_manual_rollback_keeps_http_503_health_gate(tmp_path: Path) -> None:
    """A 503 after retagging is not a verified healthy rollback."""
    result = _run_actual_restart_failure_transaction(
        tmp_path,
        invoke="do_rollback dev " + "a" * 12,
        runtime_mode="prior",
        health_code="503",
    )
    combined = result.stdout + result.stderr

    assert result.returncode != 0, combined
    assert "Rollback health/digest verification failed" in combined, combined
    assert "503" in combined, combined
    assert "Rollback verified healthy" not in combined


@pytest.mark.parametrize("runtime_mode", ["absent", "unknown", "wrong"])
def test_actual_restart_failure_refuses_unowned_runtime_observation(tmp_path: Path, runtime_mode: str) -> None:
    """No container or failed inspection cannot authorize automatic live rollback."""
    result = _run_actual_restart_failure_transaction(
        tmp_path, invoke="do_deploy dev", runtime_mode=runtime_mode, fail_at="live_restart"
    )
    combined = result.stdout + result.stderr
    state = tmp_path / "rollback-state"
    docker_log = (state / "docker.log").read_text()
    ssh_log = (state / "ssh.log").read_text()
    base = "iad.ocir.io/idu2kqqe2jxy/acx-backend"
    rollback_digest = base + "@sha256:" + "a" * 64
    assert result.returncode != 0, combined
    assert "refusing" in combined.lower(), combined
    assert f"tag {rollback_digest} {base}:dev" not in docker_log
    assert f"push {base}:dev" not in docker_log
    assert ssh_log.count("systemctl start acx-dev-next") == 1, ssh_log
    assert ssh_log.count("systemctl restart acx-dev") == 1, ssh_log
    assert not (state / "running-cid").exists()


def test_do_restart_is_additive_then_flip() -> None:
    """OCIRV1-RB-11: start a next unit and flip traffic before touching the live unit."""
    body = _function_body("do_restart")
    assert "env_to_next_unit" in body
    assert "render_cutover_compose" in body
    assert "render_next_unit" in body
    assert "recreate_cutover_candidate" in body
    assert "flip_edge_alias" in body
    assert "probe_cutover_api_health" in body
    assert body.index("recreate_cutover_candidate") < body.index("flip_edge_alias")
    assert body.index("probe_cutover_api_health") < body.index("flip_edge_alias")
    assert body.index("flip_edge_alias") < body.index("systemctl restart")
    recreate = _function_body("recreate_cutover_candidate")
    assert recreate.index("systemctl stop") < recreate.index("rm -fs api") < recreate.index("systemctl start")


def test_cutover_candidate_probe_requires_immutable_image_and_commit() -> None:
    body = _function_body("probe_cutover_api_health")
    assert "remote_image_id_for_digest" in body
    assert "docker inspect --format '{{.Image}}'" in body
    assert "expected_image_id" in body
    assert "commit_sha" in body
    assert "actual == sys.argv[1]" in body


def test_abort_cutover_candidate_fails_closed_on_remote_cleanup_error(tmp_path: Path) -> None:
    records = tmp_path / "abort.log"
    command = f'''
source "{SCRIPT}"
GREEN=; YELLOW=; RED=; RESET=
ACX_TRAFFIC_FLIPPED=1
run_with_deadline() {{ return 73; }}
if abort_cutover_candidate dev; then
  exit 1
fi
printf 'traffic=%s\\n' "$ACX_TRAFFIC_FLIPPED" >"{records}"
'''
    result = subprocess.run(["bash", "-c", command], text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert records.read_text() == "traffic=1\n"


def test_do_restart_gates_canonical_health_before_flip_back() -> None:
    """R-01: a systemd restart is not enough to take traffic off the candidate."""
    body = _function_body("do_restart")
    restart_at = body.index("systemctl restart")
    health_at = body.index("probe_canonical_api_health")
    digest_at = body.index("verify_running_image_digest")
    canonical_flip = body.index('flip_edge_alias "$env" canonical', restart_at)
    abort_at = body.index("abort_cutover_candidate", restart_at)
    assert restart_at < digest_at < canonical_flip
    assert restart_at < health_at < canonical_flip < abort_at
    assert "probe_cutover_api_health" in body[restart_at:canonical_flip]


def test_canonical_health_failure_keeps_candidate_serving(tmp_path: Path) -> None:
    """R-01: retain next until the canonical API itself is healthy."""
    result = _run_actual_restart_failure_transaction(
        tmp_path,
        invoke='do_restart dev "$IMAGE_BASE@sha256:' + ("b" * 64) + '"',
        fail_at="canonical_health",
    )
    combined = result.stdout + result.stderr
    ssh_log = (tmp_path / "rollback-state" / "ssh.log").read_text()
    assert result.returncode != 0, combined
    assert "canonical api never became healthy" in combined.lower(), combined
    assert "traffic remains on acx-dev-next" in combined, combined
    assert "Flipping Caddy reverse_proxy dev-api-next:8000 -> dev-api:8000" not in combined
    assert ssh_log.count("systemctl restart acx-dev") == 1, ssh_log
    assert "systemctl stop 'acx-dev-next'" not in ssh_log
    assert (tmp_path / "rollback-state" / "next-running-cid").exists()


def test_promote_gate_restores_topology_on_converge_failure() -> None:
    """OCIRV1-FD-06: mixed compose/unit/edge files must roll back with the sticky repo."""
    body = _function_body("promote_gate")
    assert "restore_runtime_topology" in body
    converge_fail = body.index('if ! (converge_runtime "$env"); then')
    topo = body.index("restore_runtime_topology")
    assert converge_fail < topo
    assert topo < body.index("restore_prior_image_repo_env", converge_fail)


def test_restore_runtime_topology_consumes_bak_files() -> None:
    """OCIRV1-FD-06: .bak topology files are the rollback participants, not just backups."""
    backups = _function_body("restore_topology_backups")
    edge = _function_body("restore_edge_backups")
    wrapper = _function_body("restore_runtime_topology")
    for body in (backups, edge):
        assert ".bak" in body
    assert "docker-compose.env.yml.bak" in backups
    assert ".service.bak" in backups
    assert "docker-compose.admin.yml.bak" in backups
    assert "Caddyfile.bak" in edge
    assert "docker-compose.caddy.yml.bak" in edge
    assert "restore_topology_backups" in wrapper
    assert "restore_edge_backups" in wrapper
    assert "abort_cutover_candidate" in wrapper


def test_restore_topology_backups_copies_bak_via_ssh(tmp_path: Path) -> None:
    records = tmp_path / "ssh.log"
    command = f'''
source "{SCRIPT}"
GREEN=; YELLOW=; RED=; RESET=
run_with_deadline() {{ shift 2; "$@"; }}
ssh() {{
  printf '%s\\n' "$*" >>"{records}"
  return 0
}}
restore_topology_backups dev
'''
    result = subprocess.run(["bash", "-c", command], text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    logged = records.read_text()
    assert "docker-compose.env.yml.bak" in logged
    assert "acx-dev.service.bak" in logged


def test_flip_edge_alias_rewrites_only_allowlisted_proxy_targets() -> None:
    body = _function_body("flip_edge_alias")
    assert "reverse_proxy" in body
    assert "${alias}-next" in body
    assert "caddy reload" in body
    assert "next|canonical" in body or "next)" in body
    assert "bash -s" in body
    assert "source_count" in body
    assert "expected exactly one formatted Caddy reverse_proxy source route" in body
    assert '== "reverse_proxy"' in body


def _run_flip_edge_alias(tmp_path: Path, caddyfile: str, target: str = "next") -> subprocess.CompletedProcess[str]:
    edge = tmp_path / "edge"
    edge.mkdir(exist_ok=True)
    (edge / "Caddyfile").write_text(caddyfile)
    (edge / "docker-compose.caddy.yml").write_text("services: {}\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(bin_dir / "sudo", '#!/usr/bin/env bash\nexec "$@"\n')
    _write_executable(bin_dir / "docker", "#!/usr/bin/env bash\nexit 0\n")
    digest = "b" * 64
    command = f'''
source "{SCRIPT}"
GREEN=; YELLOW=; RED=; RESET=
ACX_CANDIDATE_DIGEST_REF="$IMAGE_BASE@sha256:{digest}"
run_with_deadline() {{ shift 2; "$@"; }}
ssh() {{
  last="${{@: -1}}"
  if [[ "$last" != "bash -s" ]]; then
    exit 0
  fi
  export PATH="{bin_dir}:$PATH"
  sed "s|/opt/acx-backend|{edge}|g" | bash -s
}}
flip_edge_alias dev {target}
'''
    return subprocess.run(["bash", "-c", command], text=True, capture_output=True, check=False)


def test_flip_edge_alias_fails_closed_without_source_route(tmp_path: Path) -> None:
    """R-06: a missing reverse_proxy source must not report a successful flip."""
    original = "dev.example {\n\treverse_proxy 127.0.0.1:8000\n}\n"
    result = _run_flip_edge_alias(tmp_path, original)
    combined = result.stdout + result.stderr
    assert result.returncode != 0, combined
    assert "expected exactly one formatted Caddy reverse_proxy source route" in combined
    assert (tmp_path / "edge" / "Caddyfile").read_text() == original


def test_flip_edge_alias_rewrites_exactly_one_source_route(tmp_path: Path) -> None:
    """R-06: replacement must leave exactly one desired route."""
    original = "dev.example {\n\treverse_proxy dev-api:8000\n}\n"
    result = _run_flip_edge_alias(tmp_path, original)
    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    rewritten = (tmp_path / "edge" / "Caddyfile").read_text()
    assert "reverse_proxy dev-api-next:8000" in rewritten
    assert "reverse_proxy dev-api:8000" not in rewritten


def _cutover_state_dir(tmp_path: Path) -> Path:
    return tmp_path / "edge" / ".acx-deploy-backups" / "dev"


def test_flip_edge_alias_persists_inflight_cutover_marker(tmp_path: Path) -> None:
    """R-09: traffic-on-next must be durable on the remote, not only ACX_TRAFFIC_FLIPPED."""
    original = "dev.example {\n\treverse_proxy dev-api:8000\n}\n"
    result = _run_flip_edge_alias(tmp_path, original, target="next")
    combined = result.stdout + result.stderr
    inflight = _cutover_state_dir(tmp_path) / "cutover-inflight"
    committed = _cutover_state_dir(tmp_path) / "cutover-committed"
    assert result.returncode == 0, combined
    assert inflight.is_file(), combined
    body = inflight.read_text()
    assert "env=dev" in body
    assert "status=traffic_on_next" in body
    assert "next_unit=acx-dev-next" in body
    assert re.search(r"(?m)^digest=.+@sha256:[a-f0-9]{64}$", body)
    assert re.search(r"(?m)^timestamp=[0-9]+$", body)
    assert not committed.exists()


def test_flip_edge_alias_writes_marker_before_caddy_rewrite() -> None:
    """R-09: the durable flip marker must be written before traffic is rewritten."""
    body = _function_body("flip_edge_alias")
    marker_at = body.index("cutover-inflight")
    rewrite_at = body.index("sed -E")
    assert marker_at < rewrite_at
    assert "timestamp=" in body
    assert "digest=" in body


def test_flip_edge_alias_canonical_writes_commit_marker(tmp_path: Path) -> None:
    """R-09: canonical routing is committed only after the flip-back succeeds."""
    original = "dev.example {\n\treverse_proxy dev-api-next:8000\n}\n"
    inflight = _cutover_state_dir(tmp_path)
    inflight.mkdir(parents=True)
    (inflight / "cutover-inflight").write_text(
        "env=dev\ndigest=sha256:" + ("b" * 64) + "\ntimestamp=1\nstatus=traffic_on_next\nnext_unit=acx-dev-next\n"
    )
    result = _run_flip_edge_alias(tmp_path, original, target="canonical")
    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    assert not (inflight / "cutover-inflight").exists(), combined
    committed = inflight / "cutover-committed"
    assert committed.is_file(), combined
    assert "status=canonical" in committed.read_text()


def test_deploy_signal_traps_run_cutover_recovery() -> None:
    """R-09: HUP/INT/TERM must recover inflight cutover instead of bare-exit."""
    init = _function_body("init_deploy_ocir_docker_config")
    assert "deploy_interrupt_cleanup" in init
    assert "trap 'exit 129' HUP" not in init
    assert "trap 'exit 130' INT" not in init
    assert "trap 'exit 143' TERM" not in init
    cleanup = _function_body("deploy_interrupt_cleanup")
    assert "recover_interrupted_cutover" in cleanup
    restart = _function_body("do_restart")
    assert "enable_cutover_candidate" in restart
    assert "recover_persisted_cutover" in restart
    assert restart.index("flip_edge_alias") < restart.index("enable_cutover_candidate")


def test_recover_interrupted_cutover_keeps_candidate_if_edge_restore_fails(
    tmp_path: Path,
) -> None:
    """R-09: a failed flip-back must not drain the still-serving candidate."""
    records = tmp_path / "recover.log"
    command = f'''
source "{SCRIPT}"
GREEN=; YELLOW=; RED=; RESET=
ACX_CUTOVER_ENV=dev
ACX_TRAFFIC_FLIPPED=1
cutover_inflight_present() {{ return 0; }}
restore_edge_backups() {{ return 1; }}
abort_cutover_candidate() {{ printf 'aborted\\n' >>"{records}"; return 0; }}
enable_cutover_candidate() {{ printf 'enabled\\n' >>"{records}"; return 0; }}
commit_cutover_state() {{ printf 'committed\\n' >>"{records}"; return 0; }}
recover_interrupted_cutover
'''
    result = subprocess.run(["bash", "-c", command], text=True, capture_output=True, check=False)
    logged = records.read_text() if records.exists() else ""
    assert result.returncode != 0, result.stdout + result.stderr
    assert "aborted" not in logged
    assert "committed" not in logged
    assert "enabled" in logged


def test_recover_interrupted_cutover_commits_after_successful_restore(tmp_path: Path) -> None:
    """R-09: successful signal-safe restore may drain the candidate only after commit."""
    records = tmp_path / "recover.log"
    command = f'''
source "{SCRIPT}"
GREEN=; YELLOW=; RED=; RESET=
ACX_CUTOVER_ENV=dev
ACX_TRAFFIC_FLIPPED=1
cutover_inflight_present() {{ return 0; }}
restore_edge_backups() {{ ACX_TRAFFIC_FLIPPED=0; return 0; }}
abort_cutover_candidate() {{ printf 'aborted\\n' >>"{records}"; return 0; }}
enable_cutover_candidate() {{ printf 'enabled\\n' >>"{records}"; return 0; }}
commit_cutover_state() {{ printf 'committed\\n' >>"{records}"; return 0; }}
recover_interrupted_cutover
'''
    result = subprocess.run(["bash", "-c", command], text=True, capture_output=True, check=False)
    logged = records.read_text() if records.exists() else ""
    assert result.returncode == 0, result.stdout + result.stderr
    assert logged.splitlines() == ["committed", "aborted"]


def test_killed_run_flip_marker_recovers_on_next_deploy(tmp_path: Path) -> None:
    """R-09: a leftover remote marker must recover even when ACX_TRAFFIC_FLIPPED starts at 0."""
    records = tmp_path / "recover.log"
    command = f'''
source "{SCRIPT}"
GREEN=; YELLOW=; RED=; RESET=
ACX_TRAFFIC_FLIPPED=0
cutover_inflight_present() {{ return 0; }}
restore_edge_backups() {{ printf 'restored\\n' >>"{records}"; ACX_TRAFFIC_FLIPPED=0; return 0; }}
abort_cutover_candidate() {{ printf 'aborted\\n' >>"{records}"; return 0; }}
enable_cutover_candidate() {{ printf 'enabled\\n' >>"{records}"; return 0; }}
commit_cutover_state() {{ printf 'committed\\n' >>"{records}"; return 0; }}
recover_persisted_cutover dev
printf 'traffic=%s\\n' "$ACX_TRAFFIC_FLIPPED" >>"{records}"
'''
    result = subprocess.run(["bash", "-c", command], text=True, capture_output=True, check=False)
    logged = records.read_text() if records.exists() else ""
    assert result.returncode == 0, result.stdout + result.stderr
    assert logged.splitlines() == ["restored", "committed", "aborted", "traffic=0"]


def test_term_after_traffic_flip_invokes_cutover_recovery(tmp_path: Path) -> None:
    """R-09: SIGTERM during an inflight cutover must run recovery before exit."""
    marker = tmp_path / "recovered"
    ready = tmp_path / "traps-ready"
    driver = tmp_path / "term-recover.sh"
    driver.write_text(
        f'''
source "{SCRIPT}"
GREEN=; YELLOW=; RED=; RESET=
export TMPDIR="{tmp_path}"
recover_interrupted_cutover() {{ printf 'recovered\\n' >"{marker}"; return 0; }}
init_deploy_ocir_docker_config
printf 'ready\\n' >"{ready}"
sleep 30
'''
    )
    proc = subprocess.Popen(
        ["bash", str(driver)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            break
        if ready.is_file():
            time.sleep(0.05)
            break
        time.sleep(0.05)
    if proc.poll() is None:
        os.killpg(proc.pid, signal.SIGTERM)
    stdout, stderr = proc.communicate(timeout=8)
    combined = (stdout or "") + (stderr or "")
    assert proc.returncode == 143, combined
    assert marker.is_file(), combined
    assert marker.read_text() == "recovered\n"


def test_read_api_runtime_evidence_inspects_cutover_project() -> None:
    body = _function_body("read_api_runtime_evidence")
    assert "docker-compose.cutover.yml" in body
    assert "acx-${env}-next" in body
    assert "-p ${next_project}" in body or "-p ${next_project} -f docker-compose.cutover.yml" in body


def test_assert_rollback_fence_accepts_next_project_candidate() -> None:
    body = _function_body("assert_rollback_fence")
    assert 'next_project="acx-${env}-next"' in body
    assert "${canonical_project}" in body
    assert "${next_project}" in body
    assert "stopped-candidate" in body


def test_restore_rollback_helpers_are_split() -> None:
    orchestrator = _function_body("restore_env_tag_to_rollback")
    fence = _function_body("assert_rollback_fence")
    registry = _function_body("restore_registry_env_tag")
    runtime = _function_body("restore_runtime_and_edge")
    assert "assert_rollback_fence" in orchestrator
    assert "restore_registry_env_tag" in orchestrator
    assert "restore_runtime_and_edge" in orchestrator
    assert "systemctl restart" not in registry
    assert "remote_docker_with_config push" in registry
    assert "read_api_runtime_evidence" in fence
    assert "restore_topology_backups" in runtime
    assert "leaving candidate serving" in runtime


def test_restore_edge_backups_uses_immutable_pre_cutover_snapshot() -> None:
    body = _function_body("restore_edge_backups")
    assert "Caddyfile.pre-cutover" in body
    assert "edge-cutover.current" in body
    assert "Caddyfile.flip.bak" not in body
    assert 'ACX_TRAFFIC_FLIPPED:-0}" == "1"' in body
    assert "require_canonical_route" in body
    assert "compose_restored" in body


def test_cutover_failure_restart_runtime_ignores_evidence_phase() -> None:
    helper = _function_body("cutover_failure_restart_runtime")
    deploy = _function_body("_ship_selected_env")
    assert '_ship_selected_env "$env" aggregate' in _function_body("do_deploy")
    promote = _function_body("do_promote")
    assert "ACX_LIVE_DISRUPTED" in helper
    assert "ACX_TRAFFIC_FLIPPED" in helper
    assert "post_restart" not in helper
    assert "cutover_failure_restart_runtime" in deploy
    assert "cutover_failure_restart_runtime" in promote
    assert 'ACX_RESTART_EVIDENCE_PHASE:-pre_candidate}" == "post_restart"' not in deploy
    assert 'ACX_RESTART_EVIDENCE_PHASE:-pre_candidate}" == "post_restart"' not in promote


def test_prepare_producer_cli_verifies_image_and_scoped_load() -> None:
    """Explicit prepare-producer remains a real gate, not ACX_VERIFY_OPTIONAL.

    Changed contract (ISSUEDAG-1 / RLSE-03): NORMAL verify_live_gpu_snapshots
    always executes the aggregate checker and never substitutes
    verify_scoped_producer_snapshots. Explicit producer-convergence stays on
    do_prepare_producer (next slice); that helper still only verifies existing
    state and cannot create cold loads.
    """
    source = SCRIPT.read_text()
    assert "prepare-producer <env>" in source
    dispatch = source.split('case "$cmd" in', 1)[1]
    assert "prepare-producer)" in dispatch
    body = _function_body("do_prepare_producer")
    assert "verify_running_image_matches_deployed" in body
    assert "verify_scoped_producer_snapshots" in body
    assert "ACX_VERIFY_OPTIONAL" not in body
    scoped = _function_body("verify_scoped_producer_snapshots")
    assert "/run/acx-write/" in scoped
    assert "describe-load.json" in scoped
    assert "written_at" in scoped
    assert "queue_depth" in scoped
    assert "ACX_VERIFY_OPTIONAL" not in scoped
    gate = _function_body("verify_live_gpu_snapshots")
    assert "check-gpu-snapshots.sh" in gate
    assert "paste -sd," in gate
    assert "ACX_GPU_CHECKER_V1" in gate
    assert "timeout" in gate
    assert "verify_scoped_producer_snapshots" not in gate
    assert "using scoped producer-preparation" not in gate


def _run_verify_live_gpu_snapshots(
    tmp_path: Path,
    *,
    sibling_rc: int,
    timeout_rc: int,
    scoped_rc: int = 0,
) -> tuple[subprocess.CompletedProcess[str], str]:
    """Drive verify_live_gpu_snapshots via its exact helpers, not an invented API.

    timeout is the aggregate-checker transport (check-gpu-snapshots.sh over ssh).
    verify_scoped_producer_snapshots is stubbed successful so a silent substitute
    cannot hide an aggregate failure (TEST-15).
    """
    records = tmp_path / "gate.log"
    command = f'''
source "{SCRIPT}"
GREEN=; YELLOW=; RED=; RESET=
sibling_gpu_snapshots_complete() {{ printf 'probe:%s\\n' "$1" >>"{records}"; return {sibling_rc}; }}
verify_scoped_producer_snapshots() {{ printf 'scoped:%s\\n' "$1" >>"{records}"; return {scoped_rc}; }}
ssh() {{ printf 'ssh\\n' >>"{records}"; return 0; }}
timeout() {{ cat >/dev/null; printf 'aggregate:%s\\n' "{timeout_rc}" >>"{records}"; return {timeout_rc}; }}
verify_live_gpu_snapshots prod
'''
    result = subprocess.run(["bash", "-c", command], text=True, capture_output=True, check=False)
    logged = records.read_text() if records.exists() else ""
    return result, logged


def test_normal_verify_uses_aggregate_not_scoped_when_siblings_incomplete(
    tmp_path: Path,
) -> None:
    """Changed contract: missing siblings still run the aggregate checker.

    Former R3-01 approved implicit NORMAL-verify fallback to
    verify_scoped_producer_snapshots. That substitutes a single-env writer
    check for the registry-wide gate (RLSE-03, DATA-13). Scoped success is
    stubbed so a bypass would still return 0 (TEST-15).
    """
    result, logged = _run_verify_live_gpu_snapshots(
        tmp_path, sibling_rc=1, timeout_rc=0, scoped_rc=0
    )
    combined = result.stdout + result.stderr
    lines = logged.splitlines()
    assert "aggregate:0" in lines, combined
    assert "scoped:prod" not in lines
    assert "using scoped producer-preparation" not in combined
    assert result.returncode == 0, combined


def test_subsequent_deploy_keeps_aggregate_snapshot_gate(tmp_path: Path) -> None:
    """Once every sibling has a snapshot, the aggregate gate still governs."""
    result, logged = _run_verify_live_gpu_snapshots(
        tmp_path, sibling_rc=0, timeout_rc=0, scoped_rc=0
    )
    combined = result.stdout + result.stderr
    lines = logged.splitlines()
    assert "aggregate:0" in lines, combined
    assert "scoped:prod" not in lines
    assert "using scoped producer-preparation" not in combined
    assert "Verifying live GPU snapshot contract" in combined
    assert result.returncode == 0, combined


@pytest.mark.parametrize(
    "timeout_rc",
    [1, 255, 124],
    ids=["missing", "ssh_error", "deadline"],
)
def test_normal_verify_propagates_aggregate_checker_failure(
    tmp_path: Path, timeout_rc: int
) -> None:
    """Aggregate checker failure must propagate; scoped success must not bypass.

    RES-02 / RES-03: missing snapshots (1), SSH error (255), and GNU timeout
    deadline (124) are distinct failure modes. A hung or refused checker must
    not be replaced by a scoped writer check. TEST-15: scoped stub returns 0
    so a silent substitute would turn this green for the wrong reason.
    """
    result, logged = _run_verify_live_gpu_snapshots(
        tmp_path, sibling_rc=1, timeout_rc=timeout_rc, scoped_rc=0
    )
    combined = result.stdout + result.stderr
    lines = logged.splitlines()
    assert f"aggregate:{timeout_rc}" in lines, combined
    assert "scoped:prod" not in lines
    assert result.returncode == timeout_rc, (
        f"expected aggregate rc {timeout_rc}, got {result.returncode}: {combined}"
    )


def test_normal_verify_runs_aggregate_on_sibling_probe_error(tmp_path: Path) -> None:
    """Sibling probe errors must not substitute scoped producer snapshots."""
    result, logged = _run_verify_live_gpu_snapshots(
        tmp_path, sibling_rc=255, timeout_rc=1, scoped_rc=0
    )
    combined = result.stdout + result.stderr
    lines = logged.splitlines()
    assert "aggregate:1" in lines, combined
    assert "scoped:prod" not in lines
    assert result.returncode == 1, combined


_CANDIDATE_SHA = "b" * 64
_ROLLBACK_SHA = "a" * 64
_FENCED_DIGEST = re.compile(r"^[A-Za-z0-9_.:/-]+@sha256:[a-f0-9]{64}$")


def _run_prepare_producer(
    tmp_path: Path,
    *,
    env: str = "prod",
    confirm: str | None = "PROMOTE",
    candidate_sha: str = _CANDIDATE_SHA,
    public_deploy: bool = False,
    sibling_rc: int = 0,
    restart_after_fence_rc: int = 0,
    image_rc: int = 0,
    scoped_rc: int = 0,
    preserve_sets_rollback: bool = True,
    records_name: str = "prepare.log",
) -> tuple[subprocess.CompletedProcess[str], str]:
    """Drive do_prepare_producer against real do_deploy transaction shapes.

    do_restart is not a no-op: it applies the smoke-fenced digest check from
    recognition-service.sh (expected_digest must match ACX_IMAGE_REPO@sha256:64).
    restore_env_tag_to_rollback applies assert_rollback_fence's identity check
    (ACX_ROLLBACK_DIGEST_REF must already be a captured digest). Scoped image
    and snapshot verifies are stubbed successful so a verify-only path cannot
    hide a missing transaction (TEST-15). do_deploy is left real so
    CONFIRM=PROMOTE is not bypassed.
    """
    records = tmp_path / records_name
    confirm_line = f'export CONFIRM="{confirm}"' if confirm is not None else "unset CONFIRM || true"
    preserve_body = (
        f'  ACX_ROLLBACK_DIGEST_REF="$IMAGE_BASE@sha256:{_ROLLBACK_SHA}"\n'
        '  ACX_ROLLBACK_IMAGE_BASE="$IMAGE_BASE"\n'
        if preserve_sets_rollback
        else ""
    )
    command = f'''
source "{SCRIPT}"
GREEN=; YELLOW=; RED=; RESET=
{confirm_line}
ACX_IMAGE_REPO="$IMAGE_BASE"
init_deploy_ocir_docker_config() {{ return 0; }}
preflight_ssh() {{ printf 'preflight\\n' >>"{records}"; return 0; }}
preflight_remote_face_pipeline_models() {{ return 0; }}
preflight_git_clean() {{ return 0; }}
preflight_branch_synced() {{ return 0; }}
preflight_remote_ocir_auth() {{ return 0; }}
preflight_remote_docker() {{ return 0; }}
preflight_docker() {{ return 0; }}
preflight_ocir_auth() {{ return 0; }}
assert_remote_disk_headroom_for_pull() {{ return 0; }}
capture_failure_evidence() {{ return 0; }}
capture_prior_runtime_identity() {{ printf 'prior-identity:%s\\n' "$1" >>"{records}"; return 0; }}
sibling_gpu_snapshots_complete() {{ printf 'sibling:%s\\n' "$1" >>"{records}"; return {sibling_rc}; }}
preserve_rollback_tag() {{
  printf 'preserve:%s\\n' "$1" >>"{records}"
{preserve_body}  return 0
}}
do_build() {{ printf 'build\\n' >>"{records}"; return 0; }}
do_build_remote() {{ printf 'build-remote\\n' >>"{records}"; return 0; }}
do_push_sha() {{
  printf 'push-sha\\n' >>"{records}"
  ACX_CANDIDATE_DIGEST_REF="$IMAGE_BASE@sha256:{candidate_sha}"
}}
do_push_tag() {{ printf 'push-tag:%s\\n' "$1" >>"{records}"; return 0; }}
do_boot_smoke() {{ printf 'smoke:%s:%s\\n' "$1" "$2" >>"{records}"; return 0; }}
promote_gate() {{
  printf 'promote:%s:%s\\n' "$1" "$2" >>"{records}"
  if [[ ! "$2" =~ ^[A-Za-z0-9_.:/-]+@sha256:[a-f0-9]{{64}}$ ]]; then
    warn "promote gate requires a digest-pinned candidate (got: ${{2:-empty}})"
    return 1
  fi
  local repo="${{2%@sha256:*}}"
  if [[ "$repo" != "$IMAGE_BASE" ]]; then
    warn "promote digest repository does not match IMAGE_BASE"
    return 1
  fi
  ACX_CANDIDATE_DIGEST_REF="$2"
  return 0
}}
do_restart() {{
  local env="$1" expected_digest="${{2:-${{ACX_CANDIDATE_DIGEST_REF:-}}}}"
  local expected_repo="${{expected_digest%@sha256:*}}"
  printf 'restart:%s:%s\\n' "$env" "$expected_digest" >>"{records}"
  if [[ ! "${{expected_digest}}" =~ ^[A-Za-z0-9_.:/-]+@sha256:[a-f0-9]{{64}}$ \\
    || "${{expected_repo}}" != "${{ACX_IMAGE_REPO}}" ]]; then
    warn "restart requires the smoke-fenced digest for ACX_IMAGE_REPO=${{ACX_IMAGE_REPO}} (got: ${{expected_digest:-empty}})"
    printf 'restart-unfenced\\n' >>"{records}"
    return 1
  fi
  printf 'restart-accepted:%s\\n' "$env" >>"{records}"
  return {restart_after_fence_rc}
}}
do_verify() {{ printf 'verify:%s\\n' "$1" >>"{records}"; return 0; }}
verify_live_gpu_snapshots() {{ printf 'aggregate:%s\\n' "$1" >>"{records}"; return 0; }}
verify_running_image_matches_deployed() {{ printf 'image:%s\\n' "$1" >>"{records}"; return {image_rc}; }}
verify_scoped_producer_snapshots() {{ printf 'scoped:%s\\n' "$1" >>"{records}"; return {scoped_rc}; }}
restore_env_tag_to_rollback() {{
  printf 'rollback:%s\\n' "$1" >>"{records}"
  if [[ ! "${{ACX_ROLLBACK_DIGEST_REF:-}}" =~ ^[A-Za-z0-9_.:/-]+@sha256:[a-f0-9]{{64}}$ ]]; then
    warn "ROLLBACK REQUIRED but no previous serving digest was captured"
    printf 'rollback-unfenced\\n' >>"{records}"
    return 1
  fi
  printf 'rollback-fenced:%s\\n' "$1" >>"{records}"
  return 0
}}
{'export _ACX_SHIP_COMPLETION=scoped' if public_deploy else ':'}
{'do_deploy' if public_deploy else 'do_prepare_producer'} {env}
'''
    result = subprocess.run(["bash", "-c", command], text=True, capture_output=True, check=False)
    logged = records.read_text() if records.exists() else ""
    return result, logged


def test_prepare_producer_setting_cannot_downgrade_public_deploy(tmp_path: Path) -> None:
    result, logged = _run_prepare_producer(tmp_path, public_deploy=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "verify:prod" in logged.splitlines(), logged
    assert "scoped:prod" not in logged.splitlines(), logged


def _first_line(prefix: str, lines: list[str]) -> str | None:
    for line in lines:
        if line.startswith(prefix):
            return line
    return None


def test_prepare_producer_converges_selected_env_before_verify(tmp_path: Path) -> None:
    """Cold selected-env must run the safe deploy transaction before verifies.

    Finding 10250: a stale leftover snapshot can masquerade as a live writer.
    Observable order (do_deploy 3665): preserve prior state, smoke-fenced
    candidate via promote_gate, do_restart with that digest, then image/writer
    checks. TEST-15: image/scoped stubs succeed so verify-only still looks green.
    """
    result, logged = _run_prepare_producer(tmp_path, records_name="converge.log")
    combined = result.stdout + result.stderr
    lines = logged.splitlines()
    preserve = _first_line("preserve:prod", lines)
    promote = _first_line("promote:prod:", lines)
    restart = _first_line("restart:prod:", lines)
    assert preserve is not None, combined
    assert promote is not None, combined
    assert restart is not None, combined
    assert "restart-accepted:prod" in lines, combined
    assert "restart-unfenced" not in lines
    digest = promote.split(":", 2)[2]
    assert _FENCED_DIGEST.match(digest), digest
    assert restart == f"restart:prod:{digest}", restart
    assert "image:prod" in lines, combined
    assert "scoped:prod" in lines, combined
    assert lines.index(preserve) < lines.index("restart-accepted:prod"), lines
    assert lines.index(promote) < lines.index("restart-accepted:prod"), lines
    assert lines.index("restart-accepted:prod") < lines.index("image:prod"), lines
    assert lines.index("restart-accepted:prod") < lines.index("scoped:prod"), lines
    assert "aggregate:prod" not in lines
    assert "verify:prod" not in lines
    assert result.returncode == 0, combined


def test_prepare_producer_convergence_does_not_require_missing_siblings(
    tmp_path: Path,
) -> None:
    """Bootstrap the selected env whether sibling snapshots exist or not."""
    result, logged = _run_prepare_producer(
        tmp_path, sibling_rc=0, records_name="sib-complete.log"
    )
    combined = result.stdout + result.stderr
    assert "restart-accepted:prod" in logged.splitlines(), combined
    assert result.returncode == 0, combined
    result_missing, logged_missing = _run_prepare_producer(
        tmp_path, sibling_rc=1, records_name="sib-missing.log"
    )
    combined_missing = result_missing.stdout + result_missing.stderr
    assert "restart-accepted:prod" in logged_missing.splitlines(), combined_missing
    assert result_missing.returncode == 0, combined_missing
    assert logged.splitlines() != logged_missing.splitlines() or "sibling:prod" not in logged


def test_prepare_producer_prod_requires_confirm_promote(tmp_path: Path) -> None:
    """Prod prepare-producer must not bypass CONFIRM=PROMOTE (do_deploy 3684)."""
    result, logged = _run_prepare_producer(
        tmp_path, confirm=None, records_name="no-confirm.log"
    )
    combined = result.stdout + result.stderr
    assert result.returncode != 0, combined
    assert "passed" not in combined.lower()
    assert "CONFIRM=PROMOTE" in combined
    assert "restart-accepted:prod" not in logged.splitlines()


def test_prepare_producer_restart_without_fenced_digest_is_refused(tmp_path: Path) -> None:
    """A restart with no smoke-fenced digest must fail, not skip to scoped success."""
    result, logged = _run_prepare_producer(
        tmp_path, candidate_sha="malformed", records_name="unfenced-restart.log"
    )
    combined = result.stdout + result.stderr
    lines = logged.splitlines()
    assert result.returncode != 0, combined
    assert "passed" not in combined.lower()
    assert "restart-accepted:prod" not in lines
    assert "scoped:prod" not in lines


def test_prepare_producer_restart_failure_rolls_back_and_does_not_succeed(
    tmp_path: Path,
) -> None:
    """Start failure must fence-rollback with captured identity, never report success.

    DATA-13 / RES-03: same boundary as do_deploy. assert_rollback_fence refuses
    empty ACX_ROLLBACK_DIGEST_REF. TEST-15: scoped stub succeeds.
    """
    result, logged = _run_prepare_producer(
        tmp_path,
        restart_after_fence_rc=1,
        image_rc=0,
        scoped_rc=0,
        preserve_sets_rollback=True,
        records_name="restart-fail.log",
    )
    combined = result.stdout + result.stderr
    lines = logged.splitlines()
    assert "restart-accepted:prod" in lines, combined
    assert "rollback-fenced:prod" in lines, combined
    assert "rollback-unfenced" not in lines
    assert "scoped:prod" not in lines
    assert result.returncode != 0, combined
    assert "passed" not in combined.lower()


def test_prepare_producer_unfenced_rollback_does_not_compensate(tmp_path: Path) -> None:
    """Verify/start failure must not roll back without a captured prior digest."""
    result, logged = _run_prepare_producer(
        tmp_path,
        restart_after_fence_rc=1,
        preserve_sets_rollback=False,
        records_name="unfenced-rollback.log",
    )
    combined = result.stdout + result.stderr
    lines = logged.splitlines()
    assert "rollback-fenced:prod" not in lines
    assert result.returncode != 0, combined
    assert "passed" not in combined.lower()


def test_prepare_producer_scoped_failure_after_converge_is_not_success(
    tmp_path: Path,
) -> None:
    """Writer/schema/freshness failure after a fenced restart must not report success."""
    result, logged = _run_prepare_producer(
        tmp_path, restart_after_fence_rc=0, image_rc=0, scoped_rc=1, records_name="scoped-fail.log"
    )
    combined = result.stdout + result.stderr
    lines = logged.splitlines()
    assert "restart-accepted:prod" in lines, combined
    assert "scoped:prod" in lines, combined
    assert lines.index("restart-accepted:prod") < lines.index("scoped:prod"), lines
    assert result.returncode != 0, combined
    assert "passed" not in combined.lower()


def test_prepare_producer_does_not_invoke_aggregate_snapshot_gate(tmp_path: Path) -> None:
    """Bootstrap completes scoped-only; aggregate stays on NORMAL verify.

    AGT-06: skip of verify_live_gpu_snapshots is explicit. RLSE-03: the
    registry-wide gate remains on verify_live_gpu_snapshots.
    """
    result, logged = _run_prepare_producer(tmp_path, records_name="no-aggregate.log")
    combined = result.stdout + result.stderr
    lines = logged.splitlines()
    assert "aggregate:prod" not in lines
    assert "verify:prod" not in lines
    assert "restart-accepted:prod" in lines, combined
    assert "scoped:prod" in lines, combined
    assert result.returncode == 0, combined


def test_prepare_producer_leaves_aggregate_refusal_for_missing_siblings(
    tmp_path: Path,
) -> None:
    """NORMAL verify still fails closed on missing siblings (RLSE-03, TEST-15)."""
    result, logged = _run_verify_live_gpu_snapshots(
        tmp_path, sibling_rc=1, timeout_rc=1, scoped_rc=0
    )
    combined = result.stdout + result.stderr
    lines = logged.splitlines()
    assert "aggregate:1" in lines, combined
    assert "scoped:prod" not in lines
    assert result.returncode == 1, combined


def _fresh_load_snapshot(written_at: int = 1000) -> str:
    return (
        '{"queue_depth":1,"in_flight":0,"batch_in_progress":false,'
        f'"written_at":{written_at}}}\n'
    )


def _run_scoped_producer(
    tmp_path: Path,
    *,
    env: str = "prod",
    snapshot: str | None = _fresh_load_snapshot(),
    now: int = 1000,
    stale: int = 120,
    compose: bool = True,
) -> subprocess.CompletedProcess[str]:
    remote = tmp_path / "remote"
    load_root = tmp_path / "run" / "acx-write"
    env_dir = load_root / env
    env_dir.mkdir(parents=True)
    remote.mkdir(exist_ok=True)
    if compose:
        (remote / "docker-compose.env.yml").write_text(
            "services:\n"
            "  api:\n"
            "    environment:\n"
            "      - ACX_DESCRIBE_LOAD_PATH=/run/acx-write/${ACX_ENV}/describe-load.json\n"
        )
    if snapshot is not None:
        (env_dir / "describe-load.json").write_text(snapshot)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    _write_executable(bin_dir / "sudo", '#!/usr/bin/env bash\nexec "$@"\n')
    load_root_s = str(load_root)
    remote_s = str(remote)
    rewriter = tmp_path / "rewrite-remote"
    _write_executable(
        rewriter,
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "src = sys.stdin.read()\n"
        f"src = src.replace('load_dir=\"/run/acx-write/', 'load_dir=\"{load_root_s}/')\n"
        f"src = src.replace('/opt/acx-backend/{env}', '{remote_s}')\n"
        "sys.stdout.write(src)\n",
    )
    command = f'''
source "{SCRIPT}"
GREEN=; YELLOW=; RED=; RESET=
ACX_DESCRIBE_LOAD_STALE_SECONDS={stale}
ACX_NOW_EPOCH={now}
run_with_deadline() {{ shift 2; "$@"; }}
ssh() {{
  export PATH="{bin_dir}:$PATH"
  last="${{@: -1}}"
  if [[ "$last" == "bash -s" ]]; then
    "{rewriter}" | bash -s
    exit $?
  fi
  last="${{last//\\/run\\/acx-write/{load_root_s}}}"
  bash -c "$last"
}}
verify_scoped_producer_snapshots {env}
'''
    return subprocess.run(["bash", "-c", command], text=True, capture_output=True, check=False)


def test_scoped_producer_refuses_missing_describe_load(tmp_path: Path) -> None:
    result = _run_scoped_producer(tmp_path, snapshot=None)
    combined = result.stdout + result.stderr
    assert result.returncode != 0, combined
    assert "describe-load.json" in combined
    assert "queue_depth\":0" not in combined


def test_scoped_producer_refuses_stale_describe_load(tmp_path: Path) -> None:
    result = _run_scoped_producer(tmp_path, snapshot=_fresh_load_snapshot(1), now=1000, stale=120)
    combined = result.stdout + result.stderr
    assert result.returncode != 0, combined
    assert "stale" in combined.lower()


def test_scoped_producer_refuses_invalid_schema(tmp_path: Path) -> None:
    result = _run_scoped_producer(tmp_path, snapshot='{"written_at":1000}\n')
    combined = result.stdout + result.stderr
    assert result.returncode != 0, combined
    assert "schema" in combined.lower() or "queue_depth" in combined


def test_scoped_producer_accepts_fresh_valid_load(tmp_path: Path) -> None:
    result = _run_scoped_producer(tmp_path, snapshot=_fresh_load_snapshot(1000), now=1000)
    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    assert "Scoped producer-preparation" in combined or "scoped producer" in combined.lower()
