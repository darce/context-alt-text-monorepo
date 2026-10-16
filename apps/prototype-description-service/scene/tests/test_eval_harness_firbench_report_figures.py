"""Figure adjudication using real scores/clusters wire shapes and synthetic data.

No metric implementation, schema replacement or private pixels. The files-only
integration uses the common typed binding factory with actual S3 face outcomes.
The optional coverage wire is consumed as frozen by MCP16885/16893; renderer
tests inspect coordinates as well as prose so invisible marks cannot pass.
"""

from __future__ import annotations

import copy
import json
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from scripts.eval_harness import firbench_contract as fc
from scripts.eval_harness import firbench_report as report

FIXTURES = Path(__file__).parent / "fixtures" / "firbench_interchange_v1"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}-v1.json").read_text())


def _svgs(text: str) -> list[ET.Element]:
    return [ET.fromstring(svg) for svg in re.findall(r"<svg\b.*?</svg>", text, re.S)]


def _marks(svg: ET.Element, tag: str, cls: str) -> list[ET.Element]:
    return [node for node in svg.iter(tag) if cls in node.get("class", "").split()]


def _xy(mark: ET.Element) -> list[tuple[float, float]]:
    return [tuple(map(float, pair.split(","))) for pair in mark.attrib["points"].split()]


def _scores() -> dict:
    scores = _load("scores")
    fc.validate_interchange("scores-v1", scores)
    return scores


@pytest.mark.parametrize("mated_n,nonmated_n", [(1, 6000), (6000, 5)])
def test_resolvability_uses_native_nonmated_count_not_mated_n(mated_n: int, nonmated_n: int) -> None:
    scores = _scores()
    scores["n_nonmated_eff"] = nonmated_n
    scores["legs"][0]["operating_point"]["fnir"]["data"]["n_eff"] = mated_n
    scores["legs"][0]["operating_point"]["fpir"]["data"]["n_nonmated_eff"] = nonmated_n
    fc.validate_interchange("scores-v1", scores)
    text = report._curves_svg(scores)
    svg = _svgs(text)[0]
    shade = _marks(svg, "rect", "unresolvable")[0]
    # x=130..724 encodes log FPIR 1e-4..1; 3/N is the boundary.
    expected = 130 + (math.log10(3 / nonmated_n) + 4) / 4 * 594
    assert float(shade.attrib["width"]) == pytest.approx(expected - 130, abs=0.01)
    assert f"Native nonmated n_eff = {nonmated_n}" in text
    assert "No FNIR inference in this region" in text


def test_root_nonmated_fallback_and_unknown_are_explicit() -> None:
    scores = _scores()
    for leg in scores["legs"]:
        leg["operating_point"]["fpir"] = {"status": "unavailable", "reason": "empty_nonmated_pool", "data": None}
    scores["n_nonmated_eff"] = 600
    fc.validate_interchange("scores-v1", scores)
    assert "3/n_nonmated_eff = 0.005" in report._curves_svg(scores)
    # Raw legacy/helper input with no support is unknown, never borrowed from FNIR.
    del scores["n_nonmated_eff"]
    text = report._curves_svg(scores)
    assert "Native nonmated effective count unknown" in text
    assert not _marks(_svgs(text)[0], "rect", "unresolvable")


def test_zero_nonmated_support_shades_full_positive_domain() -> None:
    scores = _scores()
    scores["n_nonmated_eff"] = 0
    for leg in scores["legs"]:
        leg["operating_point"]["fpir"] = {"status": "unavailable", "reason": "empty_nonmated_pool", "data": None}
    fc.validate_interchange("scores-v1", scores)
    for svg in _svgs(report._curves_svg(scores)):
        assert float(_marks(svg, "rect", "unresolvable")[0].attrib["width"]) == 594


def test_challenge_has_own_descriptive_panel_no_borrowed_support_and_exact_pointer() -> None:
    scores = _scores()
    challenge = copy.deepcopy(scores["curves"][0])
    challenge["leg_key"] += "::sampling=challenge"
    challenge["points"][0].update(fpir=0.05, fnir=0.9)
    scores["curves"].insert(0, challenge)
    fc.validate_interchange("scores-v1", scores)
    text = report._curves_svg(scores)
    svg = _svgs(text)[-1]
    assert "Challenge arm · descriptive only" in svg.attrib["aria-label"]
    assert not _marks(svg, "rect", "unresolvable")
    assert "Challenge nonmated effective count: unknown" in text
    assert "no probability-arm count is borrowed" in text
    table = report._tau_markers(scores)
    assert "challenge · descriptive only; effective count unknown" in table
    assert "scores.json#/curves/0/points/0" in table
    assert "scores.json#/curves/1/points/0" in table
    assert "scores.json#/curves/2/points/0" in table


def test_tau_is_visible_exact_and_zero_is_not_a_positive_log_measurement() -> None:
    scores = _scores()
    tau = scores["legs"][0]["tau"]["data"]["value"]
    scores["curves"][0]["points"] = [
        {"threshold": math.nextafter(tau, -math.inf), "fpir": 1, "fnir": 0},
        {"threshold": tau, "fpir": 0, "fnir": 0.5},
        {"threshold": math.nextafter(tau, math.inf), "fpir": 0.0001, "fnir": 1},
    ]
    fc.validate_interchange("scores-v1", scores)
    text = report._curves_svg(scores)
    svg = _svgs(text)[0]
    markers = _marks(svg, "polygon", "tau")
    assert len(markers) == 1
    points = {p.attrib["data-point"]: p for p in svg.iter("circle")}
    zero = points["1"]
    assert float(zero.attrib["cx"]) < float(points["2"].attrib["cx"])
    diamond = _xy(markers[0])
    assert sum(p[0] for p in diamond) / 4 == float(zero.attrib["cx"])
    assert sum(p[1] for p in diamond) / 4 == float(zero.attrib["cy"])
    assert diamond[0][1] != diamond[2][1]  # a real visible symbol, not a zero-size mark
    assert {float(p.attrib["data-fpir"]) for p in _marks(svg, "line", "ref")} == {0.001, 0.01, 0.05}
    # Both endpoint observations fit strictly inside the canvas, including FNIR=0/1.
    for p in svg.iter("circle"):
        assert 6 < float(p.attrib["cx"]) < 754
        assert 6 < float(p.attrib["cy"]) < 264
    # No polyline may bridge the zero/log discontinuity.
    assert all(x >= 130 for line in _marks(svg, "polyline", "series") for x, _ in _xy(line))
    assert "0 (separate)" in text


def test_adjacent_float_is_not_a_tau_match_and_missing_calibration_is_named() -> None:
    scores = _scores()
    tau = scores["legs"][0]["tau"]["data"]["value"]
    scores["curves"][0]["points"][0]["threshold"] = math.nextafter(tau, math.inf)
    fc.validate_interchange("scores-v1", scores)
    text = report._curves_svg(scores)
    assert not _marks(_svgs(text)[0], "polygon", "tau")
    assert "no exact recorded curve point" in text
    assert "no exact recorded curve point" in report._tau_markers(scores)
    scores["legs"][0]["tau"] = {"status": "unavailable", "reason": "empty_calibration_pool", "data": None}
    fc.validate_interchange("scores-v1", scores)
    assert "empty_calibration_pool" in report._curves_svg(scores)
    assert "empty_calibration_pool" in report._tau_markers(scores)


def test_tied_measurements_keep_all_points_and_each_leg_readable() -> None:
    scores = _scores()
    for curve in scores["curves"]:
        curve["points"][0].update(fpir=0.01, fnir=0.5)
        point = copy.deepcopy(curve["points"][0])
        point["threshold"] = math.nextafter(point["threshold"], math.inf)
        curve["points"].append(point)
    fc.validate_interchange("scores-v1", scores)
    text = report._curves_svg(scores)
    svgs = _svgs(text)
    assert len(svgs) == len(scores["legs"])
    for svg, leg in zip(svgs, scores["legs"], strict=True):
        assert leg["leg_key"] in svg.attrib["aria-label"]
        assert f"<strong>{leg['leg_key']}</strong>" in text
        assert len(list(svg.iter("circle"))) == 2
        assert len(_marks(svg, "polygon", "tau")) == 1


def test_positive_values_below_old_floor_keep_their_own_coordinates() -> None:
    scores = _scores()
    scores["curves"][0]["points"].extend(
        [
            {"threshold": 0.8, "fpir": 1e-7, "fnir": 0.9},
            {"threshold": 0.9, "fpir": 1e-4, "fnir": 1},
        ]
    )
    fc.validate_interchange("scores-v1", scores)
    dots = list(_svgs(report._curves_svg(scores))[0].iter("circle"))
    assert float(dots[0].attrib["cx"]) < float(dots[1].attrib["cx"]) < float(dots[2].attrib["cx"])


def test_exact_serialized_tau_above_one_is_kept_on_curve() -> None:
    scores = _scores()
    tau = math.nextafter(1.0, math.inf)
    scores["legs"][0]["tau"]["data"]["value"] = tau
    scores["curves"][0]["points"][0]["threshold"] = tau
    fc.validate_interchange("scores-v1", scores)
    svg = _svgs(report._curves_svg(scores))[0]
    assert _marks(svg, "polygon", "tau")[0].attrib["data-threshold"] == str(tau)
    assert str(tau) in report._tau_markers(scores)


def test_hierarchy_and_negative_acceptance_reference_share_truthful_distance_domain() -> None:
    clusters = _load("clusters")
    leg = clusters["legs"][0]
    tau = math.nextafter(1.0, math.inf)
    leg["acceptance_tau_reference"]["data"].update(tau=tau, distance=1 - tau)
    fc.validate_interchange("clusters-v1", clusters)
    text = report._dendrogram_svg(leg)
    svg = _svgs(text)[0]
    tau_line = _marks(svg, "line", "tau")[0]
    cut_line = _marks(svg, "line", "cut")[0]
    assert float(tau_line.attrib["data-d"]) < 0
    assert 0 < float(tau_line.attrib["x1"]) < float(cut_line.attrib["x1"]) < 760
    assert "separate acceptance reference, not hierarchy evidence" in text
    assert "original space" in text
    assert len(_marks(svg, "polyline", "tree")) == len(leg["dendrogram"]["data"]["linkage"])
    # The supplied hierarchy orders leaves 3,2,0,1; raw index order would cross branches.
    face_rows = {
        node.text: float(node.attrib["y"])
        for node in svg.iter("text")
        if node.text in leg["dendrogram"]["data"]["leaf_face_ids"]
    }
    assert [face for face, _ in sorted(face_rows.items(), key=lambda pair: pair[1])] == [
        "face-0004",
        "face-0003",
        "face-0001",
        "face-0002",
    ]


def test_null_cut_and_unavailable_hierarchy_keep_distinct_states() -> None:
    clusters = _load("clusters")
    leg = clusters["legs"][0]
    leg["config"].update(similarity_threshold=None, cluster_selection_epsilon=None)
    leg["dendrogram_cut"] = {"distance": None, "labels": None, "caption": "no production cut recorded"}
    fc.validate_interchange("clusters-v1", clusters)
    text = report._dendrogram_svg(leg)
    assert "no production cut recorded" in text
    assert not _marks(_svgs(text)[0], "line", "cut")
    assert len(_marks(_svgs(text)[0], "line", "tau")) == 1
    leg["dendrogram"] = {"status": "unavailable", "reason": "no_eligible_embedded_gt", "data": None}
    text = report._dendrogram_svg(leg)
    assert "no production cut recorded" in text and "no_eligible_embedded_gt" in text
    assert not _svgs(text)


def test_hierarchy_cut_table_uses_its_own_labels() -> None:
    clusters = _load("clusters")
    # Keep reference labels different to make reading the wrong list observable.
    for row in clusters["legs"][0]["dendrogram_cut"]["labels"]:
        row["label"] = 72
    fc.validate_interchange("clusters-v1", clusters)
    text = report._clusters_html(clusters)
    assert "Recorded hierarchy cut labels" in text and "<td>72</td>" in text
    assert "Recorded average linkage in cosine distance" in text
    assert "GRPH-18" not in report._dendrogram_svg(clusters["legs"][0])


def test_projection_versions_parameter_caption_correct_pointer_and_geometry() -> None:
    clusters = _load("clusters")
    leg = clusters["legs"][0]
    second = copy.deepcopy(leg["projections"][0])
    second["name"] = "projection-0002"
    second["parameters"]["min_dist"] = 0.25
    second["result"]["data"][0]["coordinates"] = [0, 0]
    second["result"]["data"][1]["coordinates"] = [1, 2]
    leg["projections"].append(second)
    fc.validate_interchange("clusters-v1", clusters)
    text = report._projection_html(2, leg)
    assert "umap-learn synthetic-1" in text and "min_dist 0.25" in text
    assert "clusters.json#/legs/2/projections/1" in text
    assert "distances not meaningful" in text and "original embedding space only" in text
    dots = list(_svgs(text)[1].iter("circle"))
    dx = float(dots[1].attrib["cx"]) - float(dots[0].attrib["cx"])
    dy = float(dots[0].attrib["cy"]) - float(dots[1].attrib["cy"])
    assert dy / dx == pytest.approx(2, abs=0.001)
    assert not _marks(_svgs(text)[1], "line", "axis")  # VIZ-35 has no bivariate-extrema task here.


def test_projection_degenerate_coordinates_center_and_unavailable_keeps_provenance() -> None:
    clusters = _load("clusters")
    leg = clusters["legs"][0]
    for point in leg["projections"][0]["result"]["data"]:
        point["coordinates"] = [7, 7]
    fc.validate_interchange("clusters-v1", clusters)
    for dot in _svgs(report._projection_html(0, leg))[0].iter("circle"):
        assert (dot.attrib["cx"], dot.attrib["cy"]) == ("320.00", "170.00")
    leg["projections"][0]["result"] = {"status": "unavailable", "reason": "too_few_vectors", "data": None}
    text = report._projection_html(0, leg)
    assert "too_few_vectors" in text and "umap-learn synthetic-1" in text
    assert not _svgs(text)


@pytest.mark.parametrize("missing", [0, 2, None])
def test_optional_vector_wire_counts_are_exact_and_null_stays_unknown(missing: int | None) -> None:
    clusters = _load("clusters")
    leg = clusters["legs"][0]
    leg["vector_coverage"] = {
        "label": "diagnostics conditional on available GT vectors",
        "conditional": True,
        "n_gt_faces": 4,
        "n_named_gt_faces": 4,
        "n_embedded_gt_faces": None if missing is None else 4 - missing,
        "n_missing_gt_faces": missing,
        "n_embedded_named_faces": None if missing is None else 4 - missing,
        "n_detector_only_rows": None if missing is None else 3,
    }
    text = report._figure_vector_coverage(0, leg)
    for field, value in leg["vector_coverage"].items():
        if field.startswith("n_"):
            assert f"clusters.json#/legs/0/vector_coverage/{field}" in text
            assert f"<td>{'unknown (null)' if value is None else value}</td>" in text
    assert "diagnostics conditional on available GT vectors" in report._clusters_html(clusters)
    assert "full GT/outcome denominators are unchanged" in text


def test_absent_vector_coverage_does_not_claim_full_cohort() -> None:
    clusters = _load("clusters")
    clusters["legs"][0].pop("vector_coverage", None)
    fc.validate_interchange("clusters-v1", clusters)
    text = report._clusters_html(clusters)
    assert "Vector coverage unknown: not recorded" in text
    assert "full-cohort coverage is not established" in text


def test_vector_count_labels_do_not_swap_units_or_infer_from_dots() -> None:
    leg = _load("clusters")["legs"][0]
    leg["vector_coverage"] = {
        "label": "diagnostics conditional on available GT vectors",
        "conditional": True,
        "n_gt_faces": 17,
        "n_named_gt_faces": 11,
        "n_embedded_gt_faces": 12,
        "n_missing_gt_faces": 5,
        "n_embedded_named_faces": 7,
        "n_detector_only_rows": 2,
    }
    text = report._figure_vector_coverage(3, leg)
    expected = {
        "GT faces (FRAME total)": 17,
        "Named GT faces (FRAME total)": 11,
        "Available embedded GT faces": 12,
        "Missing GT vectors": 5,
        "Available embedded named GT faces": 7,
        "Detector-only rows (excluded from GT)": 2,
    }
    for label, count in expected.items():
        assert f"<td>{label}</td><td>{count}</td>" in text
    # Four projection rows are not a full-cohort count or the coverage denominator.
    assert len(leg["projections"][0]["result"]["data"]) == 4
    assert "clusters.json#/legs/3/vector_coverage/n_detector_only_rows" in text


def test_files_only_render_preserves_scores_and_exposes_visible_marks(tmp_path: Path) -> None:
    from scene.tests.test_eval_harness_firbench_report import _make_run

    # Keep the chart specimens, but bind the new outcome wire to actual typed
    # FRAME/search rows and declared galleries before the files-only render.
    clusters = _load("clusters")
    for leg in clusters["legs"]:
        leg.pop("vector_coverage", None)  # This case exercises optional-wire absence.
    run = _make_run(tmp_path, scores=_scores(), clusters=clusters)
    scores = json.loads((run / "scores.json").read_text())
    assert scores["face_outcomes"]
    assert scores["curves"] == _scores()["curves"]
    before = {path.relative_to(run): path.read_bytes() for path in run.rglob("*") if path.is_file()}
    path = report.render_report(run, out_dir=run / "report")
    text = path.read_text()
    curves = re.search(r'<section[^>]*id="curves"[^>]*>(.*?)</section>', text, re.S)
    assert curves is not None
    svgs = _svgs(curves.group(1))
    assert len(svgs) == 2 and all(_marks(svg, "polygon", "tau") for svg in svgs)
    assert "Vector coverage unknown: not recorded" in text
    assert "legacy_face_outcomes_unavailable" not in text
    assert before == {name: (run / name).read_bytes() for name in before}


def test_supplied_optional_wire_fixture_against_its_actual_schema() -> None:
    # Companion is supplied in the remote review packet; pure-core checkouts
    # without it still run all the raw optional-wire rendering assertions above.
    root = Path("/home/gate/firbench-1-context/vector-coverage-wire/apps/prototype-description-service")
    if not root.is_dir():
        pytest.skip("source companion not present")
    schema = json.loads((root / "scripts/eval_harness/firbench_schemas/clusters-v1.json").read_text())
    payload = json.loads((root / "scene/tests/fixtures/firbench_interchange_v1/clusters-v1.json").read_text())
    fc._check(schema, payload, schema, "$")
    before = copy.deepcopy(payload)
    text = report._clusters_html(payload)
    assert "Recorded vector coverage" in text
    assert payload == before
