#!/usr/bin/env python3
"""Backward-compatible entry point; delegates to the EPICSYNC doc-chain verifier."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def main() -> int:
    target = Path(__file__).resolve().parent / "verify_e15_epicsync_doc_chain.py"
    spec = importlib.util.spec_from_file_location("verify_e15_epicsync_doc_chain", target)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load verifier module from {target}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.main()
    return int(result)


if __name__ == "__main__":
    raise SystemExit(main())