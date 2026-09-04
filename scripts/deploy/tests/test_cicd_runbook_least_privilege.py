"""OCIRV1-FS-06: the CI tailnet grant must be documented as mandatory.

The runbook used to tell the operator that the default allow-all grant made a
grant edit unnecessary. That reading is only safe if nothing else is exposed on
the tailnet: a compromised CI OAuth identity inherits `src=* dst=* ip=*` and can
reach every service on every node, not just TCP/22 on the deploy VM. Least
privilege and safe defaults (Anderson, Security Engineering; PRINCIPLES.md #14)
say the narrow grant is the setup step and the wildcard is the exception.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNBOOK = REPO_ROOT / "docs" / "runbooks" / "deploy-recognition-cicd.md"


def _tailscale_section() -> str:
    text = RUNBOOK.read_text(encoding="utf-8")
    start = text.index("### 1. Tailscale")
    end = text.index("\n### ", start + 1)
    return text[start:end]


def test_runbook_requires_the_narrow_ci_grant() -> None:
    section = _tailscale_section()
    assert re.search(
        r'\{\s*"src":\s*\["tag:ci"\],\s*"dst":\s*\["tag:oci-vm"\],\s*"ip":\s*\["tcp:22"\]\s*\}',
        section,
    ), "the least-privilege tag:ci -> tag:oci-vm tcp:22 grant is no longer documented"


def test_runbook_does_not_present_the_wildcard_as_sufficient() -> None:
    section = _tailscale_section()
    assert "no grant edit needed" not in section, (
        "the runbook still tells the operator the default allow-all grant makes the least-privilege grant optional"
    )
    assert "If/when you tighten that wildcard" not in section, (
        "the narrow grant is still framed as a later, optional tightening"
    )


def test_runbook_names_the_wildcard_blast_radius() -> None:
    section = _tailscale_section()
    assert "blast radius" in section.lower(), (
        "the runbook does not tell the operator what leaving the wildcard in "
        "place actually grants a compromised CI identity"
    )
