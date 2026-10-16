"""Actual default run/score/S4/S5 join; only model kernels and assets are fake.

Replay and conditional-vector coverage deliberately require the parallel S4
fixes (and its actual coverage schema). No substitute producer or statistic
makes those dependency regressions pass. No fixture is a human observation.
"""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from scene.tests.test_eval_harness_firbench_cli_integration import ARMS, AT, KINDS
from scene.tests.test_eval_harness_firbench_cli_integration import runtime_files as native_runtime_fixture
from scripts.eval_harness import firbench_cli as cli
from scripts.eval_harness import firbench_contract as fc
from scripts.eval_harness import firbench_legs as legs


@pytest.fixture
def native_files(tmp_path, monkeypatch):
    # Reuse the fake kernel/assets fixture's native-repository mode: actual S3
    # resolves the persisted decision path against its installed source tree.
    request = SimpleNamespace(node=SimpleNamespace(name="test_default_run_and_actual_score"))
    yield from native_runtime_fixture.__wrapped__(tmp_path, monkeypatch, request)


def _snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def _run_and_score(files):
    directory = files.private / "run"
    assert (
        cli.main(
            [
                "run",
                "--frame",
                "fake-only",
                "--decision",
                str(files.decision),
                "--legs",
                ",".join(k.value for k in KINDS),
                "--arms",
                ",".join(a.value for a in ARMS),
                "--created-at",
                AT,
                "--out",
                str(directory),
            ]
        )
        == 0
    )
    assert files.callbacks
    # Every downstream producer must use persisted inventory, not reopen pixels,
    # source annotations or templates. Keep the original timing receipt pinned.
    for path in files.private.glob("*.png"):
        path.unlink()
    files.source.unlink()
    files.templates.unlink()
    files.binding_path.unlink()
    receipt = (directory / "timings.json").read_bytes()
    assert cli.main(["score", str(directory)]) == 0
    scores = (directory / "scores.json").read_bytes()
    fc.validate_interchange("scores-v1", json.loads(scores))
    assert cli.main(["score", str(directory)]) == 0
    assert (directory / "scores.json").read_bytes() == scores
    assert (directory / "timings.json").read_bytes() == receipt
    return directory


def _report(directory):
    source = _snapshot(directory)
    assert cli.main(["report", str(directory)]) == 0
    assert {name: (directory / name).read_bytes() for name in source} == source
    report_dir = directory / "report"
    assert fc.require_private_output_path(report_dir, repo_root=cli._repo_root()) == report_dir
    html = (report_dir / "index.html").read_text()
    assert "data:image" not in html
    report = json.loads((report_dir / "report.json").read_bytes())
    scores = json.loads(source["scores.json"])
    assert report["verdict"] == scores["verdict"]
    assert report["verdict"]["state"] == "unratified"
    assert report["frames"]["created_at"] == json.loads(source["manifest.json"])["firbench"]["created_at"]
    for name in ("scores.json", "clusters.json", "frame.json", "manifest.json"):
        assert report["inputs"][name] == hashlib.sha256((directory / name).read_bytes()).hexdigest()
    tables = {p.name for p in report_dir.glob("*.csv")}
    assert {"legs.csv", "curves.csv", "cells.csv", "waterfall.csv", "failures.csv"} <= tables
    with (report_dir / "legs.csv").open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert {row["leg_key"] for row in rows} == {leg["leg_key"] for leg in scores["legs"]}
    clusters = json.loads((directory / "clusters.json").read_bytes())
    fc.validate_interchange("clusters-v1", clusters)
    declared = json.loads(source["manifest.json"])["firbench"]["leg_keys"]
    assert {leg["leg_key"] for leg in clusters["legs"]} == set(declared)
    return clusters


def test_default_cli_run_score_report_writes_actual_private_outputs(native_files):
    _report(_run_and_score(native_files))


def test_default_cli_report_replays_identical_bytes_with_pinned_inputs(native_files, capsys):
    directory = _run_and_score(native_files)
    _report(directory)
    first = _snapshot(directory)
    # Requires actual S4 canonical-byte replay; report_run must not skip S4 or
    # delete its output to conceal a producer that cannot replay.
    assert cli.main(["report", str(directory)]) == 0, "S4 materializer replay prerequisite unavailable"
    assert _snapshot(directory) == first
    # Replay must still invoke S4's input validation. A corrupt fake cache must
    # refuse while preserving the previously published derived artifacts.
    next((directory / "legs").glob("*/cache.npz")).write_bytes(b"invalid fake cache")
    corrupted = _snapshot(directory)
    assert cli.main(["report", str(directory)]) == 2
    assert "cache.npz" in capsys.readouterr().err
    assert _snapshot(directory) == corrupted


def test_default_cli_report_keeps_diagnostics_for_available_gt_vectors(native_files, monkeypatch):
    factory = legs.load_pinned_face_pipeline_leg

    def partial_kernel(kind, **kwargs):
        leg = factory(kind, **kwargs)
        if kind is not fc.LegKind.sface:
            return leg
        detect = leg.detector.detect

        def miss_one_query(batch):
            rows = detect(batch)
            return [
                [] if int(pixel[0, 0, 0]) == 1 and int(pixel[0, 0, 1]) == 1 else row
                for pixel, row in zip(batch, rows, strict=True)
            ]

        return replace(leg, detector=SimpleNamespace(detect=miss_one_query))

    monkeypatch.setattr(legs, "load_pinned_face_pipeline_leg", partial_kernel)
    directory = _run_and_score(native_files)
    clusters = _report(directory)
    native = next(leg for leg in clusters["legs"] if leg["leg_key"].startswith("sface__native__"))
    assert "vector_coverage" in native, "S4 conditional-vector coverage/schema prerequisite unavailable"
    assert native["vector_coverage"] == {
        "label": "diagnostics conditional on available GT vectors",
        "conditional": True,
        "n_gt_faces": 30,
        "n_named_gt_faces": 30,
        "n_embedded_gt_faces": 29,
        "n_missing_gt_faces": 1,
        "n_embedded_named_faces": 29,
        "n_detector_only_rows": 0,
    }
    assert native["partition_metrics"]["status"] == "available"
    assert native["pca_spectrum"]["status"] == "available"
    # The actual scorer still sees all FRAME GT, including the missed face.
    frame = json.loads((directory / "frame.json").read_bytes())
    assert len(frame["faces"]) == 30
    ledger = directory / "ledger" / f"{native['leg_key']}.jsonl"
    assert len(ledger.read_text().splitlines()) == 30


@pytest.mark.parametrize("module", ["firbench_cluster_io", "firbench_report"])
def test_report_missing_producer_refuses_before_materializing(tmp_path, monkeypatch, module):
    directory = tmp_path / "benchmarks/private/firbench/run"
    directory.mkdir(parents=True)
    # A real materializer would reject this incomplete run. A missing S5 must
    # instead refuse during import, before S4 is invoked or creates artifacts.
    (directory / "sentinel").write_bytes(b"unchanged")
    before = _snapshot(tmp_path)
    original = cli.importlib.import_module

    def unavailable(name, *args, **kwargs):
        if name == f"scripts.eval_harness.{module}":
            raise ModuleNotFoundError(f"No module named '{name}'", name=name)
        return original(name, *args, **kwargs)

    monkeypatch.setattr(cli.importlib, "import_module", unavailable)
    with pytest.raises(NotImplementedError, match=f"report needs.*{module}"):
        cli.report_run(directory, include_crops=False, repo_root=tmp_path)
    assert _snapshot(tmp_path) == before


@pytest.mark.parametrize("location", ["public", "private_root", "redirected"])
def test_report_private_guard_precedes_producer_imports(tmp_path, monkeypatch, location):
    repo = tmp_path / "repo"
    private = repo / "benchmarks/private"
    private.mkdir(parents=True)
    if location == "public":
        directory = repo / "public/run"
    elif location == "private_root":
        directory = private
    else:
        outside = tmp_path / "outside"
        outside.mkdir()
        (private / "redirect").symlink_to(outside, target_is_directory=True)
        directory = private / "redirect/run"
    before = _snapshot(tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("private output guard must precede producer imports")

    monkeypatch.setattr(cli.importlib, "import_module", forbidden)
    with pytest.raises(fc.NonPrivateOutputError):
        cli.report_run(directory, include_crops=False, repo_root=repo)
    assert _snapshot(tmp_path) == before
