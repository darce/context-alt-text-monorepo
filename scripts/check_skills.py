#!/usr/bin/env python3
"""Validate skill anatomy and wiring for `.claude/skills/*/SKILL.md`."""

from __future__ import annotations

import ast
from collections import Counter
import importlib.util
import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ModuleNotFoundError as exc:
    yaml = None
    _YAML_IMPORT_ERROR = exc
else:
    _YAML_IMPORT_ERROR = None

try:
    from scripts.overlay_resolver import BrokenOverlayError, OverlayResolverError, resolve_surface
except ModuleNotFoundError:
    from overlay_resolver import BrokenOverlayError, OverlayResolverError, resolve_surface

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = REPO_ROOT / ".claude" / "skills"
ROUTING_FILE = REPO_ROOT / "docs" / "workstate" / "maps" / "mcp-tool-routing.yaml"

REQUIRED_FIELDS = (
    "name",
    "description",
    "mode",
    "context_budget",
    "makefile_target",
    "mcp_tools",
    "tdd_gate",
    "disable-model-invocation",
)
REQUIRED_SECTIONS = (
    "## Overview",
    "## Trigger",
    "## Goal",
    "## Canonical Policy",
    "## Core Process",
    "## Common Rationalizations",
    "## Red Flags",
    "## Recovery",
    "## Convergence Criteria",
    "## See Also",
)
VALID_MODES = {"advisory", "execution"}
SERVER_API_FILES = {
    "workstate-handoff-mcp": ("workstate_handoff_mcp", "api.py"),
    "workstate-orchestrator-mcp": ("workstate_orchestrator_mcp", "api.py"),
}
MAKEFILE_RE = re.compile(r"^([A-Za-z0-9_.-]+):")


class SkillCheckError(Exception):
    pass


def _resolve_package_file(*, package_name: str, relative_name: str) -> Path:
    spec = importlib.util.find_spec(package_name)
    if spec is None:
        raise SkillCheckError(f"unable to resolve `{package_name}` from the import path")

    candidate_dirs: list[Path] = []
    if spec.submodule_search_locations:
        candidate_dirs.extend(Path(path).resolve() for path in spec.submodule_search_locations)
    if spec.origin:
        candidate_dirs.append(Path(spec.origin).resolve().parent)

    seen_dirs: set[Path] = set()
    for package_dir in candidate_dirs:
        if package_dir in seen_dirs:
            continue
        seen_dirs.add(package_dir)
        candidate = package_dir / relative_name
        if candidate.is_file():
            return candidate

    raise SkillCheckError(f"unable to resolve `{package_name}/{relative_name}` from the import path")


def _load_frontmatter_and_body(path: Path) -> tuple[dict, str]:
    text = path.read_text()
    if not text.startswith("---\n"):
        raise SkillCheckError("missing YAML frontmatter block")
    try:
        _, frontmatter_raw, body = text.split("---\n", 2)
    except ValueError as exc:
        raise SkillCheckError("frontmatter delimiters are malformed") from exc
    frontmatter = yaml.safe_load(frontmatter_raw) or {}
    if not isinstance(frontmatter, dict):
        raise SkillCheckError("frontmatter must parse to a mapping")
    return frontmatter, body


def _extract_literal_tool_names(api_path: Path) -> set[str]:
    module = ast.parse(api_path.read_text(), filename=str(api_path))
    for node in module.body:
        names_to_collect: list[str] = []
        value: ast.AST | None = None
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in {"TOOL_DESCRIPTIONS", "LEGACY_TOOL_DESCRIPTIONS"}:
                    names_to_collect.append(target.id)
                    value = node.value
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id in {"TOOL_DESCRIPTIONS", "LEGACY_TOOL_DESCRIPTIONS"}:
                names_to_collect.append(node.target.id)
                value = node.value

        if not names_to_collect:
            continue
        if not isinstance(value, ast.Dict):
            raise SkillCheckError(f"{api_path} {', '.join(names_to_collect)} is not a dict literal")
        names: set[str] = set()
        for key in value.keys:
            if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                raise SkillCheckError(f"{api_path} {', '.join(names_to_collect)} contains a non-literal key")
            names.add(key.value)
        return names
    raise SkillCheckError(f"{api_path} does not define TOOL_DESCRIPTIONS or LEGACY_TOOL_DESCRIPTIONS")


def _load_known_tools() -> set[str]:
    routing = yaml.safe_load(ROUTING_FILE.read_text()) or {}
    if not isinstance(routing, dict):
        raise SkillCheckError("mcp-tool-routing.yaml must parse to a mapping")

    server_names: set[str] = set()
    always = routing.get("always", [])
    if isinstance(always, list):
        server_names.update(str(item) for item in always)

    on_demand = routing.get("on_demand", {})
    if isinstance(on_demand, dict):
        server_names.update(str(name) for name in on_demand)

    known_tools: set[str] = set()
    for server_name in sorted(server_names):
        api_spec = SERVER_API_FILES.get(server_name)
        if api_spec is None:
            # External services such as computer-use do not ship a local API
            # manifest in this repo, so they cannot contribute local
            # skill-wiring entries here.
            continue
        package_name, relative_name = api_spec
        api_path = _resolve_package_file(package_name=package_name, relative_name=relative_name)
        known_tools.update(_extract_literal_tool_names(api_path))
    return known_tools


def _load_make_targets() -> set[str]:
    targets: set[str] = set()
    for path in [REPO_ROOT / "Makefile", *(REPO_ROOT / "mk").glob("*.mk")]:
        for line in path.read_text().splitlines():
            match = MAKEFILE_RE.match(line)
            if match:
                targets.add(match.group(1))
    return targets


def _validate_frontmatter(frontmatter: dict, make_targets: set[str], known_tools: set[str]) -> list[str]:
    errors: list[str] = []

    for field in REQUIRED_FIELDS:
        if field not in frontmatter:
            errors.append(f"missing required frontmatter field `{field}`")

    mode = frontmatter.get("mode")
    if mode not in VALID_MODES:
        errors.append(f"`mode` must be one of {sorted(VALID_MODES)}, got {mode!r}")

    context_budget = frontmatter.get("context_budget")
    if not isinstance(context_budget, int) or context_budget <= 0:
        errors.append("`context_budget` must be a positive integer")

    for bool_field in ("tdd_gate", "disable-model-invocation"):
        if not isinstance(frontmatter.get(bool_field), bool):
            errors.append(f"`{bool_field}` must be a boolean")

    target = frontmatter.get("makefile_target")
    if target is not None:
        if not isinstance(target, str) or not target.strip():
            errors.append("`makefile_target` must be null or a non-empty string")
        elif target not in make_targets:
            errors.append(f"`makefile_target` references unknown target `{target}`")

    mcp_tools = frontmatter.get("mcp_tools")
    if not isinstance(mcp_tools, list):
        errors.append("`mcp_tools` must be a list")
    else:
        for tool_name in mcp_tools:
            if not isinstance(tool_name, str) or not tool_name.strip():
                errors.append("`mcp_tools` entries must be non-empty strings")
                continue
            if tool_name not in known_tools:
                errors.append(f"`mcp_tools` references unknown MCP tool `{tool_name}`")

    for text_field in ("name", "description"):
        value = frontmatter.get(text_field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"`{text_field}` must be a non-empty string")

    return errors


def _validate_sections(body: str) -> list[str]:
    return [f"missing required section `{section}`" for section in REQUIRED_SECTIONS if section not in body]


def _has_workstate_bootstrap_manifest(repo_root: Path) -> bool:
    manifest_path = repo_root / ".workstate-bootstrap.json"
    if not manifest_path.is_file():
        return False
    try:
        payload = json.loads(manifest_path.read_text())
    except OSError:
        return False
    except json.JSONDecodeError as exc:
        # A malformed manifest is an infrastructure error, not a resilient
        # fall-through; only valid-but-non-contract-shaped payloads fall back.
        raise OverlayResolverError(f"workstate bootstrap manifest is not valid JSON: {exc}") from exc
    return isinstance(payload, dict) and "surfaces" in payload


def _resolve_skill_files(repo_root: Path, skills_root: Path) -> tuple[list[Path], list[str]]:
    try:
        is_overlay = _has_workstate_bootstrap_manifest(repo_root)
    except OverlayResolverError as exc:
        return [], [f"infrastructure error: {exc}"]
    if not is_overlay:
        return sorted(skills_root.glob("*/SKILL.md")), []

    try:
        resolved_entries = resolve_surface("skills", repo_root)
    except BrokenOverlayError as exc:
        return [], [f"BrokenOverlayError: {exc}"]
    except OverlayResolverError as exc:
        return [], [f"infrastructure error: {exc}"]

    resolved_files = sorted(
        entry.effective_path / "SKILL.md"
        for entry in resolved_entries
        if (entry.effective_path / "SKILL.md").is_file()
    )
    return resolved_files, []


def _format_success_message(*, repo_root: Path, skills_root: Path) -> str:
    skill_files, _overlay_failures = _resolve_skill_files(repo_root, skills_root)
    if not _has_workstate_bootstrap_manifest(repo_root):
        return f"check-skills: OK ({len(skill_files)} skills)"

    counts: Counter[str] = Counter(
        entry.source
        for entry in resolve_surface("skills", repo_root)
        if (entry.effective_path / "SKILL.md").is_file()
    )
    return (
        "check-skills: OK "
        f"({len(skill_files)} skills; shared={counts['shared']} local={counts['local']} overlapping={counts['overlapping']})"
    )


def check_skills(
    *,
    repo_root: Path = REPO_ROOT,
    skills_root: Path | None = None,
    routing_file: Path | None = None,
) -> tuple[list[str], int]:
    if _YAML_IMPORT_ERROR is not None:
        return ["infrastructure error: PyYAML is required to load skill frontmatter"], 1

    skills_root = skills_root or (repo_root / ".claude" / "skills")
    routing_file = routing_file or (repo_root / "docs" / "workstate" / "maps" / "mcp-tool-routing.yaml")

    global REPO_ROOT, SKILLS_ROOT, ROUTING_FILE
    original_repo_root, original_skills_root, original_routing_file = REPO_ROOT, SKILLS_ROOT, ROUTING_FILE
    REPO_ROOT, SKILLS_ROOT, ROUTING_FILE = repo_root, skills_root, routing_file

    try:
        known_tools = _load_known_tools()
        make_targets = _load_make_targets()
    except SkillCheckError as exc:
        return [f"infrastructure error: {exc}"], 1
    finally:
        REPO_ROOT, SKILLS_ROOT, ROUTING_FILE = original_repo_root, original_skills_root, original_routing_file

    failures: list[str] = []
    skill_files, overlay_failures = _resolve_skill_files(repo_root, skills_root)
    failures.extend(overlay_failures)
    for skill_path in skill_files:
        try:
            frontmatter, body = _load_frontmatter_and_body(skill_path)
        except SkillCheckError as exc:
            failures.append(f"{skill_path.relative_to(repo_root)}: {exc}")
            continue

        for error in _validate_frontmatter(frontmatter, make_targets, known_tools):
            failures.append(f"{skill_path.relative_to(repo_root)}: {error}")
        for error in _validate_sections(body):
            failures.append(f"{skill_path.relative_to(repo_root)}: {error}")

    return failures, 0 if not failures else 1


def main() -> int:
    repo_root = REPO_ROOT
    skills_root = repo_root / ".claude" / "skills"
    routing_file = repo_root / "docs" / "workstate" / "maps" / "mcp-tool-routing.yaml"

    failures, exit_code = check_skills(repo_root=repo_root, skills_root=skills_root, routing_file=routing_file)
    if exit_code == 1 and failures and failures[0].startswith("infrastructure error:"):
        print(f"check-skills: {failures[0]}", file=sys.stderr)
        return 1

    if failures:
        print("check-skills: FAILED", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1

    print(_format_success_message(repo_root=repo_root, skills_root=skills_root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
