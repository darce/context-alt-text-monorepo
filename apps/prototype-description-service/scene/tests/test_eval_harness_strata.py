"""VLM-6 S1: strata bucketing + per-stratum operator shortlists."""

import json

import pytest

from scripts.eval_harness.corpus_inventory import ImageRecord, write_records
from scripts.eval_harness.manifest import Domain
from scripts.eval_harness.strata import (
    CROWD_MIN_FACES,
    MIN_STRATUM_POOL,
    OFFLINE_DOMAINS,
    OPERATOR_DOMAINS,
    Confidence,
    Source,
    _main,
    build_report,
    celeb_label,
    is_publishable,
    load_inventory,
    report_json,
)


def rec(path="a.jpg", **over) -> ImageRecord:
    """A full-shape ImageRecord; override only what a test is about."""
    base = dict(
        path=path,
        sha256=f"sha-{path}",
        width=800,
        height=600,
        mean_saturation=0.4,
        mean_value=0.5,
        aspect_ratio=1.3333,
        celeb_name=None,
        xmp_names=[],
        xmp_face_count=0,
        bw_candidate=False,
        low_light_candidate=False,
        flat_color_coverage=0.1,
        flat_color_candidate=False,
        edge_density=0.2,
    )
    base.update(over)
    return ImageRecord(**base)


def test_record_helper_matches_the_real_dataclass_shape():
    # Guards the whole file: if ImageRecord gains a field, this fails loudly here
    # rather than silently mis-shaping every other test.
    from dataclasses import fields

    assert {f.name for f in fields(ImageRecord)} == set(rec().__dict__)


# --- identity-label gating (the Ellynheald defense) ---------------------------


def test_uploads_never_yield_an_identity_label_even_with_a_parsed_name():
    # A scraped upload filename can parse to a plausible name that names nobody.
    assert celeb_label(rec(celeb_name="Ellynheald"), Source.LOCALWP_UPLOADS) is None


def test_celebs01_filename_is_the_identity_label():
    assert celeb_label(rec(celeb_name="Clint Eastwood"), Source.CELEBS01) == "Clint Eastwood"


def test_candidate_from_uploads_carries_no_celeb_name():
    report = build_report([(rec(celeb_name="Ellynheald", xmp_face_count=1), Source.LOCALWP_UPLOADS)])
    candidates = report.offline[Domain.PEOPLE].candidates
    assert len(candidates) == 1 and candidates[0].celeb_name is None


# --- publishability is fail-closed -------------------------------------------


def test_only_celebs01_publishes():
    assert is_publishable(rec(), Source.CELEBS01) is True
    assert is_publishable(rec(), Source.LOCALWP_UPLOADS) is False


def test_celebs_stay_publishable_despite_carrying_an_xmp_name():
    # 2320/2327 real celebs01 images embed a noisy partial name ("Al" for al_pacino).
    # Treating any XMP name as personal would mark 99.7% of the publishable corpus
    # unpublishable; the private-personal signal is the uploads root, not the name.
    assert is_publishable(rec(xmp_names=["Al"]), Source.CELEBS01) is True


def test_named_personal_uploads_are_never_publishable():
    # The 219 XMP-named personal photos are local-only.
    assert is_publishable(rec(xmp_names=["Maria Correonero"]), Source.LOCALWP_UPLOADS) is False


# --- bucketing ---------------------------------------------------------------


def test_bw_low_light_and_charts_bucket_on_their_features():
    report = build_report(
        [
            (rec(path="bw.jpg", bw_candidate=True), Source.LOCALWP_UPLOADS),
            (rec(path="dark.jpg", low_light_candidate=True), Source.LOCALWP_UPLOADS),
            (rec(path="chart.jpg", flat_color_candidate=True), Source.LOCALWP_UPLOADS),
        ]
    )
    assert [c.path for c in report.offline[Domain.BLACK_AND_WHITE].candidates] == ["bw.jpg"]
    assert [c.path for c in report.offline[Domain.LOW_LIGHT].candidates] == ["dark.jpg"]
    assert [c.path for c in report.offline[Domain.CHARTS].candidates] == ["chart.jpg"]


def test_face_counts_drive_people_and_crowds():
    report = build_report(
        [
            (rec(path="solo.jpg", xmp_face_count=1), Source.LOCALWP_UPLOADS),
            (rec(path="crowd.jpg", xmp_face_count=CROWD_MIN_FACES), Source.LOCALWP_UPLOADS),
            (rec(path="none.jpg", xmp_face_count=0), Source.LOCALWP_UPLOADS),
        ]
    )
    assert {c.path for c in report.offline[Domain.PEOPLE].candidates} == {"solo.jpg", "crowd.jpg"}
    assert [c.path for c in report.offline[Domain.CROWDS].candidates] == ["crowd.jpg"]
    assert [c.path for c in report.offline[Domain.FACES].candidates] == ["solo.jpg"]


def test_celebs01_images_are_faces_by_construction():
    report = build_report([(rec(path="dali_3.jpg", xmp_face_count=0), Source.CELEBS01)])
    assert [c.path for c in report.offline[Domain.FACES].candidates] == ["dali_3.jpg"]


def test_faces_ranks_public_figures_ahead_of_uploads():
    # Ranking FACES by descending face_count put ZERO public figures in the top 40 of
    # the real corpus -- it floats multi-face uploads to the top of a single-face
    # stratum and starves the identification-P/R stratum of its whole point.
    rows = [(rec(path=f"upload{i}.jpg", xmp_face_count=1), Source.LOCALWP_UPLOADS) for i in range(40)]
    rows.append((rec(path="zz_dali_3.jpg", celeb_name="Dali", xmp_face_count=1), Source.CELEBS01))
    candidates = build_report(rows, per_stratum=5).offline[Domain.FACES].candidates
    assert candidates[0].path == "zz_dali_3.jpg"
    assert candidates[0].publishable is True


def test_faces_shortlist_spreads_across_identities_not_one_figure():
    # celebs01 is ONE flat directory, so a folder-keyed spread collapsed to a single
    # group and returned 40 photos of Al Pacino -- one figure out of 111.
    rows = [
        (rec(path=f"al_pacino_{i}.jpg", celeb_name="Al Pacino", xmp_face_count=1), Source.CELEBS01) for i in range(20)
    ]
    rows += [(rec(path=f"dali_{i}.jpg", celeb_name="Dali", xmp_face_count=1), Source.CELEBS01) for i in range(20)]
    candidates = build_report(rows, per_stratum=4).offline[Domain.FACES].candidates
    assert len({c.celeb_name for c in candidates}) == 2, "a 4-image shortlist must show both figures"


def test_strata_are_not_exclusive():
    report = build_report([(rec(path="x.jpg", bw_candidate=True, xmp_face_count=1), Source.LOCALWP_UPLOADS)])
    strata = report.offline[Domain.PEOPLE].candidates[0].strata
    assert Domain.PEOPLE in strata and Domain.FACES in strata and Domain.BLACK_AND_WHITE in strata


def test_dense_scene_is_the_busiest_quartile_and_excludes_charts():
    rows = [(rec(path=f"{i:02d}.jpg", edge_density=i / 100), Source.LOCALWP_UPLOADS) for i in range(100)]
    rows.append((rec(path="chart.jpg", edge_density=0.99, flat_color_candidate=True), Source.LOCALWP_UPLOADS))
    report = build_report(rows)
    paths = {c.path for c in report.offline[Domain.DENSE_SCENE].candidates}
    assert "99.jpg" in paths, "the busiest image must be dense"
    assert "00.jpg" not in paths, "the flattest image must not be dense"
    assert "chart.jpg" not in paths, "a flat-color chart is not a dense scene"


# --- ranking -----------------------------------------------------------------


def test_bw_ranks_most_grayscale_first():
    report = build_report(
        [
            (rec(path="b.jpg", bw_candidate=True, mean_saturation=0.05), Source.LOCALWP_UPLOADS),
            (rec(path="a.jpg", bw_candidate=True, mean_saturation=0.01), Source.LOCALWP_UPLOADS),
        ]
    )
    assert [c.path for c in report.offline[Domain.BLACK_AND_WHITE].candidates] == ["a.jpg", "b.jpg"]


def test_charts_rank_flattest_first():
    report = build_report(
        [
            (rec(path="a.jpg", flat_color_candidate=True, flat_color_coverage=0.6), Source.LOCALWP_UPLOADS),
            (rec(path="b.jpg", flat_color_candidate=True, flat_color_coverage=0.9), Source.LOCALWP_UPLOADS),
        ]
    )
    assert [c.path for c in report.offline[Domain.CHARTS].candidates] == ["b.jpg", "a.jpg"]


def test_ties_break_by_path_so_output_is_stable():
    rows = [
        (rec(path="z.jpg", bw_candidate=True, mean_saturation=0.02), Source.LOCALWP_UPLOADS),
        (rec(path="a.jpg", bw_candidate=True, mean_saturation=0.02), Source.LOCALWP_UPLOADS),
        (rec(path="m.jpg", bw_candidate=True, mean_saturation=0.02), Source.LOCALWP_UPLOADS),
    ]
    first = [c.path for c in build_report(rows).offline[Domain.BLACK_AND_WHITE].candidates]
    second = [c.path for c in build_report(list(reversed(rows))).offline[Domain.BLACK_AND_WHITE].candidates]
    assert first == ["a.jpg", "m.jpg", "z.jpg"] and first == second


def test_per_stratum_truncates_but_pool_size_reports_the_whole_pool():
    rows = [(rec(path=f"{i:03d}.jpg", bw_candidate=True), Source.LOCALWP_UPLOADS) for i in range(50)]
    shortlist = build_report(rows, per_stratum=10).offline[Domain.BLACK_AND_WHITE]
    assert len(shortlist.candidates) == 10 and shortlist.pool_size == 50


# --- degrade paths -----------------------------------------------------------


def test_unreadable_image_is_dropped_from_feature_ranked_strata_without_crashing():
    # An unreadable image degrades to metadata-only: every feature is None, so there
    # is nothing to rank it on. It must not crash the sort.
    rows = [
        (
            rec(
                path="broken.jpg",
                mean_saturation=None,
                mean_value=None,
                edge_density=None,
                flat_color_coverage=None,
                bw_candidate=True,
            ),
            Source.LOCALWP_UPLOADS,
        ),
        (rec(path="ok.jpg", bw_candidate=True, mean_saturation=0.01), Source.LOCALWP_UPLOADS),
    ]
    shortlist = build_report(rows).offline[Domain.BLACK_AND_WHITE]
    assert [c.path for c in shortlist.candidates] == ["ok.jpg"]


def test_empty_inventory_yields_every_domain_with_an_empty_shortlist():
    report = build_report([])
    assert set(report.offline) == set(OFFLINE_DOMAINS)
    assert all(s.pool_size == 0 and s.candidates == [] for s in report.offline.values())
    assert report.operator_review.candidates == []


def test_every_offline_domain_is_present_even_when_unmatched():
    # A silently missing stratum reads as "covered" when it is not.
    report = build_report([(rec(), Source.LOCALWP_UPLOADS)])
    assert set(report.offline) == set(OFFLINE_DOMAINS)


# --- dedupe + exclusions -----------------------------------------------------


def test_duplicate_bytes_are_deduped_across_sources():
    dupe = rec(path="a.jpg", bw_candidate=True)
    same_bytes = rec(path="b.jpg", bw_candidate=True)
    object.__setattr__(same_bytes, "sha256", dupe.sha256)
    report = build_report([(dupe, Source.CELEBS01), (same_bytes, Source.LOCALWP_UPLOADS)])
    assert report.pool_size == 1


def test_exclude_sha256_drops_already_pinned_images():
    keep, drop = rec(path="keep.jpg", bw_candidate=True), rec(path="drop.jpg", bw_candidate=True)
    report = build_report(
        [(keep, Source.LOCALWP_UPLOADS), (drop, Source.LOCALWP_UPLOADS)],
        exclude_sha256=frozenset({drop.sha256}),
    )
    assert [c.path for c in report.offline[Domain.BLACK_AND_WHITE].candidates] == ["keep.jpg"]


# --- operator browse set -----------------------------------------------------


def test_operator_review_set_spans_directories_rather_than_one_folder():
    # A path-sorted head would return 3 images from 2025/09 and nothing else.
    rows = [(rec(path=f"2025/09/{i:03d}.jpg"), Source.LOCALWP_UPLOADS) for i in range(10)]
    rows += [(rec(path=f"2025/12/{i:03d}.jpg"), Source.LOCALWP_UPLOADS) for i in range(10)]
    candidates = build_report(rows, operator_sample=4).operator_review.candidates
    assert len({c.path.split("/")[1] for c in candidates}) == 2


def test_operator_review_is_marked_needs_operator_and_names_the_domains_it_serves():
    report = build_report([(rec(), Source.LOCALWP_UPLOADS)])
    assert report.operator_review.confidence is Confidence.NEEDS_OPERATOR
    assert set(report.operator_domains) == set(OPERATOR_DOMAINS)


def test_operator_review_draws_from_uploads_not_celeb_portraits():
    # Semantic strata (mirrors/art/products) are sourced from uploads by operator
    # directive; drawing from every root let celebs' 111 identity groups outvote
    # uploads' ~20 folders 196:4 -- a browse set that was 98% publicity portraits
    # for strata that contain no portraits.
    rows = [(rec(path=f"2025/09/{i}.jpg"), Source.LOCALWP_UPLOADS) for i in range(5)]
    rows += [(rec(path=f"celeb_{i}.jpg", celeb_name=f"Figure {i}"), Source.CELEBS01) for i in range(50)]
    report = build_report(rows, operator_sample=10)
    assert {c.source for c in report.operator_review.candidates} == {Source.LOCALWP_UPLOADS}
    assert report.operator_review.pool_size == 5, "pool_size counts only the sourced roots"


def test_operator_sources_is_overridable():
    rows = [(rec(path="celeb_1.jpg", celeb_name="Dali"), Source.CELEBS01)]
    report = build_report(rows, operator_sources=(Source.CELEBS01,))
    assert [c.path for c in report.operator_review.candidates] == ["celeb_1.jpg"]


def test_offline_and_operator_domains_partition_the_domain_enum_without_overlap():
    assert not set(OFFLINE_DOMAINS) & set(OPERATOR_DOMAINS)
    assert set(OFFLINE_DOMAINS) | set(OPERATOR_DOMAINS) == set(Domain)


def test_report_is_deterministic_across_runs():
    rows = [
        (rec(path=f"d{i}/{i}.jpg", bw_candidate=bool(i % 2), edge_density=i / 10), Source.LOCALWP_UPLOADS)
        for i in range(20)
    ]
    assert report_json(build_report(rows)) == report_json(build_report(rows))


# --- thin-stratum reporting --------------------------------------------------


def test_thin_stratum_is_flagged():
    rows = [(rec(path=f"{i}.jpg", bw_candidate=True), Source.LOCALWP_UPLOADS) for i in range(MIN_STRATUM_POOL - 1)]
    report = build_report(rows)
    assert report.offline[Domain.BLACK_AND_WHITE].thin is True
    assert Domain.BLACK_AND_WHITE in report.thin_domains()


def test_stratum_at_the_floor_is_not_thin():
    rows = [(rec(path=f"{i}.jpg", bw_candidate=True), Source.LOCALWP_UPLOADS) for i in range(MIN_STRATUM_POOL)]
    assert build_report(rows).offline[Domain.BLACK_AND_WHITE].thin is False


# --- CLI ---------------------------------------------------------------------


def test_load_inventory_tags_records_with_their_source(tmp_path):
    path = tmp_path / "inv.jsonl"
    write_records(path, [rec(path="a.jpg")])
    assert load_inventory(path, Source.CELEBS01) == [(rec(path="a.jpg"), Source.CELEBS01)]


def test_cli_writes_report_and_warns_on_thin_strata(tmp_path, capsys):
    inv = tmp_path / "inv.jsonl"
    write_records(inv, [rec(path=f"{i}.jpg", bw_candidate=True, celeb_name="Dali") for i in range(2)])
    out = tmp_path / "shortlists.json"
    assert _main(["--inventory", f"celebs01={inv}", "--out", str(out)]) == 0
    data = json.loads(out.read_text())
    assert data["offline"]["black_and_white"]["pool_size"] == 2
    assert data["offline"]["black_and_white"]["thin"] is True
    assert data["offline"]["black_and_white"]["candidates"][0]["celeb_name"] == "Dali"
    assert "WARNING" in capsys.readouterr().err


def test_cli_rejects_an_unknown_source(tmp_path):
    with pytest.raises(SystemExit):
        _main(["--inventory", "not_a_source=/tmp/x.jsonl", "--out", str(tmp_path / "o.json")])


def test_cli_rejects_a_malformed_inventory_arg(tmp_path):
    with pytest.raises(SystemExit):
        _main(["--inventory", "celebs01", "--out", str(tmp_path / "o.json")])
