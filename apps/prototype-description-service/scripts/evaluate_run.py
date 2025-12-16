#!/usr/bin/env python3
"""Evaluate a clustering run against a canonical report.

Usage:
    python -m scripts.evaluate_run --canonical <path> --tenant-id <UUID>
"""

from __future__ import annotations

import argparse
import asyncio


async def main() -> int:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Evaluate clustering output against canonical report")
    parser.add_argument("--canonical", required=True, help="Path to canonical_report.json")
    parser.add_argument("--tenant-id", required=True, help="Tenant UUID for the run to evaluate")
    parser.add_argument("--output", required=False, help="Optional output path for metrics JSON")
    args = parser.parse_args()

    _ = args
    raise NotImplementedError("TODO: implement scripts.evaluate_run main")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
