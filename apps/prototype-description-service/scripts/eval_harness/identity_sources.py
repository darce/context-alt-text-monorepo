"""Identity + face-box ground-truth readers for Golden-100 curation (VLM-6 S1).

Two offline, deterministic sources feed the manifest bridge — no network:

1. **Public-figure filenames** (celebs01): ``clint_eastwood_8.jpg`` -> "Clint Eastwood".
   The filename IS the label; publishable identity ground truth.
2. **Embedded XMP face regions** written by the plugin (IPTC ImageRegion: person
   ``Name`` + normalized centre-point ``RegionBoundary``) and by Apple/Photos
   (MWG ``mwg-rs`` regions: boxes, usually no name). Read by sha256 match so
   curated identities flow back into the manifest as ground truth.

Anti-circularity: only human-confirmed (named) regions become identity truth;
box-only regions contribute detection/``face_count`` and spatial boxes, never a name.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# A per-figure disambiguator is SHORT (celebs01 runs 1-2 digits). Bounding the
# strip is what separates `madonna_7` from a scraped `handle_3134640125107970990`:
# an unbounded `_\d+$` ate the 19-digit social post id and left a clean handle,
# which then passed the no-digits check and yielded the fake label "GildedCypress".
_TRAILING_INDEX = re.compile(r"_\d{1,3}$")
_EXT = re.compile(r"\.(jpe?g|png|webp|gif|heic)$", re.IGNORECASE)
_HAS_ALPHA_WORD = re.compile(r"[A-Za-z]{2,}")


def celeb_identity_from_filename(filename: str) -> str | None:
    """``robert_downey_jr._5.jpg`` -> "Robert Downey Jr."; None for non-name stems.

    Strips the extension and the trailing short ``_<index>`` disambiguator, then
    title-cases the underscore-separated stem. Returns None when the residual stem
    doesn't look like a person name: empty, lacking an alphabetic word, or holding
    ANY digit (once the numeric index is removed a real name has none — so
    social-media / camera ids like ``28514407_10156297712651133_..._o`` or
    ``IMG_9DABF3F03B85-1`` are rejected instead of yielding fake labels). The label
    is a scoring key, not a canonical name.

    Single-token stems are accepted: mononyms are real in this corpus (``dali``,
    ``madonna``, ``rihanna``), so a first+last requirement would drop them.
    """
    stem = _EXT.sub("", filename.strip())
    stem = _TRAILING_INDEX.sub("", stem)
    stem = stem.strip("_ ")
    if not stem or any(ch.isdigit() for ch in stem) or not _HAS_ALPHA_WORD.search(stem):
        return None
    return " ".join(part for part in stem.split("_") if part).title()


@dataclass(frozen=True)
class FaceRegion:
    """A face box (normalized) with an optional confirmed identity name.

    ``x``/``y`` are the region CENTRE and ``w``/``h`` the size, all in 0..1 —
    matching both the plugin's IPTC ``rbUnit=relative`` centre-point convention
    (per recognition-media-xmp-mapping.md) and MWG ``stArea`` centre semantics.
    ``source`` is 'iptc' (plugin, may be named) or 'mwg' (Apple, box-only).
    """

    name: str | None
    x: float
    y: float
    w: float
    h: float
    source: str


def _f(value: str | None) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _extract_xmp_packet(image_bytes: bytes) -> str | None:
    match = re.search(rb"<x:xmpmeta.*?</x:xmpmeta>", image_bytes, re.DOTALL)
    return match.group(0).decode("utf-8", "replace") if match else None


# Element bodies are matched tolerating the inline xmlns:* attribute the writers
# emit on every qualified element (the reason a naive `<tag>` match misses them). The
# prefix group is [\w-]+, not \w+, so hyphenated namespace prefixes match — the
# MWG-Regions standard prefix is `mwg-rs` (e.g. <mwg-rs:Name>), which \w cannot match.
def _tag(body: str, local: str) -> str | None:
    m = re.search(rf"<[\w-]+:{local}\b[^>]*>([^<]*)</[\w-]+:{local}>", body)
    return m.group(1).strip() if m else None


def _iptc_regions(xmp: str) -> list[FaceRegion]:
    regions: list[FaceRegion] = []
    for li in re.findall(r"<rdf:li\b[^>]*>(.*?)</rdf:li>", xmp, re.DOTALL):
        if "RegionBoundary" not in li:
            continue
        name = _tag(li, "Name")
        x, y, w, h = (_f(_tag(li, t)) for t in ("rbX", "rbY", "rbW", "rbH"))
        if None in (x, y, w, h):
            continue
        regions.append(FaceRegion(name=name or None, x=x, y=y, w=w, h=h, source="iptc"))
    return regions


def _mwg_regions(xmp: str) -> list[FaceRegion]:
    regions: list[FaceRegion] = []
    for li in re.findall(r"<rdf:li\b[^>]*>(.*?)</rdf:li>", xmp, re.DOTALL):
        if "stArea:" not in li:
            continue
        name = _tag(li, "Name")
        x, y, w, h = (_f(_tag(li, t)) for t in ("x", "y", "w", "h"))
        if None in (x, y, w, h):
            continue
        regions.append(FaceRegion(name=name or None, x=x, y=y, w=w, h=h, source="mwg"))
    return regions


def extract_face_regions(image_bytes: bytes) -> list[FaceRegion]:
    """Parse plugin IPTC + Apple MWG face regions from an image's embedded XMP.

    Returns [] when there is no XMP packet. IPTC regions (which the plugin writes
    with confirmed names) come first; MWG regions (box-only, Apple-sourced) after.
    """
    xmp = _extract_xmp_packet(image_bytes)
    if xmp is None:
        return []
    return _iptc_regions(xmp) + _mwg_regions(xmp)


def named_identities(regions: list[FaceRegion]) -> list[str]:
    """Distinct confirmed names across regions, order-stable (identity ground truth)."""
    seen: dict[str, None] = {}
    for region in regions:
        if region.name:
            seen.setdefault(region.name, None)
    return list(seen)
