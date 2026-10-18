"""Published v1 count domain through the actual producer, writer and ``explore`` CLI.

Every count the comparison-export producer publishes must render, and a count outside that
domain (one past the top, a boolean, a negative) must still be refused with exit 2 and no output.
Inputs are the retained public synthetic legacy report (nonnull clustering with parameters.d_cut).
No task-state, registry, database, image or private input is read. Native SQLite registration and
its composition with this path are a separate validation gate and are not proven here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scene.tests.test_eval_harness_firbench_explorer_presentation import _Page
from scene.tests.test_eval_harness_firbench_explorer_wire import _legacy_bytes
from scripts.eval_harness import firbench_cli as cli
from scripts.eval_harness.firbench_comparison_export import (
    ComparisonExportError,
    summarize_legacy_report,
    write_export,
)

ARTIFACT_ID = "public-count-domain"


def _project(section: tuple[str, ...], field: str, value: object) -> dict:
    source = json.loads(_legacy_bytes())
    block = source
    for name in section:
        block = block[name]
    block[field] = value
    return summarize_legacy_report(json.dumps(source).encode("ascii"), artifact_id=ARTIFACT_ID)


def _export(tmp_path: Path, report: dict) -> Path:
    digest = report["file_sha256"]
    assert report["clustering"]["parameters"] == {"d_cut": 0.6}
    payload = {
        "schema": "firbench/comparison-explorer-export-v1", "schema_version": 1,
        "sources": [{"artifact_id": ARTIFACT_ID, "file_sha256": digest, "kind": "report-json",
                     "qualification": "unqualified", "source_sha": None, "manifest_sha256": None,
                     "manifest_hash_kind": None}],
        "reports": [report],
        "dedup": [{"file_sha256": digest, "artifact_ids": [ARTIFACT_ID]}],
    }
    return write_export(payload, tmp_path / "comparison.json")


def _explore(tmp_path: Path, capsys, data: Path) -> tuple[object, str, str, Path]:
    out = tmp_path / "explorer"
    try:
        code = cli.main(["explore", "--data", str(data), "--out", str(out)])
    except SystemExit as exc:
        code = exc.code
    captured = capsys.readouterr()
    return code, captured.out, captured.err, out


@pytest.mark.parametrize(
    "section, field, value, metric, expected",
    [
        (("counts",), "total", 150, "images-scored", "150 of 150 images"),
        (("counts",), "total", 1000000001, "images-scored", "150 of 1000000001 images"),
        (("counts",), "total", 2147483647, "images-scored", "150 of 2147483647 images"),
        (("counts",), "total", None, "images-scored", "150"),
        (("counts",), "failed", 0, "images-failed", "0"),
        (("counts",), "failed", 2147483647, "images-failed", "2147483647"),
        (("slices", "clustering"), "n_faces", 2147483647, "grouped-faces", "2147483647"),
    ],
    ids=["total-150", "total-1000000001", "total-2147483647", "total-null", "failed-zero",
         "failed-2147483647", "n_faces-2147483647"],
)
def test_explore_renders_every_count_the_producer_publishes(
    tmp_path: Path, capsys, section: tuple[str, ...], field: str, value: object, metric: str, expected: str
) -> None:
    report = _project(section, field, value)
    data = _export(tmp_path, report)
    written = data.read_bytes()
    exported = json.loads(written)["reports"][0]
    assert (exported["clustering"] if "clustering" in section else exported["counts"])[field] == value

    code, stdout, stderr, out = _explore(tmp_path, capsys, data)

    assert code == 0, stderr
    index = out / "index.html"
    assert stdout.strip() == str(index)
    assert data.read_bytes() == written
    page = _Page(index.read_text(encoding="utf-8")).root
    cell = page.find("tr", **{"data-metric": metric}).find("span", **{"data-pipeline": "sface"})
    assert " ".join(cell.text.split()) == expected


@pytest.mark.parametrize("value", [2147483648, True, -1], ids=["max-plus-one", "boolean", "negative"])
def test_producer_refuses_counts_outside_its_published_domain(value: object) -> None:
    with pytest.raises(ComparisonExportError, match="malformed field"):
        _project(("counts",), "total", value)


@pytest.mark.parametrize("value", [2147483648, True, -1], ids=["max-plus-one", "boolean", "negative"])
def test_explore_refuses_counts_outside_the_published_domain(tmp_path: Path, capsys, value: object) -> None:
    export = json.loads(_export(tmp_path, _project(("counts",), "total", 150)).read_bytes())
    export["reports"][0]["counts"]["total"] = value
    data = tmp_path / "out-of-domain.json"
    data.write_text(json.dumps(export, sort_keys=True), encoding="ascii")

    code, stdout, stderr, out = _explore(tmp_path, capsys, data)

    assert code == 2
    assert stdout == ""
    assert stderr == (
        "error: invalid explorer export: expected a non-negative integer or null at reports[0].counts.total\n"
    )
    assert not out.exists()
    assert sorted(path.name for path in tmp_path.iterdir()) == ["comparison.json", "out-of-domain.json"]
