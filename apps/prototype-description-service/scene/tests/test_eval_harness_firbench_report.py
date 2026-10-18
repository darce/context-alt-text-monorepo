"""Fake-only S5 private static report regressions.

Search rows are typed ``FaceSearchRecord`` objects written by ``write_searches_jsonl``, so every
row is validated against the producer schema. ``face_outcomes`` rows come from the actual S3
IO producer, which calls core ``_outcome`` on those records. Chart values remain independent
software-only presentation specimens, never statistical evidence for this small view inventory.
Nothing here reads benchmarks/private, real images or real identities. Canon v0.26.2: VIZ-41
(selection pool first), VIZ-23 and INT-22 (state tied to its reason), WRIT-81 (limits stay in the
prose), MEAS-29 (no invented observation), EVAL-19 (detector alarms are not non-mated units).
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from scripts.eval_harness import firbench_contract as fc
from scripts.eval_harness import firbench_frames as ff
from scripts.eval_harness import firbench_score_io as score_io
from scripts.eval_harness.firbench_legs import FaceSearchRecord, write_searches_jsonl
from scripts.eval_harness.firbench_report import render_report

FIXTURES = Path(__file__).parent / "fixtures" / "firbench_interchange_v1"
RUN_ID = "run-0001"
SFACE = "sface__native__ab12cd__cv4.10.0__ort1.18.0"
AURA = "auraface__native__ef34ab__cv4.10.0__ort1.18.0"
FUSED = fc.LegId(fc.LegKind.insightface, fc.Arm.native, "cd56ef", "4.10.0", "1.18.0").key()
GLYPHS = ("✓", "✗", "○", "▼")
# The primary run scores one fixed test fold: fold_protocol.seed % k (2406466110 % 5, fir-bench-decision-v1).
TEST_FOLD = 2406466110 % 5


def _load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _legacy_scores() -> dict[str, Any]:
    """Display-only legacy wire: optional per-face classification genuinely absent.

    Positive classification cases below replace this absence with actual S3 output.
    These are software fixtures, never observations or evidence of real eligibility.
    """
    scores = _load("scores-v1.json")
    scores.pop("face_outcomes", None)
    return scores


def _psu(image_id: str) -> str:
    return image_id  # S1 canonical component ID for an independent singleton image.


def _gallery_sha(fold: int) -> str:
    return hashlib.sha256(f"gallery-fold-{fold}".encode()).hexdigest()


def _face(face_id: str, image_id: str, identity: str | None, status: str = "named") -> dict[str, Any]:
    return {
        "face_id": face_id,
        "image_id": image_id,
        "box": [1.0, 2.0, 30.0, 40.0],
        "identity_status": status,
        "identity_id": identity if status == "named" else None,
        "cohort": {"sex": None, "age_band": None, "origin": None},
        "annotation": {
            "occluders": None,
            "visibility": {"left_eye": None, "right_eye": None, "nose": None, "mouth": None},
            "annotation_tier": "b",
            "exhaustive": None,
            "provenance_ref": "software-fixture-only",
            "rule_id": None,
            "observation_ref": None,
            "qc_ref": None,
        },
    }


def _typed_frame(payload: Mapping[str, Any]) -> ff.Frame:
    """Decode the actual FRAME types; no scoring, eligibility or evidence substitute."""
    faces = []
    for source in payload["faces"]:
        row = copy.deepcopy(source)
        annotation = row.pop("annotation")
        annotation["visibility"] = ff.Visibility(**annotation["visibility"])
        row["annotation"] = ff.FaceAnnotation(**annotation)
        row["identity_status"] = fc.IdentityStatus(row["identity_status"])
        row["cohort"] = ff.Cohort(**row["cohort"]) if row["cohort"] is not None else None
        row["box"] = tuple(row["box"])
        faces.append(ff.GtFace(**row))
    return ff.Frame(
        fc.FrameSpec(
            payload["frame_id"],
            fc.Admissibility(payload["admissibility"]),
            payload["sealed"],
            payload["source_sha256"],
            payload["exhaustive"],
        ),
        tuple(ff.ImageUnit(**i) for i in payload["images"]),
        tuple(faces),
        {r["image_id"]: r["psu_id"] for r in payload["psu_map"]},
        {r["psu_id"]: r["fold"] for r in payload["folds"]},
        {r["identity_id"]: r["fold"] for r in payload["identity_folds"]},
        {r["fold"]: r["sha256"] for r in payload["gallery_sha256_by_fold"]},
        {r["fold"]: fc.FoldRole(r["role"]) for r in payload["fold_roles"]},
        payload["planning_icc"],
        payload["design_effect"],
        payload["n_eff"],
        payload["n_units"],
        payload["n_nonmated_eff"],
        payload["sampling_arm_counts"],
    )


def _frame(
    *,
    exhaustive: bool | None = True,
    faces: list[dict[str, Any]] | None = None,
    folds: Mapping[str, int] | None = None,
    challenge: frozenset[str] = frozenset(),
    nonmated: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Actual S1 FRAME serialization for a controlled software-only view specimen.

    The fold mapping is an explicit view input. Full protocol/fold/bootstrap
    integration is separately exercised through S3's genuine fake_run fixture.
    """
    faces = faces if faces is not None else [_face("face-0001", "image-0001", "id-0001")]
    images = tuple(
        ff.ImageUnit(
            image_id,
            hashlib.sha256(image_id.encode()).hexdigest(),
            fc.SamplingArm.challenge if image_id in challenge else fc.SamplingArm.probability,
            None if image_id in challenge else 0.5,
        )
        for image_id in sorted({f["image_id"] for f in faces})
    )
    payload = _load("frame-v1.json")
    payload["images"], payload["faces"] = [i.to_json() for i in images], faces
    typed_faces = _typed_frame(payload).faces
    psus = ff.build_psu_components(images, typed_faces)
    fold_map = {psus[i.image_id]: (folds or {}).get(i.image_id, TEST_FOLD) for i in images}
    identity_folds = {i: fold_map[p] for i, p in ff.identity_to_component(typed_faces, psus).items()}
    resolved = tuple(f for f in typed_faces if f.identity_status is not fc.IdentityStatus.unresolved)
    enrolled = frozenset(f.identity_id for f in typed_faces if f.identity_id and f.face_id not in nonmated)
    # Unknown exhaustiveness is a refusal/display fixture, never admissible N.
    pool = (
        ff.build_nonmated_pool(
            resolved,
            images,
            fold_map,
            fold=TEST_FOLD,
            component_map=psus,
            exhaustive=True,
            planning_icc=0.1,
            enrolled_identity_ids=enrolled,
        )
        if exhaustive is True
        else None
    )
    sizes = list(ff.psu_face_counts(psus, typed_faces).values())
    deff = ff.design_effect(sizes, 0.1) if sizes else 1.0
    frame = ff.Frame(
        fc.FrameSpec("fixture-v1", fc.Admissibility.development, False, None, exhaustive),
        images,
        typed_faces,
        psus,
        fold_map,
        identity_folds,
        {f: _gallery_sha(f) for f in set(fold_map.values())},
        {f: fc.FoldRole.test if f == TEST_FOLD else fc.FoldRole.fit for f in set(fold_map.values())},
        0.1,
        deff,
        len(typed_faces) / deff,
        pool.n_units if pool else 0,
        pool.n_nonmated_eff if pool else 0.0,
        {arm.value: sum(i.sampling_arm is arm for i in images) for arm in fc.SamplingArm},
    )
    return json.loads(ff.frame_json(frame))


def _manifest(frame, scores, *, nonmated=frozenset()):
    """Declare shared native galleries before binding searches or outcomes."""
    identities = {r["identity_id"]: r["fold"] for r in frame["identity_folds"]}
    enrolled = sorted(f["identity_id"] for f in frame["faces"] if f["identity_id"] and f["face_id"] not in nonmated)
    return {
        "firbench": {
            "created_at": "2026-10-15T08:00:00Z",
            "created_at_source": "explicit",
            "leg_keys": [r["leg_key"] for r in scores["legs"]],
            "arms": ["native"],
            "gallery_membership": [
                {
                    "leg_key": leg["leg_key"],
                    "fold": fold["fold"],
                    "gallery_sha256": fold["sha256"],
                    "enrolled_identity_ids": [i for i in enrolled if identities[i] == fold["fold"]],
                    "identity_folds": identities,
                }
                for leg in scores["legs"]
                for fold in frame["gallery_sha256_by_fold"]
            ],
        }
    }


def _search(
    face_id: str,
    image_id: str,
    stage: str,
    *,
    leg: str = SFACE,
    status: str = "named",
    fold: int = TEST_FOLD,
    enrolled: bool = True,
    challenge: bool = False,
    top_k: Sequence[tuple[str, float]] = (),
) -> FaceSearchRecord:
    """One FaceSearchRecord as S2 writes it. A GT face outside the gallery is non-mated, as is an unknown one."""
    mated = status == "named" and enrolled
    nonmated = status == "unknown" or (status == "named" and not enrolled)
    return FaceSearchRecord(
        face_id=face_id,
        image_id=image_id,
        psu_id=_psu(image_id),
        identity_id=f"id-{face_id[-4:]}" if mated else None,
        identity_status=fc.IdentityStatus(status),
        fold=fold,
        fold_role=fc.FoldRole.test if fold == TEST_FOLD else fc.FoldRole.fit,
        cell=("unknown", "unknown"),
        unit_id=face_id if nonmated else None,
        sampling_arm=fc.SamplingArm.challenge if challenge else fc.SamplingArm.probability,
        inclusion_probability=None if challenge else 0.5,
        cohort=None,
        leg_key=leg,
        arm=fc.Arm.native,
        arm_availability=fc.ArmStatus.available,
        alignment_mode=fc.AlignmentMode.separable,
        stage_reached=fc.SearchStage(stage),
        top_k=tuple(top_k),
        gallery_sha256=_gallery_sha(fold),
        timing_receipt_ref=f"{leg}/native/{face_id}",
    )


def _face_outcomes(scores, frame, searches, manifest=None):
    """Use the actual S3 row producer, including its named-null precedence.

    Controlled chart scores supply immutable native tau values; no row outcome
    dictionaries or classifier implementation are copied into these tests.
    """
    typed = _typed_frame(frame)
    inventory = score_io.Inventory(
        frame,
        typed.spec,
        {i.image_id: i for i in typed.images},
        {f.face_id: f for f in typed.faces},
        typed.psu_map,
        typed.folds,
        typed.identity_fold,
        TEST_FOLD,
        {},
    )
    registry = {
        (r["leg_key"], r["fold"]): r for r in (manifest or _manifest(frame, scores))["firbench"]["gallery_membership"]
    }
    contexts = {
        r["leg_key"]: {"tau": r["tau"]["data"]["value"] if r["tau"]["status"] == "available" else None}
        for r in scores["legs"]
    }
    return score_io._face_outcomes(
        [r for records in searches.values() for r in records],
        inventory,
        registry,
        contexts,
        fc.BoundarySemantics(scores["boundary_semantics"]),
    )


def _make_run(
    tmp_path: Path,
    *,
    scores: dict[str, Any] | None = None,
    clusters: dict[str, Any] | None = None,
    frame: dict[str, Any] | None = None,
    searches: Mapping[str, Sequence[FaceSearchRecord]] | None = None,
    manifest: dict[str, Any] | None = None,
    skip: frozenset[str] = frozenset(),
    legacy: bool = False,
    nonmated: frozenset[str] = frozenset(),
) -> Path:
    """Build ``benchmarks/private/firbench/runs/<run>`` under a fake repository root."""
    repo = tmp_path / "repo"
    run = repo / "benchmarks" / "private" / "firbench" / "runs" / RUN_ID
    run.mkdir(parents=True)
    scores = copy.deepcopy(scores if scores is not None else _legacy_scores())
    frame = frame if frame is not None else _frame()
    if not legacy and "frame" not in skip:
        manifest = manifest if manifest is not None else _manifest(frame, scores, nonmated=nonmated)
        if searches is None:
            typed = _typed_frame(frame)
            searches = {
                leg["leg_key"]: [
                    FaceSearchRecord(
                        face_id=f.face_id,
                        image_id=f.image_id,
                        psu_id=typed.psu_map[f.image_id],
                        identity_id=f.identity_id,
                        identity_status=f.identity_status,
                        fold=typed.folds[typed.psu_map[f.image_id]],
                        fold_role=typed.fold_roles[typed.folds[typed.psu_map[f.image_id]]],
                        cell=("unknown", "unknown"),
                        unit_id=f.face_id if f.identity_status is fc.IdentityStatus.unknown else None,
                        sampling_arm=next(i.sampling_arm for i in typed.images if i.image_id == f.image_id),
                        inclusion_probability=next(
                            i.inclusion_probability for i in typed.images if i.image_id == f.image_id
                        ),
                        cohort=None,
                        leg_key=leg["leg_key"],
                        arm=fc.Arm.native,
                        arm_availability=fc.ArmStatus.available,
                        alignment_mode=fc.AlignmentMode.fused_internal
                        if leg["leg_key"].startswith("insightface__")
                        else fc.AlignmentMode.separable,
                        stage_reached=fc.SearchStage.missed,
                        top_k=(),
                        gallery_sha256=typed.gallery_sha256_by_fold[typed.folds[typed.psu_map[f.image_id]]],
                        timing_receipt_ref=None,
                    )
                    for f in typed.faces
                ]
                for leg in scores["legs"]
            }
        scores["face_outcomes"] = _face_outcomes(scores, frame, searches, manifest)
        scores["n_units"] = frame["n_units"]
    else:
        scores.pop("face_outcomes", None)
    if "scores" not in skip:
        (run / "scores.json").write_text(json.dumps(scores, sort_keys=True), "utf-8")
    if "clusters" not in skip:
        (run / "clusters.json").write_text(json.dumps(clusters or _load("clusters-v1.json"), sort_keys=True), "utf-8")
    if "frame" not in skip:
        (run / "frame.json").write_text(ff.frame_json(_typed_frame(frame)), "utf-8")
    if manifest is not None:
        (run / "manifest.json").write_text(json.dumps(manifest, sort_keys=True), "utf-8")
    for leg, rows in (searches or {}).items():
        leg_dir = run / "legs" / leg
        leg_dir.mkdir(parents=True)
        write_searches_jsonl(leg_dir / "searches.jsonl", rows)
    return run


def _render(run: Path, tmp_path: Path, name: str = "out", *, include_crops: bool = False) -> Path:
    out = run / "report" if name == "out" else run / name
    render_report(run, out_dir=out, include_crops=include_crops)
    return out


def _html(run: Path, tmp_path: Path, **kwargs: Any) -> str:
    return (_render(run, tmp_path, **kwargs) / "index.html").read_text(encoding="utf-8")


def _section(html: str, section_id: str) -> str:
    match = re.search(rf'<section[^>]*id="{re.escape(section_id)}"[^>]*>(.*?)</section>', html, re.S)
    assert match is not None, f"missing section {section_id}"
    return match.group(1)


# --- network and navigation -------------------------------------------------------


def test_offline_inline_ui_has_no_external_network_and_escapes_data(tmp_path: Path) -> None:
    html = _html(_make_run(tmp_path, frame=_frame()), tmp_path)
    targets = re.findall(r"""\b(?:src|href)\s*=\s*["']([^"']*)["']""", html)
    assert targets, "expected the skip link and tab anchors"
    assert all(t.startswith("#") or t.startswith("data:") for t in targets), targets
    assert "<link" not in html and "@import" not in html
    scripts = re.findall(r"<script\b([^>]*)>(.*?)</script>", html, re.S)
    assert scripts and all(not re.search(r"\bsrc\s*=", attrs) for attrs, _ in scripts)
    assert any('type="application/json"' in attrs for attrs, _ in scripts)
    assert not re.search(r"\b(?:fetch|XMLHttpRequest|WebSocket|EventSource)\s*\(", html)
    payloads = [body for attrs, body in scripts if 'type="application/json"' in attrs]
    for payload in payloads:
        assert "<" not in payload and "\u2028" not in payload and "\u2029" not in payload
        json.loads(payload)
    view = next(body for attrs, body in scripts if 'id="report-view-data"' in attrs)
    assert isinstance(json.loads(view)["files"], dict)


def test_skip_link_is_first_focusable_and_targets_verdict(tmp_path: Path) -> None:
    html = _html(_make_run(tmp_path, frame=_frame()), tmp_path)
    focusables = re.findall(r"<(a|button|input|select|summary|details)\b([^>]*)>", html)
    assert focusables[0][0] == "a"
    assert 'class="skip"' in focusables[0][1] and 'href="#verdict"' in focusables[0][1]
    assert 'id="verdict"' in html
    assert not re.search(r'tabindex="[1-9]\d*"', html), "no positive tabindex"


def test_tab_anchors_follow_map_order_and_each_targets_a_section(tmp_path: Path) -> None:
    html = _html(_make_run(tmp_path, frame=_frame()), tmp_path)
    nav = re.search(r"<nav[^>]*>(.*?)</nav>", html, re.S)
    assert nav is not None
    hrefs = re.findall(r'href="#([^"]+)"', nav.group(1))
    assert hrefs == [
        "curves",
        "pair-cells",
        "stages",
        "failures",
        "clusters",
        "compare",
        "frames-power",
    ]
    for section_id in hrefs:
        assert f'id="{section_id}"' in html


# --- S1 verdict line --------------------------------------------------------------


def test_verdict_line_shows_admissibility_n_eff_and_interval_for_each_leg(tmp_path: Path) -> None:
    verdict = _section(_html(_make_run(tmp_path, frame=_frame()), tmp_path), "verdict")
    for leg in (SFACE, AURA):
        assert leg in verdict
    assert "development" in verdict
    assert "n_eff" in verdict and "5.000" in verdict
    assert "0.800" in verdict and "95%" in verdict


def test_inconclusive_fixture_renders_reason_verbatim_and_no_winner(tmp_path: Path) -> None:
    verdict = _section(_html(_make_run(tmp_path, frame=_frame()), tmp_path), "verdict")
    assert "INCONCLUSIVE" in verdict
    assert "insufficient_independent_psus" in verdict
    assert not re.search(r"\b(superior|non_inferior)\b", verdict)


def test_h1_inconclusive_renders_h2_as_not_evaluated(tmp_path: Path) -> None:
    scores = _legacy_scores()
    h2 = copy.deepcopy(scores["hypotheses"][0])
    h2.update(id="H2", kind="non_inferiority", step_index=2, state="superior", reason=None)
    scores["hypotheses"].append(h2)
    verdict = _section(_html(_make_run(tmp_path, scores=scores, frame=_frame()), tmp_path), "verdict")
    assert "H2" in verdict and "not evaluated" in verdict
    assert "✓" not in verdict


@pytest.mark.parametrize("reason", ["primary_fpir_unresolvable", "insufficient_independent_psus"])
def test_named_inconclusive_reasons_render_verbatim_without_winner(tmp_path: Path, reason: str) -> None:
    scores = _legacy_scores()
    scores["verdict"] = {"state": "inconclusive", "reason": reason}
    scores["hypotheses"][0]["reason"] = reason
    verdict = _section(_html(_make_run(tmp_path, scores=scores, frame=_frame()), tmp_path), "verdict")
    assert reason in verdict
    assert not re.search(r"\b(superior|non_inferior)\b", verdict)


def test_unratified_shows_numbers_and_no_verdict_text(tmp_path: Path) -> None:
    scores = _legacy_scores()
    scores["verdict"] = {"state": "unratified", "reason": None}
    scores["hypotheses"][0].update(state="unratified", reason=None)
    html = _html(_make_run(tmp_path, scores=scores, frame=_frame()), tmp_path)
    verdict = _section(html, "verdict")
    assert "unratified: no verdict" in verdict
    assert "✓" not in verdict and "▼" not in verdict


def test_numbers_link_to_their_json_path(tmp_path: Path) -> None:
    html = _html(_make_run(tmp_path, frame=_frame()), tmp_path)
    # A source pointer is an accessible button carrying data-source, not unbreakable inline code text.
    assert re.search(r'<button\b[^>]*\bdata-source="scores\.json#/legs/0/operating_point/fnir"', html)


# --- global floor and cell floor ---------------------------------------------------


def test_global_floor_fails_before_any_fpir_interval_is_shown(tmp_path: Path) -> None:
    scores = _legacy_scores()
    scores["n_psu"] = 49
    scores["min_n_independent"] = 50
    scores["legs"][0]["operating_point"]["fpir"]["data"]["iid_ucl"]["data"]["upper"] = 0.123456
    scores["legs"][0]["operating_point"]["fpir"]["data"]["clustered_ucl"]["data"]["upper"] = 0.234567
    html = _html(_make_run(tmp_path, scores=scores, frame=_frame()), tmp_path)
    assert "global floor 49 &lt; 50" in html or "global floor 49 < 50" in html
    assert "FPIR interval not shown" in html
    visible = re.sub(r"<script\b.*?</script>", "", html, flags=re.S)
    assert "0.123" not in visible and "0.234" not in visible
    # Immutable source evidence remains inspectable even when the interval is withheld.
    payload = re.search(r'<script[^>]*id="report-view-data"[^>]*>(.*?)</script>', html, re.S)
    source = json.loads(payload.group(1))["files"]["scores.json"]
    assert source["legs"][0]["operating_point"]["fpir"]["data"]["iid_ucl"]["data"]["upper"] == 0.123456


def test_cell_with_29_independent_units_reads_not_scored(tmp_path: Path) -> None:
    scores = _legacy_scores()
    cell = scores["cells"][0]
    cell.update(scored=True, fnir=0.25, n_psu=29, n_units=40, n_eff=12.0, data_origin="real")
    cell["interval"] = {"lower": 0.1, "upper": 0.4, "level": 0.95}
    html = _html(_make_run(tmp_path, scores=scores, frame=_frame()), tmp_path)
    grid = _section(html, "pair-cells")
    assert "not scored" in grid
    assert "0.250" not in grid


def test_empty_cell_reads_collect_not_error(tmp_path: Path) -> None:
    scores = _legacy_scores()
    scores["cells"][0].update(n_units=0, n_psu=0, n_identities=0, n_eff=0.0)
    grid = _section(_html(_make_run(tmp_path, scores=scores, frame=_frame()), tmp_path), "pair-cells")
    assert "no data → collect" in grid


# --- glyph and state rules ---------------------------------------------------------


def test_every_state_element_contains_a_glyph(tmp_path: Path) -> None:
    html = _html(_make_run(tmp_path, frame=_frame()), tmp_path)
    states = re.findall(r'<(?:span|td|li|div)[^>]*class="[^"]*\bst\b[^"]*"[^>]*>(.*?)</(?:span|td|li|div)>', html, re.S)
    assert states, "expected state-classed elements"
    for inner in states:
        assert any(g in inner for g in GLYPHS), inner


# --- S4 stages ---------------------------------------------------------------------


def test_fused_leg_waterfall_has_no_unaligned_row(tmp_path: Path) -> None:
    scores = _legacy_scores()
    fused = copy.deepcopy(scores["legs"][0])
    fused["leg_key"] = FUSED
    scores["legs"].append(fused)
    scores["waterfall"].append({"leg_key": FUSED, "arm": "native", "stage": "detected", "count": 2})
    scores["waterfall"].append({"leg_key": FUSED, "arm": "native", "stage": "embedded", "count": 1})
    stages = _section(_html(_make_run(tmp_path, scores=scores, frame=_frame()), tmp_path), "stages")
    fused_rows = [line for line in stages.splitlines() if FUSED in line]
    assert fused_rows and not any("unaligned" in line for line in fused_rows)


def test_unavailable_attribution_counts_sit_in_arm_availability_column(tmp_path: Path) -> None:
    stages = _section(_html(_make_run(tmp_path, frame=_frame()), tmp_path), "stages")
    assert "arm_availability" in stages
    # The fixture's unavailable attribution counts (10) appear in that column, not as a stage row.
    assert not re.search(r"<td[^>]*>\s*unavailable\s*</td>", stages)
    assert "10" in stages


# --- S5 failures and pool accounting -----------------------------------------------


def _pool_run(tmp_path: Path, *, exhaustive: bool | None, outcomes: bool = True) -> Path:
    faces = [
        _face("face-0001", "image-0001", "id-0001"),
        _face("face-0002", "image-0001", "id-0002"),
        _face("face-0003", "image-0002", "id-0003"),
        _face("face-0004", "image-0002", "id-0004", status="unresolved"),
    ]
    searches = {
        leg: [
            _search("face-0001", "image-0001", "missed", leg=leg),
            _search("face-0002", "image-0001", "detected", leg=leg),
            _search("face-0003", "image-0002", "embedded", leg=leg, top_k=[("id-0003", 0.9)]),
            _search("face-0004", "image-0002", "missed", leg=leg, status="unresolved"),
        ]
        for leg in (SFACE, AURA)
    }
    frame = _frame(exhaustive=exhaustive, faces=faces)
    scores = _legacy_scores()
    return _make_run(tmp_path, scores=scores, frame=frame, searches=searches, legacy=not outcomes)


def test_pool_accounting_reconciles_selection_with_pool(tmp_path: Path) -> None:
    run = _pool_run(tmp_path, exhaustive=True)
    _render(run, tmp_path)
    report = json.loads((run / "report" / "report.json").read_text(encoding="utf-8"))
    pool = report["failures"]["pool"]
    assert pool["overall_images"] == 2 and pool["overall_gt_faces"] == 4
    assert pool["unresolved_identity_faces"] == 1
    # Two failing faces share image-0001: distinct images are counted once.
    assert pool["selected_faces"] == pool["eligible_faces"] == 2
    assert pool["selected_images"] == 1
    assert pool["omitted_rows"] == pool["eligible_rows"] - pool["shown_rows"] == 0
    assert pool["crop_images_shown"] == 0
    # An unresolved GT row must not erase the independently established image pool.
    assert pool["status"] == "established"
    assert pool["fixed_background_source_units"] == 2
    assert pool["eligibility_restrictions"] == ["unresolved_identity; analytics withheld"]
    assert pool["reason"] == "; ".join(pool["eligibility_restrictions"])
    rows = report["failures"]["rows"]
    assert pool["inventory_rows"] == 8 and pool["inventory_faces"] == 4
    assert pool["eligible_rows"] == pool["selected_rows"] == pool["shown_rows"] == 4
    assert pool["outside_default_scope_rows"] == 4
    assert pool["inventory_rows"] == pool["eligible_rows"] + pool["outside_default_scope_rows"]
    assert {r["face_id"] for r in rows if r["default_visible"]} == {"face-0001", "face-0002"}
    unresolved = [r for r in rows if r["face_id"] == "face-0004"]
    assert len(unresolved) == 2
    assert all(r["mated"] is r["outcome"] is None for r in unresolved)
    assert all(not r["qualified"] and not r["outcome_available"] and not r["default_visible"] for r in unresolved)
    html = (run / "report/index.html").read_text()
    assert "Selection pool (VIZ-41): overall 2 images and 4 GT faces" in html
    assert "Analytic display withheld" not in html and "Analytic curves withheld" not in html


def test_missing_exhaustive_gt_reads_pool_not_established(tmp_path: Path) -> None:
    run = _pool_run(tmp_path, exhaustive=None)
    html = _html(run, tmp_path)
    failures = _section(html, "failures")
    assert "exhaustive GT unestablished" in failures and "withheld" in failures
    result = json.loads((run / "report/report.json").read_bytes())
    assert result["failures"]["pool"]["status"] == "not established"
    assert result["failures"]["pool"]["fixed_background_source_units"] is None
    # Never an admissible non-mated N: no number may follow the phrase.
    assert not re.search(r"non-mated N\D{0,40}\d", failures)


@pytest.mark.parametrize("exhaustive", [True, False, None])
@pytest.mark.parametrize("tier_a", [False, True])
def test_pool_inventory_and_eligibility_are_independent(tmp_path: Path, exhaustive, tier_a) -> None:
    faces = [
        _face("face-0001", "image-0001", "id-0001"),
        _face("face-0002", "image-0001", None, status="unknown"),
        _face("face-0003", "image-0002", None, status="unresolved"),
    ]
    if tier_a:
        # Reference strings are deliberately insufficient; no verifier is replaced.
        faces[0]["annotation"].update(annotation_tier="a", observation_ref="unverified.json", qc_ref="unverified")
    run = _make_run(tmp_path, frame=_frame(exhaustive=exhaustive, faces=faces))
    html = _html(run, tmp_path)
    result = json.loads((run / "report/report.json").read_bytes())
    rows, pool = result["failures"]["rows"], result["failures"]["pool"]
    assert pool["status"] == ("established" if exhaustive is True else "not established")
    assert pool["overall_images"] == pool["inventory_images"] == 2
    assert pool["overall_gt_faces"] == pool["inventory_faces"] == 3
    assert pool["named_faces"] == pool["unknown_faces"] == pool["unresolved_identity_faces"] == 1
    assert pool["inventory_rows"] == 6
    assert pool["fixed_background_source_units"] == (2 if exhaustive is True else None)
    assert pool["primary_background_source_units"] == (2 if exhaustive is True else None)
    # Explicitly unknown is a known nonmated identity state, unlike unresolved.
    unknown = [r for r in rows if r["identity_status"] == "unknown"]
    unresolved = [r for r in rows if r["identity_status"] == "unresolved"]
    assert len(unknown) == len(unresolved) == 2
    assert all(r["mated"] is False for r in unknown)
    assert all(r["mated"] is r["outcome"] is None and not r["qualified"] for r in unresolved)
    if exhaustive is True:
        assert all(r["qualified"] for r in unknown)
        assert "unresolved_identity; analytics withheld" in pool["eligibility_restrictions"]
        assert pool["eligible_faces"] == pool["selected_faces"] == (0 if tier_a else 1)
        assert pool["selected_images"] == (0 if tier_a else 1)
        named = [r for r in rows if r["identity_status"] == "named"]
        assert all(r["qualified"] is (not tier_a) for r in named)
        if tier_a:
            assert all(r["outcome"] is None and not r["outcome_available"] for r in named)
            assert any("S7" in reason for reason in pool["eligibility_restrictions"])
        assert ("Analytic display withheld" in html) is tier_a
        assert ("Analytic curves withheld" in html) is tier_a
    else:
        assert all(not r["qualified"] and not r["outcome_available"] for r in rows)
        assert pool["eligible_rows"] == pool["selected_rows"] == 0
        assert "exhaustive GT unestablished" in pool["reason"]
        assert "Analytic display withheld" in html and "Analytic curves withheld" in html
    assert pool["inventory_rows"] == pool["eligible_rows"] + pool["outside_default_scope_rows"]
    assert pool["eligible_rows"] == pool["shown_rows"] + pool["omitted_rows"]
    assert pool["omitted_rows"] == 0


def test_crop_counts_are_zero_and_no_data_uri_without_include_crops(tmp_path: Path) -> None:
    run = _pool_run(tmp_path, exhaustive=True)
    html = _html(run, tmp_path)
    assert "data:image" not in html
    report = json.loads((run / "report" / "report.json").read_text(encoding="utf-8"))
    assert report["failures"]["pool"]["crop_images_shown"] == 0


def test_failure_rows_use_only_pseudonymous_ids_and_stage_labels(tmp_path: Path) -> None:
    failures = _section(_html(_pool_run(tmp_path, exhaustive=True), tmp_path), "failures")
    assert "face-0001" in failures and "image-0001" in failures
    assert "missed" in failures
    assert "tier-(a) labels: none" in failures


def test_tier_a_labels_without_recorded_observation_block_analysis(tmp_path: Path) -> None:
    faces = [_face("face-0001", "image-0001", "id-0001")]
    faces[0]["annotation"]["annotation_tier"] = "a"
    faces[0]["annotation"]["observation_ref"] = None
    run = _make_run(tmp_path, frame=_frame(exhaustive=True, faces=faces))
    html = _html(run, tmp_path)
    failures = _section(html, "failures")
    assert "S7" in failures and "observation" in failures and "withheld" in failures
    rows = json.loads((run / "report/report.json").read_bytes())["failures"]["rows"]
    assert rows and all(not row["qualified"] and not row["default_visible"] for row in rows)
    assert "Analytic display withheld" in _section(html, "verdict")


def _classification_run(tmp_path: Path) -> Path:
    """Every outcome class in one exhaustive frame, plus fit-fold, challenge-arm and unresolved scope cases."""
    faces = [
        _face("face-0010", "image-0010", "id-0010"),
        _face("face-0011", "image-0011", "id-0011"),
        _face("face-0012", "image-0012", "id-0012"),
        _face("face-0013", "image-0013", None, status="unknown"),
        _face("face-0014", "image-0014", "id-0014"),
        _face("face-0015", "image-0015", "id-0015"),
        _face("face-0016", "image-0016", None, status="unresolved"),
    ]
    searches = {
        leg: [
            _search("face-0010", "image-0010", "embedded", leg=leg, top_k=[("id-0011", 0.9)]),
            _search("face-0011", "image-0011", "embedded", leg=leg, top_k=[("id-0011", 0.2)]),
            _search("face-0012", "image-0012", "embedded", leg=leg, enrolled=False, top_k=[("id-0010", 0.9)]),
            _search("face-0013", "image-0013", "embedded", leg=leg, status="unknown", top_k=[("id-0010", 0.1)]),
            _search("face-0014", "image-0014", "embedded", leg=leg, fold=TEST_FOLD + 1, top_k=[("id-0014", 0.9)]),
            _search("face-0015", "image-0015", "missed", leg=leg, challenge=True),
            _search("face-0016", "image-0016", "missed", leg=leg, status="unresolved"),
        ]
        for leg in (SFACE, AURA)
    }
    frame = _frame(
        exhaustive=True,
        faces=faces,
        folds={"image-0014": TEST_FOLD + 1},
        challenge=frozenset({"image-0015"}),
        nonmated=frozenset({"face-0012", "face-0013"}),
    )
    scores = _legacy_scores()
    return _make_run(
        tmp_path, scores=scores, frame=frame, searches=searches, nonmated=frozenset({"face-0012", "face-0013"})
    )


def test_face_outcomes_classify_core_outcomes_and_default_visible_scope(tmp_path: Path) -> None:
    run = _classification_run(tmp_path)
    _render(run, tmp_path)
    report = json.loads((run / "report" / "report.json").read_text(encoding="utf-8"))
    rows = {(row["face_id"], row["leg_key"]): row for row in report["failures"]["rows"]}
    expected = {
        "face-0010": ("wrong_identity", True),
        "face-0011": ("rejected", True),
        "face-0012": ("false_accept", True),
        "face-0013": ("correct_reject", False),
        "face-0014": (None, False),  # fit fold: never scored
        "face-0015": ("missed", False),  # challenge arm is not the primary scope
        "face-0016": (None, False),  # unresolved identity: named null
    }
    for leg in (SFACE, AURA):
        for face_id, (outcome, visible) in expected.items():
            row = rows[(face_id, leg)]
            assert row["outcome"] == outcome, (face_id, leg)
            assert row["outcome_available"] is (outcome is not None), (face_id, leg)
            assert row["default_visible"] is visible, (face_id, leg)
    fit = rows[("face-0014", SFACE)]
    assert fit["outcome_reason"] == "fit_fold_not_scored"
    assert rows[("face-0016", SFACE)]["outcome_reason"], "an unavailable outcome names its reason"
    assert report["failures"]["pool"]["selected_faces"] == 3


def test_pool_counts_are_order_invariant_and_do_not_multiply_source_units_per_leg(tmp_path: Path) -> None:
    from scripts.eval_harness.firbench_report import _pool

    run = _classification_run(tmp_path)
    _render(run, tmp_path)
    frame = json.loads((run / "frame.json").read_bytes())
    rows = json.loads((run / "report/report.json").read_bytes())["failures"]["rows"]
    original_frame, original_rows = copy.deepcopy(frame), copy.deepcopy(rows)
    pool = _pool(frame, rows, include_crops=False)
    permuted = dict(frame, faces=list(reversed(frame["faces"])), images=list(reversed(frame["images"])))
    assert _pool(permuted, list(reversed(rows)), include_crops=False) == pool
    assert pool["status"] == "established"
    assert pool["overall_images"] == pool["overall_gt_faces"] == pool["fixed_background_source_units"] == 7
    assert pool["primary_background_source_units"] == 5
    assert pool["inventory_rows"] == 14 and pool["eligible_rows"] == 6
    assert pool["selected_faces"] == pool["selected_images"] == 3
    for leg in (SFACE, AURA):
        subset = [r for r in rows if r["leg_key"] == leg]
        subpool = _pool(frame, subset, include_crops=False)
        for key in (
            "status", "overall_images", "overall_gt_faces", "fixed_background_source_units",
            "primary_background_source_units", "inventory_faces", "inventory_images", "eligible_faces",
            "eligible_images", "selected_faces", "selected_images", "eligibility_restrictions",
        ):
            assert subpool[key] == pool[key], key
        assert subpool["inventory_rows"] * 2 == pool["inventory_rows"]
        assert subpool["eligible_rows"] * 2 == pool["eligible_rows"]
        assert subpool["outside_default_scope_rows"] * 2 == pool["outside_default_scope_rows"]
        assert subpool["scope_counts_by_leg"] == {leg: pool["scope_counts_by_leg"][leg]}
        assert subpool["nonmated_gt_source_units_by_leg"] == {leg: 2}
        assert subpool["eligible_rows"] == subpool["shown_rows"] + subpool["omitted_rows"]
        assert subpool["omitted_rows"] == 0 and subpool["limit"] is None
    for key in (
        "overall_images", "overall_gt_faces", "inventory_rows", "inventory_faces", "inventory_images",
        "eligible_rows", "eligible_faces", "eligible_images", "selected_rows", "selected_faces",
        "selected_images", "omitted_rows", "outside_default_scope_rows", "fixed_background_source_units",
    ):
        assert type(pool[key]) is int, key
    assert frame == original_frame and rows == original_rows


def test_legacy_scores_without_face_outcomes_read_classification_unavailable(tmp_path: Path) -> None:
    run = _pool_run(tmp_path, exhaustive=True, outcomes=False)
    failures = _section(_html(run, tmp_path), "failures")
    assert "classification unavailable" in failures
    assert "no all-clear claim can be made" in failures
    rows = json.loads((run / "report/report.json").read_bytes())["failures"]["rows"]
    assert all(row["outcome"] is None and row["outcome_reason"] == "legacy_face_outcomes_unavailable" for row in rows)


# --- S7 clusters ------------------------------------------------------------------


def _chaining(clusters: dict[str, Any], leg_index: int = 0) -> dict[str, Any]:
    return clusters["legs"][leg_index]["chaining"]["data"]


def test_chaining_zero_eligible_pairs_reads_not_evaluated_not_zero_risk(tmp_path: Path) -> None:
    clusters = _load("clusters-v1.json")
    data = _chaining(clusters)
    data.update(eligible_pairs=0, path_linked_pairs=0, third_identity_linked_pairs=0, pairs=[])
    data["D"] = {"status": "unavailable", "reason": "no eligible pairs", "data": None}
    data["C"] = {"status": "unavailable", "reason": "no eligible pairs", "data": None}
    text = _section(_html(_make_run(tmp_path, clusters=clusters, frame=_frame()), tmp_path), "clusters")
    assert "not evaluated: no eligible held-out different-identity pairs" in text


def test_chaining_missing_evidence_reads_unavailable(tmp_path: Path) -> None:
    clusters = _load("clusters-v1.json")
    clusters["legs"][0]["chaining"] = {"status": "unavailable", "reason": "no chaining run", "data": None}
    text = _section(_html(_make_run(tmp_path, clusters=clusters, frame=_frame()), tmp_path), "clusters")
    assert "not evaluated: chaining evidence unavailable" in text


def test_chaining_malformed_evidence_is_an_error(tmp_path: Path) -> None:
    clusters = _load("clusters-v1.json")
    _chaining(clusters).update(eligible_pairs=1, path_linked_pairs=3, third_identity_linked_pairs=0)
    with pytest.raises(fc.FrameContractError):
        _html(_make_run(tmp_path, clusters=clusters, frame=_frame()), tmp_path)


def test_dendrogram_without_production_cut_states_it_and_draws_tau_at_one_minus_tau(tmp_path: Path) -> None:
    clusters = _load("clusters-v1.json")
    clusters["legs"][0]["config"].update(similarity_threshold=None, cluster_selection_epsilon=None)
    clusters["legs"][0]["dendrogram_cut"] = {"distance": None, "caption": "no production cut recorded", "labels": None}
    clusters["legs"][0]["labels"] = {"status": "unavailable", "reason": "no production cut", "data": None}
    text = _section(_html(_make_run(tmp_path, clusters=clusters, frame=_frame()), tmp_path), "clusters")
    assert "no production cut recorded" in text
    assert "acceptance τ (not a cluster cut)" in text
    assert 'data-d="0.59"' in text


# --- S8 frames and power ----------------------------------------------------------


def test_frame_absent_reads_not_acquired_and_floors_stay_separate(tmp_path: Path) -> None:
    text = _section(_html(_make_run(tmp_path, skip=frozenset({"frame"})), tmp_path), "frames-power")
    assert "not acquired" in text
    assert "min_n_independent" in text and "cell_floor_n_independent" in text
    assert "p_d" in text and "0.15" in text


def test_sensitivity_rows_show_all_three_planning_iccs(tmp_path: Path) -> None:
    text = _section(_html(_make_run(tmp_path, frame=_frame()), tmp_path), "frames-power")
    for icc in ("0.050", "0.100", "0.200"):
        assert icc in text


def test_missing_semantic_timestamp_on_manifest_is_refused(tmp_path: Path) -> None:
    manifest = {"firbench": {"created_at": "not-a-timestamp", "created_at_source": "seal.sealed_at"}}
    run = _make_run(tmp_path, frame=_frame(), manifest=manifest, legacy=True)
    with pytest.raises(fc.FrameContractError):
        _render(run, tmp_path)


def test_display_only_record_without_manifest_reads_date_not_recorded(tmp_path: Path) -> None:
    text = _section(_html(_make_run(tmp_path, frame=_frame(), legacy=True), tmp_path), "frames-power")
    assert "date not recorded" in text


# --- privacy and determinism -------------------------------------------------------


def test_writing_to_benchmarks_reports_is_refused(tmp_path: Path) -> None:
    run = _make_run(tmp_path, frame=_frame())
    repo = tmp_path / "repo"
    with pytest.raises(fc.NonPrivateOutputError):
        render_report(run, out_dir=repo / "benchmarks" / "reports" / "x", include_crops=False)


def test_same_run_renders_byte_identically_twice(tmp_path: Path) -> None:
    run = _pool_run(tmp_path, exhaustive=True)
    first = _render(run, tmp_path, name="first")
    second = _render(run, tmp_path, name="second")
    names = sorted(p.name for p in first.iterdir())
    assert names == sorted(p.name for p in second.iterdir())
    assert "index.html" in names and "report.json" in names
    assert any(name.endswith(".csv") for name in names)
    for name in names:
        assert (first / name).read_bytes() == (second / name).read_bytes(), name


def test_end_to_end_fake_run_writes_every_artifact_and_no_pixels(tmp_path: Path) -> None:
    """Clean-environment integration: fakes only, one run, every artifact checked."""
    run = _pool_run(tmp_path, exhaustive=True)
    index = render_report(run, out_dir=run / "report", include_crops=False)
    assert index == run / "report" / "index.html"
    report = json.loads((run / "report" / "report.json").read_text(encoding="utf-8"))
    assert report["verdict"]["state"] == "inconclusive"
    assert report["inputs"]["scores.json"] and report["inputs"]["frame.json"]
    names = {p.name for p in (run / "report").iterdir()}
    assert {"index.html", "report.json", "legs.csv", "failures.csv", "cells.csv"} <= names
    html = index.read_text(encoding="utf-8")
    assert "data:image" not in html and "INCONCLUSIVE" in html
