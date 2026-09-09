from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
EXPECTED_WRAPPERS = {
    REPO_ROOT / "scripts/localwp-gate-status.sh",
    REPO_ROOT / "scripts/remote_gate.sh",
}
REQUIRED_RUN_SHELL = "bash --noprofile --norc -eo pipefail {0}"
_PIPEFAIL_SET = re.compile(r"^set\s+-[^\n]*\bpipefail\b", re.MULTILINE)
# Sourced libraries inherit the caller's `set` options; POSIX /bin/sh wrappers
# with no pipelines are documented exclusions, not silent omissions (D5-AR-01).
QUARANTINED_SHELL_SCRIPTS: dict[Path, str] = {
    REPO_ROOT / "scripts/consumer-hooks/run-php-characterization.sh": "POSIX /bin/sh, no pipelines, set -eu",
    REPO_ROOT / "scripts/deploy/lib/smoke-gate.sh": "sourced library; inherits caller pipefail",
    REPO_ROOT / "scripts/deploy/lib/ocir-auth.sh": "sourced library; inherits caller pipefail",
    REPO_ROOT / "scripts/deploy/lib/fixture-denylist.sh": "sourced library; inherits caller pipefail",
    REPO_ROOT / "scripts/deploy/lib/gpu-env-contract.sh": "sourced library; inherits caller pipefail",
}


def _write_executable(path: Path, source: str) -> None:
    path.write_text(source, encoding="utf-8")
    path.chmod(0o755)


def _pipeline_wrappers() -> set[Path]:
    """Discover top-level gate wrappers that filter command output through a pipeline."""
    return {path for path in (REPO_ROOT / "scripts").glob("*gate*.sh") if "|" in path.read_text(encoding="utf-8")}


def test_pipeline_wrapper_discovery_matches_expected_inventory() -> None:
    assert _pipeline_wrappers() == EXPECTED_WRAPPERS


def _read_null_terminated_argv(path: Path) -> list[str]:
    return [part.decode() for part in path.read_bytes().split(b"\0") if part]


def test_localwp_status_propagates_a_filtered_wp_failure(tmp_path: Path) -> None:
    wp_wrapper = tmp_path / "wp-wrapper"
    _write_executable(
        wp_wrapper,
        """#!/usr/bin/env bash
case "$*" in
  *"option get siteurl"*) printf 'https://example.test\\n'; exit 23 ;;
  *"plugin status alt-context"*) printf 'Status: Active\\nVersion: 1.2.3\\n' ;;
  *"TenantIdentity"*) printf '00000000-0000-0000-0000-000000000001' ;;
  *"fingerprint"*) printf '{"fingerprint":null,"source":"default"}' ;;
  *"settings/test"*) printf '{"ok":true}' ;;
  *"/acx/v1/settings"*) printf '{"key_source":"default"}' ;;
  *) exit 2 ;;
esac
""",
    )

    completed = subprocess.run(
        [
            "bash",
            str(REPO_ROOT / "scripts/localwp-gate-status.sh"),
            "--wp-path",
            str(tmp_path / "wordpress"),
        ],
        env={**os.environ, "LOCALWP_GATE_WP_WRAPPER": str(wp_wrapper)},
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 23, (
        "localwp status masked the wp wrapper's exit 23 while trimming its output; "
        f"stdout={completed.stdout!r}; stderr={completed.stderr!r}"
    )


@pytest.mark.parametrize(
    ("failing_program", "injected_exit"),
    [
        pytest.param(None, 0, id="success-control"),
        pytest.param("free", 23, id="free-exit-23"),
        pytest.param("free", 41, id="free-exit-41"),
        pytest.param("df", 23, id="df-exit-23"),
        pytest.param("df", 41, id="df-exit-41"),
        pytest.param("make", 23, id="make-exit-23"),
        pytest.param("make", 41, id="make-exit-41"),
    ],
)
def test_remote_doctor_propagates_a_pipeline_failure_across_ssh(
    tmp_path: Path,
    failing_program: str | None,
    injected_exit: int,
) -> None:
    """Local pipefail cannot substitute for pipefail in the remote shell."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    ssh_argv_log = tmp_path / "ssh-argv"
    _write_executable(
        fake_bin / "ssh",
        """#!/usr/bin/env bash
printf '%s\\0' "$@" > "$REMOTE_GATE_TEST_SSH_ARGV_LOG"
exec bash -c "${!#}"
""",
    )
    _write_executable(
        fake_bin / "free",
        """#!/usr/bin/env bash
printf 'header\\nrow a b c d e available\\n'
[[ "${REMOTE_GATE_TEST_FAILING_PROGRAM:-}" == free ]] && exit "$REMOTE_GATE_TEST_INJECTED_EXIT"
exit 0
""",
    )
    _write_executable(
        fake_bin / "df",
        """#!/usr/bin/env bash
printf 'header\\nrow a b available\\n'
[[ "${REMOTE_GATE_TEST_FAILING_PROGRAM:-}" == df ]] && exit "$REMOTE_GATE_TEST_INJECTED_EXIT"
exit 0
""",
    )
    _write_executable(
        fake_bin / "make",
        """#!/usr/bin/env bash
printf 'GNU Make 4.4\\n'
[[ "${REMOTE_GATE_TEST_FAILING_PROGRAM:-}" == make ]] && exit "$REMOTE_GATE_TEST_INJECTED_EXIT"
exit 0
""",
    )

    completed = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts/remote_gate.sh"), "doctor"],
        cwd=REPO_ROOT,
        env={
            **os.environ,
            "HOME": str(tmp_path / "home"),
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "WORKBAY_REMOTE_GATE_HOST": "gate@example.invalid",
            "REMOTE_GATE_TEST_SSH_ARGV_LOG": str(ssh_argv_log),
            "REMOTE_GATE_TEST_FAILING_PROGRAM": failing_program or "",
            "REMOTE_GATE_TEST_INJECTED_EXIT": str(injected_exit),
        },
        text=True,
        capture_output=True,
        check=False,
    )

    argv = _read_null_terminated_argv(ssh_argv_log)
    assert argv[:-1] == [
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        "-o",
        "ServerAliveInterval=30",
        "-o",
        "ServerAliveCountMax=4",
        "gate@example.invalid",
    ]
    assert _remote_shell_enables_pipefail(argv[-1]), argv[-1][:120]
    assert completed.returncode == injected_exit, (
        f"remote doctor masked {failing_program}'s exit {injected_exit} at the SSH boundary; "
        f"stdout={completed.stdout!r}; stderr={completed.stderr!r}"
    )


def test_remote_gate_propagates_git_common_dir_discovery_failure(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(fake_bin / "git", "#!/usr/bin/env bash\nexit 23\n")

    completed = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts/remote_gate.sh"), "doctor"],
        cwd=REPO_ROOT,
        env={
            **os.environ,
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "WORKBAY_REMOTE_GATE_HOST": "gate@example.invalid",
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 23, (
        "dirname masked git rev-parse's exit 23 while discovering the common directory; "
        f"stdout={completed.stdout!r}; stderr={completed.stderr!r}"
    )


def test_remote_run_propagates_filtered_git_status_failure(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(
        fake_bin / "git",
        """#!/usr/bin/env bash
case "$1 $2" in
  "rev-parse --path-format=absolute") printf '%s\\n' "$REMOTE_GATE_TEST_COMMON_DIR" ;;
  "status --porcelain") printf 'dirty-path\\n'; exit 23 ;;
  *) echo "git should have stopped at the failed status pipeline: $*" >&2; exit 74 ;;
esac
""",
    )

    completed = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts/remote_gate.sh"), "run", "test"],
        cwd=REPO_ROOT,
        env={
            **os.environ,
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "WORKBAY_REMOTE_GATE_HOST": "gate@example.invalid",
            "WORKBAY_REMOTE_GATE_DIR": "src/repo",
            "REMOTE_GATE_TEST_COMMON_DIR": str(tmp_path / "repo" / ".git"),
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 23, (
        "remote run masked git status's exit 23 while counting filtered output; "
        f"stdout={completed.stdout!r}; stderr={completed.stderr!r}"
    )


@pytest.mark.parametrize("remote_exit", [0, 41])
def test_remote_run_pushes_scratch_ref_and_checks_out_the_pushed_sha(
    tmp_path: Path,
    remote_exit: int,
) -> None:
    """Exercise the transport contract without running Linux gate tools locally."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    call_log = tmp_path / "git-calls"
    ssh_argv_log = tmp_path / "ssh-argv"
    pushed_sha = tmp_path / "pushed-sha"
    expected_sha = "0123456789abcdef0123456789abcdef01234567"

    _write_executable(
        fake_bin / "git",
        """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$REMOTE_GATE_TEST_CALL_LOG"
case "$1 $2" in
  "rev-parse --path-format=absolute") printf '%s\\n' "$REMOTE_GATE_TEST_COMMON_DIR" ;;
  "status --porcelain") exit 0 ;;
  "rev-parse HEAD") printf '%s\\n' "$REMOTE_GATE_TEST_SHA" ;;
  "push --quiet")
    refspec="${!#}"
    if [[ "$refspec" == HEAD:refs/heads/* ]]; then
      echo 'branch-naming hook rejected transport branch' >&2
      exit 71
    fi
    [[ "$refspec" == "HEAD:refs/workbay/gate" ]] || exit 72
    printf '%s\\n' "$REMOTE_GATE_TEST_SHA" > "$REMOTE_GATE_TEST_PUSHED_SHA"
    ;;
  *) echo "unexpected git invocation: $*" >&2; exit 74 ;;
esac
""",
    )
    _write_executable(
        fake_bin / "ssh",
        """#!/usr/bin/env bash
printf '%s\\0' "$@" > "$REMOTE_GATE_TEST_SSH_ARGV_LOG"
exit "$REMOTE_GATE_TEST_SSH_EXIT"
""",
    )

    completed = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts/remote_gate.sh"), "run", "test"],
        cwd=REPO_ROOT,
        env={
            **os.environ,
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "WORKBAY_REMOTE_GATE_HOST": "gate@example.invalid",
            "WORKBAY_REMOTE_GATE_DIR": "src/repo",
            "REMOTE_GATE_TEST_CALL_LOG": str(call_log),
            "REMOTE_GATE_TEST_COMMON_DIR": str(tmp_path / "repo" / ".git"),
            "REMOTE_GATE_TEST_PUSHED_SHA": str(pushed_sha),
            "REMOTE_GATE_TEST_SHA": expected_sha,
            "REMOTE_GATE_TEST_SSH_ARGV_LOG": str(ssh_argv_log),
            "REMOTE_GATE_TEST_SSH_EXIT": str(remote_exit),
        },
        text=True,
        capture_output=True,
        check=False,
    )

    calls = call_log.read_text(encoding="utf-8").splitlines()
    ssh_argv = _read_null_terminated_argv(ssh_argv_log)
    assert completed.returncode == remote_exit, (
        f"remote run masked ssh exit {remote_exit}; stdout={completed.stdout!r}; stderr={completed.stderr!r}"
    )
    assert "push --quiet --force gate@example.invalid:src/repo HEAD:refs/workbay/gate" in calls
    assert pushed_sha.read_text(encoding="utf-8").strip() == expected_sha
    assert ssh_argv[:-1] == [
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        "-o",
        "ServerAliveInterval=30",
        "-o",
        "ServerAliveCountMax=4",
        "gate@example.invalid",
    ]
    assert _remote_shell_enables_pipefail(ssh_argv[-1]), ssh_argv[-1][:120]
    assert f"git checkout -qf {expected_sha} || exit 1" in ssh_argv[-1]


def _remote_shell_enables_pipefail(source: str) -> bool:
    """True when the first executable remote line enables pipefail (D5-AR-03).

    Flag order (`set -euo pipefail` vs `set -uo pipefail`) is not pinned; a
    commented-out or late `set` does not count.
    """
    for line in source.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        return bool(_PIPEFAIL_SET.match(stripped))
    return False


def _iter_shell_scripts() -> list[Path]:
    return sorted(path for path in (REPO_ROOT / "scripts").rglob("*.sh") if path.is_file())


def test_shell_scripts_are_pipefail_or_documented_quarantine() -> None:
    """OWNED/QUARANTINED ratchet: a new wrapper cannot silently omit pipefail."""
    missing: list[str] = []
    for path in _iter_shell_scripts():
        if path in QUARANTINED_SHELL_SCRIPTS:
            continue
        text = path.read_text(encoding="utf-8")
        if _PIPEFAIL_SET.search(text):
            continue
        missing.append(str(path.relative_to(REPO_ROOT)))
    assert missing == [], f"scripts missing set -o pipefail and not quarantined: {missing}"


def test_quarantined_shell_scripts_still_exist() -> None:
    missing = [str(path.relative_to(REPO_ROOT)) for path in QUARANTINED_SHELL_SCRIPTS if not path.is_file()]
    assert missing == [], f"quarantine entries drifted off disk: {missing}"


@dataclass(frozen=True)
class _YamlLine:
    indent: int
    content: str


def _strip_inline_comment(content: str) -> str:
    in_single = False
    in_double = False
    escaped = False
    for index, char in enumerate(content):
        if escaped:
            escaped = False
            continue
        if char == "\\" and in_double:
            escaped = True
            continue
        if char == "'" and not in_double:
            in_single = not in_single
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            continue
        if char == "#" and not in_single and not in_double:
            return content[:index].rstrip()
    return content.rstrip()


def _yaml_lines(text: str) -> list[_YamlLine]:
    lines: list[_YamlLine] = []
    for raw in text.splitlines():
        if not raw.strip():
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        content = _strip_inline_comment(raw.lstrip(" "))
        if not content or content.startswith("#"):
            continue
        lines.append(_YamlLine(indent, content))
    return lines


def _parse_yaml_scalar(raw: str) -> object:
    token = raw.strip()
    if token in {"", "~", "null", "Null", "NULL"}:
        return None
    if token in {"true", "True", "TRUE"}:
        return True
    if token in {"false", "False", "FALSE"}:
        return False
    if len(token) >= 2 and token[0] == token[-1] and token[0] in {"'", '"'}:
        return token[1:-1]
    if token.startswith("[") and token.endswith("]"):
        inner = token[1:-1].strip()
        if not inner:
            return []
        parts: list[str] = []
        buf: list[str] = []
        in_single = in_double = False
        for char in inner:
            if char == "'" and not in_double:
                in_single = not in_single
            elif char == '"' and not in_single:
                in_double = not in_double
            elif char == "," and not in_single and not in_double:
                parts.append("".join(buf))
                buf = []
                continue
            buf.append(char)
        parts.append("".join(buf))
        return [_parse_yaml_scalar(part) for part in parts]
    if re.fullmatch(r"-?\d+", token):
        return int(token)
    return token


def _split_key(content: str) -> tuple[str, str]:
    if content.startswith("- "):
        content = content[2:].strip()
    elif content == "-":
        return "", ""
    key, sep, rest = content.partition(":")
    if not sep:
        return content, ""
    return key.strip().strip("'\""), rest.strip()


def _parse_yaml_block_scalar(lines: list[_YamlLine], index: int, parent_indent: int) -> tuple[str, int]:
    body: list[str] = []
    while index < len(lines) and lines[index].indent > parent_indent:
        body.append(lines[index].content)
        index += 1
    return "\n".join(body), index


def _parse_yaml_value(lines: list[_YamlLine], index: int, min_indent: int) -> tuple[object, int]:
    if index >= len(lines) or lines[index].indent < min_indent:
        return None, index
    if lines[index].content.startswith("-"):
        return _parse_yaml_seq(lines, index, lines[index].indent)
    return _parse_yaml_map(lines, index, lines[index].indent)


def _parse_yaml_map(lines: list[_YamlLine], index: int, indent: int) -> tuple[dict[str, object], int]:
    mapping: dict[str, object] = {}
    while index < len(lines) and lines[index].indent == indent:
        if lines[index].content.startswith("-"):
            break
        key, rest = _split_key(lines[index].content)
        index += 1
        if rest in {"|", "|-", "|+", ">", ">-", ">+"}:
            value, index = _parse_yaml_block_scalar(lines, index, indent)
        elif rest:
            value = _parse_yaml_scalar(rest)
        elif index < len(lines) and lines[index].indent > indent:
            value, index = _parse_yaml_value(lines, index, indent + 1)
        else:
            value = None
        mapping[key] = value
    return mapping, index


def _parse_yaml_seq(lines: list[_YamlLine], index: int, indent: int) -> tuple[list[object], int]:
    sequence: list[object] = []
    while index < len(lines) and lines[index].indent == indent and lines[index].content.startswith("-"):
        item = lines[index].content[1:].strip()
        index += 1
        if not item:
            value, index = _parse_yaml_value(lines, index, indent + 1)
        elif ":" in item:
            key, rest = _split_key(item)
            if rest in {"|", "|-", "|+", ">", ">-", ">+"}:
                nested_value, index = _parse_yaml_block_scalar(lines, index, indent)
            elif rest:
                nested_value = _parse_yaml_scalar(rest)
            else:
                nested_value = None
            mapping: dict[str, object] = {key: nested_value}
            if index < len(lines) and lines[index].indent > indent:
                extra, index = _parse_yaml_map(lines, index, lines[index].indent)
                mapping.update(extra)
            value = mapping
        else:
            value = _parse_yaml_scalar(item)
        sequence.append(value)
    return sequence, index


def _load_gha_yaml(path: Path) -> dict[str, object]:
    """Structurally load a GitHub Actions workflow without PyYAML (D5-AR-07)."""
    lines = _yaml_lines(path.read_text(encoding="utf-8"))
    value, index = _parse_yaml_value(lines, 0, 0)
    leftover = lines[index].content if index < len(lines) else ""
    assert index == len(lines), f"{path} YAML subset parser stopped at {leftover!r}"
    if not isinstance(value, dict):
        raise AssertionError(f"{path} did not parse as a mapping")
    return value


def _nested_map(payload: object, *keys: str) -> dict[str, object]:
    current: object = payload
    for key in keys:
        if not isinstance(current, dict):
            return {}
        current = current.get(key)
    return current if isinstance(current, dict) else {}


def _workflow_paths_with_run_steps() -> list[Path]:
    paths: list[Path] = []
    workflow_dir = REPO_ROOT / ".github" / "workflows"
    for workflow_path in sorted(workflow_dir.glob("*.y*ml")):
        workflow = _load_gha_yaml(workflow_path)
        jobs = workflow.get("jobs", {}) if isinstance(workflow.get("jobs"), dict) else {}
        if any(
            isinstance(step, dict) and "run" in step
            for job in jobs.values()
            if isinstance(job, dict)
            for step in job.get("steps", [])
            if isinstance(job.get("steps"), list)
        ):
            paths.append(workflow_path)
    return paths


def _unsafe_run_steps(workflow: dict[str, object], workflow_name: str) -> list[str]:
    unsafe: list[str] = []
    workflow_shell = _nested_map(workflow, "defaults", "run").get("shell")
    jobs = workflow.get("jobs", {})
    if not isinstance(jobs, dict):
        return [f"{workflow_name}:<jobs>"]
    for job_name, job in jobs.items():
        if not isinstance(job, dict):
            continue
        job_shell = _nested_map(job, "defaults", "run").get("shell", workflow_shell)
        for step in job.get("steps", []) if isinstance(job.get("steps"), list) else []:
            if not isinstance(step, dict) or "run" not in step:
                continue
            effective_shell = step.get("shell", job_shell)
            if effective_shell != REQUIRED_RUN_SHELL:
                unsafe.append(f"{workflow_name}:{job_name}:{step.get('name', '<unnamed>')}")
    return unsafe


def test_every_workflow_run_step_uses_fail_closed_bash() -> None:
    unsafe: list[str] = []
    for workflow_path in _workflow_paths_with_run_steps():
        unsafe.extend(_unsafe_run_steps(_load_gha_yaml(workflow_path), workflow_path.name))
    assert unsafe == [], f"workflow run steps without {REQUIRED_RUN_SHELL!r}: {unsafe}"


def test_workflow_shell_survives_working_directory_before_shell(tmp_path: Path) -> None:
    workflow_path = tmp_path / "sample.yml"
    workflow_path.write_text(
        "jobs:\n"
        "  build:\n"
        "    defaults:\n"
        "      run:\n"
        "        working-directory: apps/example\n"
        "        shell: bash --noprofile --norc -eo pipefail {0}\n"
        "    steps:\n"
        "      - name: hello\n"
        "        working-directory: apps/example\n"
        "        run: echo hi | cat\n",
        encoding="utf-8",
    )
    assert _unsafe_run_steps(_load_gha_yaml(workflow_path), workflow_path.name) == []


def test_remote_gate_no_args_prints_usage_and_does_not_run() -> None:
    completed = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts/remote_gate.sh")],
        cwd=REPO_ROOT,
        env={**os.environ, "WORKBAY_REMOTE_GATE_HOST": "gate@example.invalid"},
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "scripts/remote_gate.sh run" in completed.stdout + completed.stderr
    assert "pushing" not in (completed.stdout + completed.stderr).lower()


def test_remote_gate_help_does_not_require_a_host() -> None:
    env = {**os.environ}
    env.pop("WORKBAY_REMOTE_GATE_HOST", None)
    completed = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts/remote_gate.sh"), "--help"],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "Usage:" in completed.stdout + completed.stderr
