from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROVISION = REPO_ROOT / "scripts/workstate/provision_lane_worktree.py"


def test_provision_symlinks_binaries_instead_of_dereferencing(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    worktree = tmp_path / "worktree"
    bin_dir = primary / "apps/prototype-wp-alt-context/node_modules/.bin"
    bin_dir.mkdir(parents=True)
    real = primary / "apps/prototype-wp-alt-context/node_modules/vitest/vitest.mjs"
    real.parent.mkdir(parents=True)
    real.write_text("#!/usr/bin/env node\nimport './dist/cli.js'\n", encoding="utf-8")
    (bin_dir / "vitest").symlink_to(real)
    (primary / "Makefile.d").mkdir()
    (primary / "Makefile.d/lifecycle.mk").write_text("# overlay\n", encoding="utf-8")
    worktree.mkdir()
    (worktree / "apps/prototype-wp-alt-context").mkdir(parents=True)

    completed = subprocess.run(
        [sys.executable, str(PROVISION), "--worktree", str(worktree), "--primary", str(primary)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    dest = worktree / "apps/prototype-wp-alt-context/node_modules"
    assert dest.is_symlink(), "node_modules must be a symlink, not a copied tree"
    vitest = dest / ".bin" / "vitest"
    assert vitest.is_symlink()
    assert (worktree / "Makefile.d/lifecycle.mk").read_text(encoding="utf-8") == "# overlay\n"


def test_provision_does_not_copytree_node_modules() -> None:
    source = PROVISION.read_text(encoding="utf-8")
    tree_fn = source.split("def provision_dependency_trees")[1].split("def main")[0]
    assert "copytree" not in tree_fn
    assert "os.symlink" in source
    assert "symlinks=True" in source


def test_provision_replaces_a_dereferenced_copy(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    worktree = tmp_path / "worktree"
    src = primary / "apps/prototype-wp-alt-context/node_modules"
    src.mkdir(parents=True)
    (src / ".bin").mkdir()
    (src / ".bin" / "vitest").symlink_to(src / "vitest.mjs")
    dest_root = worktree / "apps/prototype-wp-alt-context/node_modules"
    dest_root.mkdir(parents=True)
    (dest_root / ".bin").mkdir()
    (dest_root / ".bin" / "vitest").write_text("import './dist/cli.js'\n", encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(PROVISION), "--worktree", str(worktree), "--primary", str(primary)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    dest = worktree / "apps/prototype-wp-alt-context/node_modules"
    assert dest.is_symlink()
    assert dest.resolve() == src.resolve()
    assert (dest / ".bin" / "vitest").is_symlink()
