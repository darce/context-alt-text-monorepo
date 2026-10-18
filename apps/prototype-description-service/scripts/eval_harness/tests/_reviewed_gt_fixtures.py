"""Confirmed-review evidence for report fixtures, without changing scoring mode."""

from __future__ import annotations

import copy
from typing import Any

from scripts.eval_harness.face_metrics import has_human_adjudicated_gt_lineage
from scripts.eval_harness.report import build_reports as _build_reports
from scripts.eval_harness.report import score_run_record as _score_run_record


def reviewed_report_entries(entries: list[dict]) -> tuple[list[dict], dict[str, Any]]:
    """Return copied GT and explicit independent blind review records (PROV-01)."""
    reviewed_entries = copy.deepcopy(entries)
    records: list[dict[str, Any]] = []
    for entry in reviewed_entries:
        for box_index, box in enumerate(entry.get("face_boxes") or []):
            # Review admission needs complete boxes even when geometry is not
            # relevant to the report assertion, as in the scene-suite precedent.
            box.setdefault("w", 0.2)
            box.setdefault("h", 0.3)
            box.setdefault("source", "iptc")
            if not has_human_adjudicated_gt_lineage(box):
                continue
            record_id = f"report-fixture-review-{entry['media_id']}-{box_index}"
            box["adjudication_source"] = f"human_adjudicated:{record_id}"
            records.append(
                {
                    "record_id": record_id,
                    "media_id": entry["media_id"],
                    "box_index": box_index,
                    "reviewer_id": "report-fixture-reviewer",
                    "reviewer_kind": "human",
                    "review_method": "independent_blind_review",
                    "decision": "confirmed",
                    "reviewed_at": "2026-08-15T00:00:00Z",
                }
            )
    return reviewed_entries, {"adjudication_records": records}


def score_run_record(run_record: dict[str, Any], entries: list[dict], *args: Any, **kwargs: Any) -> dict[str, Any]:
    """Score fixtures with review-only evidence unless evidence is explicit."""
    if kwargs.get("run_manifest") is None and kwargs.get("review_manifest") is None:
        entries, kwargs["review_manifest"] = reviewed_report_entries(entries)
    return _score_run_record(run_record, entries, *args, **kwargs)


def build_reports(run_record: dict[str, Any], entries: list[dict], *args: Any, **kwargs: Any) -> tuple[str, str]:
    """Build fixture reports with the same review-only scoring evidence."""
    if kwargs.get("run_manifest") is None and kwargs.get("review_manifest") is None:
        entries, kwargs["review_manifest"] = reviewed_report_entries(entries)
    return _build_reports(run_record, entries, *args, **kwargs)
