#!/usr/bin/env python3
"""Verify E15-EPICSYNC doc-chain consistency across linked planning surfaces."""

from __future__ import annotations

import re
from pathlib import Path

E15_3_PLAN = Path("docs/tasks/15.0/E15-3-wordpress-demo-provisioning-task-plan.md")
SELF_HOSTING_EPIC = Path("docs/epics/v0.3.1/self-hosting-epic.md")
LAUNCH_EPIC = Path("docs/epics/v0.4.0/public-demo-launch-readiness-epic.md")


def verify_e15_3_predecessors() -> list[str]:
    text = E15_3_PLAN.read_text(encoding="utf-8")
    required = (
        "E15-3a-localwp-oci-roundtrip-task-plan.md",
        "E15-22-workbench-avatar-and-progress-readiness-task-plan.md",
    )
    return [marker for marker in required if marker not in text]


def verify_self_hosting_scope_split() -> list[str]:
    text = SELF_HOSTING_EPIC.read_text(encoding="utf-8")
    errors: list[str] = []

    for label, pattern in (
        ("budget alerts owner", r"OCI budget alerts.*\|\s*\*\*E15-5a\*\*"),
        ("Hetzner fallback owner", r"Hetzner CX22 fallback plan documented.*\|\s*\*\*E15-5a\*\*"),
        ("budget checklist delegation", r"Configure budget alerts.*delegated to E15-5a"),
        ("Hetzner checklist missing", r"Hetzner CX22 fallback plan documented.*delegated to E15-5a"),
        ("ARM owner stays E15-5", r"ARM compatibility verification artifact.*\|\s*\*\*E15-5\*\*"),
        ("remote E2E owner stays E15-5", r"End-to-end WP → backend → recognition smoke test.*\|\s*\*\*E15-5\*\*"),
        ("E15-3a gate row", r"LocalWP → OCI round-trip gate.*\|\s*\*\*E15-3a\*\*"),
    ):
        if not re.search(pattern, text):
            errors.append(f"self-hosting-epic.md: {label} not satisfied")

    if "delegated to E15-5" in text and "delegated to E15-5a" not in text:
        errors.append("self-hosting-epic.md: stale E15-5 hygiene delegation remains")

    stale_hygiene = re.findall(
        r"(budget alerts|Hetzner CX22 fallback).*\*\*E15-5\*\*(?!a)",
        text,
        flags=re.IGNORECASE,
    )
    if stale_hygiene:
        errors.append(
            "self-hosting-epic.md: hygiene items still owned by E15-5 instead of E15-5a"
        )

    return errors


def verify_launch_epic_phase4_split() -> list[str]:
    text = LAUNCH_EPIC.read_text(encoding="utf-8")
    errors: list[str] = []
    if "E15-5a OCI operational hygiene" not in text:
        errors.append("launch epic: missing E15-5a Phase 4 enumeration")
    if "E15-3a" not in text.split("Phase 3", 1)[-1][:1200]:
        errors.append("launch epic: missing E15-3a Phase 3 gate")
    if re.search(r"budget alerts.*\*\*E15-5\*\*(?!a)", text):
        errors.append("launch epic: budget alerts still assigned to E15-5")
    return errors


def main() -> int:
    errors: list[str] = []
    errors.extend(
        f"E15-3 plan missing predecessor link: {marker}"
        for marker in verify_e15_3_predecessors()
    )
    errors.extend(verify_self_hosting_scope_split())
    errors.extend(verify_launch_epic_phase4_split())

    if errors:
        for error in errors:
            print(error)
        return 1

    print("ok: E15-EPICSYNC doc chain consistent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())