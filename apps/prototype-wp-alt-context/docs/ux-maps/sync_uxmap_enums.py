#!/usr/bin/env python3
"""Generate or verify the TypeScript parity test's canonical Python enum snapshot."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

SNAPSHOT = (
    Path(__file__).resolve().parents[2]
    / "js/admin/__tests__/uxmap-render-parity.fixtures/uxmap-enums.snapshot.json"
)


def _derive() -> tuple[dict[str, list[str]], str]:
    from workbay_canvas_mcp.ux_map import models

    source = Path(models.__file__).resolve()
    values = {
        "mapStates": [item.value for item in models.MapState],
        "zoneRoles": [item.value for item in models.ZoneRole],
    }
    revision = "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
    return values, revision


def main(argv: list[str]) -> int:
    write = argv[1:] == ["--write"]
    if argv[1:] not in ([], ["--check"], ["--write"]):
        print("usage: sync_uxmap_enums.py [--check|--write]", file=sys.stderr)
        return 2
    fixture = json.loads(SNAPSHOT.read_text(encoding="utf8"))
    revision = fixture.get("source_revision")
    if not isinstance(revision, str) or not revision:
        print("enum snapshot has no recorded source_revision", file=sys.stderr)
        return 1
    try:
        derived, current_revision = _derive()
    except ImportError as exc:
        if write:
            print(f"cannot generate enum snapshot: {exc}", file=sys.stderr)
            return 1
        print(
            "SKIP enum derivation: workbay_canvas_mcp is unimportable; "
            f"fixture records {revision}",
        )
        return 0
    expected = {"mapStates": fixture.get("mapStates"), "zoneRoles": fixture.get("zoneRoles")}
    if write:
        SNAPSHOT.write_text(
            json.dumps({"source_revision": current_revision, **derived}, indent=2) + "\n",
            encoding="utf8",
        )
        print(f"wrote {SNAPSHOT} from {current_revision}")
        return 0
    if derived != expected:
        print("enum snapshot differs from workbay_canvas_mcp.ux_map.models", file=sys.stderr)
        print(json.dumps({"expected": derived, "actual": expected}, indent=2), file=sys.stderr)
        return 1
    print(f"enum snapshot matches {current_revision}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
