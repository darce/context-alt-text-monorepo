"""The GPU cost runbook must not present a never-deployed reaper as a cost cap.

WBUX6-W4-F-01: `docs/runbooks/oci-instance-state-and-cost.md` told operators
that `acx-gpu-idle-reaper.timer` stops `acx-gpu-burst` after 300 s idle, naming
it as the cap on a ~$2.00/GPU-hour spend. OCIGOV-1 records a 2026-08-04
verification on `acx-backend` that the unit does not exist on any booted host
and that the cloud-init block is a dead template. Both cannot be true, and the
false one is the one an operator acts on: they believe a control is running that
nobody has ever observed, and budget accordingly.

Two documents, one claim, no check between them. This module is the check
(rg-006 documented behaviour must hold as written; RLSE-05 silent failure is
the worst failure -- here the silence is a cost control that does not exist,
~/Development/heuristics-canon-research/lexicons/engineering.md:696).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNBOOK = REPO_ROOT / "docs/runbooks/oci-instance-state-and-cost.md"
OCIGOV = REPO_ROOT / "docs/tasks/ocigov/OCIGOV-1-workbay-estate-governance.md"

_REAPER = "acx-gpu-idle-reaper"
# Wording that marks a mention as "this is not running", in any of the forms the
# two documents use. A mention carrying none of these reads as an active control.
_NOT_LIVE_MARKERS = (
    "dead template",
    "never been deployed",
    "not live",
    "no idle reaper is live",
    "not installed",
    "no reaper is running",
    "does not exist",
    "not-found",
)


def _mentions(text: str) -> list[str]:
    """Paragraph-level context for each reaper mention (markdown blocks, not lines)."""

    return [block for block in re.split(r"\n\s*\n", text) if _REAPER in block]


def test_ocigov_still_records_the_reaper_as_never_deployed() -> None:
    """If OCIGOV-1 ever lands the supervisor, this guard must be revisited, not deleted."""

    ocigov = OCIGOV.read_text(encoding="utf-8")

    assert "never been deployed" in ocigov, (
        "OCIGOV-1 no longer records the reaper as never deployed. If a supervisor is now "
        "live, update the runbook to describe it and re-point this guard at the new evidence."
    )
    assert "dead template" in ocigov


def test_runbook_never_presents_the_reaper_as_an_active_cost_cap() -> None:
    runbook = RUNBOOK.read_text(encoding="utf-8")
    blocks = _mentions(runbook)

    assert blocks, f"{RUNBOOK.name} no longer mentions {_REAPER}; this guard has lost its subject"
    unqualified = [
        block for block in blocks if not any(marker in block.lower() for marker in _NOT_LIVE_MARKERS)
    ]
    assert not unqualified, (
        "the runbook presents the idle reaper as an active control, but OCIGOV-1 verified "
        f"2026-08-04 that no such unit exists on any booted host. Offending block(s): {unqualified}"
    )


def test_runbook_states_that_no_automatic_gpu_cost_cap_exists() -> None:
    """Removing the qualification is not enough; the absence has to be stated."""

    runbook = RUNBOOK.read_text(encoding="utf-8").lower()

    assert "no automatic gpu cost cap" in runbook, (
        "the runbook must say plainly that nothing stops a running burst GPU automatically"
    )
    assert "ocigov-1" in runbook, "the runbook must cite the verification it relies on"
