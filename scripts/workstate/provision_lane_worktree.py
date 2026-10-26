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

ORCA-1: --overlay-path PATH (repeatable) appends checkout-relative paths to
OVERLAY_PATHS under the same ignored-entries-only rule, so a bootstrap can
carry every overlay prefix its contract names without editing this list.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path, PurePosixPath
from typing import NamedTuple

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

DEPENDENCY_LOCKFILES: dict[str, str] = {
    "apps/prototype-wp-alt-context/node_modules": "apps/prototype-wp-alt-context/package-lock.json",
    "apps/prototype-wp-alt-context/vendor": "apps/prototype-wp-alt-context/composer.lock",
}

SECURE_OFFLOAD_MARKER = ".acx-secure-offload"
DEP_SOURCE_SIDECAR = ".acx-dep-source"
# Tail case (PERF-08): one wave of many lanes, each freezing GB-scale trees.
# Keep only live lockfile digests; history of lockfile churn must not accumulate.
DEP_CACHE_SCAN_LIMIT = 32
SIDECAR_ENTRY_KEYS = ("lockfile", "sha256", "readonly", "cache")


class _OverlayOp(NamedTuple):
    """One planned overlay copy; ``entries`` is ``None`` for a whole-path copy."""

    rel: str
    src: Path
    dest: Path
    kind: str
    entries: list[str] | None = None


class OverlayPathError(ValueError):
    """An overlay path that is not a checkout-relative POSIX path."""

    def __init__(self, value: str, reason: str) -> None:
        super().__init__(f"invalid overlay path {value!r}: {reason}")
        self.value = value
        self.reason = reason


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


def _is_secure_offload_sandbox(worktree: Path, *, flagged: bool) -> bool:
    """Return whether the destination is a secret-scanned untrusted sandbox."""
    if flagged:
        return True
    marker = worktree / SECURE_OFFLOAD_MARKER
    return marker.exists() or marker.is_symlink()


def _refuse_secure_offload(worktree: Path) -> None:
    raise RuntimeError(
        f"refusing overlay copy and primary dependency symlinks into secure-offload "
        f"sandbox {worktree}; never add external primary files after the secret scan"
    )


def _require_git_primary(primary: Path) -> None:
    """Refuse an explicit --primary that is missing or not a Git checkout."""
    if not primary.exists():
        raise RuntimeError(f"explicit --primary {primary} does not exist; refusing to provision")
    if not _git_metadata_present(primary):
        raise RuntimeError(
            f"explicit --primary {primary} is not a Git checkout; pass --fixture-mode only for hermetic tests"
        )


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


def _target_tracked_paths(worktree: Path, pathspecs: list[str]) -> set[str] | None:
    """Return paths the target index tracks at or below ``pathspecs``; ``None`` means no Git metadata."""
    try:
        proc = subprocess.run(
            ["git", "--literal-pathspecs", "-C", str(worktree), "ls-files", "-z", "--cached", "--", *pathspecs],
            capture_output=True,
            check=False,
        )
    except OSError:
        if _git_metadata_present(worktree):
            raise RuntimeError(
                f"git ls-files could not run for target worktree {worktree}; refusing overlay copy"
            ) from None
        return None
    if proc.returncode != 0:
        if _git_metadata_present(worktree):
            detail = os.fsdecode(proc.stderr).strip() or "no output"
            raise RuntimeError(
                f"git ls-files failed for target worktree {worktree} (exit {proc.returncode}): {detail}; "
                "refusing overlay copy"
            )
        # No index means no branch-owned file the overlay could clobber.
        return None
    return {os.fsdecode(raw_entry) for raw_entry in proc.stdout.split(b"\0") if raw_entry}


def _is_within(path: str, root: str) -> bool:
    return os.path.commonpath([path, root]) == root


def _require_inside(root: Path, path: Path) -> None:
    """Refuse ``path`` when following its existing components leaves ``root``."""
    real = os.path.realpath(path)
    root_real = os.path.realpath(root)
    if not _is_within(real, root_real):
        raise RuntimeError(f"refusing overlay copy to {path}: it resolves to {real}, outside worktree {root_real}")


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


def _relative_stays_inside(rel: str) -> bool:
    """Return whether ``rel`` cannot walk above its overlay root."""
    if not rel:
        return True
    path = Path(rel)
    if path.is_absolute():
        return False
    depth = 0
    for part in path.parts:
        if part == "..":
            depth -= 1
            if depth < 0:
                return False
        elif part in (".", ""):
            continue
        else:
            depth += 1
    return True


def _require_contained_overlay_entry(src: Path, rel: str) -> None:
    if _relative_stays_inside(rel):
        return
    raise RuntimeError(f"ignored overlay entry {rel!r} escapes {src}; refusing overlay copy")


def _copy_overlay_entries(src: Path, dest: Path, entries: list[str], *, root: Path | None = None) -> None:
    """Copy an ignored-entry manifest without dereferencing entry symlinks."""
    for rel in entries:
        _require_contained_overlay_entry(src, rel)
        source = src / rel
        target = dest / rel
        if root is not None:
            _require_inside(root, target.parent)
        target.parent.mkdir(parents=True, exist_ok=True)
        _remove_existing_path(target)
        if source.is_symlink():
            target.symlink_to(_relocated_symlink_target(source, target))
        elif source.is_dir():
            shutil.copytree(source, target, symlinks=True, dirs_exist_ok=True)
        else:
            shutil.copy2(source, target, follow_symlinks=False)


def _rsync_overlay(src: Path, dest: Path, *, root: Path, entries: list[str] | None = None) -> None:
    # Defence in depth behind _validate_overlay_plan: never create parents
    # through a symlink that leaves the worktree.
    _require_inside(root, dest.parent)
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
        for rel in entries:
            _require_contained_overlay_entry(src, rel)
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
                _copy_overlay_entries(src, dest, other_entries, root=root)
        if symlink_entries:
            _copy_overlay_entries(src, dest, symlink_entries, root=root)
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


def _normalize_overlay_path(value: str) -> str:
    if not value:
        raise OverlayPathError(value, "empty path; pass a path relative to the checkout root")
    path = PurePosixPath(value)
    if path.is_absolute():
        raise OverlayPathError(value, "absolute path; pass a path relative to the checkout root")
    if ".." in path.parts:
        raise OverlayPathError(value, "'..' segment; pass a path inside the checkout without '..'")
    if not path.parts:
        # "." would hand git the whole checkout and copy every ignored tree,
        # including the dependency trees this provisioner refuses to copy.
        raise OverlayPathError(value, "names the checkout root; pass a path below it")
    # as_posix() also drops "./" and repeated "/"; git ls-files reports
    # normalized paths, so an unnormalized prefix would silently match nothing.
    return path.as_posix()


def _normalize_overlay_paths(paths: Iterable[str]) -> list[str]:
    if isinstance(paths, str | bytes):
        raise TypeError("paths must be an iterable of overlay paths, not a single string")
    return list(dict.fromkeys(_normalize_overlay_path(value) for value in paths))


def _plan_overlay(primary: Path, worktree: Path, overlay_paths: list[str], *, fixture_mode: bool) -> list[_OverlayOp]:
    plan: list[_OverlayOp] = []
    for rel in overlay_paths:
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
            plan.append(_OverlayOp(rel, src, dest, "link"))
            continue

        ignored_entries = _ignored_overlay_entries(primary, rel)
        if ignored_entries is None:
            if not fixture_mode:
                raise RuntimeError(
                    f"explicit --primary {primary} has no Git metadata; "
                    "refusing overlay copy (pass --fixture-mode only for hermetic tests)"
                )
            # Hermetic callers may provide a directory without Git metadata.
            plan.append(_OverlayOp(rel, src, dest, "tree" if src.is_dir() else "file"))
        elif src.is_dir():
            # In a real checkout, only ignored overlay entries are eligible.
            # Tracked files (for example Makefile.d/demo-auth.mk) are omitted,
            # leaving the linked worktree's branch-owned version untouched.
            for entry in ignored_entries:
                _require_contained_overlay_entry(src, entry)
            plan.append(_OverlayOp(rel, src, dest, "entries", ignored_entries))
        elif "" in ignored_entries:
            plan.append(_OverlayOp(rel, src, dest, "file"))
    return plan


def _source_tree(src: Path) -> tuple[list[str], list[str]]:
    """Return (files and symlinks, real directories) below ``src`` without following links."""
    leaves: list[str] = []
    dirs: list[str] = []
    for dirpath, dirnames, filenames in os.walk(src):
        base = Path(dirpath).relative_to(src)
        for name in dirnames:
            (leaves if (Path(dirpath) / name).is_symlink() else dirs).append((base / name).as_posix())
        leaves.extend((base / name).as_posix() for name in filenames)
    return leaves, dirs


def _contained_dest_rel(worktree: Path, root_real: str, op: _OverlayOp) -> str:
    """Return ``op.dest`` relative to the resolved worktree, refusing escaping ancestors.

    mkdir, rsync and copy all follow symlinked ancestors of ``op.dest``, so the
    lexical overlay-path check alone cannot keep writes inside the worktree.
    ``op.dest`` itself is replaced rather than followed, so it is not walked.
    """
    current = worktree
    for part in PurePosixPath(op.rel).parts[:-1]:
        current = current / part
        try:
            mode = os.lstat(current).st_mode
        except FileNotFoundError:
            break
        except OSError as exc:
            raise RuntimeError(f"refusing overlay copy to {op.dest}: cannot inspect {current}: {exc}") from None
        if stat.S_ISLNK(mode):
            real = os.path.realpath(current)
            if not _is_within(real, root_real):
                raise RuntimeError(
                    f"refusing overlay copy to {op.dest}: {current} is a symlink to {real}, outside worktree "
                    f"{root_real}; replace it with a directory inside the worktree or drop {op.rel!r} "
                    "from the overlay paths"
                )
        if not current.is_dir():
            raise RuntimeError(
                f"refusing overlay copy to {op.dest}: {current} is not a directory; "
                f"move it aside or drop {op.rel!r} from the overlay paths"
            )
    real_dest = os.path.join(os.path.realpath(op.dest.parent), op.dest.name)
    return Path(os.path.relpath(real_dest, root_real)).as_posix()


def _require_plain_overlay_dirs(op: _OverlayOp, dirs: Iterable[str], root_real: str) -> None:
    """Refuse a symlink or non-directory where the copy needs a directory below ``op.dest``.

    rsync replaces such a symlink while the Python fallback writes through it,
    so neither outcome is safe to pick silently.
    """
    for rel_dir in sorted(set(dirs)):
        path = op.dest / rel_dir
        try:
            mode = os.lstat(path).st_mode
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise RuntimeError(f"refusing overlay copy into {op.dest}: cannot inspect {path}: {exc}") from None
        if stat.S_ISLNK(mode):
            real = os.path.realpath(path)
            where = f"outside worktree {root_real}" if not _is_within(real, root_real) else "inside the overlay"
            raise RuntimeError(
                f"refusing overlay copy into {op.dest}: {path} is a symlink to {real}, {where}; "
                f"remove the symlink or drop {op.rel!r} from the overlay paths"
            )
        if not stat.S_ISDIR(mode):
            raise RuntimeError(
                f"refusing overlay copy into {op.dest}: {path} is not a directory; "
                f"move it aside or drop {op.rel!r} from the overlay paths"
            )


def _require_untracked_leaves(worktree: Path, leaves: list[tuple[_OverlayOp, str]], tracked: set[str]) -> None:
    """Refuse a planned write onto, over, or below a path the target branch tracks."""
    tracked_below: dict[str, str] = {}
    for path in sorted(tracked):
        parts = PurePosixPath(path).parts
        for depth in range(1, len(parts)):
            tracked_below.setdefault(PurePosixPath(*parts[:depth]).as_posix(), path)
    for op, leaf in leaves:
        parts = PurePosixPath(leaf).parts
        ancestors = (PurePosixPath(*parts[:depth]).as_posix() for depth in range(1, len(parts)))
        collision = leaf if leaf in tracked else tracked_below.get(leaf)
        if collision is None:
            collision = next((ancestor for ancestor in ancestors if ancestor in tracked), None)
        if collision is not None:
            raise RuntimeError(
                f"refusing overlay copy onto {worktree / leaf}: the target worktree tracks {collision!r}; "
                f"untrack it on the target branch or drop {op.rel!r} from the overlay paths"
            )


def _validate_overlay_plan(plan: list[_OverlayOp], worktree: Path) -> None:
    if not plan:
        return
    root_real = os.path.realpath(worktree)
    roots: set[str] = set()
    leaves: list[tuple[_OverlayOp, str]] = []
    below: list[tuple[_OverlayOp, list[str]]] = []
    for op in plan:
        dest_rel = _contained_dest_rel(worktree, root_real, op)
        if op.kind == "file" and op.dest.is_dir() and not op.dest.is_symlink():
            # rsync and copy2 would write into dest/<name>, past every check above.
            raise RuntimeError(
                f"refusing overlay copy to {op.dest}: it is a directory but {op.src} is a file; "
                f"move it aside or drop {op.rel!r} from the overlay paths"
            )
        roots.add(dest_rel)
        rels: list[str] = [""]
        dirs: list[str] = []
        if op.kind == "entries":
            rels = list(op.entries or [])
            dirs = [
                PurePosixPath(*PurePosixPath(entry).parts[:depth]).as_posix()
                for entry in rels
                for depth in range(1, len(PurePosixPath(entry).parts))
            ]
        elif op.kind == "tree":
            rels, dirs = _source_tree(op.src)
        if op.kind in ("entries", "tree") and (op.dest.is_symlink() or op.dest.is_file()):
            # _rsync_overlay replaces this with a fresh directory before copying.
            rels, dirs = ["", *rels], []
        leaves.extend((op, PurePosixPath(dest_rel, rel).as_posix()) for rel in rels)
        below.append((op, dirs))
    tracked = _target_tracked_paths(worktree, sorted(roots))
    if tracked:
        _require_untracked_leaves(worktree, leaves, tracked)
    for op, dirs in below:
        _require_plain_overlay_dirs(op, dirs, root_real)


def provision_overlay(
    *,
    primary: Path,
    worktree: Path,
    fixture_mode: bool = False,
    paths: Iterable[str] | None = None,
) -> list[str]:
    # Validate the whole list first so one bad path leaves the worktree untouched.
    overlay_paths = _normalize_overlay_paths(OVERLAY_PATHS if paths is None else paths)
    # FLOW-17: plan and validate every copy before the first write, so a later
    # colliding or escaping path cannot leave earlier paths already copied.
    plan = _plan_overlay(primary, worktree, overlay_paths, fixture_mode=fixture_mode)
    _validate_overlay_plan(plan, worktree)
    for op in plan:
        _rsync_overlay(op.src, op.dest, root=worktree, entries=op.entries)
    return [op.rel for op in plan]


def _replace_with_symlink(dest: Path, src: Path) -> None:
    if dest.is_symlink() or dest.is_file():
        dest.unlink()
    elif dest.is_dir():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(src, dest)


def _dep_cache_path(worktree: Path, rel: str, digest: str) -> Path:
    """Return the lockfile-keyed freeze directory for one dependency tree."""
    tree = Path(rel)
    return worktree / tree.parent / ".acx-dep-cache" / digest / tree.name


def _usable_dep_cache(cache: Path) -> bool:
    """Return whether ``cache`` is a real directory snapshot, not a dangling hit."""
    return cache.is_dir()


def _freeze_dependency_tree(src: Path, cache: Path) -> None:
    """Snapshot ``src`` into ``cache`` without dereferencing bin stubs.

    Parallel lanes with the same lockfile digest reuse this snapshot instead of
    the live primary tree, so an ``npm install`` in the primary cannot mutate a
    provisioned lane.
    """
    if _usable_dep_cache(cache):
        return
    if cache.exists() or cache.is_symlink():
        _remove_existing_path(cache)
    cache.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache.parent / f".tmp-{cache.name}.{os.getpid()}"
    _remove_existing_path(tmp)
    try:
        shutil.copytree(src, tmp, symlinks=True)
        try:
            tmp.rename(cache)
        except OSError:
            _remove_existing_path(tmp)
            if not _usable_dep_cache(cache):
                raise
    except Exception:
        _remove_existing_path(tmp)
        raise


def _lockfile_digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sidecar_path(dest: Path) -> Path:
    return dest.parent / DEP_SOURCE_SIDECAR


def _require_sidecar_entry(sidecar: Path, name: object, entry: object) -> None:
    if not isinstance(name, str) or not name:
        raise RuntimeError(f"{sidecar} has an invalid dependency key; refusing to provision")
    if not isinstance(entry, dict):
        raise RuntimeError(f"{sidecar}: {name} must be an object; refusing to provision")
    missing = [key for key in SIDECAR_ENTRY_KEYS if key not in entry]
    if missing:
        raise RuntimeError(f"{sidecar}: {name} missing {', '.join(missing)}; refusing to provision")
    lockfile = entry["lockfile"]
    digest = entry["sha256"]
    cache = entry["cache"]
    if not isinstance(lockfile, str) or not lockfile:
        raise RuntimeError(f"{sidecar}: {name}.lockfile must be a non-empty string")
    if not isinstance(digest, str) or not digest:
        raise RuntimeError(f"{sidecar}: {name}.sha256 must be a non-empty string")
    if not isinstance(entry["readonly"], bool):
        raise RuntimeError(f"{sidecar}: {name}.readonly must be a boolean")
    if not isinstance(cache, str) or not cache:
        raise RuntimeError(f"{sidecar}: {name}.cache must be a non-empty string")


def _read_sidecar(dest: Path) -> dict[str, object]:
    sidecar = _sidecar_path(dest)
    if not sidecar.exists() and not sidecar.is_symlink():
        return {}
    if sidecar.is_symlink() or not sidecar.is_file():
        raise RuntimeError(f"{sidecar} is not a regular file; refusing to provision")
    try:
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{sidecar} is not valid JSON; refusing to provision") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{sidecar} must be a JSON object; refusing to provision")
    for name, entry in payload.items():
        _require_sidecar_entry(sidecar, name, entry)
    return payload


def _sidecar_digests(payload: dict[str, object]) -> set[str]:
    keep: set[str] = set()
    for entry in payload.values():
        if isinstance(entry, dict):
            digest = entry.get("sha256")
            if isinstance(digest, str) and digest:
                keep.add(digest)
    return keep


def _evict_stale_dep_caches(worktree: Path, rel: str, *, keep_digests: set[str]) -> None:
    """Drop stale snapshots of ``rel`` so the per-worktree cache stays bounded.

    RES-08 / PERF-08: the miss path is one copytree of the current lockfile
    tree. Retaining old digests does not help the many-lanes-in-one-wave tail;
    it only grows disk. RES-05: directory scan is capped per provision.
    """
    cache_root = worktree / Path(rel).parent / ".acx-dep-cache"
    tree_name = Path(rel).name
    if cache_root.is_symlink() or not cache_root.is_dir():
        return
    scanned = 0
    try:
        iterator = os.scandir(cache_root)
    except OSError as exc:
        raise RuntimeError(f"cannot scan dependency cache {cache_root}: {exc}") from exc
    with iterator:
        for entry in iterator:
            scanned += 1
            if scanned > DEP_CACHE_SCAN_LIMIT:
                break
            path = Path(entry.path)
            if entry.name.startswith(".tmp-"):
                _remove_existing_path(path)
                continue
            if not entry.is_dir(follow_symlinks=False):
                continue
            if entry.name in keep_digests:
                continue
            stale_tree = path / tree_name
            if stale_tree.exists() or stale_tree.is_symlink():
                _remove_existing_path(stale_tree)
            try:
                next(path.iterdir())
            except StopIteration:
                _remove_existing_path(path)
            except OSError:
                continue


def _write_sidecar_entry(dest: Path, *, lockfile: str, digest: str, cache: Path) -> None:
    payload = _read_sidecar(dest)
    payload[dest.name] = {
        "lockfile": lockfile,
        "sha256": digest,
        "readonly": True,
        "cache": str(cache),
    }
    sidecar = _sidecar_path(dest)
    sidecar.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _drop_sidecar_entry(dest: Path) -> None:
    payload = _read_sidecar(dest)
    if dest.name not in payload:
        return
    del payload[dest.name]
    sidecar = _sidecar_path(dest)
    if payload:
        sidecar.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    elif sidecar.exists() or sidecar.is_symlink():
        sidecar.unlink()


def provision_dependency_trees(*, primary: Path, worktree: Path) -> list[str]:
    """Symlink primary trees only when lane and primary lockfiles match."""
    linked: list[str] = []
    mismatches: list[str] = []
    for rel in DEPENDENCY_TREES:
        src = primary / rel
        dest = worktree / rel
        if worktree.resolve(strict=False) == primary.resolve(strict=False):
            # Same checkout root (main tree, or --primary omitted on a normal
            # clone): never rmtree the live node_modules/vendor tree into a
            # dangling link. A separate worktree whose dest symlink merely
            # resolves to primary still needs lock checks and a frozen cache.
            if dest.is_symlink():
                linked.append(rel)
            continue
        if not src.exists():
            continue

        lock_rel = DEPENDENCY_LOCKFILES[rel]
        digest = _lockfile_digest(worktree / lock_rel)
        primary_digest = _lockfile_digest(primary / lock_rel)
        _read_sidecar(dest)
        if digest is None or primary_digest is None or digest != primary_digest:
            if dest.is_symlink():
                dest.unlink()
            _drop_sidecar_entry(dest)
            _evict_stale_dep_caches(worktree, rel, keep_digests=_sidecar_digests(_read_sidecar(dest)))
            mismatches.append(rel)
            print(
                f"{rel}: lockfile mismatch or missing; install dependencies in the lane "
                f"(no shared {rel} symlink). Align {lock_rel} with the primary checkout.",
                file=sys.stderr,
            )
            continue

        cache = _dep_cache_path(worktree, rel, digest)
        _freeze_dependency_tree(src, cache)
        if dest.exists() or dest.is_symlink():
            _replace_with_symlink(dest, cache)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(cache, dest)
        _write_sidecar_entry(dest, lockfile=lock_rel, digest=digest, cache=cache)
        _evict_stale_dep_caches(worktree, rel, keep_digests=_sidecar_digests(_read_sidecar(dest)))
        linked.append(rel)
    if mismatches:
        raise RuntimeError("dependency lockfile mismatch; install dependencies in the lane: " + ", ".join(mismatches))
    return linked


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worktree", required=True, type=Path)
    parser.add_argument("--primary", type=Path, default=None)
    parser.add_argument(
        "--secure-offload",
        action="store_true",
        help="Fail closed: do not copy overlays or symlink primary trees into a sandbox",
    )
    parser.add_argument(
        "--fixture-mode",
        action="store_true",
        help="Allow a non-Git --primary for hermetic tests only",
    )
    parser.add_argument(
        "--overlay-path",
        action="append",
        default=[],
        metavar="PATH",
        help="Also copy gitignored entries at or below this checkout-relative PATH (repeatable)",
    )
    args = parser.parse_args(argv)
    try:
        overlay_paths = _normalize_overlay_paths((*OVERLAY_PATHS, *args.overlay_path))
    except OverlayPathError as exc:
        print(f"provision_lane_worktree: invalid --overlay-path {exc.value}: {exc.reason}", file=sys.stderr)
        return 1
    worktree = args.worktree.resolve()
    try:
        if args.primary is not None:
            primary = args.primary.expanduser()
            if not primary.exists():
                raise RuntimeError(f"explicit --primary {primary} does not exist; refusing to provision")
            primary = primary.resolve()
            if not args.fixture_mode:
                _require_git_primary(primary)
        else:
            primary = primary_checkout(worktree).resolve()
        if _is_secure_offload_sandbox(worktree, flagged=args.secure_offload):
            _refuse_secure_offload(worktree)
        provision_overlay(primary=primary, worktree=worktree, fixture_mode=args.fixture_mode, paths=overlay_paths)
        provision_dependency_trees(primary=primary, worktree=worktree)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
