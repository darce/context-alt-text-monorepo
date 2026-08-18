"""VLM-6 S1: curation->manifest identity bridge + publishable flag."""

import pytest

from scripts.eval_harness.export_identities import (
    enrich_entry,
    identities_for_image,
    spatial_facts_from_regions,
)
from scripts.eval_harness.identity_sources import FaceRegion
from scripts.eval_harness.manifest import (
    FaceBox,
    LicenseTag,
    Provenance,
    SpatialRelation,
)


def _region(name, x, y=0.5, w=0.2, h=0.2, source="iptc"):
    return FaceRegion(name=name, x=x, y=y, w=w, h=h, source=source)


def _iptc_xmp(*regions) -> bytes:
    lis = "".join(
        f'<rdf:li xmlns:Iptc4xmpExt="http://iptc.org/std/Iptc4xmpExt/2008-02-29/">'
        f"<Iptc4xmpExt:RegionBoundary><Iptc4xmpExt:rbX>{x}</Iptc4xmpExt:rbX>"
        f"<Iptc4xmpExt:rbY>0.5</Iptc4xmpExt:rbY><Iptc4xmpExt:rbW>0.2</Iptc4xmpExt:rbW>"
        f"<Iptc4xmpExt:rbH>0.2</Iptc4xmpExt:rbH></Iptc4xmpExt:RegionBoundary>"
        f'<Iptc4xmpExt:Name xmlns:Iptc4xmpExt="http://iptc.org/std/Iptc4xmpExt/2008-02-29/">'
        f"{name}</Iptc4xmpExt:Name></rdf:li>"
        for name, x in regions
    )
    xmp = (
        '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF '
        'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><rdf:Description>'
        f"<Iptc4xmpExt:ImageRegion><rdf:Bag>{lis}</rdf:Bag></Iptc4xmpExt:ImageRegion>"
        "</rdf:Description></rdf:RDF></x:xmpmeta>"
    )
    return b"\xff\xd8" + xmp.encode("utf-8") + b"\xff\xd9"


# --- publishable flag --------------------------------------------------------


def test_publishable_explicit_wins():
    p = Provenance(source="celeb", license=LicenseTag.CONSENTED, publishable=True)
    assert p.is_publishable is True


def test_publishable_license_derived_failclosed():
    assert Provenance(source="wikimedia", license=LicenseTag.CC0).is_publishable is True
    assert Provenance(source="wikimedia", license=LicenseTag.PUBLIC_DOMAIN).is_publishable is True
    # private/consented/mock/fixture are local-only unless explicitly flagged
    assert Provenance(source="localwp", license=LicenseTag.CONSENTED).is_publishable is False
    assert Provenance(source="wikimedia", license=LicenseTag.MOCK_ENTITY).is_publishable is False
    assert Provenance(source="wikimedia", license=LicenseTag.FIXTURE).is_publishable is False


def test_publishable_explicit_false_overrides_cc0():
    assert Provenance(source="wikimedia", license=LicenseTag.CC0, publishable=False).is_publishable is False


# --- identities_for_image ----------------------------------------------------


def test_celeb_identity_from_filename_source():
    gt = identities_for_image(b"\xff\xd8\xff\xd9", source="celeb", filename="al_pacino_10.jpg")
    assert gt.present_identities == ["Al Pacino"]
    assert gt.face_count == 1 and gt.spatial_facts == []


def test_personal_identity_from_xmp():
    img = _iptc_xmp(("Slate Willow", 0.3))
    gt = identities_for_image(img, source="localwp", filename="whatever.jpg")
    assert gt.present_identities == ["Slate Willow"] and gt.face_count == 1


def test_stranger_source_has_no_identity_but_counts_faces():
    img = _iptc_xmp(("Ignored Name", 0.5))
    gt = identities_for_image(img, source="wikimedia", filename="crowd.jpg")
    assert gt.present_identities == [] and gt.face_count == 1


# --- spatial facts -----------------------------------------------------------


def test_spatial_left_of_from_boxes():
    facts = spatial_facts_from_regions([_region("Alice", 0.2), _region("Bob", 0.8)])
    assert len(facts) == 1
    assert facts[0].subject == "Alice" and facts[0].relation is SpatialRelation.LEFT_OF
    assert facts[0].reference == "Bob"
    assert any("to the left of Bob" in p for p in facts[0].phrases)


def test_spatial_skips_near_equal_centres():
    assert spatial_facts_from_regions([_region("A", 0.50), _region("B", 0.51)]) == []


def test_spatial_dedupes_same_name():
    facts = spatial_facts_from_regions([_region("A", 0.2), _region("A", 0.9)])
    assert facts == []  # only one distinct identity -> no pair


def test_spatial_unnamed_regions_ignored():
    assert spatial_facts_from_regions([_region(None, 0.2), _region(None, 0.8)]) == []


def test_personal_multiface_derives_spatial():
    img = _iptc_xmp(("Alice Ray", 0.2), ("Bob Lin", 0.8))
    gt = identities_for_image(img, source="localwp", filename="pair.jpg")
    assert set(gt.present_identities) == {"Alice Ray", "Bob Lin"} and gt.face_count == 2
    assert gt.spatial_facts and gt.spatial_facts[0].subject == "Alice Ray"


# --- enrich_entry ------------------------------------------------------------


def test_enrich_entry_fills_celeb():
    entry = {"path": "celebs/al_pacino_3.jpg", "provenance": {"source": "celeb", "license": "public_domain"}}
    out = enrich_entry(entry, b"\xff\xd8\xff\xd9")
    assert out["present_identities"] == ["Al Pacino"]
    assert out["face_count"] == 1 and out["must_right"] == ["Al Pacino"]


def test_enrich_entry_skips_legacy_without_provenance():
    entry = {"path": "old.jpg", "present_identities": ["Existing"]}
    assert enrich_entry(entry, b"\xff\xd8\xff\xd9") == entry


def test_enrich_entry_does_not_overwrite_curated_identities():
    entry = {
        "path": "x_1.jpg",
        "provenance": {"source": "celeb", "license": "public_domain"},
        "present_identities": ["Hand Curated"],
    }
    out = enrich_entry(entry, b"\xff\xd8\xff\xd9")
    assert out["present_identities"] == ["Hand Curated"]


def test_enrich_entry_personal_adds_spatial():
    entry = {"path": "pair.jpg", "provenance": {"source": "localwp", "license": "consented"}}
    out = enrich_entry(entry, _iptc_xmp(("Alice Ray", 0.2), ("Bob Lin", 0.8)))
    assert out["face_count"] == 2 and out["spatial_facts"]
    assert out["spatial_facts"][0]["subject"] == "Alice Ray"


# --- VLM-6 review fixes: source-aware publishability + canonical source vocab -----


def test_private_source_never_publishable_even_with_public_license():
    # Crown-jewel invariant (E-01): a personal/upload photo is never publishable — not
    # via a CC0/public-domain license and not via an explicit publishable=True flag.
    assert Provenance(source="localwp", license=LicenseTag.CC0).is_publishable is False
    assert Provenance(source="localwp", license=LicenseTag.PUBLIC_DOMAIN).is_publishable is False
    assert Provenance(source="localwp", license=LicenseTag.CC0, publishable=True).is_publishable is False
    assert Provenance(source="operator", license=LicenseTag.PUBLIC_DOMAIN, publishable=True).is_publishable is False


def test_strata_scan_root_or_unknown_source_raises_not_strangers():
    # A curator copying strata's scan-root label ("celebs01"/"localwp_uploads") verbatim
    # into golden.json must fail loudly, not silently drop identity ground truth (E-02).
    with pytest.raises(ValueError, match="unknown provenance source"):
        identities_for_image(b"\xff\xd8\xff\xd9", source="celebs01", filename="al_pacino_10.jpg")
    with pytest.raises(ValueError, match="unknown provenance source"):
        identities_for_image(b"\xff\xd8\xff\xd9", source="localwp_uploads", filename="x.jpg")


def test_enrich_entry_face_count_covers_curated_identities():
    # A curated multi-identity entry whose image carries no XMP must not land below its
    # own present_identities count (would raise ManifestError downstream) (E-04).
    entry = {
        "path": "group.jpg",
        "provenance": {"source": "localwp", "license": "consented"},
        "present_identities": ["Ana Ruiz", "Beto Sol", "Cyd Vega"],
    }
    out = enrich_entry(entry, b"\xff\xd8\xff\xd9")  # no XMP -> zero detected regions
    assert out["face_count"] >= 3


def test_enrich_entry_persists_all_face_boxes_including_anonymous():
    # FIR-1: box-level detection ground truth must include anonymous strangers (name=None),
    # not just the named identities (which stay in present_identities).
    entry = {"path": "group.jpg", "provenance": {"source": "localwp", "license": "consented"}}
    out = enrich_entry(entry, _iptc_xmp(("Alice Ray", 0.2), ("", 0.8)))  # one named + one anonymous box
    boxes = out["face_boxes"]
    assert len(boxes) == 2
    assert {b["name"] for b in boxes} == {"Alice Ray", None}
    assert out["present_identities"] == ["Alice Ray"]  # names-only leg unchanged
    # each persisted box round-trips through the FaceBox schema (locks output <-> schema)
    parsed = [FaceBox(**b) for b in boxes]
    assert all(0.0 <= fb.x <= 1.0 and fb.source == "iptc" for fb in parsed)


def test_enrich_entry_does_not_write_tags_domain_or_cohort():
    """FIR-5 S1: enrich_entry stays identity + detection-GT only (real shape).

    Must not invent tags / domain / demographic_cohort on the returned dict.
    """
    entry = {
        "path": "celebs/al_pacino_3.jpg",
        "provenance": {"source": "celeb", "license": "public_domain"},
    }
    out = enrich_entry(entry, b"\xff\xd8\xff\xd9")
    # Real producer keys (identity + detection GT only for a celeb fill):
    assert "present_identities" in out and "face_count" in out and "must_right" in out
    assert "tags" not in out
    assert "domain" not in out
    assert "demographic_cohort" not in out
    # Also not present when the input already lacked them (no silent defaults).
    assert set(out) == {
        "path",
        "provenance",
        "present_identities",
        "face_count",
        "must_right",
    }
