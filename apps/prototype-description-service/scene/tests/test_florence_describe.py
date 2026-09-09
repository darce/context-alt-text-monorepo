"""VLM-6 on-box florence_describe driver — model-stubbed unit tests.

Covers TSV parsing / path remapping, resume-skip, bounded-stall abort (rg-007),
JSONL row shape, and revision-pin parity with scene/config/profiles.py. The
model itself is never loaded: ``run`` takes an injected captioner.
"""

import json
import time
from pathlib import Path

import pytest

from scene.config.profiles import PROFILE_SPECS, DescriptionProfile
from scripts.eval_harness.describe_baseline import cost_report_fields, parse_cost_per_image_usd
from scripts.eval_harness.florence_describe import (
    CAPTION_TASK,
    MODEL_SPECS,
    BoundedStallError,
    done_ids,
    main,
    parse_tsv,
    resolve_image_path,
    run,
)

SPEC = MODEL_SPECS["base-ft"]
LARGE_SPEC = MODEL_SPECS["large-ft"]


def _ok_row(attachment_id: int, *, spec=SPEC, revision=None, **extra) -> dict:
    row = {
        "attachment_id": attachment_id,
        "model_id": spec.model_id,
        "model_version": spec.model_version,
        "model_revision": revision if revision is not None else spec.revision,
        "task": CAPTION_TASK,
        "caption": "ok",
        "error": None,
    }
    row.update(extra)
    return row


@pytest.fixture()
def corpus(tmp_path):
    d = tmp_path / "corpus"
    (d / "2026" / "07").mkdir(parents=True)
    for i in range(1, 6):
        (d / "2026" / "07" / f"img-{i}.png").write_bytes(b"x")
    return d


def _run(rows, captioner, out, **kw):
    kw.setdefault("spec", SPEC)
    kw.setdefault("resolved_revision", SPEC.revision)
    return run(rows, captioner, out, **kw)


# ------------------------------------------------------------------ tsv parse
def test_parse_tsv_remaps_uploads_absolute_paths_into_images_dir(corpus):
    tsv = "651\t/Volumes/Butter/WP/vlm/app/public/wp-content/uploads/2026/07/img-1.png\n"
    rows = parse_tsv(tsv, corpus)
    assert rows == [(651, corpus / "2026" / "07" / "img-1.png")]
    assert rows[0][1].exists()


def test_parse_tsv_tolerates_headers_malformed_and_relative_paths(corpus):
    tsv = "\n".join(
        [
            "attachment_id\tpath",  # header: non-int id skipped
            "no-tab-line",
            "12\t",  # empty path skipped
            "650\t2026/07/img-2.png",  # relative: joined onto images_dir
            "649\t/nonexistent/abs/img-9.png",  # missing abs path kept as-is
        ]
    )
    rows = parse_tsv(tsv, corpus)
    assert rows == [
        (650, corpus / "2026" / "07" / "img-2.png"),
        (649, Path("/nonexistent/abs/img-9.png")),
    ]


def test_resolve_image_path_prefers_existing_absolute(corpus):
    existing = corpus / "2026" / "07" / "img-3.png"
    assert resolve_image_path(str(existing), Path("/elsewhere")) == existing


# --------------------------------------------------------------------- resume
def test_done_ids_tolerates_torn_last_line(tmp_path):
    out = tmp_path / "out.jsonl"
    good = _ok_row(1)
    out.write_text(json.dumps(good) + "\n" + '{"attachment_id": 2, "capt')
    assert done_ids(out) == {(1, SPEC.model_id, SPEC.model_version, SPEC.revision, CAPTION_TASK)}


def test_done_ids_skips_error_rows(tmp_path):
    """A2: rows with error set are not complete — must be retried on rerun."""
    out = tmp_path / "out.jsonl"
    out.write_text(json.dumps(_ok_row(1, error="RuntimeError: boom")) + "\n" + json.dumps(_ok_row(2)) + "\n")
    assert done_ids(out) == {(2, SPEC.model_id, SPEC.model_version, SPEC.revision, CAPTION_TASK)}


def test_done_ids_requires_full_model_key(tmp_path):
    """A3: attachment_id alone is not enough; incomplete rows are not done."""
    out = tmp_path / "out.jsonl"
    out.write_text(json.dumps({"attachment_id": 1, "caption": "x", "error": None}) + "\n")
    assert done_ids(out) == set()


def test_run_skips_already_done_ids_and_records_missing_files(corpus, tmp_path, monkeypatch):
    out = tmp_path / "out.jsonl"
    out.write_text(json.dumps(_ok_row(1)) + "\n")
    rows = [
        (1, corpus / "2026" / "07" / "img-1.png"),  # done: skipped
        (2, corpus / "2026" / "07" / "img-2.png"),
        (3, corpus / "missing.png"),  # not on disk: written with explicit error
    ]
    # Fixed monotonic pair so latency.mean is an independent literal.
    ticks = iter([100.0, 101.5])  # one caption => latency 1.5s
    monkeypatch.setattr(time, "monotonic", lambda: next(ticks))
    seen: list[int] = []
    summary = _run(rows, lambda p: seen.append(1) or "A photo.", out)
    assert summary == {
        "total": 3,
        "already_done": 1,
        "missing": 1,
        "captioned_ok": 1,
        "errors": 1,  # A-04: missing-on-disk increments errors
        "latency": {
            "unit": "s",
            "n": 1,
            "mean": 1.5,
            "min": 1.5,
            "p50": 1.5,
            "p95": 1.5,
            "p99": 1.5,
            "max": 1.5,
        },
    }
    assert len(seen) == 1
    recorded = [json.loads(ln) for ln in out.read_text().splitlines()]
    assert [r["attachment_id"] for r in recorded] == [1, 3, 2]
    missing_row = next(r for r in recorded if r["attachment_id"] == 3)
    assert missing_row["error"] is not None
    assert "missing on disk" in missing_row["error"]
    assert missing_row["model_id"] == SPEC.model_id
    assert missing_row["caption"] is None


def test_latency_aggregates_use_three_distinct_values(corpus, tmp_path, monkeypatch):
    """A-12: mean/min/max/p50/p95 must be independently assertable (not a single-value tautology)."""
    out = tmp_path / "out.jsonl"
    rows = [
        (1, corpus / "2026" / "07" / "img-1.png"),
        (2, corpus / "2026" / "07" / "img-2.png"),
        (3, corpus / "2026" / "07" / "img-3.png"),
    ]
    # Three captions with latencies 1.0, 2.0, 10.0 — each aggregate has a distinct expected value.
    ticks = iter([0.0, 1.0, 10.0, 12.0, 20.0, 30.0])
    monkeypatch.setattr(time, "monotonic", lambda: next(ticks))
    summary = _run(rows, lambda p: "A photo.", out)
    assert summary["captioned_ok"] == 3
    lat = summary["latency"]
    assert lat is not None
    assert lat["unit"] == "s"
    assert lat["n"] == 3
    assert lat["mean"] == pytest.approx(4.333, abs=0.001)  # (1+2+10)/3
    assert lat["min"] == 1.0
    assert lat["max"] == 10.0
    assert lat["p50"] == 2.0
    assert lat["p95"] == 10.0
    assert lat["p99"] == 10.0
    # Prove they are not all the same number (the old single-caption tautology).
    values = [
        lat["mean"],
        lat["min"],
        lat["max"],
        lat["p50"],
    ]
    assert len(set(values)) == 4


def test_run_retries_error_rows_on_resume(corpus, tmp_path):
    """A2: a prior error row for the same model key is not treated as done."""
    out = tmp_path / "out.jsonl"
    out.write_text(json.dumps(_ok_row(1, error="RuntimeError: boom", caption=None)) + "\n")
    rows = [(1, corpus / "2026" / "07" / "img-1.png")]
    summary = _run(rows, lambda p: "recovered caption", out)
    assert summary["already_done"] == 0
    assert summary["captioned_ok"] == 1
    last = json.loads(out.read_text().splitlines()[-1])
    assert last["caption"] == "recovered caption"
    assert last["error"] is None


def test_resume_does_not_accumulate_duplicate_error_rows(corpus, tmp_path):
    """A-03: retrying an error rewrites the prior row out — JSONL does not grow unboundedly."""
    out = tmp_path / "out.jsonl"
    out.write_text(json.dumps(_ok_row(1, error="RuntimeError: boom", caption=None)) + "\n")
    rows = [(1, corpus / "2026" / "07" / "img-1.png")]

    def still_broken(path):
        raise RuntimeError("boom again")

    summary = _run(rows, still_broken, out, stall_limit=5)
    assert summary["errors"] == 1
    lines = out.read_text().splitlines()
    assert len(lines) == 1  # old error dropped, one new error row — not 2
    assert json.loads(lines[0])["error"] == "RuntimeError: boom again"


def test_missing_on_disk_increments_errors_counter(corpus, tmp_path):
    """A-04: summary.errors must match error rows written for missing files."""
    out = tmp_path / "out.jsonl"
    rows = [(9, corpus / "nope.png")]
    summary = _run(rows, lambda p: "unused", out)
    assert summary["missing"] == 1
    assert summary["errors"] == 1
    assert summary["captioned_ok"] == 0
    recorded = [json.loads(ln) for ln in out.read_text().splitlines()]
    assert len(recorded) == 1 and recorded[0]["error"] is not None


def test_unresolved_revision_is_hard_error(corpus, tmp_path):
    """A-05: null model_revision makes resume keys unstable — refuse to write."""
    out = tmp_path / "out.jsonl"
    rows = [(1, corpus / "2026" / "07" / "img-1.png")]
    with pytest.raises(ValueError, match="revision unresolved"):
        _run(rows, lambda p: "x", out, resolved_revision=None)


def test_done_ids_ignores_null_model_revision(tmp_path):
    """A-05: a row with null revision is never treated as done."""
    out = tmp_path / "out.jsonl"
    out.write_text(json.dumps(_ok_row(1, revision=None if False else None)) + "\n")
    # Force null revision explicitly (override helper default).
    row = _ok_row(1)
    row["model_revision"] = None
    out.write_text(json.dumps(row) + "\n")
    assert done_ids(out) == set()


def test_run_does_not_skip_when_prior_row_is_different_model(corpus, tmp_path):
    """A3: base-ft output must not suppress large-ft coverage for the same ids."""
    out = tmp_path / "out.jsonl"
    out.write_text(json.dumps(_ok_row(1, spec=SPEC)) + "\n")
    rows = [(1, corpus / "2026" / "07" / "img-1.png")]
    seen: list[Path] = []
    summary = _run(
        rows,
        lambda p: seen.append(p) or "large caption",
        out,
        spec=LARGE_SPEC,
        resolved_revision="abc123resolved",
    )
    assert summary["already_done"] == 0
    assert summary["captioned_ok"] == 1
    assert len(seen) == 1
    last = json.loads(out.read_text().splitlines()[-1])
    assert last["model_id"] == LARGE_SPEC.model_id
    assert last["model_version"] == LARGE_SPEC.model_version
    assert last["model_revision"] == "abc123resolved"


def test_limit_bounds_the_todo_list(corpus, tmp_path):
    out = tmp_path / "out.jsonl"
    rows = [(i, corpus / "2026" / "07" / f"img-{i}.png") for i in range(1, 6)]
    summary = _run(rows, lambda p: "A photo.", out, limit=2)
    assert summary["captioned_ok"] == 2
    assert len(out.read_text().splitlines()) == 2


# -------------------------------------------------------------- bounded stall
def test_bounded_stall_aborts_after_consecutive_failures(corpus, tmp_path):
    out = tmp_path / "out.jsonl"
    rows = [(i, corpus / "2026" / "07" / f"img-{i}.png") for i in range(1, 6)]

    def broken(path):
        raise RuntimeError("boom")

    with pytest.raises(BoundedStallError):
        _run(rows, broken, out, stall_limit=3)
    error_rows = [json.loads(ln) for ln in out.read_text().splitlines()]
    assert len(error_rows) == 3  # every failure durably recorded before the abort
    assert all(r["error"] == "RuntimeError: boom" for r in error_rows)


def test_intermittent_failures_reset_the_stall_counter(corpus, tmp_path):
    out = tmp_path / "out.jsonl"
    rows = [(i, corpus / "2026" / "07" / f"img-{i}.png") for i in range(1, 6)]
    calls = iter([RuntimeError("x"), "ok", RuntimeError("x"), "ok", "ok"])

    def flaky(path):
        result = next(calls)
        if isinstance(result, Exception):
            raise result
        return result

    summary = _run(rows, flaky, out, stall_limit=2)
    assert summary["captioned_ok"] == 3
    assert summary["errors"] == 2
    assert len(out.read_text().splitlines()) == 5  # error rows are recorded too


# ---------------------------------------------------------------- jsonl shape
def test_jsonl_row_shape(corpus, tmp_path):
    out = tmp_path / "out.jsonl"
    rows = [(1, corpus / "2026" / "07" / "img-1.png")]
    _run(rows, lambda p: "A detailed photo.", out)
    (row,) = (json.loads(ln) for ln in out.read_text().splitlines())
    assert row["attachment_id"] == 1
    assert row["caption"] == "A detailed photo."
    assert row["error"] is None
    assert row["task"] == CAPTION_TASK
    assert row["model_id"] == "microsoft/Florence-2-base-ft"
    assert row["model_version"] == "florence-2-base-ft"
    assert row["model_revision"] == SPEC.revision
    assert isinstance(row["latency_s"], float)
    assert isinstance(row["completed_at"], float)
    assert row["path"].endswith("img-1.png")


# -------------------------------------------------------------- pins / config
def test_model_specs_mirror_profiles_registry():
    """Revision pins must not drift from scene/config/profiles.py."""
    small = PROFILE_SPECS[DescriptionProfile.FLORENCE_SMALL]
    large = PROFILE_SPECS[DescriptionProfile.FLORENCE_LARGE]
    assert MODEL_SPECS["base-ft"].model_id == small.model_id
    assert MODEL_SPECS["base-ft"].revision == small.model_revision
    assert MODEL_SPECS["large-ft"].model_id == large.model_id
    assert MODEL_SPECS["large-ft"].revision == large.model_revision  # unpinned until enablement


def test_main_refuses_unpinned_large_ft_before_load(tmp_path, monkeypatch, capsys):
    """VLM6-RH-09: --model large-ft fails at parse time, never calls load_captioner."""
    tsv = tmp_path / "a.tsv"
    tsv.write_text("1\t2026/07/img-1.png\n")
    called: list[object] = []

    def _boom(spec):  # pragma: no cover — must not be reached
        called.append(spec)
        raise AssertionError("load_captioner must not run for unpinned large-ft")

    monkeypatch.setattr("scripts.eval_harness.florence_describe.load_captioner", _boom)
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "--images-dir",
                str(tmp_path),
                "--tsv",
                str(tsv),
                "--out-jsonl",
                str(tmp_path / "out.jsonl"),
                "--model",
                "large-ft",
            ]
        )
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "no pinned revision" in err
    assert "large-ft" in err
    assert called == []


def test_main_requires_paths(capsys):
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2  # argparse error
    assert "IMAGES_DIR" in capsys.readouterr().err


def test_main_reports_missing_tsv(tmp_path, capsys):
    rc = main(
        [
            "--images-dir",
            str(tmp_path),
            "--tsv",
            str(tmp_path / "nope.tsv"),
            "--out-jsonl",
            str(tmp_path / "out.jsonl"),
        ]
    )
    assert rc == 1
    assert "TSV not found" in capsys.readouterr().err


def test_main_reports_missing_tsv_with_printable_path_text(tmp_path, capsys):
    """VLM6-RV18-13: operator errors must encode PEP 383 path surrogates."""
    tsv = tmp_path / "missing-\udce9.tsv"
    rc = main(
        [
            "--images-dir",
            str(tmp_path),
            "--tsv",
            str(tsv),
            "--out-jsonl",
            str(tmp_path / "out.jsonl"),
        ]
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "undecodable:" in err
    assert "\udce9" not in err


# -------------------------------------------------------- baseline cost (A4)
def test_cost_report_fields_null_when_no_rate():
    assert cost_report_fields(cost_per_image_usd=None, paid_describe_calls=10) == {
        "cost_per_image_usd": None,
        "total_cost_usd": None,
    }


def test_cost_report_fields_total_from_rate_and_paid_calls():
    assert cost_report_fields(cost_per_image_usd=0.02, paid_describe_calls=3) == {
        "cost_per_image_usd": 0.02,
        "total_cost_usd": 0.06,
    }


def test_parse_cost_per_image_usd_empty_is_none():
    assert parse_cost_per_image_usd(None) is None
    assert parse_cost_per_image_usd("") is None
    assert parse_cost_per_image_usd("0.015") == 0.015
