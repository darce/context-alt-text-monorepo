"""Public synthetic presentation cases; null clustering isolates the separate wire fix.

These fixtures are portable and do not read task-state, registries, images or databases.
The sparse rejection block is projected by the actual legacy-report producer.
"""

from __future__ import annotations

import json
from html.parser import HTMLParser
from pathlib import Path

from scripts.eval_harness.firbench_comparison_export import summarize_legacy_report
from scripts.eval_harness.firbench_explorer import render_explorer


class _Element:
    def __init__(self, tag: str, attrs=()) -> None:
        self.tag = tag
        self.attrs = dict(attrs)
        self.children = []

    @property
    def text(self) -> str:
        return " ".join(child if isinstance(child, str) else child.text for child in self.children)

    def find(self, tag: str, **attrs):
        if self.tag == tag and all(self.attrs.get(key) == value for key, value in attrs.items()):
            return self
        for child in self.children:
            if isinstance(child, _Element):
                found = child.find(tag, **attrs)
                if found is not None:
                    return found
        return None


class _Page(HTMLParser):
    def __init__(self, html: str) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Element("root")
        self.stack = [self.root]
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        node = _Element(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in {"meta", "link", "input", "br", "hr", "img"}:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def _public_synthetic_export() -> dict:
    sources, reports, dedup = [], [], []
    for index, (pipeline, model, dimension) in enumerate(
        (("auraface", "auraface", 512), ("sface", "ort-yunet-sface", 128), ("insightface", "buffalo_l", 512)), 1
    ):
        artifact_id = f"public-synthetic-{pipeline}"
        digest = str(index) * 64
        sources.append({"artifact_id": artifact_id, "file_sha256": digest, "kind": "report-json",
                        "qualification": "partial", "source_sha": None, "manifest_sha256": None,
                        "manifest_hash_kind": None})
        reports.append({"artifact_id": artifact_id, "file_sha256": digest, "pipeline": pipeline,
                        "model_id": model, "embedding_dim": dimension,
                        "counts": dict.fromkeys(("total", "scored", "failed", "matched_faces", "named_matched", "stranger_matched")),
                        "detection": dict.fromkeys(("tp", "fp", "fn", "precision", "recall")),
                        "unknown_rejection": None, "clustering": None, "identification": None,
                        "slice_sections": [], "compatibility": "unknown", "qualification": "partial"})
        dedup.append({"file_sha256": digest, "artifact_ids": [artifact_id]})
    return {"schema": "firbench/comparison-explorer-export-v1", "schema_version": 1,
            "sources": sources, "reports": reports, "dedup": dedup}


def _render(tmp_path: Path, export: dict) -> _Element:
    data = tmp_path / "public-export.json"
    data.write_text(json.dumps(export, allow_nan=False), encoding="utf-8")
    output = render_explorer(data, tmp_path / "page")
    return _Page(output.read_text(encoding="utf-8")).root


def test_source_evidence_preserves_recorded_pins_and_per_source_unknowns(tmp_path: Path) -> None:
    export = _public_synthetic_export()
    commit, manifest = "abcde12345" * 4, "f0123456789abcde" * 4
    export["sources"][0].update(source_sha=commit, manifest_sha256=manifest, manifest_hash_kind="raw-sha256")
    # A recorded hash kind is independently useful even when its digest is missing.
    export["sources"][1]["manifest_hash_kind"] = "legacy-model-dump-sha256"
    page = _render(tmp_path, export)
    table = page.find("table", **{"class": "source-table"})
    body = table.find("tbody")
    rows = [node for node in body.children if isinstance(node, _Element) and node.tag == "tr"]
    assert commit in rows[0].text, "source evidence must retain the full supplied source commit"
    assert manifest in rows[0].text, "source evidence must retain the full supplied manifest digest"
    assert "raw-sha256" in rows[0].text
    assert "legacy-model-dump-sha256" in rows[1].text
    assert "not recorded" in rows[1].text and "not recorded" in rows[2].text
    summary = page.find("details", id="source-evidence").find("p", **{"class": "sub"}).text.lower()
    assert "no source commit and no manifest hash are recorded" not in summary
    assert "1 of 3" in summary and "recorded" in summary
    assert "declared" in summary and "verified" in summary
    assert all(word in summary for word in ("inputs", "weights", "templates", "gallery", "winner"))


def test_sparse_producer_rejection_preserves_count_and_labels_missing_denominator_and_rate(tmp_path: Path) -> None:
    raw = json.dumps({"schema": "acx-eval/v1", "kind": "report", "report_kind": "face_bakeoff",
                      "slices": {"unknown_rejection": {"correct_rejects": 7}}}).encode()
    block = summarize_legacy_report(raw, artifact_id="public-synthetic-sparse")["unknown_rejection"]
    assert block["correct_rejects"] == 7 and block["n"] is None and block["rate"] is None
    export = _public_synthetic_export()
    export["reports"][0]["unknown_rejection"] = block
    page = _render(tmp_path, export)
    row = page.find("tr", **{"data-metric": "strangers-rejected"})
    cell = row.find("span", **{"data-pipeline": "auraface"})
    assert cell.text.split()[0] == "7", "the known correct-rejection count must survive rendering"
    assert "denominator not recorded" in cell.text.lower()
    assert "rate not recorded" in cell.text.lower()
    assert "0%" not in cell.text and "None" not in cell.text
    assert "not recorded" in row.find("span", **{"data-pipeline": "sface"}).text


def test_auraface_definition_does_not_claim_absence_when_all_pipelines_are_present(tmp_path: Path) -> None:
    page = _render(tmp_path, _public_synthetic_export())
    assert all(page.find("select", id=f"variant-{pipeline}") is not None
               for pipeline in ("auraface", "sface", "insightface"))
    assert page.find("h3", id="auraface-head") is None
    definition = page.find("article", id="term-auraface")
    description = definition.find("p")
    assert "512" in description.text
    assert "No AuraFace report file is in this set" not in description.text
