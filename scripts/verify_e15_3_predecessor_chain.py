#!/usr/bin/env python3
"""Backward-compatible entry point; delegates to the EPICSYNC doc-chain verifier."""

from __future__ import annotations

from verify_e15_epicsync_doc_chain import main

if __name__ == "__main__":
    raise SystemExit(main())