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
        if json.loads(FIXTURE.read_text(encoding="utf8")) != expected:
            raise SystemExit("Unicode width fixture differs from Python unicodedata; regenerate explicitly")
        print("Unicode width fixture matches Python " + unicodedata.unidata_version)
    else:
        raise SystemExit("usage: sync_unicode_width.py --write|--check")
