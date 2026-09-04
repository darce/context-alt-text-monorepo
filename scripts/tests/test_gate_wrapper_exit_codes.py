from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_executable(path: Path, source: str) -> None:
    path.write_text(source, encoding="utf-8")
    path.chmod(0o755)


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


def test_remote_doctor_propagates_a_pipeline_failure_across_ssh(tmp_path: Path) -> None:
    """Local pipefail cannot substitute for pipefail in the remote shell."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(
        fake_bin / "ssh",
        '#!/usr/bin/env bash\nexec bash -c "${!#}"\n',
    )
    _write_executable(
        fake_bin / "free",
        "#!/usr/bin/env bash\nprintf 'header\\nrow a b c d e available\\n'\nexit 23\n",
    )

    completed = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts/remote_gate.sh"), "doctor"],
        cwd=REPO_ROOT,
        env={
            **os.environ,
            "HOME": str(tmp_path / "home"),
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "WORKBAY_REMOTE_GATE_HOST": "gate@example.invalid",
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 23, (
        "remote doctor masked free's exit 23 at the SSH boundary; "
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
    _write_executable(fake_bin / "ssh", '#!/usr/bin/env bash\nexec bash -c "${!#}"\n')
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
        },
        text=True,
        capture_output=True,
        check=False,
    )

    calls = call_log.read_text(encoding="utf-8").splitlines()
    assert completed.returncode == 0, f"remote run failed; stdout={completed.stdout!r}; stderr={completed.stderr!r}"
    assert "push --quiet --force gate@example.invalid:src/repo HEAD:refs/workbay/gate" in calls
    assert f"checkout -qf {expected_sha}" in calls
