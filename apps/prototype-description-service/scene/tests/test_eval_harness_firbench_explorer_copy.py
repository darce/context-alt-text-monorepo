"""Public synthetic copy regressions for the explorer's H2 gate and code-reader wire keys.

The fixture is the public synthetic projection used by the wire tests. It goes through the
actual producer, the actual v1 writer, and the actual explorer renderer. Assertions read the
produced HTML and the written export, not private constants.
"""

from __future__ import annotations

import json
import re
from html import unescape
from pathlib import Path

from scene.tests.test_eval_harness_firbench_explorer_wire import _projected_wire
from scripts.eval_harness import firbench_comparison_export as producer
from scripts.eval_harness.firbench_explorer import render_explorer


H1_DEFINITION = (
    "The first hypothesis: whether the model change is real at the primary operating point "
    "(FNIR at FPIR 0.01, end to end). It is not evaluated on this page."
)
H2_DEFINITION = (
    "The second hypothesis, a non-inferiority check between AuraFace and InsightFace with a margin of 0.05. "
    "It runs only after H1 passes. It is not evaluated on this page."
)
CODE_READER_KEYS = [
    "Images scored: counts.scored of counts.total",
    "Faces matched: counts.matched_faces (detection.tp)",
    "Faces missed and extra detections: detection.fn and detection.fp",
    "Detection precision and recall: detection.precision and detection.recall",
    "Named and stranger faces: counts.named_matched and counts.stranger_matched",
    "Strangers rejected: unknown_rejection.correct_rejects, n, rate",
    "Merge and split: clustering.false_merge (over m_co_clustered) and clustering.false_split (over p_same)",
    "Grouping setting: clustering.parameters.d_cut, clustering.algorithm, clustering.metric",
]


def _render(tmp_path: Path) -> tuple[str, dict]:
    data = producer.write_export(_projected_wire(), tmp_path / "comparison.json")
    export = json.loads(data.read_text(encoding="utf-8"))
    index = render_explorer(data, tmp_path / "explorer")
    return index.read_text(encoding="utf-8"), export


def _term_definition(page: str, term_id: str) -> str:
    match = re.search(rf'<article class="term" id="term-{term_id}"[^>]*><h3>[^<]*</h3><p>([^<]*)</p>', page)
    assert match is not None, term_id
    return unescape(match.group(1))


def _code_reader_keys(page: str) -> list[str]:
    match = re.search(r"<summary>Source keys for code readers</summary><ul>(.*?)</ul>", page)
    assert match is not None
    return [unescape(item) for item in re.findall(r"<li>(.*?)</li>", match.group(1))]


def test_h2_definition_runs_after_h1_passes_and_is_not_evaluated_here(tmp_path: Path) -> None:
    page, _ = _render(tmp_path)
    assert _term_definition(page, "h2") == H2_DEFINITION


def test_code_reader_keys_name_the_actual_nested_wire_path(tmp_path: Path) -> None:
    page, export = _render(tmp_path)
    clustering = export["reports"][0]["clustering"]
    assert clustering["parameters"] == {"d_cut": 0.6}
    assert "d_cut" not in clustering
    assert _code_reader_keys(page) == CODE_READER_KEYS
    assert "clustering.d_cut" not in page


def test_unchanged_h1_h2_links_and_recorded_numeric_still_render(tmp_path: Path) -> None:
    page, _ = _render(tmp_path)
    assert _term_definition(page, "h1") == H1_DEFINITION
    assert 'id="term-h2"' in page
    assert 'href="#term-h2"' in page
    assert "H1 (initial hypothesis) and H2 (second, only after H1 passes) are not evaluated here." in page
    assert "0.600" in page
