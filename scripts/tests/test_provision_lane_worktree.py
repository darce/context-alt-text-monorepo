from __future__ import annotations

import os
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


def test_provision_preserves_symlinked_overlay(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    worktree = tmp_path / "worktree"
    overlay = primary / "plugin-overlay"
    overlay.mkdir(parents=True)
    (overlay / "lifecycle.mk").write_text("# live overlay\n", encoding="utf-8")
    (primary / "Makefile.d").symlink_to(overlay, target_is_directory=True)
    worktree.mkdir()

    completed = subprocess.run(
        [sys.executable, str(PROVISION), "--worktree", str(worktree), "--primary", str(primary)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    dest = worktree / "Makefile.d"
    assert dest.is_symlink(), "top-level plugin overlay links must not be dereferenced"
    assert os.readlink(dest) == str(overlay)
    assert (dest / "lifecycle.mk").read_text(encoding="utf-8") == "# live overlay\n"


def test_provision_relocates_relative_overlay_symlink(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    worktree = tmp_path / "separate-parent" / "worktree"
    overlay = primary / "overlay"
    overlay.mkdir(parents=True)
    (overlay / "lifecycle.mk").write_text("# live overlay\n", encoding="utf-8")
    (primary / "Makefile.d").symlink_to("../primary/overlay", target_is_directory=True)
    worktree.mkdir(parents=True)

    completed = subprocess.run(
        [sys.executable, str(PROVISION), "--worktree", str(worktree), "--primary", str(primary)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    dest = worktree / "Makefile.d"
    assert dest.is_symlink()
    assert dest.resolve() == overlay.resolve()
    assert (dest / "lifecycle.mk").read_text(encoding="utf-8") == "# live overlay\n"


def test_provision_does_not_overwrite_tracked_overlay_files(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    worktree = tmp_path / "worktree"
    primary.mkdir()
    worktree.mkdir()
    (primary / ".gitignore").write_text("Makefile.d/*\n!Makefile.d/demo-auth.mk\n", encoding="utf-8")
    overlay = primary / "Makefile.d"
    overlay.mkdir()
    (overlay / "demo-auth.mk").write_text("# primary tracked copy\n", encoding="utf-8")
    (overlay / "lifecycle.mk").write_text("# ignored overlay\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(primary), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(primary), "add", ".gitignore", "Makefile.d/demo-auth.mk"], check=True)

    destination_overlay = worktree / "Makefile.d"
    destination_overlay.mkdir()
    (destination_overlay / "demo-auth.mk").write_text("# linked branch copy\n", encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(PROVISION), "--worktree", str(worktree), "--primary", str(primary)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert (destination_overlay / "demo-auth.mk").read_text(encoding="utf-8") == "# linked branch copy\n"
    assert (destination_overlay / "lifecycle.mk").read_text(encoding="utf-8") == "# ignored overlay\n"


def test_provision_fails_closed_when_git_manifest_lookup_fails(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    worktree = tmp_path / "worktree"
    fake_bin = tmp_path / "bin"
    (primary / ".git").mkdir(parents=True)
    (primary / "Makefile.d").mkdir()
    (primary / "Makefile.d" / "primary.mk").write_text("# primary\n", encoding="utf-8")
    worktree.mkdir()
    (worktree / "Makefile.d").mkdir()
    tracked_copy = worktree / "Makefile.d" / "primary.mk"
    tracked_copy.write_text("# branch-owned\n", encoding="utf-8")
    fake_bin.mkdir()
    fake_git = fake_bin / "git"
    fake_git.write_text("#!/usr/bin/env bash\necho 'simulated git failure' >&2\nexit 42\n", encoding="utf-8")
    fake_git.chmod(0o755)

    completed = subprocess.run(
        [sys.executable, str(PROVISION), "--worktree", str(worktree), "--primary", str(primary)],
        env={**os.environ, "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"},
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "refusing overlay copy" in completed.stderr
    assert tracked_copy.read_text(encoding="utf-8") == "# branch-owned\n"


def test_provision_does_not_copytree_node_modules() -> None:
    source = PROVISION.read_text(encoding="utf-8")
    tree_fn = source.split("def provision_dependency_trees")[1].split("def main")[0]
    assert "copytree" not in tree_fn
    assert "os.symlink" in source
    assert "symlinks=True" in source


def test_provision_does_not_destroy_same_path_dependency_trees(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    src = checkout / "apps/prototype-wp-alt-context/node_modules"
    src.mkdir(parents=True)
    marker = src / "keep-me"
    marker.write_text("payload\n", encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(PROVISION), "--worktree", str(checkout), "--primary", str(checkout)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert src.is_dir() and not src.is_symlink()
    assert marker.read_text(encoding="utf-8") == "payload\n"


def test_provision_skips_dependency_trees_when_worktree_is_primary_clone(tmp_path: Path) -> None:
    worktree = tmp_path / "clone"
    worktree.mkdir()
    subprocess.run(["git", "-C", str(worktree), "init", "-q"], check=True)
    src = worktree / "apps/prototype-wp-alt-context/node_modules"
    src.mkdir(parents=True)
    (src / "keep-me").write_text("payload\n", encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(PROVISION), "--worktree", str(worktree)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert src.is_dir() and not src.is_symlink()
    assert (src / "keep-me").read_text(encoding="utf-8") == "payload\n"


def test_provision_fails_closed_when_primary_checkout_lookup_fails(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    src = worktree / "apps/prototype-wp-alt-context/node_modules"
    src.mkdir(parents=True)
    (src / "keep-me").write_text("payload\n", encoding="utf-8")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_git = fake_bin / "git"
    fake_git.write_text("#!/usr/bin/env bash\necho 'simulated git failure' >&2\nexit 42\n", encoding="utf-8")
    fake_git.chmod(0o755)

    completed = subprocess.run(
        [sys.executable, str(PROVISION), "--worktree", str(worktree)],
        env={**os.environ, "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"},
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "refusing to guess the primary checkout" in completed.stderr
    assert src.is_dir() and not src.is_symlink()
    assert (src / "keep-me").read_text(encoding="utf-8") == "payload\n"


def test_provision_relocates_nested_ignored_overlay_symlink(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    worktree = tmp_path / "separate-parent" / "worktree"
    primary.mkdir()
    worktree.mkdir(parents=True)
    (primary / ".gitignore").write_text("Makefile.d/*\n!Makefile.d/tracked.mk\n", encoding="utf-8")
    overlay = primary / "Makefile.d"
    overlay.mkdir()
    (overlay / "tracked.mk").write_text("# tracked overlay\n", encoding="utf-8")
    shared = primary / "shared"
    shared.mkdir()
    (shared / "lifecycle.mk").write_text("# shared overlay\n", encoding="utf-8")
    (overlay / "lifecycle.mk").symlink_to("../shared/lifecycle.mk")
    subprocess.run(["git", "-C", str(primary), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(primary), "add", ".gitignore", "Makefile.d/tracked.mk"], check=True)

    completed = subprocess.run(
        [sys.executable, str(PROVISION), "--worktree", str(worktree), "--primary", str(primary)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    dest = worktree / "Makefile.d" / "lifecycle.mk"
    assert dest.is_symlink()
    assert dest.resolve() == (shared / "lifecycle.mk").resolve()
    assert dest.read_text(encoding="utf-8") == "# shared overlay\n"


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
