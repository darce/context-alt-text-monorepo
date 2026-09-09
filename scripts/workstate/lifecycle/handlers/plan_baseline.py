#!/usr/bin/env python3
"""Tracked plan-accept handler.

Makefile.d/lifecycle.mk must invoke this file through ACX_LIFECYCLE_HANDLERS.
The external workbay_lifecycle package is not the source of truth here.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HANDLER_ID = "scripts/workstate/lifecycle/handlers/plan_baseline.py"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", required=True)
    parser.add_argument("--plan", default="")
    args = parser.parse_args(argv)
    payload = {
        "handler": HANDLER_ID,
        "task": args.task,
        "plan": args.plan,
    }
    if not args.plan:
        payload["status"] = "missing_plan"
        print(json.dumps(payload, sort_keys=True))
        print("PLAN= is required for plan-accept", file=sys.stderr)
        return 2
    plan = Path(args.plan)
    if not plan.is_file():
        payload["status"] = "missing_file"
        print(json.dumps(payload, sort_keys=True))
        print(f"plan file not found: {plan}", file=sys.stderr)
        return 1
    payload["status"] = "accepted"
    payload["plan"] = str(plan.resolve())
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
