"""FIRBENCH-1 report language: plain-English labels, the in-page glossary and linked definitions.

Renders the public synthetic fixture through the real ``render_report``. The legacy path is
used exactly as in the H2-REP suite: ``face_outcomes`` is removed from the copied scores, and
no producer is mocked. This module never imports the glossary module, so a RED run fails on
the missing report text rather than on setup.
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

import pytest

from scripts.eval_harness import firbench_report as report
from scripts.eval_harness.firbench_report import render_report

FIXTURES = Path(__file__).parent / "fixtures" / "firbench_interchange_v1"
RUN_ID = "run-0001"
EXISTING_SECTIONS = ("verdict", "curves", "pair-cells", "stages", "failures", "clusters", "compare", "frames-power")

TERM_ENTRIES = [
    ("glossary-fnir", "FNIR (false negative identification rate)"),
    ("glossary-fpir", "FPIR (false positive identification rate)"),
    ("glossary-threshold", "Acceptance threshold τ"),
    ("glossary-clustering-cut", "Clustering cut"),
    ("glossary-psu", "PSU (primary sampling unit)"),
    ("glossary-neff", "Effective count (n_eff)"),
    ("glossary-mde", "MDE (minimum detectable effect)"),
    ("glossary-ratified", "Ratified"),
    ("glossary-sealed", "Sealed"),
    ("glossary-admissibility", "Frame admissibility: diagnostic, development, confirmatory"),
    ("glossary-occlusion-cell", "Occlusion cell"),
    ("glossary-native", "Native arm"),
    ("glossary-gt-crop-redetect", "GT-crop redetect arm"),
    ("glossary-cached-landmark-replay", "Cached landmark replay arm"),
    ("glossary-hypothesis", "Hypothesis (H1, H2)"),
    ("glossary-guardrail", "Guardrail"),
    ("glossary-kind-per-cohort-fpir", "False-match rate by demographic group (per_cohort_fpir)"),
    ("glossary-kind-p95", "95th-percentile time per face (p95_ms_per_face)"),
]


def _public_run(root: Path) -> Path:
    run = root / "repo" / "benchmarks" / "private" / "firbench" / "runs" / RUN_ID
    run.mkdir(parents=True)
    scores = json.loads((FIXTURES / "scores-v1.json").read_text(encoding="utf-8"))
    scores.pop("face_outcomes", None)
    (run / "scores.json").write_text(json.dumps(scores, sort_keys=True), encoding="utf-8")
    (run / "clusters.json").write_bytes((FIXTURES / "clusters-v1.json").read_bytes())
    return run


@pytest.fixture(scope="module")
def page_html(tmp_path_factory: pytest.TempPathFactory) -> str:
    run = _public_run(tmp_path_factory.mktemp("public"))
    index = render_report(run, out_dir=run / "report", include_crops=False)
    assert index.name == "index.html"
    return index.read_text(encoding="utf-8")


def test_existing_section_anchors_and_inspector_stay_stable(page_html: str) -> None:
    for section_id in EXISTING_SECTIONS:
        assert f'id="{section_id}"' in page_html, f"existing section anchor lost: {section_id}"
    assert 'id="source-inspector"' in page_html
    assert 'class="source"' in page_html


def test_glossary_section_exists_with_return_link_and_no_fake_controls(page_html: str) -> None:
    assert 'id="glossary"' in page_html, 'glossary section missing: expected id="glossary"'
    glossary = page_html.split('id="glossary"', 1)[1].split("</section>", 1)[0]
    assert 'href="#verdict"' in glossary, "glossary needs a real return link to the verdict"
    assert "<button" not in glossary, "glossary must not contain fake buttons"


def test_contextual_glossary_links_are_native_anchors_that_resolve(page_html: str) -> None:
    anchors = set(re.findall(r'href="#(glossary-[a-z0-9-]+)"', page_html))
    assert anchors, "no contextual glossary links in the report"
    unresolved = sorted(anchor for anchor in anchors if f'id="{anchor}"' not in page_html)
    assert not unresolved, f"glossary links without a definition: {unresolved}"


@pytest.mark.parametrize(("anchor", "term"), TERM_ENTRIES)
def test_required_terms_have_linked_plain_english_definitions(page_html: str, anchor: str, term: str) -> None:
    pattern = rf'<dt id="{anchor}"[^>]*>{re.escape(term)}</dt>\s*<dd>'
    assert re.search(pattern, page_html), f"glossary term missing: {anchor} ({term})"


def test_fnir_definition_and_contextual_link_are_plain_english(page_html: str) -> None:
    assert 'href="#glossary-fnir"' in page_html, "contextual FNIR link missing"
    definition = _definition(page_html, "fnir")
    assert "enrolled" in definition and "miss" in definition
    assert "undetected" in definition or "detector misses" in definition


def test_threshold_definition_is_plain_english(page_html: str) -> None:
    definition = _definition(page_html, "threshold")
    assert "similarity" in definition and "accept" in definition


def test_hypothesis_column_is_named_by_question_not_bare_id(page_html: str) -> None:
    assert '<th scope="col">Hypothesis</th>' in page_html, "hypothesis column must be headed Hypothesis, not H"
    assert '<th scope="col">H</th>' not in page_html
    text = html.unescape(page_html).lower()
    assert "lower bound" in text and "margin" in text
    assert "comparison question unavailable" in text
    assert "h1 passes" in text, "later hypotheses require H1 PASS"


def test_guardrail_kinds_have_plain_names_and_keep_technical_keys(page_html: str) -> None:
    text = html.unescape(page_html)
    assert "False-match rate by demographic group" in text, "per-cohort guardrail needs its plain name"
    assert "95th-percentile time per face" in text, "p95 guardrail needs its plain name"
    assert "per_cohort_fpir" in page_html and "p95_ms_per_face" in page_html, "technical guardrail keys must stay"


def test_p95_definition_describes_allocated_cost_not_a_stopwatch(page_html: str) -> None:
    definition = _definition(page_html, "kind-p95")
    for concept in ("whole", "native", "gt face", "no gt faces", "95th", "stopwatch"):
        assert concept in definition, f"missing amortized p95 concept: {concept}"


def test_model_names_are_plain_and_implementation_ids_stay_inspectable(page_html: str) -> None:
    assert "<strong>SFace</strong>" in page_html, "leg table must name the model SFace in plain text"
    assert "<strong>AuraFace</strong>" in page_html, "leg table must name the model AuraFace in plain text"
    assert "sface__native__ab12cd__cv4.10.0__ort1.18.0" in page_html, "implementation model ID must stay inspectable"


def test_synthetic_origin_describes_cells_without_promoting_whole_run_to_fixture(page_html: str) -> None:
    cells = page_html.split('id="pair-cells"', 1)[1].split("</section>", 1)[0]
    text = html.unescape(re.sub("<[^>]+>", " ", cells)).lower()
    assert "synthetic" in text and "cell origin" in text
    assert "whole run" in text and "fixture" in text
    assert "its figures check the report layout and are not evidence" not in text
    assert "explicit fixture metadata marks" not in text


def test_glossary_also_renders_in_an_empty_state() -> None:
    sections = [(section_id, "<p>No rows in this state.</p>") for section_id, _ in report._SECTIONS]
    page = report._page("empty state", sections, "<p>No verdict rows.</p>")
    assert 'id="glossary"' in page, "glossary must also render in the empty state"


def _definition(page: str, term: str) -> str:
    match = re.search(rf'<dt id="glossary-{term}"[^>]*>.*?</dt>\s*<dd>(.*?)</dd>', page, re.S)
    assert match, f"definition missing: {term}"
    return html.unescape(re.sub("<[^>]+>", " ", match[1])).lower()


def test_fpir_denominator_is_independent_nonmated_sources_not_legacy_precision(page_html: str) -> None:
    definition = _definition(page_html, "fpir")
    for concept in ("independent", "nonmated", "source", "precision", "recall"):
        assert concept in definition


def test_unrecorded_policy_values_stay_unavailable(page_html: str) -> None:
    hypotheses = page_html.split('id="verdict"', 1)[1].split("</section>", 1)[0]
    text = html.unescape(re.sub("<[^>]+>", " ", hypotheses)).lower()
    assert "margin unavailable" in text
    assert "direction unavailable" in text
    assert "comparison legs unavailable" in text


def test_degraded_report_keeps_glossary_and_explicit_unknowns(tmp_path: Path) -> None:
    run = _public_run(tmp_path)
    (run / "clusters.json").unlink()
    page = render_report(run, out_dir=run / "report", include_crops=False).read_text(encoding="utf-8")
    assert 'id="glossary"' in page
    clusters = page.split('id="clusters"', 1)[1].split("</section>", 1)[0]
    assert "clusters.json" in clusters and "not evaluated" in clusters
    assert 'href="#glossary-hypothesis"' in page
