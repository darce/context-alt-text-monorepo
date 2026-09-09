from __future__ import annotations

import fnmatch
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github/workflows/gates-harness.yml"

OWNED_PREFIXES = (
    "scripts/remote_agent.sh",
    "scripts/remote_gate.sh",
    "scripts/lint_ratchet.py",
    "scripts/tests/",
    "scripts/workstate/",
    "scripts/workbay_lifecycle/",
    "scripts/vm/",
    "scripts/deploy/lib/bounded-remote-build",
    ".github/workflows/",
    ".gitignore",
    "pyproject.toml",
    "Makefile.d/lifecycle.mk",
    "mk/lane-lifecycle.mk",
    "mk/lane-worker.mk",
)


def _github_match(path: str, pattern: str) -> bool:
    """Match a GitHub Actions path filter (minimatch-style **)."""
    path = path.rstrip("/")
    if pattern.endswith("/**"):
        prefix = pattern[:-3]
        return path == prefix or path.startswith(prefix + "/")
    if "**" in pattern:
        regex = re.escape(pattern)
        regex = regex.replace(r"\*\*/", "(?:.*/)?")
        regex = regex.replace(r"\*\*", ".*")
        regex = regex.replace(r"\*", "[^/]*")
        regex = regex.replace(r"\?", "[^/]")
        return re.fullmatch(regex, path) is not None
    return fnmatch.fnmatchcase(path, pattern)


def _path_filters(text: str) -> list[str]:
    filters: list[str] = []
    in_paths = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "paths:":
            in_paths = True
            continue
        if in_paths:
            match = re.fullmatch(r'- "([^"]+)"', stripped)
            if match:
                filters.append(match.group(1))
                continue
            if stripped and not stripped.startswith("#"):
                in_paths = False
    return filters


def _candidates(prefix: str) -> list[str]:
    trimmed = prefix.rstrip("/")
    if prefix.endswith("/") or trimmed != prefix:
        return [
            trimmed,
            f"{trimmed}/example.sh",
            f"{trimmed}/example.py",
            f"{trimmed}/example.mk",
            f"{trimmed}/example.yml",
            f"{trimmed}/nested/file.sh",
        ]
    return [trimmed]


def test_owned_path_prefixes_are_covered_by_workflow_filters() -> None:
    filters = _path_filters(WORKFLOW.read_text(encoding="utf-8"))
    assert filters, "workflow has no path filters"
    missing: list[str] = []
    for prefix in OWNED_PREFIXES:
        if not any(_github_match(candidate, pattern) for candidate in _candidates(prefix) for pattern in filters):
            missing.append(prefix)
    assert missing == [], f"owned prefixes not covered by gates-harness.yml path filters: {missing}"
