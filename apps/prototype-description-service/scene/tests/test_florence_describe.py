"""VLM-6 on-box florence_describe driver — model-stubbed unit tests.

Covers TSV parsing / path remapping, resume-skip, bounded-stall abort (rg-007),
JSONL row shape, and revision-pin parity with scene/config/profiles.py. The
model itself is never loaded: ``run`` takes an injected captioner.
"""

import json
from pathlib import Path

import pytest

from scene.config.profiles import PROFILE_SPECS, DescriptionProfile
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
    out.write_text(json.dumps({"attachment_id": 1}) + "\n" + '{"attachment_id": 2, "capt')
    assert done_ids(out) == {1}


def test_run_skips_already_done_ids_and_missing_files(corpus, tmp_path):
    out = tmp_path / "out.jsonl"
    out.write_text(json.dumps({"attachment_id": 1}) + "\n")
    rows = [
        (1, corpus / "2026" / "07" / "img-1.png"),  # done: skipped
        (2, corpus / "2026" / "07" / "img-2.png"),
        (3, corpus / "missing.png"),  # not on disk: counted, not captioned
    ]
    seen: list[int] = []
    summary = _run(rows, lambda p: seen.append(1) or "A photo.", out)
    assert summary == {
        "total": 3,
        "already_done": 1,
        "missing": 1,
        "captioned_ok": 1,
        "errors": 0,
        "mean_latency_s": summary["mean_latency_s"],
    }
    assert len(seen) == 1
    recorded = [json.loads(ln)["attachment_id"] for ln in out.read_text().splitlines()]
    assert recorded == [1, 2]


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
    assert MODEL_SPECS["large-ft"].revision == large.model_revision  # unpinned: logged at load


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
