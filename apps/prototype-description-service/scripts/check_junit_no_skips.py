#!/usr/bin/env python3
"""Fail closed when a JUnit XML report contains any skipped testcases.

FINALB-03 / RLSE-05 / TEST-08: ordinary pytest exits 0 when tests are skipped.
Parity CI must emit JUnit and run this gate so silent greens cannot land.

Usage:
    python scripts/check_junit_no_skips.py <junit.xml>
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def count_skipped(path: Path | str) -> int:
    """Count ``<skipped>`` elements under ``<testcase>`` (not suite attributes).

    Nested ``<testsuites>`` / ``<testsuite>`` shapes are supported. Aggregate
    ``skipped=`` attributes are ignored so parent+child suite summaries cannot
    double-count.
    """
    report = Path(path)
    tree = ET.parse(report)
    root = tree.getroot()
    count = 0
    for elem in root.iter():
        tag = elem.tag.rsplit("}", 1)[-1]  # strip optional XML namespace
        if tag != "testcase":
            continue
        for child in elem:
            child_tag = child.tag.rsplit("}", 1)[-1]
            if child_tag == "skipped":
                count += 1
    return count


def main(argv: list[str] | None = None) -> int:
    """Return 0 iff the report exists, parses, and has zero skipped testcases."""
    args = list(sys.argv[1:] if argv is None else argv)
    # Allow ``main([path])`` from tests; strip a leading script name if present.
    if len(args) == 1:
        report_arg = args[0]
    elif len(args) == 2 and args[0].endswith("check_junit_no_skips.py"):
        report_arg = args[1]
    else:
        print(
            "usage: check_junit_no_skips.py <junit.xml>",
            file=sys.stderr,
        )
        return 2

    report = Path(report_arg)
    if not report.is_file():
        print(f"check_junit_no_skips: missing report: {report}", file=sys.stderr)
        return 2

    try:
        skipped = count_skipped(report)
    except ET.ParseError as exc:
        print(f"check_junit_no_skips: malformed XML: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"check_junit_no_skips: cannot read report: {exc}", file=sys.stderr)
        return 2

    if skipped > 0:
        print(
            f"check_junit_no_skips: FAIL — {skipped} skipped testcase(s) in {report}",
            file=sys.stderr,
        )
        return 1

    print(f"check_junit_no_skips: OK — 0 skipped in {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
