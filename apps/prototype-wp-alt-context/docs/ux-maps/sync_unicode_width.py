#!/usr/bin/env python3
"""Export Python's Unicode properties for the TypeScript width mirror."""

import json
from pathlib import Path
import sys
import unicodedata

FIXTURE = Path(__file__).resolve().parents[2] / "js/admin/__tests__/uxmap-render-parity.fixtures/unicode-width.json"


def ranges(predicate):
    result = []
    for codepoint in range(0x110000):
        if not predicate(chr(codepoint)):
            continue
        if result and result[-1][1] == codepoint - 1:
            result[-1][1] = codepoint
        else:
            result.append([codepoint, codepoint])
    return result


def derive():
    return {
        "unicode_version": unicodedata.unidata_version,
        "wide": ranges(lambda char: unicodedata.east_asian_width(char) in {"W", "F"}),
        "marks": ranges(lambda char: unicodedata.category(char).startswith("M")),
        "format": ranges(lambda char: unicodedata.category(char) == "Cf"),
    }


if __name__ == "__main__":
    expected = derive()
    if sys.argv[1:] == ["--write"]:
        FIXTURE.write_text(json.dumps(expected, separators=(",", ":")) + "\n", encoding="utf8")
    elif sys.argv[1:] == ["--check"]:
        fixture = json.loads(FIXTURE.read_text(encoding="utf8"))
        fixture_version = fixture.pop("unicode_version", None)
        interpreter_version = expected.pop("unicode_version")
        if not isinstance(fixture_version, str) or not fixture_version:
            raise SystemExit("Unicode width fixture must record unicode_version; regenerate explicitly")
        if fixture_version != interpreter_version:
            print(
                f"Unicode version mismatch: fixture {fixture_version}, Python {interpreter_version}; "
                "comparing property ranges",
                file=sys.stderr,
            )
        if fixture != expected:
            raise SystemExit("Unicode width fixture differs from Python unicodedata; regenerate explicitly")
        print("Unicode width fixture property ranges match Python " + interpreter_version)
    else:
        raise SystemExit("usage: sync_unicode_width.py --write|--check")
