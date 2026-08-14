"""Ingest-time filename heuristic for social-CDN scrape signatures (FIR-11 Slice 1).

``warn_scrape_signature`` implements signature families A–D only. Family E
(bare 15-char Instagram shortcodes) is dropped: it produced all 12 measured
false positives when the family was run against normalized manifest stems.

Scope (binding):
    Ingest-time original filenames only. Never run this function against
    normalized manifest stems (``<subject_slug>_<media_id>.<ext>``). The
    committed manifests carry only those stems; the original upload names
    survive nowhere on disk. The loader surface is banned — ``manifest.py``
    must not import or call this module (plan L382, R3P-10 / R4P-08).

Explicit descope:
    No in-scope caller exists in this plan. Every intake path that still sees
    raw upload names lives outside the eval harness. This module ships as a
    tested, unwired helper. Wiring it into a real ingest path is future work
    owned by whichever plan owns that surface. Do not invent a wiring point.
"""

from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path


class ScrapeSignatureFamily(StrEnum):
    """Closed vocabulary of scrape-signature families that this helper fires on.

    Family E is intentionally absent (sr-007).
    """

    A = "A"
    B = "B"
    C = "C"
    D = "D"


# Camera-roll prefixes excluded *before* family matching (plan census procedure).
# Case-sensitive to match the plan census procedure (IMG|DSC|PXL|Screen[- ]?Shot).
_CAMERA_ROLL_PREFIX = re.compile(r"^(?:IMG|DSC|PXL|Screen[- ]?Shot)")

# Stem-matched families A–D. Compiled once; order is the check order.
_FAMILY_A = re.compile(r"\d{6,}_\d{5,}[^/]*_(n|o)(-\d+)?$")
_FAMILY_B = re.compile(r"(^|[_-])\d{15,}$")
_FAMILY_C = re.compile(r"^highlights[_-]\d{10,}")
_FAMILY_D = re.compile(r"^vsco[0-9a-f]{10,}")

_FAMILY_PATTERNS: tuple[tuple[ScrapeSignatureFamily, re.Pattern[str]], ...] = (
    (ScrapeSignatureFamily.A, _FAMILY_A),
    (ScrapeSignatureFamily.B, _FAMILY_B),
    (ScrapeSignatureFamily.C, _FAMILY_C),
    (ScrapeSignatureFamily.D, _FAMILY_D),
)


def warn_scrape_signature(original_filename: str) -> ScrapeSignatureFamily | None:
    """Return the matching scrape-signature family, or None if silent.

    Parameters
    ----------
    original_filename:
        An ingest-time original filename (optionally with directory prefix).
        This function is never to be run against normalized manifest stems.

    Returns
    -------
    ScrapeSignatureFamily or None
        The first matching family (A–D), or None when the name is camera-roll
        or matches no family. The helper does not warn via ``warnings.warn``;
        there is no in-scope caller to receive a warning. The return value *is*
        the warning signal.
    """
    basename = Path(original_filename).name
    stem = Path(basename).stem
    if _CAMERA_ROLL_PREFIX.search(stem) or _CAMERA_ROLL_PREFIX.search(basename):
        return None
    for family, pattern in _FAMILY_PATTERNS:
        if pattern.search(stem):
            return family
    return None
