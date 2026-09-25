#!/usr/bin/env python3
"""Tracked fallback for `make plan-accept`, used only when `Makefile.d/plans.mk` is not installed.
When the overlay is installed, its recipe runs instead and owns review gating and landing.
This fallback validates `TASK`/`PLAN` inputs only; it exits 3 because nothing was landed.
`mk/lane-lifecycle.mk` invokes this file through `ACX_LIFECYCLE_HANDLERS`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HANDLER_ID = "scripts/workstate/lifecycle/handlers/plan_baseline.py"
EXIT_VALIDATED_ONLY = 3


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", required=True)
    parser.add_argument("--plan", default="")
    args = parser.parse_args(argv)
    task = args.task.strip()
    plan_arg = args.plan.strip()
    payload = {
        "handler": HANDLER_ID,
        "task": task,
        "plan": plan_arg,
    }
    if not task:
        payload["status"] = "missing_task"
        print(json.dumps(payload, sort_keys=True))
        print("TASK= is required for plan-accept", file=sys.stderr)
        return 2
    if not plan_arg:
        payload["status"] = "missing_plan"
        print(json.dumps(payload, sort_keys=True))
        print("PLAN= is required for plan-accept", file=sys.stderr)
        return 2
    plan = Path(plan_arg)
    if not plan.is_file():
        payload["status"] = "missing_file"
        print(json.dumps(payload, sort_keys=True))
        print(f"plan file not found: {plan}", file=sys.stderr)
        return 1
    payload["status"] = "validated_only"
    payload["plan"] = str(plan.resolve())
    print(json.dumps(payload, sort_keys=True))
    print(
        "plan-accept fallback: inputs validated; nothing was landed "
        "(install the workbay plugin overlay for the gated plan-accept)",
        file=sys.stderr,
    )
    return EXIT_VALIDATED_ONLY


if __name__ == "__main__":
    sys.exit(main())
