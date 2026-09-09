"""Planning-path classification for plan-accept (E15-23-PR-20260605-03).

Tracked copy of the overlay handler prefix set so task-plan drafts under
``docs/tasks/`` are recognized even when the gitignored workbay_lifecycle
overlay is missing from a linked worktree.
"""

from __future__ import annotations

PLANNING_DIR_PREFIXES: tuple[str, ...] = (
    "docs/scopes/",
    "docs/plans/",
    "docs/assessments/",
    "docs/adrs/",
    "docs/reviews/",
    "docs/tech-debt/",
    "docs/tasks/",
)


def is_planning_path(path: str) -> bool:
    normalized = path.lstrip("./")
    if any(normalized.startswith(prefix) for prefix in PLANNING_DIR_PREFIXES):
        return True
    if normalized.startswith("packages/"):
        parts = normalized.split("/")
        if len(parts) >= 5 and parts[2] == "docs" and parts[3] == "tasks":
            return True
    return False


def is_worktree_clean_or_only_plan(dirty_paths: list[str], plan_path: str | None = None) -> bool:
    """Allow sibling planning docs, not only the named --plan file.

    E15-23-PR-20260605-03: `--local` used to fail closed on any dirty path that
    was not exactly the plan file, including a sibling docs/tasks draft from
    the same planning slice.
    """
    if not dirty_paths:
        return True
    allowed = {path.lstrip("./") for path in dirty_paths if is_planning_path(path)}
    if plan_path:
        allowed.add(plan_path.lstrip("./"))
    return {path.lstrip("./") for path in dirty_paths} <= allowed
