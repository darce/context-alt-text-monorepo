"""FIR-12: disjoint G1/G2 galleries — open-set non-mated probes (EVAL-18 / MLDATA-09).

TEST-15: each assertion is can-fail against a LOO-style dual-enroll impl.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from scripts.eval_harness.gallery_split import (
    GalleryName,
    GallerySplit,
    GallerySplitError,
    Template,
    build_disjoint_galleries,
    probes_for,
)


def _roster(*pairs: tuple[str, tuple[str, ...]]) -> dict[str, list[Template]]:
    """Unique media per template so string-id fixtures keep subject independence."""
    by_subject: dict[str, list[Template]] = {}
    media_id = 1
    for subject, ids in pairs:
        templates: list[Template] = []
        for template_id in ids:
            templates.append(
                Template(
                    template_id=template_id,
                    subject_id=subject,
                    media_ids=(media_id,),
                )
            )
            media_id += 1
        by_subject[subject] = templates
    return by_subject


def _two_plus_roster() -> dict[str, list[Template]]:
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
            templates_by_subject={
                "alice": [
                    Template(template_id="a1", subject_id="alice", media_ids=(1,)),
                    Template(template_id="a2", subject_id="alice", media_ids=(2,)),
                ],
                "bob": [],
            },
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


def test_single_component_roster_refuses_empty_gallery():
    """One connected component fills G1 and leaves G2 empty — not a 1:N split."""
    with pytest.raises(GallerySplitError, match="empty gallery"):
        build_disjoint_galleries(
            templates_by_subject=_roster(("alice", ("a1", "a2"))),
            seed=0,
        )
    shared = {
        "alice": [Template(template_id="a1", subject_id="alice", media_ids=(1,))],
        "bob": [Template(template_id="b1", subject_id="bob", media_ids=(1,))],
    }
    with pytest.raises(GallerySplitError, match="empty gallery"):
        build_disjoint_galleries(templates_by_subject=shared, seed=0)


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
        "carol": [
            Template(template_id="c1", subject_id="carol", media_ids=(8,)),
            Template(template_id="c2", subject_id="carol", media_ids=(9,)),
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


def test_string_templates_parse_media_ids_and_coassign_shared_still():
    """'{media}:{subject}' strings must not empty media_ids (JANUS 2.2 / MLDATA-09).

    Defaulting the convenience path to media_ids=() makes every media-disjointness
    invariant a no-op: alice and bob sharing still 99 land in different galleries.
    """
    roster = {
        "alice": ["99:alice"],
        "bob": ["99:bob"],
        "carol": ["1:carol", "2:carol"],
    }
    split = build_disjoint_galleries(templates_by_subject=roster, seed=0)
    assert ("alice" in split.g1) == ("bob" in split.g1)
    enrolled_alice = split.g1.get("alice") or split.g2["alice"]
    enrolled_bob = split.g1.get("bob") or split.g2["bob"]
    assert enrolled_alice.media_ids == (99,)
    assert enrolled_bob.media_ids == (99,)
    g1_media = {mid for t in split.g1.values() for mid in t.media_ids}
    g2_media = {mid for t in split.g2.values() for mid in t.media_ids}
    assert g1_media
    assert g2_media
    assert g1_media.isdisjoint(g2_media)


def _shared_still_string_roster() -> dict[str, list[str]]:
    return {
        "alice": ["99:alice"],
        "bob": ["99:bob"],
        "carol": ["1:carol", "2:carol"],
    }


def _shared_still_object_roster_empty_media() -> dict[str, list[Template]]:
    """Same shared still as the string roster, default media_ids=() (BR-30)."""
    return {
        "alice": [Template(template_id="99:alice", subject_id="alice")],
        "bob": [Template(template_id="99:bob", subject_id="bob")],
        "carol": [
            Template(template_id="1:carol", subject_id="carol"),
            Template(template_id="2:carol", subject_id="carol"),
        ],
    }


def test_shared_still_coassigns_in_both_forms_across_seeds():
    """JANUS 2.2: '{media}:{subject}' co-assigns for Template | str, seeds 0–15."""
    strings = _shared_still_string_roster()
    objects = _shared_still_object_roster_empty_media()
    for seed in range(16):
        from_strings = build_disjoint_galleries(templates_by_subject=strings, seed=seed)
        from_objects = build_disjoint_galleries(templates_by_subject=objects, seed=seed)
        assert from_strings == from_objects
        assert ("alice" in from_objects.g1) == ("bob" in from_objects.g1)
        enrolled_alice = from_objects.g1.get("alice") or from_objects.g2["alice"]
        enrolled_bob = from_objects.g1.get("bob") or from_objects.g2["bob"]
        assert enrolled_alice.media_ids == (99,)
        assert enrolled_bob.media_ids == (99,)


def test_independent_single_still_roster_accepted_in_both_forms():
    """Two components with no shared still are a legal open-set split (MLDATA-09)."""
    strings = {"alice": ["a1"], "bob": ["b1"]}
    objects = {
        "alice": [Template(template_id="a1", subject_id="alice")],
        "bob": [Template(template_id="b1", subject_id="bob")],
    }
    from_strings = build_disjoint_galleries(templates_by_subject=strings, seed=0)
    from_objects = build_disjoint_galleries(templates_by_subject=objects, seed=0)
    assert from_strings == from_objects
    assigned = set(from_strings.g1) | set(from_strings.g2)
    assert assigned == {"alice", "bob"}
    assert set(from_strings.g1).isdisjoint(set(from_strings.g2))
    assert from_strings.g1 and from_strings.g2


def _frozen_e_clean_roster() -> dict[str, list[Template]]:
    here = Path(__file__).resolve()
    manifest = None
    for parent in here.parents:
        candidate = parent / "benchmarks" / "manifests" / "fir12-selection-v1.json"
        if candidate.is_file():
            manifest = candidate
            break
    if manifest is None:
        raise RuntimeError("cannot locate fir12-selection-v1.json from test path")
    payload = json.loads(manifest.read_text())
    by_subject: dict[str, list[Template]] = {}
    for entry in payload["entries"]:
        if entry.get("stratum") != "E_clean":
            continue
        identities = entry.get("present_identities")
        if not isinstance(identities, list) or not identities:
            continue
        media_id = int(entry["media_id"])
        for subject_id in identities:
            by_subject.setdefault(subject_id, []).append(
                Template(
                    template_id=f"{media_id}:{subject_id}",
                    subject_id=subject_id,
                    media_ids=(media_id,),
                )
            )
    return by_subject


def test_frozen_frame_both_galleries_nonempty_across_seeds():
    """Latent on the frozen frame: seeds 0–63 already yield two non-empty galleries.

    If this fails, the split or the frame changed — do not loosen the assertion.
    """
    roster = _frozen_e_clean_roster()
    empty: list[int] = []
    for seed in range(64):
        split = build_disjoint_galleries(templates_by_subject=roster, seed=seed)
        if not split.g1 or not split.g2:
            empty.append(seed)
    assert empty == []


def test_frozen_frame_seed_0_gallery_sizes():
    """FIR-12 runner depends on seed 0: g1=53, g2=56, overlap=0. Do not weaken."""
    roster = _frozen_e_clean_roster()
    split = build_disjoint_galleries(templates_by_subject=roster, seed=0)
    assert len(split.g1) == 53
    assert len(split.g2) == 56
    assert set(split.g1).isdisjoint(set(split.g2))


def _legal_other_gallery() -> dict[str, Template]:
    return {
        "Bob": Template(template_id="b1", subject_id="Bob", media_ids=(2,)),
    }


def test_blank_gallery_subject_id_is_rejected() -> None:
    """BR-56: whitespace-only roster key is a corrupt gallery, not a subject."""
    with pytest.raises(GallerySplitError, match=r"g1 subject_id must be a non-empty string, got '   '"):
        GallerySplit(
            g1={
                "   ": Template(template_id="a1", subject_id="   ", media_ids=(1,)),
            },
            g2=_legal_other_gallery(),
            probe_templates=(),
        )


def test_non_string_gallery_subject_id_is_rejected() -> None:
    """BR-56: None must not stringify into a roster key like 'None'."""
    with pytest.raises(GallerySplitError, match=r"g2 subject_id must be a non-empty string, got None"):
        GallerySplit(
            g1={
                "Alice": Template(template_id="a1", subject_id="Alice", media_ids=(1,)),
            },
            g2={
                None: Template(  # type: ignore[dict-item]
                    template_id="b1",
                    subject_id=None,  # type: ignore[arg-type]
                    media_ids=(2,),
                ),
            },
            probe_templates=(),
        )


def test_post_normalisation_key_collision_raises_with_offending_raw_value() -> None:
    """BR-59: a silent overwrite would drop a gallery mate from the FNIR denominator (EVAL-18)."""
    colliding: dict[str, Template] = {}
    colliding["Alice"] = Template(template_id="a1", subject_id="Alice", media_ids=(1,))
    colliding["Alice "] = Template(template_id="a2", subject_id="Alice ", media_ids=(3,))
    with pytest.raises(GallerySplitError) as caught:
        GallerySplit(
            g1=colliding,
            g2=_legal_other_gallery(),
            probe_templates=(),
        )
    message = str(caught.value)
    assert "collides after normalisation" in message
    assert repr("Alice ") in message


def test_distinct_stripped_gallery_keys_are_kept() -> None:
    """Whitespace-padded keys that strip to different subjects are not a collision."""
    split = GallerySplit(
        g1={
            "Alice": Template(template_id="a1", subject_id="Alice", media_ids=(1,)),
            "Bob ": Template(template_id="b1", subject_id="Bob ", media_ids=(3,)),
        },
        g2=_legal_other_gallery(),
        probe_templates=(
            Template(template_id="p2", subject_id="Ann ", media_ids=(5,)),
            Template(template_id="p1", subject_id="Ann", media_ids=(4,)),
        ),
    )
    assert list(split.g1) == ["Alice", "Bob"]
    assert split.g1["Bob"].subject_id == "Bob"
    assert split.g1["Bob"].template_id == "b1"
    assert [(t.subject_id, t.template_id) for t in split.probe_templates] == [
        ("Ann", "p1"),
        ("Ann", "p2"),
    ]


def test_gallery_and_probe_order_are_sorted_independent_of_insertion() -> None:
    """BR-60: EVAL-13 pins gallery keys and probe templates to sorted order, not insertion."""
    g1: dict[str, Template] = {}
    g1["Bob"] = Template(template_id="b1", subject_id="Bob", media_ids=(1,))
    g1["Alice"] = Template(template_id="a1", subject_id="Alice", media_ids=(2,))
    probes = (
        Template(template_id="z1", subject_id="Zoe", media_ids=(3,)),
        Template(template_id="n1", subject_id="Ann", media_ids=(4,)),
    )
    split = GallerySplit(
        g1=g1,
        g2=_legal_other_gallery(),
        probe_templates=probes,
    )
    assert list(split.g1) == ["Alice", "Bob"]
    assert [(t.subject_id, t.template_id) for t in split.probe_templates] == [
        ("Ann", "n1"),
        ("Zoe", "z1"),
    ]


def _two_subject_split() -> GallerySplit:
    return GallerySplit(
        g1={
            "Alice": Template(template_id="a1", subject_id="Alice", media_ids=(1,)),
        },
        g2=_legal_other_gallery(),
        probe_templates=(),
    )


def test_gallery_maps_reject_in_place_mutation() -> None:
    """BR-62: construction-time identity cannot be mutated in place (EVAL-13)."""
    split = _two_subject_split()
    alice = split.g1["Alice"]
    bob = split.g2["Bob"]

    with pytest.raises(TypeError):
        split.g1["Alice"] = alice
    with pytest.raises(TypeError):
        split.g1["Eve"] = alice
    with pytest.raises(TypeError):
        split.g2["Bob"] = bob
    with pytest.raises(TypeError):
        split.g2["Eve"] = bob

    with pytest.raises(TypeError):
        del split.g1["Alice"]
    with pytest.raises(TypeError):
        del split.g2["Bob"]

    with pytest.raises((TypeError, AttributeError)):
        split.g1.pop("Alice")
    with pytest.raises((TypeError, AttributeError)):
        split.g2.pop("Bob")
    with pytest.raises((TypeError, AttributeError)):
        split.g1.update({"Eve": alice})
    with pytest.raises((TypeError, AttributeError)):
        split.g2.update({"Eve": bob})

    assert list(split.g1) == ["Alice"]
    assert list(split.g2) == ["Bob"]
    assert split.g1["Alice"] is alice
    assert split.g2["Bob"] is bob


def test_gallery_map_reads_survive_readonly_wrapper() -> None:
    """BR-62: len / in / get / values / iteration order stay the published API."""
    split = GallerySplit(
        g1={
            "Bob": Template(template_id="b1", subject_id="Bob", media_ids=(1,)),
            "Alice": Template(template_id="a1", subject_id="Alice", media_ids=(2,)),
        },
        g2=_legal_other_gallery(),
        probe_templates=(),
    )
    assert len(split.g1) == 2
    assert "Alice" in split.g1
    assert "Carol" not in split.g1
    assert split.g1.get("Alice") is split.g1["Alice"]
    assert split.g1.get("Carol") is None
    assert [t.template_id for t in split.g1.values()] == ["a1", "b1"]
    assert list(split.g1) == ["Alice", "Bob"]
    assert len(split.g2) == 1
    assert "Bob" in split.g2
    assert split.g2.get("Bob") is split.g2["Bob"]
    assert [t.template_id for t in split.g2.values()] == ["b1"]
    assert list(split.g2) == ["Bob"]


def test_replace_and_readonly_input_rerun_post_init() -> None:
    """BR-62: dataclasses.replace and already-read-only maps re-normalise."""
    split = _two_subject_split()
    again = replace(split)
    assert again == split
    assert list(again.g1) == ["Alice"]
    assert list(again.g2) == ["Bob"]
    with pytest.raises(TypeError):
        again.g1["Alice"] = split.g1["Alice"]
    with pytest.raises(TypeError):
        again.g2["Bob"] = split.g2["Bob"]

    rebuilt = GallerySplit(
        g1=split.g1,
        g2=split.g2,
        probe_templates=split.probe_templates,
    )
    assert rebuilt == split
    assert list(rebuilt.g1) == ["Alice"]
    with pytest.raises(TypeError):
        rebuilt.g1["Eve"] = split.g1["Alice"]
    with pytest.raises(TypeError):
        rebuilt.g2["Eve"] = split.g2["Bob"]

    padded = replace(
        split,
        g1={" Alice ": split.g1["Alice"]},
    )
    assert list(padded.g1) == ["Alice"]
    with pytest.raises(TypeError):
        padded.g1["Alice "] = padded.g1["Alice"]


def test_internal_whitespace_subject_id_is_kept() -> None:
    """Internal spaces are identity, not padding — still a legal read-only key."""
    split = GallerySplit(
        g1={
            "Alice Smith": Template(
                template_id="a1", subject_id="Alice Smith", media_ids=(1,)
            ),
        },
        g2=_legal_other_gallery(),
        probe_templates=(),
    )
    assert list(split.g1) == ["Alice Smith"]
    assert "Alice Smith" in split.g1
    assert split.g1.get("Alice Smith") is split.g1["Alice Smith"]
    reconstructed = {**split.g1}
    assert list(reconstructed) == ["Alice Smith"]
    with pytest.raises(TypeError):
        split.g1["Alice Smith"] = split.g1["Alice Smith"]


@pytest.mark.parametrize(
    ("g1", "g2", "key", "held"),
    (
        (
            {
                "Alice": Template(
                    template_id="a1", subject_id="Carol", media_ids=(1,)
                ),
            },
            _legal_other_gallery(),
            "Alice",
            "Carol",
        ),
        (
            {
                "Alice": Template(
                    template_id="a1", subject_id="Alice", media_ids=(1,)
                ),
            },
            {
                "Bob": Template(
                    template_id="b1", subject_id="Carol", media_ids=(2,)
                ),
            },
            "Bob",
            "Carol",
        ),
    ),
    ids=("g1", "g2"),
)
def test_gallery_map_key_subject_mismatch_raises(
    g1: dict[str, Template],
    g2: dict[str, Template],
    key: str,
    held: str,
) -> None:
    """BR-65: map key vs template.subject_id that strip to different identities fail loud (EVAL-18).

    The raise sits before _with_subject rewrites the template onto the key; a
    silent rewrite would enroll Carol's media under Alice.
    """
    with pytest.raises(GallerySplitError) as caught:
        GallerySplit(g1=g1, g2=g2, probe_templates=())
    message = str(caught.value)
    assert repr(key) in message
    assert repr(held) in message


def test_builder_roster_key_subject_mismatch_raises() -> None:
    """BR-65: build_disjoint_galleries refuses Carol enrolled under roster key alice."""
    with pytest.raises(GallerySplitError) as caught:
        build_disjoint_galleries(
            templates_by_subject={
                "alice": [
                    Template(template_id="a1", subject_id="Carol", media_ids=(1,)),
                    Template(template_id="a2", subject_id="Carol", media_ids=(2,)),
                ],
                "bob": [
                    Template(template_id="b1", subject_id="bob", media_ids=(3,)),
                    Template(template_id="b2", subject_id="bob", media_ids=(4,)),
                ],
            },
            seed=0,
        )
    message = str(caught.value)
    assert repr("alice") in message
    assert repr("Carol") in message


def test_gallery_key_and_subject_id_padding_is_same_identity() -> None:
    """BR-65: key and subject_id that differ only by surrounding whitespace are accepted."""
    split = GallerySplit(
        g1={
            " Alice ": Template(template_id="a1", subject_id="Alice", media_ids=(1,)),
        },
        g2=_legal_other_gallery(),
        probe_templates=(),
    )
    assert list(split.g1) == ["Alice"]
    assert split.g1["Alice"].subject_id == "Alice"
    assert split.g1["Alice"].template_id == "a1"

    split_template_pad = GallerySplit(
        g1={
            "Alice": Template(template_id="a1", subject_id=" Alice ", media_ids=(1,)),
        },
        g2={
            " Bob ": Template(template_id="b1", subject_id="Bob", media_ids=(2,)),
        },
        probe_templates=(),
    )
    assert list(split_template_pad.g1) == ["Alice"]
    assert split_template_pad.g1["Alice"].subject_id == "Alice"
    assert list(split_template_pad.g2) == ["Bob"]
    assert split_template_pad.g2["Bob"].subject_id == "Bob"

    built = build_disjoint_galleries(
        templates_by_subject={
            " alice ": [
                Template(template_id="a1", subject_id="alice", media_ids=(1,)),
                Template(template_id="a2", subject_id=" alice ", media_ids=(2,)),
            ],
            "bob": [
                Template(template_id="b1", subject_id="bob", media_ids=(3,)),
                Template(template_id="b2", subject_id="bob", media_ids=(4,)),
            ],
        },
        seed=0,
    )
    assigned = set(built.g1) | set(built.g2)
    assert assigned == {"alice", "bob"}
    enrolled_alice = built.g1.get("alice") or built.g2["alice"]
    assert enrolled_alice.subject_id == "alice"


def test_withheld_probe_templates_are_sorted_and_stripped_independent_of_insertion() -> None:
    """BR-66: constructor-site withheld normalisation is pinned (EVAL-13), not the builder pre-sort."""
    withheld = (
        Template(template_id="z1", subject_id="Zoe ", media_ids=(3,)),
        Template(template_id="n1", subject_id="Ann ", media_ids=(4,)),
    )
    split = GallerySplit(
        g1={
            "Alice": Template(template_id="a1", subject_id="Alice", media_ids=(1,)),
        },
        g2=_legal_other_gallery(),
        probe_templates=(),
        withheld_probe_templates=withheld,
    )
    assert [
        (t.subject_id, t.template_id) for t in split.withheld_probe_templates
    ] == [
        ("Ann", "n1"),
        ("Zoe", "z1"),
    ]
