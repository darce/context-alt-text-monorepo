"""G3: persisted bundle lineage must pass the producer contract before P/R.

PROV-01 — Every output walks back to its evidence (Model Cards + AI
Engineering). TEST-15 — Prove the green can go red (The Pragmatic
Programmer, ch. 9). These regressions intentionally fail on source 73db482d.
"""

from __future__ import annotations

import json
from html.parser import HTMLParser
from pathlib import Path

import pytest

from scripts.bench.preflight import PreflightError, _parse_model_bundle_provenance
from scripts.bench.score_report import score_head_to_head
from scripts.bench.stack_pair import BenchError
from scripts.bench.tests.conftest import golden_entry
from scripts.bench.tests.test_score_head_to_head import (
    A_STACK,
    B_STACK,
    _box,
    _init,
    _pred,
    _write_leg,
)

STACKS = (A_STACK, B_STACK)
BUNDLES = {
    A_STACK: {"model_name": "buffalo_l", "bundle_files": 5, "bundle_sha256": "a" * 64},
    B_STACK: {"model_name": "sface", "bundle_files": 1, "bundle_sha256": "b" * 64},
}
INVALID_BUNDLES = [
    pytest.param("bundle_sha256", None, id="missing-digest"),
    pytest.param("bundle_sha256", "", id="empty-digest"),
    pytest.param("bundle_sha256", "a" * 63, id="short-digest"),
    pytest.param("bundle_sha256", "g" * 64, id="nonhex-digest"),
    pytest.param("bundle_sha256", "A" * 64, id="uppercase-digest"),
    pytest.param("bundle_sha256", 123, id="nonstring-digest"),
    pytest.param("model_name", None, id="missing-name"),
    pytest.param("model_name", "  ", id="blank-name"),
    pytest.param("bundle_files", None, id="missing-count"),
    pytest.param("bundle_files", 0, id="zero-count"),
    pytest.param("bundle_files", -1, id="negative-count"),
    pytest.param("bundle_files", True, id="boolean-count"),
    pytest.param("bundle_files", 1.0, id="float-count"),
    pytest.param("bundle_files", ["a.onnx"], id="list-count"),
]


def _preflight_path(run_dir: Path, stack_id: str) -> Path:
    return run_dir / "legs" / stack_id / "preflight.json"


@pytest.fixture
def lineage_run(tmp_path: Path) -> Path:
    media_ids = [1, 2]
    entries = [
        golden_entry(mid, face_count=1, face_boxes=[_box()]) for mid in media_ids
    ]
    run_dir = _init(tmp_path, media_ids, entries)
    for stack_id in STACKS:
        _write_leg(run_dir, stack_id, [_pred(mid) for mid in media_ids], media_ids)
        path = _preflight_path(run_dir, stack_id)
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["health_detailed_excerpt"]["model_cache"].update(BUNDLES[stack_id])
        _parse_model_bundle_provenance(doc["health_detailed_excerpt"])
        path.write_text(json.dumps(doc), encoding="utf-8")
    return run_dir


_REFUSAL_TITLE = "Scoring refused"
# Rejection codes the invalid-bundle and provenance-drift refusals may surface.
_REFUSAL_CODES = frozenset({"preflight_invalid", "model_bundle_unreported"})
_METRIC_TAGS = frozenset({"table", "tr", "td", "th"})


class _RefusalPage(HTMLParser):
    """Collects the structure the approved refusal page is judged on."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: set[str] = set()
        self.text: dict[str, list[str]] = {"title": [], "h1": [], "p": []}
        self._open: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.add(tag)
        if tag in self.text:
            self._open = tag
            self.text[tag].append("")

    def handle_endtag(self, tag: str) -> None:
        if tag == self._open:
            self._open = None

    def handle_data(self, data: str) -> None:
        if self._open is not None:
            self.text[self._open][-1] += data


def _assert_no_metrics(run_dir: Path) -> None:
    """Accept only the approved explicit refusal; reject any metric surface.

    File existence is not evidence. Both publications must be readable. The HTML must
    carry the refusal title and heading and one rejection line whose code matches
    frames.json, followed by a nonempty reason. It must contain no metric table markup,
    and the frames must report no emitted cells.
    """
    frames_path = run_dir / "score" / "frames.json"
    html_path = run_dir / "score" / "report.html"
    assert frames_path.is_file(), "refusal frames.json is missing"
    assert html_path.is_file(), "refusal report.html is missing"

    frames = json.loads(frames_path.read_text(encoding="utf-8"))
    assert frames.get("pr_cells_emitted") is False
    assert frames.get("cells") == []
    code = frames.get("error_code")
    assert code in _REFUSAL_CODES, f"unexpected refusal code {code!r}"

    page = _RefusalPage()
    page.feed(html_path.read_text(encoding="utf-8"))
    page.close()
    assert not (_METRIC_TAGS & page.tags), "refusal page carries metric table markup"
    assert [t.strip() for t in page.text["title"]] == [_REFUSAL_TITLE]
    assert [h.strip() for h in page.text["h1"]] == [_REFUSAL_TITLE]
    # Exactly the license banner and the rejection line; any other paragraph is a leak.
    paragraphs = [p.strip() for p in page.text["p"]]
    assert len(paragraphs) == 2, "refusal page must hold only the banner and the rejection line"
    assert sum(p.startswith("INTERNAL BENCH ONLY") for p in paragraphs) == 1
    lines = [p for p in paragraphs if p.startswith(f"{code}:")]
    assert len(lines) == 1, f"refusal page must state {code!r} exactly once"
    assert lines[0][len(code) + 1 :].strip(), "refusal reason is empty"


@pytest.mark.parametrize("stack_id", STACKS)
@pytest.mark.parametrize(("field", "value"), INVALID_BUNDLES)
def test_score_refuses_invalid_bundle_before_metric_emission(
    lineage_run: Path, stack_id: str, field: str, value: object
) -> None:
    path = _preflight_path(lineage_run, stack_id)
    doc = json.loads(path.read_text(encoding="utf-8"))
    cache = doc["health_detailed_excerpt"]["model_cache"]
    if value is None:
        del cache[field]
    else:
        cache[field] = value
    # The existing producer validator is the oracle, not a new test-only rule.
    with pytest.raises(PreflightError) as producer:
        _parse_model_bundle_provenance(doc["health_detailed_excerpt"])
    assert producer.value.code == "model_bundle_unreported"
    path.write_text(json.dumps(doc), encoding="utf-8")

    with pytest.raises(BenchError) as consumer:
        score_head_to_head(lineage_run)
    assert consumer.value.code in {"preflight_invalid", "model_bundle_unreported"}
    _assert_no_metrics(lineage_run)


def test_score_accepts_distinct_valid_bundles(lineage_run: Path) -> None:
    # Runtime fingerprints are equal; model names, counts and digests differ.
    for field in ("model_name", "bundle_files", "bundle_sha256"):
        assert BUNDLES[A_STACK][field] != BUNDLES[B_STACK][field]
    score_head_to_head(lineage_run)
    frames = json.loads((lineage_run / "score" / "frames.json").read_text())
    assert frames["pr_cells_emitted"] is True
    cells = [cell for cell in frames["cells"] if cell.get("value") is not None]
    assert cells
    for metric in ("detection_recall", "detection_precision"):
        selected = [
            cell for cell in cells
            if cell["cell"] == f"{metric}@frame_e2e/label_map_primary"
        ]
        assert len(selected) == 2
        assert {cell["value"] for cell in selected} == {1.0}


@pytest.mark.parametrize("stack_id", STACKS)
@pytest.mark.parametrize("drift", ["profile", "runtime"])
def test_score_still_refuses_unrelated_provenance_drift(
    lineage_run: Path, stack_id: str, drift: str
) -> None:
    path = _preflight_path(lineage_run, stack_id)
    doc = json.loads(path.read_text(encoding="utf-8"))
    cache = doc["health_detailed_excerpt"]["model_cache"]
    if drift == "profile":
        cache["profile"] = "wrong-profile"
    else:
        prefix, encoded = cache["detail"].split("numeric_runtime_fingerprint=", 1)
        fingerprint = json.loads(encoded)
        fingerprint["numpy_version"] = "different-version"
        cache["detail"] = prefix + "numeric_runtime_fingerprint=" + json.dumps(fingerprint)
    _parse_model_bundle_provenance(doc["health_detailed_excerpt"])
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(BenchError) as exc:
        score_head_to_head(lineage_run)
    assert exc.value.code == "preflight_invalid"
    _assert_no_metrics(lineage_run)
