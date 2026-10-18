#!/usr/bin/env python3
"""Merge re-fetched items back into a base run-record (fix corpus holes in place).

Replaces items in --base by media_id with the (successful) items from --patch,
preserving order. Fails loudly if a patch item still carries an error — a hole is
only fixed when the re-fetch actually succeeded.

    python -m scripts.eval_harness.merge_refetch \
        --base out/run-altq-646-interleave-v3.json \
        --patch out/run-refetch6.json --out out/run-altq-646-interleave-v3.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", required=True)
    ap.add_argument("--patch", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    base = json.loads(Path(args.base).read_text())
    patch = json.loads(Path(args.patch).read_text())
    patched = {int(i["media_id"]): i for i in patch["items"]}

    still_broken = [mid for mid, i in patched.items() if i.get("error")]
    if still_broken:
        sys.exit(f"re-fetch still failed for media_id(s) {sorted(still_broken)} — not merging a broken patch")

    replaced = 0
    for idx, item in enumerate(base["items"]):
        mid = int(item["media_id"])
        if mid in patched:
            base["items"][idx] = patched[mid]
            replaced += 1

    remaining_errors = [int(i["media_id"]) for i in base["items"] if i.get("error")]
    Path(args.out).write_text(json.dumps(base, indent=2, sort_keys=True) + "\n")
    print(f"merged {replaced} re-fetched item(s); remaining error items: {sorted(remaining_errors) or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
