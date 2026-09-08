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


def test_runbook_documents_a_machine_checked_policy_test() -> None:
    """Prose asks the operator to comply; a `tests` block makes Tailscale check.

    Tailscale evaluates the policy-file `tests` array on every save and rejects
    the save when an assertion fails. A surviving wildcard grant breaks both
    `deny` entries, so the narrow grant stops being a request and becomes an
    enforced precondition of saving the policy at all.
    """
    section = _tailscale_section()
    assert re.search(r'"tests":\s*\[', section), (
        "the runbook documents no Tailscale policy `tests` block, so the "
        "least-privilege grant is unenforced operator prose"
    )
    assert re.search(r'"src":\s*"tag:ci"', section)
    assert re.search(r'"accept":\s*\[\s*"tag:oci-vm:22"\s*\]', section), (
        "the policy test does not assert that CI keeps its TCP/22 deploy path"
    )
    deny = re.search(r'"deny":\s*\[([^\]]*)\]', section)
    assert deny, "the policy test asserts nothing about what tag:ci must not reach"
    assert '"tag:oci-vm:443"' in deny.group(1), (
        "the policy test does not deny tag:ci -> TCP/443"
    )
    assert '"tag:oci-vm:55432"' in deny.group(1), (
        "the policy test does not deny tag:ci -> the database listener on TCP/55432"
    )


def test_runbook_names_the_save_action_as_the_enforcement_point() -> None:
    section = _tailscale_section()
    lowered = section.lower()
    assert "save" in lowered and "reject" in lowered, (
        "the runbook does not tell the operator that saving the policy is "
        "itself the enforcement check that rejects a leftover wildcard grant"
    )
