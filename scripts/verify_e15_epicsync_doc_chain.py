#!/usr/bin/env python3
"""Verify E15-EPICSYNC doc-chain consistency across linked planning surfaces."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
E15_3_PLAN = REPO_ROOT / "docs/tasks/15.0/E15-3-wordpress-demo-provisioning-task-plan.md"
SELF_HOSTING_EPIC = REPO_ROOT / "docs/epics/v0.3.1/self-hosting-epic.md"
LAUNCH_EPIC = REPO_ROOT / "docs/epics/v0.4.0/public-demo-launch-readiness-epic.md"


def verify_e15_3_predecessors() -> list[str]:
    text = E15_3_PLAN.read_text(encoding="utf-8")
    # Anchor to the Predecessors blockquote field so reverting the predecessor
    # edit fails the check; a whole-file substring match is vacuous because the
    # E15-22 marker already appears elsewhere in the plan on main. Accumulate any
    # wrapped continuation '>' lines (tolerant of a future line wrap) but stop at
    # the next '> **Field**:' label so the anchor cannot bleed into Blocks etc.
    lines = text.splitlines()
    block_parts: list[str] = []
    for idx, line in enumerate(lines):
        if line.lstrip().startswith("> **Predecessors**"):
            block_parts.append(line)
            for cont in lines[idx + 1:]:
                stripped = cont.lstrip()
                if stripped.startswith(">") and not re.match(r">\s*\*\*", stripped):
                    block_parts.append(cont)
                else:
                    break
            break
    predecessor_block = "\n".join(block_parts)
    required = (
        "E15-3a-localwp-oci-roundtrip-task-plan.md",
        "E15-22-workbench-avatar-and-progress-readiness-task-plan.md",
    )
    return [marker for marker in required if marker not in predecessor_block]


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
        ("E2E checklist stays E15-5", r"End-to-end smoke test.*delegated to E15-5(?![\w-])"),
        ("E15-3a gate row", r"LocalWP → OCI round-trip gate.*\|\s*\*\*E15-3a\*\*"),
    ):
        if not re.search(pattern, text):
            errors.append(f"self-hosting-epic.md: {label} not satisfied")

    # The '**...**' fences already disambiguate **E15-5** from **E15-5a**, so no
    # trailing negative-lookahead is needed here.
    stale_hygiene = re.findall(
        r"(budget alerts|Hetzner CX22 fallback).*\*\*E15-5\*\*",
        text,
        flags=re.IGNORECASE,
    )
    if stale_hygiene:
        errors.append(
            "self-hosting-epic.md: hygiene items still owned by E15-5 instead of E15-5a"
        )

    return errors


def _phase_section(text: str, phase: str) -> str:
    """Body of the first '## '/'### ' 'Phase <n>' heading, up to the next phase heading."""
    match = re.search(rf"^#{{2,3}}\s+Phase {re.escape(phase)}\b.*$", text, flags=re.MULTILINE)
    if not match:
        return ""
    rest = text[match.end():]
    nxt = re.search(r"^#{2,3}\s+Phase\s", rest, flags=re.MULTILINE)
    return rest[: nxt.start()] if nxt else rest


def verify_launch_epic_phase4_split() -> list[str]:
    text = LAUNCH_EPIC.read_text(encoding="utf-8")
    errors: list[str] = []
    if "E15-5a OCI operational hygiene" not in text:
        errors.append("launch epic: missing E15-5a Phase 4 enumeration")
    if "E15-3a" not in _phase_section(text, "3"):
        errors.append("launch epic: missing E15-3a Phase 3 gate")
    # OCI-hygiene surfaces must be OWNED by E15-5a, never plain E15-5, keeping
    # owner parity with the self-hosting epic split. Match only ownership tokens
    # (bold / parenthetical / delegated forms) so narrative prose that merely
    # names E15-5's remaining scope on the same line is not a false positive.
    owner_e15_5 = r"(?:\*\*E15-5\*\*|\(E15-5\)|delegated to E15-5(?![\w-]))"
    for surface in ("budget alert", "Hetzner"):
        for line in text.splitlines():
            if surface.lower() in line.lower() and re.search(owner_e15_5, line):
                errors.append(f"launch epic: '{surface}' line still assigns ownership to E15-5 (should be E15-5a)")
                break
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
