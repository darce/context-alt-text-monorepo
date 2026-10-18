"""Regression tests for resilient append-only outcome ledger records."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.bench.stack_pair import BenchError
from scripts.eval_harness.outcome_ledger import OutcomeLedger


def test_invalid_append_preserves_prior_outcome_ledger_records(tmp_path: Path) -> None:
    path = tmp_path / "items.jsonl"
    ledger = OutcomeLedger(path)
    valid = {
        "manifest_media_id": 1,
        "phase": "analyze",
        "outcome": "ok",
        "image_width": 16,
        "image_height": 16,
    }
    ledger.append(valid)

    with pytest.raises(BenchError) as exc:
        ledger.append({**valid, "image_width": 0})

    assert exc.value.code == "image_dimensions_missing"
    assert ledger.read_all() == [valid]


def test_outcome_ledger_skips_bad_jsonl_rows_and_keeps_reading(tmp_path: Path) -> None:
    path = tmp_path / "items.jsonl"
    first = {
        "manifest_media_id": 1,
        "phase": "analyze",
        "outcome": "ok",
        "image_width": 16,
        "image_height": 16,
    }
    invalid_dimensions = {**first, "manifest_media_id": 2, "image_height": 0}
    last = {**first, "manifest_media_id": 3}
    path.write_text(
        "\n".join(
            (
                json.dumps(first),
                "{invalid json",
                json.dumps(invalid_dimensions),
                json.dumps(last),
            )
        )
        + "\n",
        encoding="utf-8",
    )

    assert OutcomeLedger(path).read_all() == [first, last]
