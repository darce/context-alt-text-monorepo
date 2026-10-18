"""Software-only evidence wire checks with actual CLI/runtime/S7 readers.

The documents below model a complete real-evidence wire for validation only.
They establish no human conduct, genuine observation, or real analysis proof.
Only media/model kernels use the existing synthetic CLI fixture.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import fields, replace
from types import SimpleNamespace

import pytest

from scene.tests import test_eval_harness_fir_occ_labels as base
from scene.tests import test_eval_harness_fir_occ_labels_evidence as evidence
from scene.tests.test_eval_harness_firbench_cli_integration import (
    rebind_source,
    run,
    runtime_files,  # noqa: F401
    write_json,
)
from scripts.eval_harness import fir_occ_labels as labels
from scripts.eval_harness import firbench_cli as cli
from scripts.eval_harness import firbench_contract as fc
from scripts.eval_harness import firbench_runtime as runtime


def test_prepared_run_keeps_old_positional_constructor():
    prepared = runtime.PreparedRun(None, (), "basis", None, 0.0, {})
    assert prepared.label_evidence is None
    assert fields(prepared)[-1].name == "label_evidence"


def test_frozen_s7_dependency_is_present():
    # Missing concurrent work is a real RED, never a substitute implementation.
    assert callable(getattr(labels, "freeze_label_evidence", None)), "missing frozen S7 freeze_label_evidence"
    assert callable(getattr(labels, "requalify_label_evidence", None)), "missing frozen S7 requalify_label_evidence"


def test_injected_old_prepared_run_without_bundle_remains_usable(runtime_files, monkeypatch):
    actual = runtime.default_collaborators()

    def prepare(**kwargs):
        prepared = actual.prepare_run(**kwargs)
        return SimpleNamespace(
            **{
                field.name: getattr(prepared, field.name)
                for field in fields(prepared)
                if field.name != "label_evidence"
            }
        )

    monkeypatch.setattr(cli, "_load_collaborators", lambda: replace(actual, prepare_run=prepare))
    directory = run(runtime_files)
    assert "label_evidence" not in json.loads((directory / "manifest.json").read_bytes())["firbench"]
    assert not (directory / "label-evidence").exists()
    assert runtime_files.callbacks


@pytest.fixture
def evidence_wire(runtime_files):
    f = runtime_files
    directory = f.private / "label-wire"
    queue_path = directory / "queue/queue.json"
    gold_path = directory / "support/gold.json"
    export_path = directory / "answers/export.json"
    observation_path = directory / "support/observation.json"
    qdoc, gdoc = base._queue_doc(), base._gold_doc()
    # Structurally complete wire, not an attestation about these test actors.
    for doc in (qdoc, gdoc):
        doc["data_origin"] = "real"
        for item in doc["items"]:
            item["data_origin"] = "real"
            item.pop("fixture_recipe", None)
    source = json.loads(f.source.read_bytes())
    qdoc["items"][0].update(image_id=source["images"][0]["image_id"], image_sha256=source["images"][0]["sha256"])
    context = {
        "rule": base.RULE,
        "instructions": "software-only instructions",
        "operators": ["ann-01"],
        "collection_workflow": "software-only collection",
        "adjudication_workflow": "software-only adjudication",
        "tool_behavior": "software-only tool behavior",
    }
    qdoc["measurement_context"] = context
    qsha = write_json(queue_path, qdoc)
    write_json(gold_path, gdoc)
    edoc = base._export_doc(qdoc, qsha, gdoc, observation_ref="../support/observation.json")
    write_json(export_path, edoc)
    export = labels.load_label_export(export_path)
    queue = labels.load_queue(queue_path, gold_path)
    _, _, applicability = evidence.comparison(export, queue)
    applicability["context_assessment"] = {
        key: {"observed": value, "current": value, "covered": True, "rationale": "software-only comparison"}
        for key, value in context.items()
    }
    write_json(
        observation_path,
        {
            "schema": "fir-occ-observation/v1",
            "record_kind": "bounded_human_observation",
            "data_origin": "real",
            "observer_id": "software-only-observer",
            "observed_at": "2026-10-15T08:00:00+00:00",
            "scope": "software-only wire validation",
            "method": "software-only wire validation",
            "operator_accounts": "software-only accounts",
            "limits": "No human observation or real analysis proof is established by this fixture.",
            "exceptions": [],
            "context": context,
            "applicability": applicability,
        },
    )
    rows = labels.to_face_instances(export, queue)
    labels.require_real_analysis_rows(rows)
    row = next(r for r in rows if r["item_id"] == "img-0000")
    source["faces"][0].update(
        box=row["box"], identity_status=row["identity_status"], identity_id=None, annotation=row["annotation"]
    )
    rebind_source(f, source)
    paths = {"export_path": export_path, "queue_path": queue_path, "gold_path": gold_path}
    f.binding["label_evidence"] = {key: path.relative_to(f.repo).as_posix() for key, path in paths.items()}
    write_json(f.binding_path, f.binding)
    originals = {path: path.read_bytes() for path in (*paths.values(), observation_path)}
    return f, paths, observation_path, originals


@pytest.mark.parametrize("query_failure", [False, True])
def test_native_cli_persists_exact_evidence_before_query(evidence_wire, monkeypatch, query_failure):
    f, paths, observation, originals = evidence_wire
    from scripts.eval_harness import firbench_legs as legs

    actual_factory = legs.load_pinned_face_pipeline_leg
    seen = []

    def check_declarations():
        directory = f.private / "run"
        frame_bytes = (directory / "frame.json").read_bytes()
        declaration = json.loads((directory / "manifest.json").read_bytes())["firbench"]["label_evidence"]
        assert frame_bytes.endswith(b"\n")
        assert declaration["frame_sha256"] == hashlib.sha256(frame_bytes).hexdigest()
        assert set(declaration) == {"schema", "frame_sha256", "export_path", "queue_path", "gold_path", "files"}
        assert declaration["schema"] == "firbench-label-evidence/v1"
        expected = {"label-evidence/" + p.relative_to(f.repo).as_posix(): data for p, data in originals.items()}
        assert declaration["files"] == [
            {"path": path, "sha256": hashlib.sha256(data).hexdigest()} for path, data in sorted(expected.items())
        ]
        for key, path in paths.items():
            assert declaration[key] == "label-evidence/" + path.relative_to(f.repo).as_posix()
        assert {
            p.relative_to(directory).as_posix() for p in (directory / "label-evidence").rglob("*") if p.is_file()
        } == set(expected)
        for path, data in expected.items():
            assert (directory / path).read_bytes() == data
        seen.append(declaration)
        if query_failure:
            raise RuntimeError("software-only query failure")

    def factory(*args, **kwargs):
        model = actual_factory(*args, **kwargs)
        actual_detect = model.detector.detect

        def detect(batch):
            if any(pixel[0, 0, 1] == 1 for pixel in batch):
                check_declarations()
            return actual_detect(batch)

        monkeypatch.setattr(model.detector, "detect", detect)
        return model

    monkeypatch.setattr(legs, "load_pinned_face_pipeline_leg", factory)
    if query_failure:
        with pytest.raises(RuntimeError, match="software-only query failure"):
            run(f)
    else:
        run(f)
    assert seen
    directory = f.private / "run"
    assert (directory / "attempt-failure.json").exists() is query_failure
    if query_failure:
        assert json.loads((directory / "attempt-failure.json").read_bytes())["phase"] == "query_outcomes"
        assert not (directory / "timings.json").exists()
        assert not list(directory.glob("legs/*/searches.jsonl"))
    for path, data in originals.items():
        assert path.read_bytes() == data
        path.unlink()
    # Requalification must use run-local bytes with all originals absent.
    frame_sha = hashlib.sha256((directory / "frame.json").read_bytes()).hexdigest()
    qualified = labels.requalify_label_evidence(directory, seen[0], frame_sha256=frame_sha)
    assert any(row["image_id"] == "image-0000" for row in qualified)
    copied_observation = directory / "label-evidence" / observation.relative_to(f.repo)
    copied_observation.write_bytes(copied_observation.read_bytes() + b" ")
    with pytest.raises(fc.FrameContractError, match="evidence|sha256|hash"):
        labels.requalify_label_evidence(directory, seen[0], frame_sha256=frame_sha)


def test_existing_support_file_is_never_overwritten(evidence_wire, monkeypatch):
    f, _, _, originals = evidence_wire
    actual = runtime.default_collaborators()
    collision = []
    sentinel = b"preexisting support: do not overwrite\r\n"

    def prepare(**kwargs):
        prepared = actual.prepare_run(**kwargs)
        # Model a competing creator after the read-only bundle has been frozen.
        target = kwargs["out_dir"] / sorted(prepared.label_evidence.files)[0]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(sentinel)
        collision.append(target)
        return prepared

    monkeypatch.setattr(cli, "_load_collaborators", lambda: replace(actual, prepare_run=prepare))
    with pytest.raises(fc.FrameContractError, match="cannot create label_evidence artifact"):
        run(f)
    assert collision[0].read_bytes() == sentinel
    assert not f.callbacks
    assert not (f.private / "run/frame.json").exists()
    assert not (f.private / "run/manifest.json").exists()
    for path, data in originals.items():
        assert path.read_bytes() == data


@pytest.mark.parametrize(
    "failure",
    [
        "observation",
        "annotation",
        "box",
        "image_sha",
        "identity_status",
        "duplicate_json",
        "export_symlink",
        "observation_symlink",
    ],
)
def test_invalid_evidence_refuses_before_declarations_or_queries(evidence_wire, failure):
    f, paths, observation, _ = evidence_wire
    if failure == "observation":
        observation.unlink()
    elif failure in {"export_symlink", "observation_symlink"}:
        path = paths["export_path"] if failure == "export_symlink" else observation
        actual = path.with_name("actual-" + path.name)
        path.rename(actual)
        path.symlink_to(actual.name)
    elif failure == "duplicate_json":
        original = paths["export_path"].read_bytes()
        paths["export_path"].write_bytes(b'{"schema":"fir-occ-labels/v1",' + original[1:])
    else:
        source = json.loads(f.source.read_bytes())
        if failure == "annotation":
            source["faces"][0]["annotation"]["rule_id"] = "unqualified-rule"
        elif failure == "box":
            source["faces"][0]["box"] = [2, 2, 4, 4]
        elif failure == "image_sha":
            source["images"][0]["sha256"] = "0" * 64
        else:
            source["faces"][0]["identity_status"] = "named"
        rebind_source(f, source)
    expected_error = "symlink|symbolic" if failure.endswith("symlink") else None
    with pytest.raises(fc.FrameContractError, match=expected_error):
        run(f)
    assert not f.callbacks
    assert not (f.private / "run").exists()
    assert not (f.private / ".run.claim").exists()
