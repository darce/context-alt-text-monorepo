"""Bake-off HTML report builder: cost/latency, token roll-up, failure frame.

Deterministic per-image cost = flat instance $/hr x measured inference seconds
(``rate * latency_s / 3600``) plus an optional run-total / cost-per-image
subtitle. Every assertion is paired with a discrimination guard [TEST-15]:
the same code path with the cost inputs *absent* must NOT emit the cost token,
so a green here proves the renderer reacts to the input rather than always
printing (or always omitting) a cost.

BR-01: the 10-image frame and the ``--cost-total`` denominator must include
every *attempted* media_id, including timeouts and transport failures.
BR-04: ``_tokens_label`` / ``_index_run`` are the token axis; they have no
other home. Tests below kill ``return ""`` and a missing ``tokens`` key.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.eval_harness.build_bakeoff_report import (
    _card_html,
    _index_run,
    _pick_varied,
    _tokens_label,
    main,
)

_ENTRY = {"path": "mock_images/alice-pool.jpg", "present_identities": ["Alice Example"]}
_RUN = {
    "Qwen3-VL-30B": {
        1: {"title": "Alice", "alt": "Alice by a pool.", "caption": "A long caption.",
            "latency_s": 5.0, "model_calls": 2, "error": None},
    }
}


def test_card_cost_rendered_only_when_hourly_rate_given() -> None:
    # rate 7.2 $/hr x 5.0 s / 3600 = $0.01000/img — clean closed-form value.
    with_rate = _card_html(1, _ENTRY, _RUN, None, hourly_rate=7.2)
    assert "$0.01000/img" in with_rate

    # Discrimination guard: same card, no rate => the cost token must vanish,
    # while the latency it is derived from stays. If this branch also printed a
    # cost the test above would be vacuous.
    without_rate = _card_html(1, _ENTRY, _RUN, None)
    assert "5.00s" in without_rate
    assert "/img" not in without_rate


def test_card_no_cost_when_latency_missing_even_with_rate() -> None:
    run_no_lat = {"M": {1: {"alt": "x", "latency_s": None, "model_calls": 1, "error": None}}}
    card = _card_html(1, _ENTRY, run_no_lat, None, hourly_rate=7.2)
    assert "/img" not in card  # no latency => no deterministic per-image cost


def _write_fixtures(tmp_path: Path) -> tuple[Path, Path]:
    manifest = {"entries": [{"media_id": 1, "path": "mock_images/a.jpg", "present_identities": []},
                            {"media_id": 2, "path": "mock_images/b.jpg", "present_identities": []}]}
    record = {"items": [
        {"media_id": 1, "describe": {"alt_text_draft": "a", "passes": [{"latency_s": 4.0}]}},
        {"media_id": 2, "describe": {"alt_text_draft": "b", "passes": [{"latency_s": 6.0}]}},
    ]}
    mpath = tmp_path / "manifest.json"
    rpath = tmp_path / "run.json"
    mpath.write_text(json.dumps(manifest))
    rpath.write_text(json.dumps(record))
    return mpath, rpath


def test_main_hourly_rate_renders_per_image_cost(tmp_path: Path) -> None:
    mpath, rpath = _write_fixtures(tmp_path)  # media 1,2 with pass latency 4.0s, 6.0s
    out = tmp_path / "report.html"

    # 7.2 $/hr x 4.0 s / 3600 = $0.00800/img ; x 6.0 s = $0.01200/img
    rc = main(["--manifest", str(mpath), "--run", f"M={rpath}",
               "--media-ids", "1,2", "--out", str(out), "--hourly-rate", "7.2"])
    assert rc == 0
    doc = out.read_text()
    assert "$0.00800/img" in doc
    assert "$0.01200/img" in doc

    # Discrimination guard: no --hourly-rate => the per-image cost token vanishes.
    rc = main(["--manifest", str(mpath), "--run", f"M={rpath}",
               "--media-ids", "1,2", "--out", str(out)])
    assert rc == 0
    assert "/img" not in out.read_text()


def test_main_hourly_rate_zero_is_free_not_suppressed(tmp_path: Path) -> None:
    # 0 $/hr is a legitimate free-tier rate; it must render $0, not be dropped as falsy.
    mpath, rpath = _write_fixtures(tmp_path)
    out = tmp_path / "report.html"
    rc = main(["--manifest", str(mpath), "--run", f"M={rpath}",
               "--media-ids", "1,2", "--out", str(out), "--hourly-rate", "0"])
    assert rc == 0
    assert "$0.00000/img" in out.read_text()


def test_main_rejects_negative_cost_args(tmp_path: Path) -> None:
    mpath, rpath = _write_fixtures(tmp_path)
    out = tmp_path / "report.html"
    for bad in (["--hourly-rate", "-1"], ["--cost-total", "-5"]):
        with pytest.raises(SystemExit):  # argparse .error() exits non-zero
            main(["--manifest", str(mpath), "--run", f"M={rpath}",
                  "--media-ids", "1,2", "--out", str(out), *bad])


def test_subtitle_cost_total_rendered_only_with_flag(tmp_path: Path) -> None:
    mpath, rpath = _write_fixtures(tmp_path)
    out = tmp_path / "report.html"

    rc = main(["--manifest", str(mpath), "--run", f"M={rpath}",
               "--media-ids", "1,2", "--out", str(out), "--cost-total", "10.0"])
    assert rc == 0
    doc = out.read_text()
    assert "total $10.00" in doc
    assert "$5.0000/image" in doc  # 10.0 / 2 images

    # Discrimination guard: drop --cost-total, the subtitle cost fragment goes away.
    rc = main(["--manifest", str(mpath), "--run", f"M={rpath}",
               "--media-ids", "1,2", "--out", str(out)])
    assert rc == 0
    doc = out.read_text()
    assert "total $" not in doc
    assert "/image" not in doc


# ---------------------------------------------------------------------------
# BR-04 — token column: _tokens_label reader contract + _index_run key
# ---------------------------------------------------------------------------

_TOKENS_NONE = {
    "prompt_tokens": None,
    "completion_tokens": None,
    "total_tokens": None,
    "complete": False,
}
_TOKENS_PARTIAL = {
    "prompt_tokens": 2400,
    "completion_tokens": 410,
    "total_tokens": 2810,
    "complete": False,
}
_TOKENS_COMPLETE = {
    "prompt_tokens": 2400,
    "completion_tokens": 410,
    "total_tokens": 2810,
    "complete": True,
}


def test_tokens_label_none_counts_are_not_captured() -> None:
    # Zero passes carried usage: counts are None, complete is False.
    # Empty string is the bug — operator cannot tell "not measured" from N/A.
    assert _tokens_label(_TOKENS_NONE) == " · tokens not captured"


def test_tokens_label_partial_integer_counts_mark_incomplete() -> None:
    # Some-but-not-all passes carried usage: integer sums, complete False.
    # The trailing + is the only signal a partial sum is not the whole image.
    assert _tokens_label(_TOKENS_PARTIAL) == " · 2810+ tok (410 out)"


def test_tokens_label_complete_integer_counts_are_plain() -> None:
    assert _tokens_label(_TOKENS_COMPLETE) == " · 2810 tok (410 out)"


def test_tokens_label_integer_zero_does_not_crash() -> None:
    # Characterisation: current writer shape (bare integer 0, or a dict of
    # zeros) may land before or after the sibling _sum_usage change. Must
    # not raise. No kill power on the BR-04 mutations — those live above.
    bare = _tokens_label(0)
    assert isinstance(bare, str)
    zeros = _tokens_label(
        {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "complete": False}
    )
    assert isinstance(zeros, str)


def test_card_html_renders_tokens_not_captured_marker() -> None:
    run = {
        "Qwen3-VL-30B": {
            1: {
                "title": "Alice",
                "alt": "Alice by a pool.",
                "caption": "A long caption.",
                "latency_s": 5.0,
                "model_calls": 2,
                "error": None,
                "tokens": _TOKENS_NONE,
            }
        }
    }
    card = _card_html(1, _ENTRY, run, None)
    assert "tokens not captured" in card


def test_index_run_always_carries_tokens_key(tmp_path: Path) -> None:
    # Deleting the "tokens" key from the _index_run payload used to go green.
    record = {
        "items": [
            {
                "media_id": 7,
                "describe": {"alt_text_draft": "x", "passes": [{"latency_s": 1.0}]},
                "error": None,
            }
        ]
    }
    path = tmp_path / "run.json"
    path.write_text(json.dumps(record))
    indexed = _index_run(str(path))
    assert "tokens" in indexed[7]


def test_index_run_forwards_describe_tokens(tmp_path: Path) -> None:
    record = {
        "items": [
            {
                "media_id": 7,
                "describe": {
                    "alt_text_draft": "x",
                    "passes": [{"latency_s": 1.0}],
                    "tokens": _TOKENS_COMPLETE,
                },
                "error": None,
            }
        ]
    }
    path = tmp_path / "run.json"
    path.write_text(json.dumps(record))
    indexed = _index_run(str(path))
    assert indexed[7]["tokens"] == _TOKENS_COMPLETE


# ---------------------------------------------------------------------------
# BR-01 — sampling frame + cost denominator admit attempted failures
# ---------------------------------------------------------------------------

def test_pick_varied_admits_errored_attempted_ids() -> None:
    manifest = {
        10: {"present_identities": []},
        20: {"present_identities": []},
    }
    runs = {
        "M": {
            10: {"error": None, "caption": "ok", "alt": "ok"},
            20: {"error": "RemoteClientError: timeout", "caption": None, "alt": None},
        }
    }
    picked = _pick_varied(manifest, runs, 10)
    assert 10 in picked
    assert 20 in picked


def test_pick_varied_keeps_image_both_legs_failed() -> None:
    # Pair report must not omit the image both generations blew the 900 s ceiling on.
    manifest = {
        1: {"present_identities": []},
        2: {"present_identities": []},
        3: {"present_identities": []},
    }
    runs = {
        "prev": {
            1: {"error": None, "caption": "a", "alt": "a"},
            2: {"error": None, "caption": "b", "alt": "b"},
            3: {"error": "timeout", "caption": None, "alt": None},
        },
        "curr": {
            1: {"error": None, "caption": "a2", "alt": "a2"},
            2: {"error": None, "caption": "b2", "alt": "b2"},
            3: {"error": "timeout", "caption": None, "alt": None},
        },
    }
    picked = _pick_varied(manifest, runs, 10)
    assert 3 in picked


def _write_attempted_with_error(tmp_path: Path) -> tuple[Path, Path]:
    """Three attempted images; media 3 is a timeout. Display sample can be a subset."""
    manifest = {
        "entries": [
            {"media_id": 1, "path": "mock_images/a.jpg", "present_identities": []},
            {"media_id": 2, "path": "mock_images/b.jpg", "present_identities": []},
            {"media_id": 3, "path": "mock_images/c.jpg", "present_identities": []},
        ]
    }
    record = {
        "items": [
            {"media_id": 1, "describe": {"alt_text_draft": "a", "passes": [{"latency_s": 4.0}]}},
            {"media_id": 2, "describe": {"alt_text_draft": "b", "passes": [{"latency_s": 6.0}]}},
            {
                "media_id": 3,
                "error": "RemoteClientError: timeout",
                "describe": {},
            },
        ]
    }
    mpath = tmp_path / "manifest.json"
    rpath = tmp_path / "run.json"
    mpath.write_text(json.dumps(manifest))
    rpath.write_text(json.dumps(record))
    return mpath, rpath


def test_cost_denominator_is_attempted_corpus_including_errors(tmp_path: Path) -> None:
    # 3 attempted (one timeout), display only the two survivors, cost $9.
    # Denominator is the corpus (9/3 = $3.0000), not the display sample (9/2 = $4.5000).
    mpath, rpath = _write_attempted_with_error(tmp_path)
    out = tmp_path / "report.html"
    rc = main(
        [
            "--manifest",
            str(mpath),
            "--run",
            f"M={rpath}",
            "--media-ids",
            "1,2",
            "--out",
            str(out),
            "--cost-total",
            "9.0",
        ]
    )
    assert rc == 0
    doc = out.read_text()
    assert "total $9.00" in doc
    assert "$3.0000/image" in doc
    assert "$4.5000/image" not in doc


def test_auto_pick_renders_failure_card_for_errored_item(tmp_path: Path) -> None:
    mpath, rpath = _write_attempted_with_error(tmp_path)
    out = tmp_path / "report.html"
    rc = main(["--manifest", str(mpath), "--run", f"M={rpath}", "--out", str(out), "--limit", "10"])
    assert rc == 0
    doc = out.read_text()
    assert 'class="err"' in doc
    assert "RemoteClientError: timeout" in doc
    assert ">#3<" in doc or "#3" in doc
