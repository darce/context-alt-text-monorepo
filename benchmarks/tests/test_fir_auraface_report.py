"""Dependency-free checks for the FIR AuraFace HTML report.

Stdlib only. Do not import the description service or recognition package.
"""

from __future__ import annotations

from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlparse

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = REPO_ROOT / "benchmarks/reports/fir-embeddings-dims-detectors-qa-20260723.html"

CURRENT_SECTION_IDS = (
    "v12",
    "v12-status",
    "v12-space",
    "v12-config",
    "v12-gates",
    "v12-rollback",
)

_HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4"})
_SKIP_SCHEMES = frozenset({"http", "https", "mailto", "javascript", "data"})


class _ReportParser(HTMLParser):
    """Collect ids, fragment hrefs, and local file hrefs scoped by heading id."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: list[str] = []
        self.fragment_hrefs: list[str] = []
        self.local_hrefs: list[tuple[str, str]] = []
        self._section = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        data = {key: (value or "") for key, value in attrs}
        element_id = data.get("id", "").strip()
        if element_id:
            self.ids.append(element_id)
            if tag in _HEADING_TAGS:
                self._section = element_id

        href = data.get("href", "").strip()
        if not href:
            return
        parsed = urlparse(href)
        if parsed.scheme.lower() in _SKIP_SCHEMES:
            return
        if href.startswith("#") or (not parsed.scheme and not parsed.path and parsed.fragment):
            fragment = unquote(parsed.fragment or href[1:])
            if fragment:
                self.fragment_hrefs.append(fragment)
            return
        if parsed.scheme:
            return
        path = unquote(parsed.path)
        if path:
            self.local_hrefs.append((self._section, path))


def _parse_report() -> _ReportParser:
    parser = _ReportParser()
    parser.feed(REPORT_PATH.read_text(encoding="utf-8"))
    parser.close()
    return parser


def _is_current_section(section_id: str) -> bool:
    return section_id == "v12" or section_id.startswith("v12-")


def test_report_file_exists() -> None:
    assert REPORT_PATH.is_file(), f"missing report {REPORT_PATH}"


def test_anchor_ids_are_unique() -> None:
    parser = _parse_report()
    counts = Counter(parser.ids)
    duplicates = sorted(anchor for anchor, count in counts.items() if count > 1)
    assert not duplicates, f"duplicate HTML ids: {duplicates}"
    empty = [anchor for anchor in parser.ids if not anchor]
    assert not empty, "blank HTML ids are not allowed"


def test_current_section_ids_exist() -> None:
    parser = _parse_report()
    present = set(parser.ids)
    missing = [anchor for anchor in CURRENT_SECTION_IDS if anchor not in present]
    assert not missing, f"missing current-section ids: {missing}"


def test_current_section_fragment_links_resolve() -> None:
    parser = _parse_report()
    present = set(parser.ids)
    current_fragments = [
        fragment
        for fragment in parser.fragment_hrefs
        if fragment in CURRENT_SECTION_IDS or fragment.startswith("v12-")
    ]
    missing = sorted({fragment for fragment in current_fragments if fragment not in present})
    assert current_fragments, "current v12 section must expose in-document links"
    assert not missing, f"unresolved current-section fragment links: {missing}"


def test_current_section_local_file_links_exist() -> None:
    parser = _parse_report()
    report_dir = REPORT_PATH.parent
    missing: list[str] = []
    checked = 0
    for section_id, relpath in parser.local_hrefs:
        if not _is_current_section(section_id):
            continue
        checked += 1
        target = (report_dir / relpath).resolve()
        try:
            target.relative_to(REPO_ROOT)
        except ValueError:
            missing.append(f"{relpath} (escapes repo)")
            continue
        if not target.exists():
            missing.append(relpath)
    assert checked > 0, "current v12 section must link to local files"
    assert not missing, f"broken current-section local file links: {missing}"
