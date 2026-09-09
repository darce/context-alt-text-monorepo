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
    if any(path.startswith(prefix) for prefix in PLANNING_DIR_PREFIXES):
        return True
    if path.startswith("packages/"):
        parts = path.split("/")
        if len(parts) >= 5 and parts[2] == "docs" and parts[3] == "tasks":
            return True
    return False
