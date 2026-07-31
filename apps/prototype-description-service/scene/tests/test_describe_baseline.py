"""Unit tests for describe_baseline report cost honesty (FL30-A-13)."""

from __future__ import annotations

import json

from scripts.eval_harness import describe_baseline as db


def _row(
    media_id: int,
    *,
    error: str | None = None,
    cached: bool | None = None,
    latency_s: float | None = 1.0,
    model_id: str = "test-model",
) -> dict:
    describe: dict | None
    if error and cached is None:
        describe = None
    else:
        describe = {
            "alt_text_draft": "caption",
            "model_id": model_id,
        }
        if cached is not None:
            describe["cached"] = cached
    return {
        "media_id": media_id,
        "path": f"{media_id}.jpg",
        "error": error,
        "describe": describe,
        "identities": [],
        "face_count": 0,
        "latency_s": latency_s,
        "completed_at": float(media_id),
    }


def test_write_report_total_cost_includes_failed_describe_attempts(tmp_path, monkeypatch):
    """A-13: total_cost_usd must include failed describe attempts, not only ok rows.

    Runner bills on attempt; feeding only error-free rows under-reports spend.
    """
    jsonl = tmp_path / "baseline.jsonl"
    report_json = tmp_path / "baseline.json"
    report_md = tmp_path / "baseline.md"
    monkeypatch.setattr(db, "JSONL", jsonl)
    monkeypatch.setattr(db, "REPORT_JSON", report_json)
    monkeypatch.setattr(db, "REPORT_MD", report_md)

    rows = [
        _row(1, cached=False),  # paid
        _row(2, error="RemoteClientError: boom", latency_s=0.4),  # paid (attempt)
        _row(3, cached=True),  # refunded
    ]
    jsonl.write_text("\n".join(json.dumps(r) for r in rows) + "\n")

    db._write_report(cost_per_image_usd=0.10)

    report = json.loads(report_json.read_text())
    summary = report["summary"]
    assert summary["described_ok"] == 2
    assert summary["errors"] == 1
    assert summary["cost_per_image_usd"] == 0.10
    # 2 paid attempts × $0.10 — NOT $0.10 from the single non-cached ok row alone
    assert summary["total_cost_usd"] == 0.20
    assert "2 paid describe calls" in report_md.read_text()


def test_write_report_total_cost_excludes_pre_describe_failures(tmp_path, monkeypatch):
    """A-16: rows that fail before describe (latency_s None) must not be billed.

    Runner only does paid_calls += 1 after describe_started is set; missing-file /
    bad-dimensions paths never reach that line, so latency_s stays None.
    """
    jsonl = tmp_path / "baseline.jsonl"
    report_json = tmp_path / "baseline.json"
    report_md = tmp_path / "baseline.md"
    monkeypatch.setattr(db, "JSONL", jsonl)
    monkeypatch.setattr(db, "REPORT_JSON", report_json)
    monkeypatch.setattr(db, "REPORT_MD", report_md)

    rows = [
        _row(1, cached=False),  # paid
        _row(
            2,
            error="FileNotFoundError: image file missing after NFC/NFD resolve: x.jpg",
            latency_s=None,
        ),  # pre-describe failure — not billed
        _row(3, error="RemoteClientError: boom", latency_s=0.4),  # paid (describe attempted)
        _row(4, cached=True),  # refunded
    ]
    jsonl.write_text("\n".join(json.dumps(r) for r in rows) + "\n")

    db._write_report(cost_per_image_usd=0.10)

    report = json.loads(report_json.read_text())
    summary = report["summary"]
    assert summary["described_ok"] == 2
    assert summary["errors"] == 2
    assert summary["cost_per_image_usd"] == 0.10
    # 2 paid attempts × $0.10 — pre-describe failure (latency_s None) excluded
    assert summary["total_cost_usd"] == 0.20
    assert "2 paid describe calls" in report_md.read_text()
