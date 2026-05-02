from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


SurfaceKind = Literal["skills", "hooks", "commands", "prompts", "contracts"]
ResolvedSource = Literal["shared", "local", "overlapping"]

DEFAULT_SURFACE_ROOTS: dict[SurfaceKind, Path] = {
    "skills": Path(".claude/skills"),
    "hooks": Path(".github/hooks"),
    "commands": Path(".claude/commands"),
    "prompts": Path(".github/prompts"),
    "contracts": Path("docs/agentic/contracts"),
}


class OverlayResolverError(RuntimeError):
    """Base class for overlay resolution errors."""


class BrokenOverlayError(OverlayResolverError):
    """Raised when an overlay entry points to a missing target."""


@dataclass(frozen=True)
class ResolvedPath:
    source: ResolvedSource
    effective_path: Path
    shared_path: Path | None = None
    local_path: Path | None = None


def _load_overlay_manifest(project_root: Path) -> dict | None:
    manifest_path = project_root / ".agentic-overlay.json"
    if not manifest_path.is_file():
        return None

    try:
        payload = json.loads(manifest_path.read_text())
    except json.JSONDecodeError as exc:
        raise OverlayResolverError(f"overlay manifest is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise OverlayResolverError("overlay manifest must parse to a mapping")
    return payload


def _surface_roots(project_root: Path, kind: SurfaceKind) -> tuple[Path, Path] | None:
    manifest = _load_overlay_manifest(project_root)
    if manifest is None:
        return None

    surfaces = manifest.get("surfaces")
    # `.agentic-overlay.json` is shared between two consumers with different
    # schemas: agentic-bootstrap writes a state file with `surfaces: [list]`,
    # the overlay-resolver contract expects `surfaces: {dict}`. When the
    # manifest is not contract-shaped, fall back to local-only resolution
    # rather than failing every caller. Resolved durably once the upstream
    # bootstrap-state file is renamed to `.agentic-bootstrap.json`.
    if not isinstance(surfaces, dict):
        return None

    surface = surfaces.get(kind)
    if surface is None:
        return None
    if not isinstance(surface, dict):
        raise OverlayResolverError(f"overlay manifest `surfaces.{kind}` must be a mapping")

    shared_root = surface.get("shared_root")
    local_root = surface.get("local_root")
    if not isinstance(shared_root, str) or not shared_root.strip():
        raise OverlayResolverError(f"overlay manifest `surfaces.{kind}.shared_root` must be a non-empty string")
    if not isinstance(local_root, str) or not local_root.strip():
        raise OverlayResolverError(f"overlay manifest `surfaces.{kind}.local_root` must be a non-empty string")

    return project_root / shared_root, project_root / local_root


def _iter_surface_entries(root: Path) -> dict[str, Path]:
    if not root.exists():
        return {}

    entries: dict[str, Path] = {}
    for entry in sorted(root.iterdir(), key=lambda path: path.name):
        if entry.name.startswith("."):
            continue
        if entry.is_file() or entry.is_dir() or entry.is_symlink():
            entries[entry.name] = entry
    return entries


def _iter_hook_entries(anchor: Path) -> dict[str, Path]:
    entries: dict[str, Path] = {}
    hook_roots = (
        anchor / ".github" / "hooks",
        anchor / "scripts" / "hooks",
    )

    for hook_root in hook_roots:
        if not hook_root.exists():
            continue
        for entry in sorted(hook_root.rglob("*"), key=lambda path: path.as_posix()):
            if not (entry.is_file() or entry.is_symlink()):
                continue
            relative_from_root = entry.relative_to(hook_root)
            if any(part.startswith(".") or part == "__pycache__" for part in relative_from_root.parts):
                continue
            entries[entry.relative_to(anchor).as_posix()] = entry
    return entries


def _hook_anchor_from_surface_root(surface_root: Path) -> Path:
    suffix = Path(".github/hooks")
    suffix_parts = suffix.parts
    if surface_root.parts[-len(suffix_parts) :] == suffix_parts:
        return surface_root.parents[1]
    return surface_root


def _validate_entry(path: Path, *, project_root: Path, label: str) -> None:
    if path.is_symlink() and not path.exists():
        raise BrokenOverlayError(
            f"{path.relative_to(project_root)} points to a missing {label} overlay target. "
            "Run agentic-bootstrap repair to restore the overlay."
        )


def _is_declared_remote_root(path: Path, *, project_root: Path) -> bool:
    try:
        relative_path = path.relative_to(project_root)
    except ValueError:
        return False
    return relative_path.parts[:2] == (".agentic", "remote")


def _resolve_shared_root(kind: SurfaceKind, *, project_root: Path, declared_root: Path) -> Path:
    if declared_root.exists():
        return declared_root

    fallback_root = project_root / DEFAULT_SURFACE_ROOTS[kind]
    if _is_declared_remote_root(declared_root, project_root=project_root) and fallback_root.exists():
        return fallback_root

    return declared_root


def resolve_surface(kind: SurfaceKind, project_root: Path) -> list[ResolvedPath]:
    project_root = project_root.expanduser().resolve()
    roots = _surface_roots(project_root, kind)
    if roots is None:
        if kind == "hooks":
            return [
                ResolvedPath(source="shared", effective_path=path, shared_path=path)
                for path in _iter_hook_entries(project_root).values()
            ]

        default_root = project_root / DEFAULT_SURFACE_ROOTS[kind]
        if not default_root.exists():
            return []
        return [
            ResolvedPath(source="shared", effective_path=path, shared_path=path)
            for path in _iter_surface_entries(default_root).values()
        ]

    shared_root, local_root = roots
    shared_root = _resolve_shared_root(kind, project_root=project_root, declared_root=shared_root)
    if kind == "hooks":
        shared_entries = _iter_hook_entries(_hook_anchor_from_surface_root(shared_root))
        local_entries = _iter_hook_entries(_hook_anchor_from_surface_root(local_root))
    else:
        shared_entries = _iter_surface_entries(shared_root)
        local_entries = _iter_surface_entries(local_root)
    resolved: list[ResolvedPath] = []

    for name in sorted(set(shared_entries) | set(local_entries)):
        local_entry = local_entries.get(name)
        shared_entry = shared_entries.get(name)

        if local_entry is not None:
            _validate_entry(local_entry, project_root=project_root, label="local")
        if shared_entry is not None:
            _validate_entry(shared_entry, project_root=project_root, label="shared")

        if local_entry is not None and shared_entry is not None:
            resolved.append(
                ResolvedPath(
                    source="overlapping",
                    effective_path=local_entry,
                    shared_path=shared_entry,
                    local_path=local_entry,
                )
            )
            continue
        if local_entry is not None:
            resolved.append(ResolvedPath(source="local", effective_path=local_entry, local_path=local_entry))
            continue
        if shared_entry is not None:
            resolved.append(ResolvedPath(source="shared", effective_path=shared_entry, shared_path=shared_entry))

    return resolved
