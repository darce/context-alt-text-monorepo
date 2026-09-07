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


def _shell_default(installer: str, name: str) -> str:
    """The default value of one installer knob, whichever fallback form it uses.

    GPUOPS-1-HV-01: this guard used to hard-code a different fallback operator
    per variable (`:-` for one, bare `-` for the others), so it went red the
    moment the installer converged on the safer `${NAME:-default}` form. That
    is the same drift class as LAND-1-MR-01: a guard that pins incidental shell
    syntax rather than the value the runbook has to agree with. Both forms are
    accepted here; `test_installer_knobs_use_the_empty_safe_fallback_form`
    below is what pins the operator, so accepting both here loses no coverage.
    """
    match = re.search(
        rf'^{re.escape(name)}="\$\{{{re.escape(name)}:?-([^}}]+)\}}"$',
        installer,
        flags=re.MULTILINE,
    )
    assert match is not None, (
        f"{INSTALLER.name} no longer declares {name} as a shell default; "
        "this guard has lost the value it compares the runbook against"
    )
    return match.group(1)


def test_installer_knobs_use_the_empty_safe_fallback_form() -> None:
    """`${NAME-default}` keeps an empty override; `${NAME:-default}` replaces it.

    An empty `IDLE_SECONDS=` reaching the reaper's argv is a broken unit, not a
    default. LAND-1-MR-01 was exactly this bug on START_INTERVAL, so the safe
    operator is pinned rather than left to chance.
    """
    installer = INSTALLER.read_text(encoding="utf-8")

    for name in ("MAX_LEASE_SECONDS", "IDLE_SECONDS", "START_INTERVAL", "REAP_INTERVAL"):
        assert re.search(rf'^{name}="\$\{{{name}:-[^}}]+\}}"$', installer, flags=re.MULTILINE), (
            f"{name} must use the empty-safe ${{{name}:-default}} form; a bare "
            f"${{{name}-default}} passes an empty override straight into the unit"
        )


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

    max_lease_seconds = int(_shell_default(installer, "MAX_LEASE_SECONDS"))
    idle_threshold_seconds = int(_shell_default(installer, "IDLE_SECONDS"))
    interval = _shell_default(installer, "REAP_INTERVAL").replace("min", " min")
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
