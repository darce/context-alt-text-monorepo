#!/usr/bin/env python3
"""Backward-compatible entry point for the legacy E15-3 predecessor check.

Delegates to ``verify_e15_epicsync_doc_chain.main()``, which runs the full
E15-EPICSYNC doc chain (predecessors + scope-split + launch-epic checks).
Kept as a stable path so existing callers / CI targets that reference this
filename keep working; it intentionally runs the whole chain, not a subset.
The importlib load (rather than a sibling ``import``) keeps it working when
``scripts/`` is not on ``sys.path``.
"""

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
