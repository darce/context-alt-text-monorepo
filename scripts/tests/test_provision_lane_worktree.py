from __future__ import annotations

import hashlib
import importlib.util
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
    _write_lockfiles(primary, '{"lock":"node"}\n', '{"lock":"vendor"}\n')
    _write_lockfiles(worktree, '{"lock":"node"}\n', '{"lock":"vendor"}\n')

    completed = subprocess.run(
        [
            sys.executable,
            str(PROVISION),
            "--worktree",
            str(worktree),
            "--primary",
            str(primary),
            "--fixture-mode",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    dest = worktree / "apps/prototype-wp-alt-context/node_modules"
    src = primary / "apps/prototype-wp-alt-context/node_modules"
    assert dest.is_symlink(), "node_modules must be a symlink, not a copied tree"
    assert dest.resolve() != src.resolve()
    assert ".acx-dep-cache" in dest.resolve().parts
    vitest = dest / ".bin" / "vitest"
    assert vitest.is_symlink()
    (src / ".bin" / "vitest").unlink()
    (src / ".bin" / "vitest").write_text("dereferenced\n", encoding="utf-8")
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
        [
            sys.executable,
            str(PROVISION),
            "--worktree",
            str(worktree),
            "--primary",
            str(primary),
            "--fixture-mode",
        ],
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
        [
            sys.executable,
            str(PROVISION),
            "--worktree",
            str(worktree),
            "--primary",
            str(primary),
            "--fixture-mode",
        ],
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


def test_provision_does_not_copytree_node_modules(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    worktree = tmp_path / "worktree"
    src = primary / "apps/prototype-wp-alt-context/node_modules"
    bin_dir = src / ".bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "vitest").symlink_to(src / "vitest.mjs")
    (src / "pkg").write_text("from-primary\n", encoding="utf-8")
    _write_lockfiles(primary, '{"lock":"node"}\n', '{"lock":"vendor"}\n')
    worktree.mkdir()
    _write_lockfiles(worktree, '{"lock":"node"}\n', '{"lock":"vendor"}\n')

    completed = subprocess.run(
        [
            sys.executable,
            str(PROVISION),
            "--worktree",
            str(worktree),
            "--primary",
            str(primary),
            "--fixture-mode",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    dest = worktree / "apps/prototype-wp-alt-context/node_modules"
    assert dest.is_symlink()
    assert dest.resolve() != src.resolve()
    assert dest.resolve().is_dir()
    assert not dest.resolve().is_symlink()
    assert (dest / ".bin" / "vitest").is_symlink()
    (src / "pkg").write_text("mutated-primary\n", encoding="utf-8")
    assert (dest / "pkg").read_text(encoding="utf-8") == "from-primary\n"


def test_provision_does_not_destroy_same_path_dependency_trees(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    src = checkout / "apps/prototype-wp-alt-context/node_modules"
    src.mkdir(parents=True)
    marker = src / "keep-me"
    marker.write_text("payload\n", encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            str(PROVISION),
            "--worktree",
            str(checkout),
            "--primary",
            str(checkout),
            "--fixture-mode",
        ],
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


def test_explicit_missing_primary_fails_before_touching(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    overlay = worktree / "Makefile.d"
    overlay.mkdir()
    tracked = overlay / "demo-auth.mk"
    tracked.write_text("# branch-owned\n", encoding="utf-8")
    missing = tmp_path / "no-such-primary"

    completed = subprocess.run(
        [sys.executable, str(PROVISION), "--worktree", str(worktree), "--primary", str(missing)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "does not exist" in completed.stderr
    assert tracked.read_text(encoding="utf-8") == "# branch-owned\n"
    assert list(overlay.iterdir()) == [tracked]


def test_explicit_non_git_primary_fails_before_touching(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    worktree = tmp_path / "worktree"
    primary.mkdir()
    (primary / "Makefile.d").mkdir()
    (primary / "Makefile.d" / "lifecycle.mk").write_text("# overlay\n", encoding="utf-8")
    worktree.mkdir()
    dest = worktree / "Makefile.d"
    dest.mkdir()
    tracked = dest / "demo-auth.mk"
    tracked.write_text("# branch-owned\n", encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(PROVISION), "--worktree", str(worktree), "--primary", str(primary)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "not a Git checkout" in completed.stderr
    assert tracked.read_text(encoding="utf-8") == "# branch-owned\n"
    assert not (dest / "lifecycle.mk").exists()


def test_provision_refuses_secure_offload_marker_without_copying(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    worktree = tmp_path / "worktree"
    src = primary / "apps/prototype-wp-alt-context/node_modules"
    src.mkdir(parents=True)
    (src / "secret-dep").write_text("from-primary\n", encoding="utf-8")
    overlay = primary / "Makefile.d"
    overlay.mkdir()
    (overlay / "lifecycle.mk").write_text("# ignored overlay\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(primary), "init", "-q"], check=True)
    worktree.mkdir()
    (worktree / ".acx-secure-offload").write_text("", encoding="utf-8")
    dest_parent = worktree / "apps/prototype-wp-alt-context"
    dest_parent.mkdir(parents=True)

    completed = subprocess.run(
        [sys.executable, str(PROVISION), "--worktree", str(worktree), "--primary", str(primary)],
        check=False,
        capture_output=True,
        text=True,
    )

    dest = dest_parent / "node_modules"
    assert completed.returncode != 0
    assert "refusing" in completed.stderr
    assert "secure-offload" in completed.stderr
    assert "unrecognized arguments" not in completed.stderr
    assert not dest.exists()
    assert not dest.is_symlink()
    assert not (worktree / "Makefile.d").exists()


def test_provision_refuses_secure_offload_flag_without_marker(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    worktree = tmp_path / "worktree"
    src = primary / "apps/prototype-wp-alt-context/node_modules"
    src.mkdir(parents=True)
    (src / "secret-dep").write_text("from-primary\n", encoding="utf-8")
    (primary / "Makefile.d").mkdir()
    (primary / "Makefile.d" / "lifecycle.mk").write_text("# overlay\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(primary), "init", "-q"], check=True)
    worktree.mkdir()
    (worktree / "apps/prototype-wp-alt-context").mkdir(parents=True)

    completed = subprocess.run(
        [
            sys.executable,
            str(PROVISION),
            "--worktree",
            str(worktree),
            "--primary",
            str(primary),
            "--secure-offload",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    dest = worktree / "apps/prototype-wp-alt-context" / "node_modules"
    assert completed.returncode != 0
    assert "refusing" in completed.stderr
    assert "secure-offload" in completed.stderr
    assert "unrecognized arguments" not in completed.stderr
    assert not dest.exists()
    assert not dest.is_symlink()
    assert not (worktree / "Makefile.d").exists()


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
    _write_lockfiles(primary, '{"lock":"node"}\n', '{"lock":"vendor"}\n')
    _write_lockfiles(worktree, '{"lock":"node"}\n', '{"lock":"vendor"}\n')

    completed = subprocess.run(
        [
            sys.executable,
            str(PROVISION),
            "--worktree",
            str(worktree),
            "--primary",
            str(primary),
            "--fixture-mode",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    dest = worktree / "apps/prototype-wp-alt-context/node_modules"
    assert dest.is_symlink()
    assert dest.resolve() != src.resolve()
    assert ".acx-dep-cache" in dest.resolve().parts
    assert (dest / ".bin" / "vitest").is_symlink()


def _write_lockfiles(root: Path, package_lock: str, composer_lock: str) -> None:
    app = root / "apps/prototype-wp-alt-context"
    app.mkdir(parents=True, exist_ok=True)
    (app / "package-lock.json").write_text(package_lock, encoding="utf-8")
    (app / "composer.lock").write_text(composer_lock, encoding="utf-8")


def test_provision_links_when_lockfiles_match(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    worktree = tmp_path / "worktree"
    src = primary / "apps/prototype-wp-alt-context/node_modules"
    src.mkdir(parents=True)
    (src / "pkg").write_text("from-primary\n", encoding="utf-8")
    vendor = primary / "apps/prototype-wp-alt-context/vendor"
    vendor.mkdir(parents=True)
    (vendor / "pkg").write_text("from-primary-vendor\n", encoding="utf-8")
    _write_lockfiles(primary, '{"lock":"a"}\n', '{"lock":"b"}\n')
    worktree.mkdir()
    _write_lockfiles(worktree, '{"lock":"a"}\n', '{"lock":"b"}\n')

    completed = subprocess.run(
        [
            sys.executable,
            str(PROVISION),
            "--worktree",
            str(worktree),
            "--primary",
            str(primary),
            "--fixture-mode",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    dest = worktree / "apps/prototype-wp-alt-context/node_modules"
    assert dest.is_symlink()
    assert dest.resolve() != src.resolve()
    assert ".acx-dep-cache" in dest.resolve().parts
    sidecar = worktree / "apps/prototype-wp-alt-context/.acx-dep-source"
    assert sidecar.is_file()
    payload = sidecar.read_text(encoding="utf-8")
    assert "node_modules" in payload
    assert "vendor" in payload
    assert "sha256" in payload
    assert (worktree / "apps/prototype-wp-alt-context/vendor").is_symlink()
    assert (worktree / "apps/prototype-wp-alt-context/vendor").resolve() != vendor.resolve()


def test_provision_refuses_symlink_when_lockfiles_differ(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    worktree = tmp_path / "worktree"
    src = primary / "apps/prototype-wp-alt-context/node_modules"
    src.mkdir(parents=True)
    (src / "pkg").write_text("from-primary\n", encoding="utf-8")
    _write_lockfiles(primary, '{"lock":"primary"}\n', '{"lock":"vendor"}\n')
    worktree.mkdir()
    _write_lockfiles(worktree, '{"lock":"lane"}\n', '{"lock":"vendor"}\n')

    completed = subprocess.run(
        [
            sys.executable,
            str(PROVISION),
            "--worktree",
            str(worktree),
            "--primary",
            str(primary),
            "--fixture-mode",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    dest = worktree / "apps/prototype-wp-alt-context/node_modules"
    assert completed.returncode != 0
    assert "install dependencies in the lane" in completed.stderr
    assert not dest.exists()
    assert not dest.is_symlink()
    assert not (worktree / "apps/prototype-wp-alt-context/.acx-dep-source").exists()


def test_provision_keyed_cache_isolates_primary_mutations(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    worktree = tmp_path / "worktree"
    src = primary / "apps/prototype-wp-alt-context/node_modules"
    src.mkdir(parents=True)
    (src / "pkg").write_text("from-primary\n", encoding="utf-8")
    bin_dir = src / ".bin"
    bin_dir.mkdir()
    (bin_dir / "vitest").symlink_to(src / "vitest.mjs")
    _write_lockfiles(primary, '{"lock":"frozen"}\n', '{"lock":"vendor"}\n')
    worktree.mkdir()
    _write_lockfiles(worktree, '{"lock":"frozen"}\n', '{"lock":"vendor"}\n')

    completed = subprocess.run(
        [
            sys.executable,
            str(PROVISION),
            "--worktree",
            str(worktree),
            "--primary",
            str(primary),
            "--fixture-mode",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    dest = worktree / "apps/prototype-wp-alt-context/node_modules"
    assert dest.is_symlink()
    assert dest.resolve() != src.resolve()
    assert (dest / "pkg").read_text(encoding="utf-8") == "from-primary\n"
    assert (dest / ".bin" / "vitest").is_symlink()

    (src / "pkg").write_text("mutated-primary\n", encoding="utf-8")
    (bin_dir / "vitest").unlink()
    (bin_dir / "vitest").write_text("dereferenced\n", encoding="utf-8")
    assert (dest / "pkg").read_text(encoding="utf-8") == "from-primary\n"
    assert (dest / ".bin" / "vitest").is_symlink()


def test_provision_migrates_direct_primary_symlink_to_frozen_cache(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    worktree = tmp_path / "worktree"
    src = primary / "apps/prototype-wp-alt-context/node_modules"
    src.mkdir(parents=True)
    (src / "pkg").write_text("from-primary\n", encoding="utf-8")
    _write_lockfiles(primary, '{"lock":"node"}\n', '{"lock":"vendor"}\n')
    worktree.mkdir()
    dest_parent = worktree / "apps/prototype-wp-alt-context"
    dest_parent.mkdir(parents=True)
    dest = dest_parent / "node_modules"
    dest.symlink_to(src)
    _write_lockfiles(worktree, '{"lock":"node"}\n', '{"lock":"vendor"}\n')

    completed = subprocess.run(
        [
            sys.executable,
            str(PROVISION),
            "--worktree",
            str(worktree),
            "--primary",
            str(primary),
            "--fixture-mode",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert dest.is_symlink()
    assert dest.resolve() != src.resolve()
    assert ".acx-dep-cache" in dest.resolve().parts
    (src / "pkg").write_text("mutated-primary\n", encoding="utf-8")
    assert (dest / "pkg").read_text(encoding="utf-8") == "from-primary\n"


def test_provision_rejects_direct_primary_symlink_when_lockfiles_differ(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    worktree = tmp_path / "worktree"
    src = primary / "apps/prototype-wp-alt-context/node_modules"
    src.mkdir(parents=True)
    (src / "pkg").write_text("from-primary\n", encoding="utf-8")
    _write_lockfiles(primary, '{"lock":"primary"}\n', '{"lock":"vendor"}\n')
    worktree.mkdir()
    dest_parent = worktree / "apps/prototype-wp-alt-context"
    dest_parent.mkdir(parents=True)
    dest = dest_parent / "node_modules"
    dest.symlink_to(src)
    _write_lockfiles(worktree, '{"lock":"lane"}\n', '{"lock":"vendor"}\n')

    completed = subprocess.run(
        [
            sys.executable,
            str(PROVISION),
            "--worktree",
            str(worktree),
            "--primary",
            str(primary),
            "--fixture-mode",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "install dependencies in the lane" in completed.stderr
    assert not dest.exists()
    assert not dest.is_symlink()
    assert src.is_dir()
    assert (src / "pkg").read_text(encoding="utf-8") == "from-primary\n"


def _load_provisioner():
    spec = importlib.util.spec_from_file_location("provision_lane_worktree", PROVISION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_provision(worktree: Path, primary: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(PROVISION),
            "--worktree",
            str(worktree),
            "--primary",
            str(primary),
            *extra,
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def test_provision_evicts_stale_dep_cache_digests(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    worktree = tmp_path / "worktree"
    src = primary / "apps/prototype-wp-alt-context/node_modules"
    src.mkdir(parents=True)
    (src / "pkg").write_text("from-primary\n", encoding="utf-8")
    vendor = primary / "apps/prototype-wp-alt-context/vendor"
    vendor.mkdir(parents=True)
    (vendor / "pkg").write_text("from-primary-vendor\n", encoding="utf-8")
    _write_lockfiles(primary, '{"lock":"a"}\n', '{"lock":"b"}\n')
    worktree.mkdir()
    _write_lockfiles(worktree, '{"lock":"a"}\n', '{"lock":"b"}\n')

    completed = _run_provision(worktree, primary, "--fixture-mode")
    assert completed.returncode == 0, completed.stderr

    cache_root = worktree / "apps/prototype-wp-alt-context/.acx-dep-cache"
    live_before = {path.name for path in cache_root.iterdir() if path.is_dir()}
    assert live_before
    stale = cache_root / ("0" * 64)
    (stale / "node_modules").mkdir(parents=True)
    (stale / "node_modules" / "old").write_text("stale\n", encoding="utf-8")
    leftover = cache_root / ".tmp-node_modules.99999"
    leftover.mkdir()
    (leftover / "x").write_text("tmp\n", encoding="utf-8")

    completed = _run_provision(worktree, primary, "--fixture-mode")
    assert completed.returncode == 0, completed.stderr
    names = {path.name for path in cache_root.iterdir()}
    assert ("0" * 64) not in names
    assert not any(name.startswith(".tmp-") for name in names)
    assert live_before <= names
    dest = worktree / "apps/prototype-wp-alt-context/node_modules"
    vendor_dest = worktree / "apps/prototype-wp-alt-context/vendor"
    assert dest.is_symlink() and ".acx-dep-cache" in dest.resolve().parts
    assert vendor_dest.is_symlink() and ".acx-dep-cache" in vendor_dest.resolve().parts
    assert dest.resolve().parent.name in names
    assert vendor_dest.resolve().parent.name in names


def test_provision_replaces_broken_dep_cache_symlink(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    worktree = tmp_path / "worktree"
    src = primary / "apps/prototype-wp-alt-context/node_modules"
    src.mkdir(parents=True)
    (src / "pkg").write_text("from-primary\n", encoding="utf-8")
    _write_lockfiles(primary, '{"lock":"node"}\n', '{"lock":"vendor"}\n')
    worktree.mkdir()
    _write_lockfiles(worktree, '{"lock":"node"}\n', '{"lock":"vendor"}\n')
    digest = hashlib.sha256(b'{"lock":"node"}\n').hexdigest()
    cache = worktree / "apps/prototype-wp-alt-context/.acx-dep-cache" / digest / "node_modules"
    cache.parent.mkdir(parents=True)
    cache.symlink_to(worktree / "missing-cache")

    completed = _run_provision(worktree, primary, "--fixture-mode")
    assert completed.returncode == 0, completed.stderr
    dest = worktree / "apps/prototype-wp-alt-context/node_modules"
    assert dest.is_symlink()
    assert cache.is_dir() and not cache.is_symlink()
    assert (dest / "pkg").read_text(encoding="utf-8") == "from-primary\n"


def test_provision_fails_closed_on_malformed_dep_sidecar(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    worktree = tmp_path / "worktree"
    src = primary / "apps/prototype-wp-alt-context/node_modules"
    src.mkdir(parents=True)
    (src / "pkg").write_text("from-primary\n", encoding="utf-8")
    _write_lockfiles(primary, '{"lock":"node"}\n', '{"lock":"vendor"}\n')
    worktree.mkdir()
    _write_lockfiles(worktree, '{"lock":"node"}\n', '{"lock":"vendor"}\n')
    sidecar = worktree / "apps/prototype-wp-alt-context/.acx-dep-source"
    sidecar.write_text("{not-json\n", encoding="utf-8")

    completed = _run_provision(worktree, primary, "--fixture-mode")
    dest = worktree / "apps/prototype-wp-alt-context/node_modules"
    assert completed.returncode != 0
    assert "not valid JSON" in completed.stderr
    assert not dest.exists()
    assert not dest.is_symlink()


def test_overlay_copy_rejects_escaping_relative_entries(tmp_path: Path) -> None:
    module = _load_provisioner()
    src = tmp_path / "src"
    dest = tmp_path / "dest"
    src.mkdir()
    dest.mkdir()
    secret = tmp_path / "secret"
    secret.write_text("nope\n", encoding="utf-8")
    raised = False
    try:
        module._copy_overlay_entries(src, dest, ["../secret"])
    except RuntimeError as exc:
        raised = True
        assert "escapes" in str(exc)
    assert raised
    assert secret.read_text(encoding="utf-8") == "nope\n"
    assert list(dest.iterdir()) == []
