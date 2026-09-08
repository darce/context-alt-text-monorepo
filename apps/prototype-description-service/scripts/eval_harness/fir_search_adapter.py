"""Produce ``SearchResult`` lists from §B run-records for ``score_run``.

Composes ``collect_matched_faces``, ``GallerySplit`` templates, and
``argmax_gallery``. Does not read ``FaceDecision`` (τ stays out of the IET
curve) and does not reuse ``build_loo_gallery`` (gallery restriction is an
assertion, not a silent filter).

EVAL-16: a missed named GT box is a mated ``detected=False`` search.
EVAL-16: a declared foil with no searchable detection is a non-mated
``detected=False`` search (score below every threshold, not an absent trial).
EVAL-18 / JANUS 2.2: mated-ness is per gallery; foils are still-level.
EVAL-18: unmatched detections on a foil still fold into the same
``(media_id, gallery)`` unit so a false alarm can produce FPI.
EVAL-19: a missed unnamed box is not an extra search — it cannot mint FPI.
MLDATA-09: an empty gallery raises rather than publishing ``-inf``.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from scripts.eval_harness.face_assignment import (
    MatchedFace,
    argmax_gallery,
    collect_matched_faces,
    mean_prototype,
)
from scripts.eval_harness.fir_bakeoff_run import (
    PROBE_STRATA,
    FirBakeoffRunError,
    MatedSearchUnit,
    RunPlan,
    occluded_probes_for,
)
from scripts.eval_harness.gallery_split import GalleryName, Template
from scripts.eval_harness.open_set_identification import SearchResult

# Foil FPI units are (media_id, gallery), not per subject (BR-29).
_FOIL_UNIT_SUBJECT = ""

SearchUnitKey = tuple[int, GalleryName | str, str]


def max_score_per_search_unit(
    scores: Sequence[tuple[SearchUnitKey, float, str | None]],
) -> dict[SearchUnitKey, tuple[float, str | None]]:
    """One ``(s_max, name_star)`` per ``(media_id, gallery, subject_id)``.

    Two boxes of one subject on one still are one 1:N search; the still
    returns its best candidate. Ties keep the first ``name_star``.
    """
    best: dict[SearchUnitKey, tuple[float, str | None]] = {}
    for key, s_max, name_star in scores:
        current = best.get(key)
        if current is None or s_max > current[0]:
            best[key] = (s_max, name_star)
    return best


def searches_from_run_records(
    run_items: Sequence[Mapping[str, Any]],
    gt_by_media: Mapping[int, Sequence[Any]],
    *,
    plan: RunPlan,
) -> tuple[dict[str, dict[str, list[SearchResult]]], list[SearchResult]]:
    """``(searches keyed by stratum, overall_nonmated)`` — ``score_run``'s args."""
    matched, associations, _, _, _ = collect_matched_faces(run_items, gt_by_media)
    # Strip identity keys once so GT/roster padding cannot drop a detected mate.
    matched = [_normalise_face(face) for face in matched]
    by_media: dict[int, list[MatchedFace]] = defaultdict(list)
    for face in matched:
        by_media[face.media_id].append(face)
    items_by_media = {int(item["media_id"]): item for item in run_items}

    searches: dict[str, dict[str, list[SearchResult]]] = {
        name: {"mated": [], "nonmated": []} for name in PROBE_STRATA
    }
    overall_nonmated: list[SearchResult] = []
    galleries = tuple(sorted(plan.probe_sets, key=lambda gallery: gallery.value))

    for gallery in galleries:
        roster = _roster(plan, gallery)
        gallery_media = _enrolled_media_ids(roster)
        prototypes = _prototypes_from_templates(roster, matched)
        mated_units, foil_entries = occluded_probes_for(plan, gallery=gallery)
        mated_units = [_normalise_unit(unit) for unit in mated_units]

        box_scores: list[tuple[SearchUnitKey, float, str | None]] = []
        for unit in mated_units:
            _reject_probe_enrolled_in_gallery(
                unit.entry.media_id, gallery_media, gallery
            )
            faces = [
                face
                for face in by_media.get(unit.entry.media_id, ())
                if face.true_name == unit.subject_id
            ]
            if not faces:
                continue
            key: SearchUnitKey = (
                unit.entry.media_id,
                gallery,
                unit.subject_id,
            )
            for face in faces:
                s_max, name_star = _search_gallery(
                    face.embedding_array(), prototypes=prototypes, gallery=gallery
                )
                box_scores.append((key, s_max, name_star))

        reduced = max_score_per_search_unit(box_scores)
        for unit in mated_units:
            key = (unit.entry.media_id, gallery, unit.subject_id)
            if key in reduced:
                s_max, name_star = reduced[key]
                searches[unit.entry.stratum]["mated"].append(
                    SearchResult(
                        detected=True,
                        top1_score=s_max,
                        top1_name=name_star,
                        true_name=unit.subject_id,
                        gallery=gallery,
                        media_id=unit.entry.media_id,
                    )
                )
                continue
            if _unmatched_named(
                associations,
                gt_by_media,
                media_id=unit.entry.media_id,
                subject_id=unit.subject_id,
            ):
                searches[unit.entry.stratum]["mated"].append(
                    SearchResult(
                        detected=False,
                        top1_score=None,
                        top1_name=None,
                        true_name=unit.subject_id,
                        gallery=gallery,
                        media_id=unit.entry.media_id,
                    )
                )

        foil_scores: list[tuple[SearchUnitKey, float, str | None]] = []
        for entry in foil_entries:
            _reject_probe_enrolled_in_gallery(entry.media_id, gallery_media, gallery)
            item = items_by_media.get(entry.media_id)
            if item is None:
                continue
            faces = by_media.get(entry.media_id, ())
            unmatched_embeddings = _unmatched_detection_embeddings(
                item,
                associations.get(entry.media_id),
            )
            key = (entry.media_id, gallery, _FOIL_UNIT_SUBJECT)
            if not faces and not unmatched_embeddings:
                result = SearchResult(
                    detected=False,
                    top1_score=None,
                    top1_name=None,
                    true_name=None,
                    gallery=gallery,
                    media_id=entry.media_id,
                )
                searches[entry.stratum]["nonmated"].append(result)
                overall_nonmated.append(result)
                continue
            for face in faces:
                s_max, name_star = _search_gallery(
                    face.embedding_array(), prototypes=prototypes, gallery=gallery
                )
                foil_scores.append((key, s_max, name_star))
            for embedding in unmatched_embeddings:
                s_max, name_star = _search_gallery(
                    embedding, prototypes=prototypes, gallery=gallery
                )
                foil_scores.append((key, s_max, name_star))

        foil_reduced = max_score_per_search_unit(foil_scores)
        for entry in foil_entries:
            key = (entry.media_id, gallery, _FOIL_UNIT_SUBJECT)
            if key not in foil_reduced:
                continue
            s_max, name_star = foil_reduced[key]
            result = SearchResult(
                detected=True,
                top1_score=s_max,
                top1_name=name_star,
                true_name=None,
                gallery=gallery,
                media_id=entry.media_id,
            )
            searches[entry.stratum]["nonmated"].append(result)
            overall_nonmated.append(result)

    return searches, overall_nonmated


def _identity_key(name: Any) -> str | None:
    if name is None:
        return None
    text = str(name).strip()
    return text or None


def _normalise_face(face: MatchedFace) -> MatchedFace:
    key = _identity_key(face.true_name)
    if key == face.true_name:
        return face
    return replace(face, true_name=key)


def _normalise_unit(unit: MatedSearchUnit) -> MatedSearchUnit:
    key = _identity_key(unit.subject_id)
    if key is None or key == unit.subject_id:
        return unit
    return replace(unit, subject_id=key)


def _roster(plan: RunPlan, gallery: GalleryName) -> Mapping[str, Template]:
    raw = plan.split.g1 if gallery is GalleryName.G1 else plan.split.g2
    out: dict[str, Template] = {}
    for subject_id, template in raw.items():
        if _identity_key(subject_id) is None:
            raise FirBakeoffRunError(
                f"gallery {gallery.value} subject_id={subject_id!r} is blank"
            )
        out[subject_id] = template
    return out


def _enrolled_media_ids(roster: Mapping[str, Template]) -> frozenset[int]:
    return frozenset(
        media_id for template in roster.values() for media_id in template.media_ids
    )


def _prototypes_from_templates(
    roster: Mapping[str, Template],
    matched: Sequence[MatchedFace],
) -> dict[str, Any]:
    faces_by: dict[tuple[int, str], list[MatchedFace]] = defaultdict(list)
    for face in matched:
        if face.true_name is None:
            continue
        faces_by[face.media_id, face.true_name].append(face)
    prototypes: dict[str, Any] = {}
    for subject_id, template in roster.items():
        embeddings = [
            face.embedding_array()
            for media_id in template.media_ids
            for face in faces_by.get((media_id, subject_id), ())
        ]
        if embeddings:
            prototypes[subject_id] = mean_prototype(embeddings)
    return prototypes


def _reject_probe_enrolled_in_gallery(
    media_id: int, gallery_media: frozenset[int], gallery: GalleryName
) -> None:
    if media_id in gallery_media:
        raise FirBakeoffRunError(
            f"probe media_id={media_id} is present in searched gallery "
            f"{gallery.value}: refusing leave-one-out filter on a broken split"
        )


def _search_gallery(
    embedding: Any,
    *,
    prototypes: Mapping[str, Any],
    gallery: GalleryName,
) -> tuple[float, str | None]:
    s_max, name_star = argmax_gallery(embedding, prototypes)
    if name_star is None or not math.isfinite(s_max):
        raise FirBakeoffRunError(
            f"empty gallery {gallery.value}: argmax_gallery returned "
            f"non-finite s_max={s_max!r} (refusing -inf)"
        )
    return s_max, name_star


def _unmatched_detection_embeddings(
    item: Mapping[str, Any] | None,
    assoc: Any | None,
) -> tuple[Any, ...]:
    if item is None or assoc is None:
        return ()
    faces = item.get("faces") or []
    n_faces = len(faces)
    embeddings: list[Any] = []
    for index in assoc.unmatched_detections:
        if index < 0 or index >= n_faces:
            raise FirBakeoffRunError(
                f"unmatched_detections index={index} is out of range for "
                f"media_id={item.get('media_id')} ({n_faces} faces)"
            )
        embeddings.append(faces[index]["embedding"])
    return tuple(embeddings)


def _box_name(gt: Any) -> str | None:
    if isinstance(gt, Mapping):
        name = gt.get("name")
    else:
        name = getattr(gt, "name", None)
    return _identity_key(name)


def _unmatched_named(
    associations: Mapping[int, Any],
    gt_by_media: Mapping[int, Sequence[Any]],
    *,
    media_id: int,
    subject_id: str,
) -> bool:
    assoc = associations.get(media_id)
    if assoc is None:
        return False
    boxes = list(gt_by_media.get(media_id, ()))
    for index in assoc.unmatched_gt:
        if index < 0 or index >= len(boxes):
            continue
        if _box_name(boxes[index]) == subject_id:
            return True
    return False


__all__ = [
    "max_score_per_search_unit",
    "searches_from_run_records",
]
