from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_executable(path: Path, source: str) -> None:
    path.write_text(source, encoding="utf-8")
    path.chmod(0o755)


def _pipeline_wrappers() -> list[Path]:
    """Discover production wrappers whose filtered output needs pipefail."""
    wrappers = []
    for path in (REPO_ROOT / "scripts").rglob("*.sh"):
        if "tests" in path.relative_to(REPO_ROOT / "scripts").parts:
            continue
        source = path.read_text(encoding="utf-8")
        if re.search(r"(?m)^set -[^\n]*e", source) and re.search(
            r"\|\s*(?:head|tail)\b", source
        ):
            wrappers.append(path)
    return sorted(wrappers)


@pytest.mark.parametrize(
    "wrapper",
    _pipeline_wrappers(),
    ids=lambda path: str(path.relative_to(REPO_ROOT)),
)
def test_pipeline_wrappers_propagate_the_inner_runner_exit(
    wrapper: Path, tmp_path: Path
) -> None:
    """Exercise each discovered wrapper's options with a real failing pipeline."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(fake_bin / "inner-runner", "#!/usr/bin/env bash\nexit 23\n")

    source = wrapper.read_text(encoding="utf-8")
    instrumented, replacements = re.subn(
        r"(?m)^(set -[^\n]*e[^\n]*)$",
        r"\1\ninner-runner | tail -n 1\nexit 0",
        source,
        count=1,
    )
    assert replacements == 1, f"could not instrument {wrapper}"
    executable = tmp_path / wrapper.name
    _write_executable(executable, instrumented)

    completed = subprocess.run(
        ["bash", str(executable)],
        env={**os.environ, "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"},
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 23, (
        f"{wrapper.relative_to(REPO_ROOT)} reported success after its inner runner exited 23 "
        "through an output-tail pipeline"
    )


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
        "#!/usr/bin/env bash\nexec bash -c \"${!#}\"\n",
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
