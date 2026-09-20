"""FIRDV-2 S1 RED contracts for the promoted ItemOutcomeStore seam."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from scripts.bench.corpus import ItemOutcomeStore
from scripts.bench.driver import init_run_dir
from scripts.bench.score_report import compute_accepted_set
from scripts.bench.stack_pair import load_stack_pair
from scripts.bench.tests.conftest import valid_pair_dict, write_manifest, write_pair
from scripts.eval_harness import outcome_ledger

STACKS = ("acx-dev-insightface", "acx-dev-fir")


def _run_fixture(tmp_path: Path) -> Path:
    media_ids = [1, 2, 3, 4]
    source_manifest = write_manifest(tmp_path / "source-manifest.json", media_ids)
    source_sha = hashlib.sha256(source_manifest.read_bytes()).hexdigest()
    pair = load_stack_pair(
        write_pair(
            tmp_path / "pair.yaml",
            valid_pair_dict(accepted_set_floor=0.5, manifest_sha256=source_sha),
        )
    )
    run_dir = init_run_dir(tmp_path / "run", pair, source_manifest)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    entries = {entry["media_id"]: entry for entry in manifest["entries"]}

    for stack_index, stack_id in enumerate(STACKS, start=1):
        leg = run_dir / "legs" / stack_id
        export_dir = leg / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        records: list[dict[str, Any]] = []
        stack_media_id = stack_index * 100
        for media_id in (1, 2):
            entry = entries[media_id]
            ingest = {
                "manifest_media_id": media_id,
                "manifest_path": entry["path"],
                "content_sha256": entry["sha256"],
                "stack_media_id": None,
                "image_width": 10,
                "image_height": 10,
                "phase": "ingest",
                "outcome": "ok",
                "terminal_ingest_outcome": "success",
                "attempt": 1,
            }
            records.append(ingest)
            records.append(
                {
                    **ingest,
                    "phase": "analyze",
                    "stack_media_id": stack_media_id + media_id,
                }
            )

        entry = entries[3]
        ingest = {
            "manifest_media_id": 3,
            "manifest_path": entry["path"],
            "content_sha256": entry["sha256"],
            "stack_media_id": None,
            "image_width": 10,
            "image_height": 10,
            "phase": "ingest",
            "outcome": "ok",
            "terminal_ingest_outcome": "success",
            "attempt": 1,
        }
        records.extend(
            [
                ingest,
                {
                    **ingest,
                    "phase": "analyze",
                    "outcome": "failed",
                    "error_code": "analyze_failed",
                },
            ]
        )

        # An analyze-ok row without an ingest roster row exercises the
        # existing join-attrition branch without inventing a new denominator.
        entry = entries[4]
        records.append(
            {
                "manifest_media_id": 4,
                "manifest_path": entry["path"],
                "content_sha256": entry["sha256"],
                "stack_media_id": stack_media_id + 4,
                "image_width": 10,
                "image_height": 10,
                "phase": "analyze",
                "outcome": "ok",
                "terminal_ingest_outcome": "success",
                "attempt": 1,
            }
        )
        (leg / "items.jsonl").write_text(
            "".join(json.dumps(record, separators=(",", ":")) + "\n" for record in records),
            encoding="utf-8",
        )
        (leg / "cluster_job.json").write_text(json.dumps({"status": "completed"}), encoding="utf-8")
        # Media 1 has a prediction; media 2 is an accepted zero-detection
        # observation and must remain in the denominator.
        (export_dir / "media_identities.json").write_text(
            json.dumps(
                [
                    {
                        "identity_id": f"id-{stack_id}-1",
                        "media_id": stack_media_id + 1,
                        "cluster_id": "cluster-1",
                        "cluster_label": "Alice Q",
                        "is_auto_label": False,
                        "bbox": {"x": 1, "y": 1, "width": 2, "height": 2},
                    }
                ]
            ),
            encoding="utf-8",
        )
        (export_dir / "clusters.json").write_text(json.dumps([{"id": "cluster-1"}]), encoding="utf-8")
        (export_dir / "cluster_members.json").write_text(json.dumps([]), encoding="utf-8")
    return run_dir


def test_outcome_ledger_round_trips_exact_existing_store_records(tmp_path: Path) -> None:
    path = tmp_path / "legs" / "acx-dev-fir" / "items.jsonl"
    record = {
        "manifest_media_id": 7,
        "manifest_path": "fixture.jpg",
        "content_sha256": "a" * 64,
        "phase": "ingest",
        "outcome": "ok",
        "terminal_ingest_outcome": "success",
        "image_width": 10,
        "image_height": 10,
    }
    existing_store = ItemOutcomeStore(path)
    existing_store.append(record)
    ledger = outcome_ledger.OutcomeLedger(path)

    assert outcome_ledger.ItemOutcomeStore is ItemOutcomeStore
    assert ledger.read_all() == existing_store.read_all() == [record]


def test_expected_observed_denominator_matches_existing_accepted_set(tmp_path: Path) -> None:
    run_dir = _run_fixture(tmp_path)
    expected = compute_accepted_set(run_dir)
    summary = outcome_ledger.summarize_run(run_dir)

    assert outcome_ledger.compute_accepted_set is compute_accepted_set
    assert summary["manifest_entry_count"] == expected.manifest_entry_count
    assert summary["accepted_set_size"] == expected.accepted_set_size
    assert summary["resolved_floor_count"] == expected.resolved_floor_count
    assert summary["manifest_media_ids"] == expected.manifest_media_ids


def test_attrition_fields_are_surfaced_from_existing_accepted_set(tmp_path: Path) -> None:
    run_dir = _run_fixture(tmp_path)
    expected = compute_accepted_set(run_dir)
    summary = outcome_ledger.summarize_run(run_dir)

    for field in ("attrition_ingest_analyze", "attrition_join", "zero_detection_media_count"):
        assert summary[field] == getattr(expected, field)
    assert summary["attrition_ingest_analyze"] >= 1
    assert summary["attrition_join"] >= 1
    assert summary["zero_detection_media_count"] == 1


def test_duplicate_append_preserves_item_outcome_store_last_record_semantics(tmp_path: Path) -> None:
    path = tmp_path / "legs" / "acx-dev-fir" / "items.jsonl"
    first = {
        "manifest_media_id": 9,
        "manifest_path": "fixture.jpg",
        "content_sha256": "a" * 64,
        "phase": "analyze",
        "outcome": "failed",
        "attempt": 1,
    }
    second = {
        **first,
        "outcome": "ok",
        "attempt": 2,
        "stack_media_id": 109,
        "image_width": 10,
        "image_height": 10,
    }
    ledger = outcome_ledger.OutcomeLedger(path)
    ledger.append(first)
    ledger.append(second)

    records = ledger.read_all()
    assert records == ItemOutcomeStore(path).read_all() == [first, second]
    assert len(records) == 2
    assert ledger.latest(9, "analyze") == second
