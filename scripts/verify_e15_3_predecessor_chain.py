#!/usr/bin/env python3
"""Verify E15-3 task plan names E15-22 and E15-3a predecessor gates."""

from __future__ import annotations

from pathlib import Path

PLAN = Path("docs/tasks/15.0/E15-3-wordpress-demo-provisioning-task-plan.md")


def main() -> int:
    text = PLAN.read_text(encoding="utf-8")
    required = (
        "E15-3a-localwp-oci-roundtrip-task-plan.md",
        "E15-22-workbench-avatar-and-progress-readiness-task-plan.md",
    )
    missing = [marker for marker in required if marker not in text]
    if missing:
        for marker in missing:
            print(f"missing predecessor link: {marker}")
        return 1
    print("ok: E15-3 predecessor chain synced")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())