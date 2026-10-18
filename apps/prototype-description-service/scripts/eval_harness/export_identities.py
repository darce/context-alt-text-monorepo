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
import warnings
from dataclasses import dataclass, field

from scripts.eval_harness._pathtext import _printable_path
from scripts.eval_harness.identity_sources import (
    FaceRegion,
    celeb_identity_from_filename,
    extract_face_regions,
    named_identities,
)
from scripts.eval_harness.manifest import ProvenanceSource, SpatialFact, SpatialRelation

# Source policy keyed off the canonical ProvenanceSource enum (sr-007), never scattered
# string literals: CELEB -> filename identity, LOCALWP/OPERATOR -> XMP identity, the rest
# (wikimedia/openverse/fixture) -> detection only. Matching the enum means a stale/foreign
# label (e.g. strata's scan-root "celebs01") fails loudly instead of silently dropping
# identity ground truth.
_PERSONAL_SOURCES = frozenset({ProvenanceSource.LOCALWP, ProvenanceSource.OPERATOR})


class CelebIdentityMissingWarning(UserWarning):
    """A celeb-sourced image whose filename yields no identity label (surfaced, not silent)."""


@dataclass(frozen=True)
class IdentityGroundTruth:
    present_identities: list[str] = field(default_factory=list)
    face_count: int = 0
    spatial_facts: list[SpatialFact] = field(default_factory=list)
    # Every detected region incl. anonymous strangers (name=None) — box-level detection
    # ground truth for FIR-1, distinct from the named-only present_identities.
    face_boxes: list[FaceRegion] = field(default_factory=list)


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
    """Compute identity + spatial ground truth for one image, by provenance source.

    ``source`` must be a canonical ``ProvenanceSource`` value; an unknown label (e.g.
    strata's scan-root "celebs01" copied verbatim into golden.json) raises rather than
    silently yielding a strangered, identity-less entry.
    """
    try:
        src = ProvenanceSource(source)
    except ValueError as exc:
        raise ValueError(
            f"unknown provenance source {source!r}; expected one of "
            f"{[s.value for s in ProvenanceSource]} (did a strata scan-root label leak in?)"
        ) from exc
    regions = extract_face_regions(image_bytes)
    face_count = len(regions)
    if src is ProvenanceSource.CELEB:
        name = celeb_identity_from_filename(filename)
        if name is None:
            warnings.warn(
                f"celeb-sourced image {_printable_path(filename)} has no parseable identity in its filename; "
                "the entry will carry zero identity ground truth",
                CelebIdentityMissingWarning,
                stacklevel=2,
            )
        present = [name] if name else []
        face_count = max(face_count, 1)  # a public-figure portrait has >=1 face
        spatial: list[SpatialFact] = []  # single-figure portraits: no placement facts
    elif src in _PERSONAL_SOURCES:
        present = named_identities(regions)
        spatial = spatial_facts_from_regions(regions)
    else:
        present = []  # wikimedia / openverse / fixture: detection only, no identity
        spatial = []
    return IdentityGroundTruth(
        present_identities=present, face_count=face_count, spatial_facts=spatial, face_boxes=regions
    )


def enrich_entry(entry: dict, image_bytes: bytes) -> dict:
    """Return a copy of a manifest entry with identity/face_count/spatial_facts/face_boxes filled.

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
    # face_count is an operator count-first figure (never derived from boxes).
    # Take the max of any existing value, the freshly-detected count, and the
    # identity count so a curated entry whose image carries no embedded XMP
    # cannot land below its own present_identities list.
    updated["face_count"] = max(
        int(updated.get("face_count") or 0), gt.face_count, len(updated.get("present_identities") or [])
    )
    if gt.spatial_facts and not updated.get("spatial_facts"):
        updated["spatial_facts"] = [f.model_dump(exclude_none=True) for f in gt.spatial_facts]
    if gt.face_boxes and not updated.get("face_boxes"):
        # Persist ALL detected boxes incl. anonymous strangers (name=None) — box-level
        # detection ground truth for FIR-1, beyond the named-only present_identities.
        updated["face_boxes"] = [
            {"x": r.x, "y": r.y, "w": r.w, "h": r.h, "name": r.name, "source": r.source} for r in gt.face_boxes
        ]
    # must_right mirrors confirmed present identities (recognition-enabled corpus).
    if updated.get("present_identities") and not updated.get("must_right"):
        updated["must_right"] = list(updated["present_identities"])
    return updated
