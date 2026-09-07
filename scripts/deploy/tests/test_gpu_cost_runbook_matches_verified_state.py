"""The GPU cost runbook must describe the installer-owned reaper accurately.

The lifecycle installer is now the single owner of the backend reaper. This
guard keeps the operator documentation tied to that deployed unit's scope and
fail-closed behavior (rg-006; RLSE-05 silent failure is especially costly for
an automatic spend control).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNBOOK = REPO_ROOT / "docs/runbooks/oci-instance-state-and-cost.md"

_REAPER = "acx-gpu-reap"
_LEGACY_REAPER = "acx-gpu-idle-reaper"


def _mentions(text: str) -> list[str]:
    """Paragraph-level context for each reaper mention (markdown blocks, not lines)."""

    return [block for block in re.split(r"\n\s*\n", text) if _REAPER in block]


def test_runbook_presents_the_installer_reaper_as_an_active_cost_cap() -> None:
    runbook = RUNBOOK.read_text(encoding="utf-8")
    blocks = _mentions(runbook)

    assert blocks, f"{RUNBOOK.name} no longer mentions {_REAPER}; this guard has lost its subject"
    assert "acx-gpu-reap.timer" in runbook
    assert "acx-gpu-reap.service" in runbook
    assert _LEGACY_REAPER not in runbook


def test_runbook_states_reaper_scope_and_fail_closed_behavior() -> None:
    """The active cap must say what it can stop and when it refuses to stop."""

    runbook = RUNBOOK.read_text(encoding="utf-8").lower()

    assert "max lease expires" in runbook
    assert "fails closed" in runbook
    assert "pinned" in runbook
    assert "hand-created" in runbook
    assert "no automatic gpu cost cap" not in runbook
