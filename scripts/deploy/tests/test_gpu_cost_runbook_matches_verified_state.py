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
INSTALLER = REPO_ROOT / "scripts/deploy/gpu-lifecycle-install.sh"

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
    assert "live backend-side idle reaper" in runbook.lower()
    assert _LEGACY_REAPER not in runbook


def test_runbook_reaper_numbers_match_installer_defaults() -> None:
    runbook = RUNBOOK.read_text(encoding="utf-8").lower()
    installer = INSTALLER.read_text(encoding="utf-8")

    max_lease = re.search(
        r'^MAX_LEASE_SECONDS="\$\{MAX_LEASE_SECONDS:-([0-9]+)\}"$',
        installer,
        flags=re.MULTILINE,
    )
    idle_seconds = re.search(
        r'^IDLE_SECONDS="\$\{IDLE_SECONDS-([0-9]+)\}"$',
        installer,
        flags=re.MULTILINE,
    )
    reap_interval = re.search(
        r'^REAP_INTERVAL="\$\{REAP_INTERVAL-([^}]+)\}"$',
        installer,
        flags=re.MULTILINE,
    )

    assert max_lease is not None
    assert idle_seconds is not None
    assert reap_interval is not None

    max_lease_seconds = int(max_lease.group(1))
    idle_threshold_seconds = int(idle_seconds.group(1))
    interval = reap_interval.group(1).replace("min", " min")
    assert f"every {interval}" in runbook
    assert f"{idle_threshold_seconds}-second" in runbook
    assert f"{idle_threshold_seconds // 60}-minute" in runbook
    assert re.search(rf"{max_lease_seconds}\s+seconds", runbook)
    assert f"{max_lease_seconds // 60}-minute" in runbook


def test_runbook_states_reaper_scope_and_fail_closed_behavior() -> None:
    """The active cap must say what it can stop and when it refuses to stop."""

    runbook = RUNBOOK.read_text(encoding="utf-8").lower()

    assert "max lease expires" in runbook
    assert "fails closed" in runbook
    assert "pinned" in runbook
    assert "hand-created" in runbook
    assert "automatic gpu cost cap" not in runbook
