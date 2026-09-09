#!/usr/bin/env python3
"""Provision a linked worktree without dereferencing dependency trees.

GPUUX-1-REPO-BR-02: `cp -R` / `shutil.copytree` (symlinks=False) turns
`node_modules/.bin/vitest` into a regular file that resolves `./dist/cli.js`
relative to `.bin/` and dies with ERR_MODULE_NOT_FOUND. This provisioner never
copies node_modules or vendor; it either symlinks the primary tree or leaves
the worktree to run `npm ci` / `composer install`.

VMREAP-1-BR-04: linked worktrees do not inherit gitignored overlay surfaces
(Makefile.d except tracked files, scripts/hooks, scripts/workbay,
scripts/workbay_lifecycle). Rsync only ignored entries from the primary
checkout with `-a` so tracked files already checked out in the linked tree are
never overwritten and overlay symlinks stay symlinks.
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
    common_dir = proc.stdout.strip()
    if proc.returncode != 0 or not common_dir:
        detail = (proc.stderr or proc.stdout or "no output").strip()
        raise RuntimeError(
            f"git rev-parse --git-common-dir failed for {start} "
            f"(exit {proc.returncode}): {detail}; refusing to guess the primary checkout"
        )
    return Path(common_dir).parent


def _remove_existing_path(path: Path) -> None:
    """Remove a destination without following a symlink at its top level."""
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def _git_metadata_present(primary: Path) -> bool:
    """Return whether ``primary`` claims to be a Git checkout.

    ``Path.exists`` is false for a broken ``.git`` link, but that is still Git
    metadata and must not be treated as a fixture.  A checkout with broken or
    unreadable metadata should fail closed instead of copying every overlay
    entry.
    """
    metadata = primary / ".git"
    return metadata.exists() or metadata.is_symlink()


def _ignored_overlay_entries(primary: Path, rel: str) -> list[str] | None:
    """Return ignored entries below ``rel``; ``None`` means no Git metadata."""
    try:
        proc = subprocess.run(
            [
                "git",
                "-C",
                str(primary),
                "ls-files",
                "--others",
                "--ignored",
                "--exclude-standard",
                "-z",
                "--",
                rel,
            ],
            capture_output=True,
            check=False,
        )
    except OSError:
        if _git_metadata_present(primary):
            raise RuntimeError(f"git ls-files could not run for {primary}; refusing overlay copy") from None
        return None
    if proc.returncode != 0:
        if _git_metadata_present(primary):
            raise RuntimeError(f"git ls-files failed for {primary} (exit {proc.returncode}); refusing overlay copy")
        return None

    prefix = f"{rel}/"
    entries: list[str] = []
    for raw_entry in proc.stdout.split(b"\0"):
        if not raw_entry:
            continue
        entry = os.fsdecode(raw_entry)
        if entry == rel:
            entries.append("")
        elif entry.startswith(prefix):
            entries.append(entry[len(prefix) :])
    return entries


def _relocated_symlink_target(source: Path, target: Path) -> str:
    """Relocate a link target so it keeps the source link's meaning.

    ``os.readlink`` returns a relative target relative to ``source.parent``.
    Reusing that text at a different worktree parent silently points at a
    different tree, so recompute the relative spelling from ``target.parent``.
    The path normalization is intentionally non-strict: an overlay may be
    linked before its external target is materialized.
    """
    link_target = os.readlink(source)
    if os.path.isabs(link_target):
        return link_target
    source_target = os.path.abspath(os.path.join(os.fspath(source.parent), link_target))
    return os.path.relpath(source_target, os.fspath(target.parent))


def _copy_overlay_entries(src: Path, dest: Path, entries: list[str]) -> None:
    """Copy an ignored-entry manifest without dereferencing entry symlinks."""
    for rel in entries:
        source = src / rel
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        _remove_existing_path(target)
        if source.is_symlink():
            target.symlink_to(_relocated_symlink_target(source, target))
        elif source.is_dir():
            shutil.copytree(source, target, symlinks=True, dirs_exist_ok=True)
        else:
            shutil.copy2(source, target, follow_symlinks=False)


def _rsync_overlay(src: Path, dest: Path, *, entries: list[str] | None = None) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Path.is_dir() follows symlinks.  Test the link first so a plugin-managed
    # overlay such as Makefile.d -> ../workbay-overlay remains a link in the
    # linked worktree instead of becoming a copied directory.
    if src.is_symlink():
        if dest.is_symlink() and os.path.realpath(dest) == os.path.realpath(src):
            return
        _remove_existing_path(dest)
        # Rsync preserves link text, not the link's source-relative meaning.
        # Create the relocated link ourselves even when rsync is available.
        dest.symlink_to(_relocated_symlink_target(src, dest))
        return

    if dest.is_symlink() or dest.is_file():
        _remove_existing_path(dest)

    if entries is not None:
        if not entries:
            return
        # rsync preserves link text and, for a one-file files-from list, may
        # replace dest with that file. Copy overlay symlinks ourselves so
        # relative targets keep source meaning on rsync and non-rsync hosts.
        symlink_entries = [rel for rel in entries if (src / rel).is_symlink()]
        other_entries = [rel for rel in entries if rel not in set(symlink_entries)]
        if other_entries:
            dest.mkdir(parents=True, exist_ok=True)
            if shutil.which("rsync"):
                payload = b"".join(os.fsencode(entry) + b"\0" for entry in other_entries)
                subprocess.run(
                    ["rsync", "-a", "--from0", "--files-from=-", f"{src}/", str(dest)],
                    input=payload,
                    check=True,
                )
            else:
                _copy_overlay_entries(src, dest, other_entries)
        if symlink_entries:
            _copy_overlay_entries(src, dest, symlink_entries)
        return

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
        # exists() is false for a broken symlink, but the contract is to carry
        # the plugin's overlay link itself even when its target is provisioned
        # separately on the host.
        if not src.exists() and not src.is_symlink():
            continue
        if dest.resolve(strict=False) == src.resolve(strict=False):
            continue

        # A top-level symlink is the overlay contract itself. Preserve it even
        # when its target is outside this checkout or Git cannot inspect it.
        if src.is_symlink():
            _rsync_overlay(src, dest)
            copied.append(rel)
            continue

        ignored_entries = _ignored_overlay_entries(primary, rel)
        if ignored_entries is None:
            # Unit fixtures and older callers may provide a directory without
            # Git metadata. The real worktree path always has Git metadata;
            # retain the historical copy behavior for those hermetic callers.
            _rsync_overlay(src, dest)
        elif src.is_dir():
            # In a real checkout, only ignored overlay entries are eligible.
            # Tracked files (for example Makefile.d/demo-auth.mk) are omitted,
            # leaving the linked worktree's branch-owned version untouched.
            _rsync_overlay(src, dest, entries=ignored_entries)
        elif "" in ignored_entries:
            _rsync_overlay(src, dest)
        else:
            continue
        copied.append(rel)
    return copied


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
        if dest.resolve(strict=False) == src.resolve(strict=False):
            # Same path (main checkout, or --primary omitted on a normal clone):
            # never rmtree the live node_modules/vendor tree into a dangling link.
            if dest.is_symlink():
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
    try:
        primary = (args.primary or primary_checkout(worktree)).resolve()
        provision_overlay(primary=primary, worktree=worktree)
        provision_dependency_trees(primary=primary, worktree=worktree)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
