#!/usr/bin/env python3
"""Keep Cursor plugin trees skills-only to avoid duplicate workflow picker entries."""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

try:  # single source of truth for the overlay clone location — no hardcoded paths
    from scripts._overlay_clone import hoisted_generator_path
except ModuleNotFoundError:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from _overlay_clone import hoisted_generator_path

PLUGIN_ROOT = REPO_ROOT / ".workbay" / "generated" / "plugins" / "workbay-system"
REMOTE_GENERATOR = hoisted_generator_path(REPO_ROOT)
MARKER_NAME = ".native-skills-only"
_FALLBACK_MARKER_BODY = (
    "# Cursor native workflows are discovered from .cursor/skills only.\n"
    "# Command markdown files are intentionally omitted to avoid duplicate picker entries.\n"
)


def _marker_body() -> str:
    # The hoisted generator owns the marker text; read it from there so an
    # upstream rewording cannot drift against a duplicated literal here.
    if REMOTE_GENERATOR is not None and REMOTE_GENERATOR.is_file():
        spec = importlib.util.spec_from_file_location("_gaw_remote", REMOTE_GENERATOR)
        if spec is not None and spec.loader is not None:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            body = getattr(module, "_CURSOR_COMMANDS_SKILLS_ONLY_MARKER", None)
            if isinstance(body, str) and body:
                return body
    return _FALLBACK_MARKER_BODY


def _cursor_commands_dirs(plugin_root: Path) -> list[Path]:
    dirs: list[Path] = []
    for harness in ("base", "effective"):
        commands_dir = plugin_root / harness / "cursor" / "commands"
        if commands_dir.is_dir():
            dirs.append(commands_dir)
    return dirs


def apply_cursor_skills_only_surface(plugin_root: Path = PLUGIN_ROOT) -> int:
    changed = 0
    marker_body = _marker_body()
    for commands_dir in _cursor_commands_dirs(plugin_root):
        for path in sorted(commands_dir.glob("*.md")):
            path.unlink()
            changed += 1
        marker = commands_dir / MARKER_NAME
        if not marker.exists() or marker.read_text() != marker_body:
            marker.write_text(marker_body)
            changed += 1
    return changed


def check_cursor_skills_only_surface(plugin_root: Path = PLUGIN_ROOT) -> list[str]:
    commands_dirs = _cursor_commands_dirs(plugin_root)
    if not commands_dirs:
        return [
            f"no cursor/commands dirs under {plugin_root}; "
            "plugin tree not built — run `make plugins-build` first"
        ]
    failures: list[str] = []
    marker_body = _marker_body()
    for commands_dir in commands_dirs:
        markdown = sorted(commands_dir.glob("*.md"))
        if markdown:
            failures.append(
                "cursor command markdown must not be emitted: "
                + ", ".join(path.name for path in markdown)
            )
        marker = commands_dir / MARKER_NAME
        if not marker.is_file() or marker.read_text() != marker_body:
            failures.append(f"missing or stale {MARKER_NAME} in {commands_dir}")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero when Cursor command markdown is present.",
    )
    parser.add_argument(
        "--plugin-root",
        type=Path,
        default=PLUGIN_ROOT,
        help="Plugin tree root (default: .workbay/generated/plugins/workbay-system).",
    )
    args = parser.parse_args(argv)
    plugin_root = args.plugin_root.resolve()

    if args.check:
        failures = check_cursor_skills_only_surface(plugin_root)
        if failures:
            print("apply-cursor-skills-only-surface: FAIL", file=sys.stderr)
            for failure in failures:
                print(f"  - {failure}", file=sys.stderr)
            return 1
        print("apply-cursor-skills-only-surface: OK")
        return 0

    changed = apply_cursor_skills_only_surface(plugin_root)
    print(f"apply-cursor-skills-only-surface: OK ({changed} change(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
