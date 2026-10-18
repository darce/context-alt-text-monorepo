from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LOCKFILE = "apps/prototype-wp-alt-context/composer.lock"


def test_plugin_composer_lock_exists_and_is_tracked() -> None:
    path = REPO_ROOT / LOCKFILE
    assert path.is_file(), f"missing {LOCKFILE}"

    listed = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "--", LOCKFILE],
        check=False,
        capture_output=True,
        text=True,
    )
    assert listed.returncode == 0, listed.stderr
    assert listed.stdout.strip() == LOCKFILE, f"{LOCKFILE} is not tracked"

    ignored = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "check-ignore", "-q", "--", LOCKFILE],
        check=False,
        capture_output=True,
        text=True,
    )
    assert ignored.returncode == 1, f"{LOCKFILE} is ignored by git"
