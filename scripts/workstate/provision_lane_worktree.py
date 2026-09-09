#!/usr/bin/env python3
"""Provision a linked worktree without dereferencing dependency trees.

GPUUX-1-REPO-BR-02: `cp -R` / `shutil.copytree` (symlinks=False) turns
`node_modules/.bin/vitest` into a regular file that resolves `./dist/cli.js`
relative to `.bin/` and dies with ERR_MODULE_NOT_FOUND. This provisioner never
copies node_modules or vendor; it either symlinks the primary tree or leaves
the worktree to run `npm ci` / `composer install`.

VMREAP-1-BR-04: linked worktrees do not inherit gitignored overlay surfaces
(Makefile.d except tracked files, scripts/hooks, scripts/workbay,
scripts/workbay_lifecycle). Rsync those from the primary checkout with `-a`
so overlay symlinks stay symlinks.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

OVERLAY_PATHS: tuple[str, ...] = (
    "Makefile.d",
    "scripts/hooks",
    "scripts/workbay",
    "scripts/workbay_lifecycle",
    "scripts/remote_agent.sh",
)

DEPENDENCY_TREES: tuple[str, ...] = (
    "apps/prototype-wp-alt-context/node_modules",
    "apps/prototype-wp-alt-context/vendor",
)


def primary_checkout(start: Path) -> Path:
    proc = subprocess.run(
        ["git", "-C", str(start), "rev-parse", "--path-format=absolute", "--git-common-dir"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return start.resolve()
    return Path(proc.stdout.strip()).parent


def _rsync_overlay(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if shutil.which("rsync"):
        source = f"{src}/" if src.is_dir() else str(src)
        target = str(dest)
        subprocess.run(["rsync", "-a", source, target], check=True)
        return
    if src.is_dir():
        shutil.copytree(src, dest, symlinks=True, dirs_exist_ok=True)
    else:
        shutil.copy2(src, dest, follow_symlinks=False)


def provision_overlay(*, primary: Path, worktree: Path) -> list[str]:
    copied: list[str] = []
    for rel in OVERLAY_PATHS:
        src = primary / rel
        dest = worktree / rel
        if not src.exists():
            continue
        if dest.resolve() == src.resolve():
            continue
        _rsync_overlay(src, dest)
        copied.append(rel)
    return copied


def _same_symlink(dest: Path, src: Path) -> bool:
    if not dest.is_symlink():
        return False
    try:
        return dest.resolve() == src.resolve()
    except OSError:
        return False


def _replace_with_symlink(dest: Path, src: Path) -> None:
    if dest.is_symlink() or dest.is_file():
        dest.unlink()
    elif dest.is_dir():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(src, dest)


def provision_dependency_trees(*, primary: Path, worktree: Path) -> list[str]:
    """Symlink primary dependency trees. Never copy; never dereference."""
    linked: list[str] = []
    for rel in DEPENDENCY_TREES:
        src = primary / rel
        dest = worktree / rel
        if not src.exists():
            continue
        if _same_symlink(dest, src):
            linked.append(rel)
            continue
        if dest.exists() or dest.is_symlink():
            _replace_with_symlink(dest, src)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(src, dest)
        linked.append(rel)
    return linked


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worktree", required=True, type=Path)
    parser.add_argument("--primary", type=Path, default=None)
    args = parser.parse_args(argv)
    worktree = args.worktree.resolve()
    primary = (args.primary or primary_checkout(worktree)).resolve()
    provision_overlay(primary=primary, worktree=worktree)
    provision_dependency_trees(primary=primary, worktree=worktree)
    return 0


if __name__ == "__main__":
    sys.exit(main())
