"""Regression tests for retaining the Caddyfile rollback copy on restore failure."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "deploy" / "sync-demo.sh"


def _remote_body(remote_dir: Path) -> str:
    script = SCRIPT.read_text(encoding="utf-8")
    section = script.split("Validate staged Caddy config, then promote", 1)[1]
    match = re.search(r"\$SSH bash -se <<'EOF'\n(.*?)\nEOF", section, re.DOTALL)
    assert match is not None, "could not find the Caddy promotion remote body"
    return match.group(1).replace("/opt/acx-backend", str(remote_dir))


def test_failed_caddyfile_restore_retains_rollback_copy(tmp_path: Path) -> None:
    remote_dir = tmp_path / "remote"
    remote_dir.mkdir()
    (remote_dir / "Caddyfile").write_text("previous valid config\n", encoding="utf-8")
    restore_match = re.search(
        r"(?ms)^restore_caddyfile\(\) \{\n.*?^\}",
        _remote_body(remote_dir),
    )
    assert restore_match is not None, "could not find restore_caddyfile in the remote body"

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    real_cat = shutil.which("cat")
    assert real_cat is not None
    (bin_dir / "cat").write_text(
        "#!/usr/bin/env bash\n"
        "if [[ \"${FAIL_RESTORE_WRITE:-0}\" == 1 && \"$#\" == 1 ]]; then\n"
        "  printf 'partial restore'\n"
        "  exit 23\n"
        "fi\n"
        "exec \"$REAL_CAT\" \"$@\"\n",
        encoding="utf-8",
    )
    (bin_dir / "cat").chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["REAL_CAT"] = real_cat
    env["FAIL_RESTORE_WRITE"] = "1"
    env["REMOTE_DIR"] = str(remote_dir)
    env["TMPDIR"] = str(remote_dir)
    script = (
        'set -euo pipefail\ncd "$REMOTE_DIR"\n'
        'rollback_file="$(mktemp)"\ncp -p Caddyfile "$rollback_file"\n'
        f"{restore_match.group(0)}\n"
        "if restore_caddyfile; then\n"
        "  echo 'restore unexpectedly succeeded' >&2\n"
        "  exit 1\n"
        "fi\n"
    )
    result = subprocess.run(
        ["bash", "-se"],
        input=script,
        cwd=remote_dir,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    retained_notice = "rollback file retained at "
    assert retained_notice in result.stderr, result.stdout + result.stderr
    rollback_file = Path(result.stderr.split(retained_notice, 1)[1].splitlines()[0])
    assert rollback_file.read_text(encoding="utf-8") == "previous valid config\n"
