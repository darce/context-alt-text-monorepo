"""FIR-12: disjoint G1/G2 galleries — open-set non-mated probes (EVAL-18 / MLDATA-09).

TEST-15: each assertion is can-fail against a LOO-style dual-enroll impl.
"""

from __future__ import annotations

import pytest

from scripts.eval_harness.gallery_split import (
    GalleryName,
    GallerySplitError,
    Template,
    build_disjoint_galleries,
    probes_for,
)


def _roster(*pairs: tuple[str, tuple[str, ...]]) -> dict[str, list[str]]:
    return {subject: list(ids) for subject, ids in pairs}


def _two_plus_roster() -> dict[str, list[str]]:
    """≥2 subjects, each with ≥2 templates — the EVAL-18 minimum."""
    return _roster(
        ("alice", ("a1", "a2", "a3")),
        ("bob", ("b1", "b2")),
        ("carol", ("c1", "c2", "c3")),
        ("dave", ("d1", "d2")),
    )


def test_empty_roster_raises():
    with pytest.raises(GallerySplitError, match="empty roster"):
        build_disjoint_galleries(templates_by_subject={}, seed=0)


def test_subject_with_no_templates_raises_rather_than_drop():
    with pytest.raises(GallerySplitError, match="no templates"):
        build_disjoint_galleries(
            templates_by_subject={"alice": ["a1", "a2"], "bob": []},
            seed=0,
        )


def test_g1_g2_template_ids_are_disjoint():
    split = build_disjoint_galleries(templates_by_subject=_two_plus_roster(), seed=1)
    assert split.g1_template_ids.isdisjoint(split.g2_template_ids)
    assert split.g1_template_ids.isdisjoint(split.probe_template_ids)
    assert split.g2_template_ids.isdisjoint(split.probe_template_ids)


def test_one_template_per_subject_per_gallery():
    split = build_disjoint_galleries(templates_by_subject=_two_plus_roster(), seed=2)
    assert len(split.g1) == len(set(split.g1))
    assert len(split.g2) == len(set(split.g2))
    for gallery in (split.g1, split.g2):
        for subject_id, template in gallery.items():
            assert isinstance(template, Template)
            assert template.subject_id == subject_id
    assert set(split.g1).isdisjoint(set(split.g2))


def test_same_seed_identical_split():
    roster = _two_plus_roster()
    a = build_disjoint_galleries(templates_by_subject=roster, seed=11)
    b = build_disjoint_galleries(templates_by_subject=roster, seed=11)
    assert a == b
    assert a.g1_template_ids == b.g1_template_ids
    assert a.g2_template_ids == b.g2_template_ids
    assert a.probe_template_ids == b.probe_template_ids


def test_different_seed_usually_different_split():
    roster = _two_plus_roster()
    splits = [
        build_disjoint_galleries(templates_by_subject=roster, seed=seed)
        for seed in (0, 1, 2, 3, 4)
    ]
    signatures = {
        (frozenset(s.g1.items()), frozenset(s.g2.items()), s.probe_templates)
        for s in splits
    }
    assert len(signatures) > 1


def test_nonmated_stratum_nonempty_for_two_plus_roster():
    split = build_disjoint_galleries(templates_by_subject=_two_plus_roster(), seed=3)
    for gallery in (GalleryName.G1, GalleryName.G2):
        probes = probes_for(split, gallery=gallery)
        assert probes.n_nonmated > 0
        assert probes.nonmated
        assert probes.n_nonmated == len(probes.nonmated)
        assert probes.n_mated == len(probes.mated)
        assert probes.n_subjects == len(
            {t.subject_id for t in (*probes.mated, *probes.nonmated)}
        )
        enrolled = set(split.g1 if gallery is GalleryName.G1 else split.g2)
        assert all(t.subject_id in enrolled for t in probes.mated)
        assert all(t.subject_id not in enrolled for t in probes.nonmated)


def test_other_gallery_only_subject_is_nonmated():
    split = build_disjoint_galleries(templates_by_subject=_two_plus_roster(), seed=4)
    g1_probes = probes_for(split, gallery="g1")
    g2_only = set(split.g2)
    nonmated_subjects = {t.subject_id for t in g1_probes.nonmated}
    assert g2_only <= nonmated_subjects
    for subject_id, template in split.g2.items():
        assert template in g1_probes.nonmated
        assert subject_id not in split.g1


def test_singleton_is_assigned_not_dropped():
    roster = _roster(
        ("alice", ("a1",)),
        ("bob", ("b1", "b2")),
        ("carol", ("c1", "c2", "c3")),
    )
    split = build_disjoint_galleries(templates_by_subject=roster, seed=5)
    in_g1 = "alice" in split.g1
    in_g2 = "alice" in split.g2
    assert in_g1 ^ in_g2
    enrolled = split.g1["alice"] if in_g1 else split.g2["alice"]
    assert enrolled.template_id == "a1"
    assert "a1" not in split.probe_template_ids
    other = GalleryName.G2 if in_g1 else GalleryName.G1
    other_probes = probes_for(split, gallery=other)
    assert enrolled in other_probes.nonmated
    own = GalleryName.G1 if in_g1 else GalleryName.G2
    own_probes = probes_for(split, gallery=own)
    assert enrolled not in own_probes.mated
    assert enrolled not in own_probes.nonmated


def test_single_subject_searching_own_gallery_has_empty_nonmated_and_raises():
    split = build_disjoint_galleries(
        templates_by_subject=_roster(("alice", ("a1", "a2"))),
        seed=0,
    )
    assert list(split.g1) == ["alice"]
    assert split.g2 == {}
    with pytest.raises(GallerySplitError, match="empty non-mated"):
        probes_for(split, gallery=GalleryName.G1)


def test_all_singleton_roster_declares_empty_mated_not_a_hidden_cell():
    """Empty mated is returned, not raised, and fnir_measurable is False.

    Owner of unmeasured FNIR is fnir_fpi_at_threshold (IETPoint.measured).
    Raising here would suppress independently meaningful FPI.
    """
    roster = _roster(("alice", ("a1",)), ("bob", ("b1",)))
    split = build_disjoint_galleries(templates_by_subject=roster, seed=0)
    for gallery in (GalleryName.G1, GalleryName.G2):
        probes = probes_for(split, gallery=gallery)
        assert probes.n_mated == 0
        assert probes.mated == ()
        assert probes.fnir_measurable is False
        assert probes.n_nonmated > 0
        assert probes.nonmated


def test_media_ids_are_disjoint_across_galleries_and_reserved_probes():
    roster = {
        "alice": [
            Template(template_id="a1", subject_id="alice", media_ids=(10, 11)),
            Template(template_id="a2", subject_id="alice", media_ids=(12,)),
        ],
        "bob": [
            Template(template_id="b1", subject_id="bob", media_ids=(20,)),
            Template(template_id="b2", subject_id="bob", media_ids=(21, 22)),
        ],
    }
    split = build_disjoint_galleries(templates_by_subject=roster, seed=6)
    g1_media = {mid for t in split.g1.values() for mid in t.media_ids}
    g2_media = {mid for t in split.g2.values() for mid in t.media_ids}
    assert g1_media.isdisjoint(g2_media)
    assert g1_media.isdisjoint(split.probe_media_ids)
    assert g2_media.isdisjoint(split.probe_media_ids)


def test_keyword_only_public_entrypoints():
    with pytest.raises(TypeError):
        build_disjoint_galleries(_two_plus_roster(), 0)  # type: ignore[misc]
    split = build_disjoint_galleries(templates_by_subject=_two_plus_roster(), seed=0)
    with pytest.raises(TypeError):
        probes_for(split, "g1")  # type: ignore[misc]


def _gallery_media(split) -> set[int]:
    return {
        mid
        for gallery in (split.g1, split.g2)
        for template in gallery.values()
        for mid in template.media_ids
    }


def test_shared_still_coassigns_subjects_and_keeps_probe_media_disjoint():
    roster = {
        "alice": [
            Template(template_id="a-group", subject_id="alice", media_ids=(7,)),
            Template(template_id="a-solo", subject_id="alice", media_ids=(1,)),
        ],
        "bob": [
            Template(template_id="b-group", subject_id="bob", media_ids=(7,)),
        ],
    }
    split = build_disjoint_galleries(templates_by_subject=roster, seed=0)
    assert ("alice" in split.g1) == ("bob" in split.g1)
    assert "alice" in split.g1 or "alice" in split.g2
    assert "bob" in split.g1 or "bob" in split.g2
    gallery_media = _gallery_media(split)
    probe_media = {mid for t in split.probe_templates for mid in t.media_ids}
    assert gallery_media.isdisjoint(probe_media)
    enrolled_alice = split.g1.get("alice") or split.g2["alice"]
    enrolled_bob = split.g1.get("bob") or split.g2["bob"]
    assert enrolled_alice.template_id == "a-solo"
    assert enrolled_bob.template_id == "b-group"
    withheld_ids = {t.template_id for t in split.withheld_probe_templates}
    assert withheld_ids == {"a-group"}
    assert "a-group" not in split.probe_template_ids


def test_only_shared_still_subject_is_enrolled_not_dropped():
    roster = {
        "alice": [Template(template_id="a1", subject_id="alice", media_ids=(3,))],
        "bob": [Template(template_id="b1", subject_id="bob", media_ids=(3,))],
        "carol": [
            Template(template_id="c1", subject_id="carol", media_ids=(8,)),
            Template(template_id="c2", subject_id="carol", media_ids=(9,)),
        ],
    }
    split = build_disjoint_galleries(templates_by_subject=roster, seed=1)
    assigned = set(split.g1) | set(split.g2)
    assert assigned == {"alice", "bob", "carol"}
    assert ("alice" in split.g1) == ("bob" in split.g1)
