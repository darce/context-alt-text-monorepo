from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
EXPECTED_WRAPPERS = {
    REPO_ROOT / "scripts/localwp-gate-status.sh",
    REPO_ROOT / "scripts/remote_gate.sh",
}


def _write_executable(path: Path, source: str) -> None:
    path.write_text(source, encoding="utf-8")
    path.chmod(0o755)


def _pipeline_wrappers() -> set[Path]:
    """Discover top-level gate wrappers that filter command output through a pipeline."""
    return {
        path
        for path in (REPO_ROOT / "scripts").glob("*gate*.sh")
        if "|" in path.read_text(encoding="utf-8")
    }


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
    assert argv[-1].startswith("set -euo pipefail\n")
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


def test_remote_run_pushes_scratch_ref_and_checks_out_the_pushed_sha(tmp_path: Path) -> None:
    """Run the real transport path through a branch-hook-enforcing fake git."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    remote_home = tmp_path / "remote-home"
    remote_clone = remote_home / "src" / "repo"
    remote_clone.mkdir(parents=True)
    (remote_clone / ".remote-gate-clone").touch()
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
  "checkout -qf")
    [[ "$3" == "$(<"$REMOTE_GATE_TEST_PUSHED_SHA")" ]] || exit 73
    ;;
  "update-ref -d"|"clean -fdq") exit 0 ;;
  *) echo "unexpected git invocation: $*" >&2; exit 74 ;;
esac
""",
    )
    _write_executable(
        fake_bin / "ssh",
        """#!/usr/bin/env bash
printf '%s\\0' "$@" > "$REMOTE_GATE_TEST_SSH_ARGV_LOG"
exec bash -c "${!#}"
""",
    )
    _write_executable(
        fake_bin / "make",
        """#!/usr/bin/env bash
if [[ "$*" == "-n gate-preflight" ]]; then exit 2; fi
if [[ "$*" == "test" ]]; then exit 0; fi
echo "unexpected make invocation: $*" >&2
exit 75
""",
    )

    completed = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts/remote_gate.sh"), "run", "test"],
        cwd=REPO_ROOT,
        env={
            **os.environ,
            "HOME": str(remote_home),
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "WORKBAY_REMOTE_GATE_HOST": "gate@example.invalid",
            "WORKBAY_REMOTE_GATE_DIR": "src/repo",
            "REMOTE_GATE_TEST_CALL_LOG": str(call_log),
            "REMOTE_GATE_TEST_COMMON_DIR": str(tmp_path / "repo" / ".git"),
            "REMOTE_GATE_TEST_PUSHED_SHA": str(pushed_sha),
            "REMOTE_GATE_TEST_SHA": expected_sha,
            "REMOTE_GATE_TEST_SSH_ARGV_LOG": str(ssh_argv_log),
        },
        text=True,
        capture_output=True,
        check=False,
    )

    calls = call_log.read_text(encoding="utf-8").splitlines()
    ssh_argv = _read_null_terminated_argv(ssh_argv_log)
    assert completed.returncode == 0, f"remote run failed; stdout={completed.stdout!r}; stderr={completed.stderr!r}"
    assert "push --quiet --force gate@example.invalid:src/repo HEAD:refs/workbay/gate" in calls
    assert f"checkout -qf {expected_sha}" in calls
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
    assert ssh_argv[-1].startswith("set -euo pipefail\n")
