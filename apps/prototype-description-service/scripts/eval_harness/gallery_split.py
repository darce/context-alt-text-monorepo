"""IJB-C-style disjoint G1/G2 galleries with an explicit non-mated probe stratum.

``build_loo_gallery`` (face_assignment) is leave-one-out: every enrolled probe
has a mate, so it cannot measure open-set rejection. This module partitions
subjects across two galleries drawn from disjoint templates so a search against
one gallery contains probes whose subject is enrolled only in the other.

Enrollment rule
    Each subject is assigned to *exactly one* gallery (seeded shuffle, even
    index → G1, odd → G2). One template is enrolled; remaining templates of
    that subject are reserved probes. Dual enrollment is refused: putting
    every multi-template subject in both galleries recreates the LOO failure
    (every probe has a mate) and empties the non-mated stratum.

Singleton rule (MLDATA-09)
    A subject with one template is assigned like any other — never dropped.
    The single template is enrolled in the assigned gallery and is used as a
    *non-mated* probe against the other gallery. There is no leftover to
    search the assigned gallery with.

Probes against G1
    Mated: reserved leftovers of G1 subjects.
    Non-mated: reserved leftovers of G2 subjects *plus* G2 enrollment
    templates (so G2 singletons are a probe source, not a silent drop).
    Symmetric for G2. An empty non-mated list raises — EVAL-18 forbids a
    silently closed-set search.
"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

__all__ = [
    "GalleryName",
    "GallerySplit",
    "GallerySplitError",
    "ProbeSet",
    "Template",
    "build_disjoint_galleries",
    "probes_for",
]


class GalleryName(StrEnum):
    """Which gallery a 1:N search is run against."""

    G1 = "g1"
    G2 = "g2"


class GallerySplitError(ValueError):
    """Roster or split that would hide the open-set regime under test."""


@dataclass(frozen=True)
class Template:
    """One subject template (gallery enrollment or probe)."""

    template_id: str
    subject_id: str
    media_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class GallerySplit:
    """Disjoint G1/G2 enrollment plus templates reserved as probes.

    ``g1`` / ``g2`` map subject_id → the single enrolled template.
    ``probe_templates`` are leftovers enrolled in neither gallery.
    Other-gallery enrollments are *not* reserved here; ``probes_for``
    promotes them to non-mated probes at search time.
    """

    g1: dict[str, Template]
    g2: dict[str, Template]
    probe_templates: tuple[Template, ...]

    @property
    def g1_template_ids(self) -> frozenset[str]:
        return frozenset(t.template_id for t in self.g1.values())

    @property
    def g2_template_ids(self) -> frozenset[str]:
        return frozenset(t.template_id for t in self.g2.values())

    @property
    def probe_template_ids(self) -> frozenset[str]:
        return frozenset(t.template_id for t in self.probe_templates)

    @property
    def probe_media_ids(self) -> frozenset[int]:
        return frozenset(mid for t in self.probe_templates for mid in t.media_ids)


@dataclass(frozen=True)
class ProbeSet:
    """Mated and non-mated probes for a search against one gallery."""

    gallery: GalleryName
    mated: tuple[Template, ...]
    nonmated: tuple[Template, ...]

    @property
    def n_mated(self) -> int:
        return len(self.mated)

    @property
    def n_nonmated(self) -> int:
        return len(self.nonmated)

    @property
    def n_subjects(self) -> int:
        return len({t.subject_id for t in (*self.mated, *self.nonmated)})


def _as_template(value: Template | str, *, subject_id: str) -> Template:
    if isinstance(value, Template):
        if value.subject_id != subject_id:
            raise GallerySplitError(
                f"template {value.template_id!r} subject_id {value.subject_id!r} "
                f"does not match roster key {subject_id!r}"
            )
        if not value.template_id:
            raise GallerySplitError("template id must be a non-empty string")
        return value
    if isinstance(value, str):
        if not value:
            raise GallerySplitError("template id must be a non-empty string")
        return Template(template_id=value, subject_id=subject_id)
    raise GallerySplitError(f"unsupported template type: {type(value).__name__}")


def _media_ids(templates: Sequence[Template]) -> list[int]:
    return [mid for t in templates for mid in t.media_ids]


def _assert_invariants(
    *,
    roster_subjects: set[str],
    g1: Mapping[str, Template],
    g2: Mapping[str, Template],
    probes: Sequence[Template],
) -> None:
    g1_ids = {t.template_id for t in g1.values()}
    g2_ids = {t.template_id for t in g2.values()}
    probe_ids = {t.template_id for t in probes}
    if g1_ids & g2_ids:
        raise GallerySplitError(
            f"gallery template ids are not disjoint: {sorted(g1_ids & g2_ids)!r}"
        )
    if g1_ids & probe_ids or g2_ids & probe_ids:
        overlap = (g1_ids | g2_ids) & probe_ids
        raise GallerySplitError(
            f"reserved probe template ids collide with a gallery: {sorted(overlap)!r}"
        )
    assigned = set(g1) | set(g2)
    dropped = roster_subjects - assigned
    if dropped:
        raise GallerySplitError(
            f"subjects dropped from both galleries (MLDATA-09): {sorted(dropped)!r}"
        )
    both = set(g1) & set(g2)
    if both:
        raise GallerySplitError(
            f"subject enrolled in both galleries; dual enrollment empties the "
            f"non-mated stratum (EVAL-18): {sorted(both)!r}"
        )
    for gallery_name, gallery in (("g1", g1), ("g2", g2)):
        for subject_id, template in gallery.items():
            if template.subject_id != subject_id:
                raise GallerySplitError(
                    f"{gallery_name} key {subject_id!r} holds template for "
                    f"{template.subject_id!r}"
                )
    media_g1 = _media_ids(list(g1.values()))
    media_g2 = _media_ids(list(g2.values()))
    media_probe = _media_ids(probes)
    if set(media_g1) & set(media_g2):
        raise GallerySplitError(
            f"gallery media ids are not disjoint: {sorted(set(media_g1) & set(media_g2))!r}"
        )
    gallery_media = set(media_g1) | set(media_g2)
    if gallery_media & set(media_probe):
        raise GallerySplitError(
            f"reserved probe media ids collide with a gallery: "
            f"{sorted(gallery_media & set(media_probe))!r}"
        )


def build_disjoint_galleries(
    *,
    templates_by_subject: Mapping[str, Sequence[Template | str]],
    seed: int,
) -> GallerySplit:
    """Partition subjects into disjoint G1/G2 galleries (one template each).

    Raises ``GallerySplitError`` on an empty roster, a subject with no
    templates, duplicate template ids, or any invariant failure. Does not
    drop singleton subjects.
    """
    if not templates_by_subject:
        raise GallerySplitError(
            "empty roster: refusing two empty galleries (no open-set stratum)"
        )

    rng = random.Random(seed)
    seen_ids: set[str] = set()
    by_subject: dict[str, list[Template]] = {}
    for subject_id in sorted(templates_by_subject):
        raw = list(templates_by_subject[subject_id])
        if not raw:
            raise GallerySplitError(
                f"subject {subject_id!r} has no templates; refusing silent drop"
            )
        templates = [_as_template(item, subject_id=subject_id) for item in raw]
        for template in templates:
            if template.template_id in seen_ids:
                raise GallerySplitError(
                    f"duplicate template id {template.template_id!r}"
                )
            seen_ids.add(template.template_id)
        rng.shuffle(templates)
        by_subject[subject_id] = templates

    order = list(by_subject)
    rng.shuffle(order)

    g1: dict[str, Template] = {}
    g2: dict[str, Template] = {}
    probes: list[Template] = []
    for index, subject_id in enumerate(order):
        templates = by_subject[subject_id]
        enrolled, leftovers = templates[0], templates[1:]
        if index % 2 == 0:
            g1[subject_id] = enrolled
        else:
            g2[subject_id] = enrolled
        probes.extend(leftovers)

    g1 = {s: g1[s] for s in sorted(g1)}
    g2 = {s: g2[s] for s in sorted(g2)}
    probe_templates = tuple(sorted(probes, key=lambda t: (t.subject_id, t.template_id)))
    _assert_invariants(
        roster_subjects=set(by_subject),
        g1=g1,
        g2=g2,
        probes=probe_templates,
    )
    return GallerySplit(g1=g1, g2=g2, probe_templates=probe_templates)


def probes_for(split: GallerySplit, *, gallery: GalleryName | str) -> ProbeSet:
    """Mated / non-mated probes for a 1:N search against ``gallery``.

    A subject enrolled only in the *other* gallery yields non-mated probes
    (EVAL-18 open-set stratum). Raises if that stratum is empty.
    """
    name = GalleryName(gallery)
    if name is GalleryName.G1:
        enrolled, other = split.g1, split.g2
    else:
        enrolled, other = split.g2, split.g1

    enrolled_subjects = set(enrolled)
    mated: list[Template] = []
    nonmated: list[Template] = []
    for template in split.probe_templates:
        if template.subject_id in enrolled_subjects:
            mated.append(template)
        else:
            nonmated.append(template)
    nonmated.extend(other.values())

    if not nonmated:
        raise GallerySplitError(
            f"empty non-mated stratum for gallery {name.value!r}: every probe "
            "has a mate in the searched gallery (EVAL-18)"
        )

    return ProbeSet(
        gallery=name,
        mated=tuple(sorted(mated, key=lambda t: (t.subject_id, t.template_id))),
        nonmated=tuple(sorted(nonmated, key=lambda t: (t.subject_id, t.template_id))),
    )
