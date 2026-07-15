"""Curation -> manifest identity & spatial-box bridge (VLM-6 S1).

Turns curated face data into scorable ground truth on the Golden-100 entries,
per source (decision vlm6_s1_corpus_composition_split_by_role):

- ``celeb``  -> identity from the filename (public-figure label; authoritative,
  the embedded XMP name is partial/noisy for this corpus so it is ignored here).
- ``localwp``/``personal`` -> confirmed identity names + boxes from the plugin's
  embedded IPTC XMP (offline, sha256-matched); private, never published.
- anything else (stranger / cc0 / fixture) -> detection/``face_count`` + boxes
  only, no identity (anti-circularity: only human-confirmed names are truth).

Spatial-relation facts are derived from the named face-box centres for
multi-face images so caption placement claims can be scored (plan S1).
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field

from scripts.eval_harness.identity_sources import (
    FaceRegion,
    celeb_identity_from_filename,
    extract_face_regions,
    named_identities,
)
from scripts.eval_harness.manifest import SpatialFact, SpatialRelation

_CELEB_SOURCES = {"celeb", "celebs", "public_figure"}
_PERSONAL_SOURCES = {"localwp", "personal", "operator"}


@dataclass(frozen=True)
class IdentityGroundTruth:
    present_identities: list[str] = field(default_factory=list)
    face_count: int = 0
    spatial_facts: list[SpatialFact] = field(default_factory=list)


def _placement_phrases(subject: str, reference: str, side: str) -> list[str]:
    """Deterministic match phrases for a horizontal placement claim (side left|right)."""
    return [
        f"{subject} to the {side} of {reference}",
        f"{subject} on the {side}",
        f"{subject}, on the {side}",
        f"{subject} is on the {side}",
    ]


def spatial_facts_from_regions(regions: list[FaceRegion]) -> list[SpatialFact]:
    """Derive left/right placement facts from named face-box centres (x is centre-x).

    Only named regions participate (placement of anonymous faces is unscorable by
    name). Ties / near-equal centres are skipped to avoid asserting a placement the
    image does not clearly support (precision-first). One fact per distinct pair.
    """
    named = [r for r in regions if r.name and r.x is not None]
    # Dedupe by name keeping the first box, so a repeated identity does not pair
    # with itself and generate a vacuous relation.
    by_name: dict[str, FaceRegion] = {}
    for region in named:
        by_name.setdefault(region.name, region)
    facts: list[SpatialFact] = []
    for a, b in itertools.combinations(by_name.values(), 2):
        if abs(a.x - b.x) < 0.02:  # too close horizontally to call a side
            continue
        left, right = (a, b) if a.x < b.x else (b, a)
        facts.append(
            SpatialFact(
                subject=left.name,
                relation=SpatialRelation.LEFT_OF,
                reference=right.name,
                phrases=_placement_phrases(left.name, right.name, "left"),
            )
        )
    return facts


def identities_for_image(image_bytes: bytes, *, source: str, filename: str) -> IdentityGroundTruth:
    """Compute identity + spatial ground truth for one image, by provenance source."""
    regions = extract_face_regions(image_bytes)
    face_count = len(regions)
    src = source.lower()
    if src in _CELEB_SOURCES:
        name = celeb_identity_from_filename(filename)
        present = [name] if name else []
        face_count = max(face_count, 1)  # a public-figure portrait has >=1 face
        spatial: list[SpatialFact] = []  # single-figure portraits: no placement facts
    elif src in _PERSONAL_SOURCES:
        present = named_identities(regions)
        spatial = spatial_facts_from_regions(regions)
    else:
        present = []  # strangers / cc0 / fixtures: detection only, no identity
        spatial = []
    return IdentityGroundTruth(present_identities=present, face_count=face_count, spatial_facts=spatial)


def enrich_entry(entry: dict, image_bytes: bytes) -> dict:
    """Return a copy of a manifest entry with identity/face_count/spatial_facts filled.

    Uses ``entry['provenance']['source']`` to select the source policy. Leaves the
    entry untouched when it has no provenance (legacy golden-38 entries). Never
    overwrites a non-empty curated ``present_identities`` already on the entry
    (idempotent re-runs and manual corrections win).
    """
    provenance = entry.get("provenance")
    if not isinstance(provenance, dict) or "source" not in provenance:
        return entry
    gt = identities_for_image(
        image_bytes,
        source=str(provenance["source"]),
        filename=str(entry.get("path", "")).rsplit("/", 1)[-1],
    )
    updated = dict(entry)
    if not updated.get("present_identities"):
        updated["present_identities"] = gt.present_identities
    updated.setdefault("face_count", gt.face_count)
    if gt.face_count > updated.get("face_count", 0):
        updated["face_count"] = gt.face_count
    if gt.spatial_facts and not updated.get("spatial_facts"):
        updated["spatial_facts"] = [f.model_dump(exclude_none=True) for f in gt.spatial_facts]
    # must_right mirrors confirmed present identities (recognition-enabled corpus).
    if updated.get("present_identities") and not updated.get("must_right"):
        updated["must_right"] = list(updated["present_identities"])
    return updated
