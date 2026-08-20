"""ALTQ-1 Slice 3: cost/latency axis in the bake-off report builder.

Deterministic per-image cost = flat instance $/hr x measured inference seconds
(``rate * latency_s / 3600``) plus an optional run-total / cost-per-image
subtitle. Every assertion is paired with a discrimination guard [TEST-15]:
the same code path with the cost inputs *absent* must NOT emit the cost token,
so a green here proves the renderer reacts to the input rather than always
printing (or always omitting) a cost.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.eval_harness.build_bakeoff_report import _card_html, main

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


# --- VLM6-CTRL: manifest-comparability gate -------------------------------
#
# A 646-image run record is a superset of a 10-image manifest, so every cell
# populates and the column renders as an unmarked "(control)". The gate refuses
# that silently-wrong comparison [EVAL-01 same split, EXP-07 mismatched
# allocation invalidates]. Each assertion is paired with a discrimination guard
# [TEST-15]: the same path with a *matching* sha must exit 0 and carry no badge,
# so a green here proves the gate reacts to provenance rather than always firing.

_V3_MANIFEST = str(Path(__file__).resolve().parents[2] / "scripts/eval_harness/bakeoff10-manifest-20260716.json")


def _v3_sha() -> str:
    from scripts.eval_harness.build_bakeoff_report import _manifest_identity

    sha, mode = _manifest_identity(_V3_MANIFEST)
    assert mode == "verified against manifest"
    assert sha
    return sha


def _v3_media_ids() -> list[int]:
    return [int(e["media_id"]) for e in json.loads(Path(_V3_MANIFEST).read_text())["entries"]][:2]


def _run_record(tmp_path: Path, name: str, media_ids: list[int], sha: str | None) -> Path:
    rec: dict = {"items": [{"media_id": m, "describe": {"alt_text_draft": f"d{m}", "passes": [{"latency_s": 1.0}]}}
                           for m in media_ids]}
    if sha is not None:
        rec["provenance"] = {"manifest_sha256": sha}
    path = tmp_path / name
    path.write_text(json.dumps(rec))
    return path


def _build(tmp_path: Path, runs: list[str], *extra: str, manifest: str = _V3_MANIFEST) -> tuple[int, Path]:
    from scripts.eval_harness.build_bakeoff_report import main as build_main

    out = tmp_path / f"report-{len(list(tmp_path.iterdir()))}.html"
    argv = ["--manifest", manifest, "--out", str(out),
            "--media-ids", ",".join(str(m) for m in _v3_media_ids())]
    for spec in runs:
        argv += ["--run", spec]
    return build_main(argv + list(extra)), out


def test_matching_manifest_sha_renders_unbadged(tmp_path: Path) -> None:
    ids = _v3_media_ids()
    rec = _run_record(tmp_path, "ok.json", ids, _v3_sha())
    rc, out = _build(tmp_path, [f"Candidate={rec}"])
    assert rc == 0
    doc = out.read_text()
    assert "NOT COMPARABLE" not in doc
    assert "manifest identity: verified against manifest" in doc


def test_foreign_manifest_sha_is_fatal_and_writes_nothing(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    ids = _v3_media_ids()
    rec = _run_record(tmp_path, "foreign.json", ids, "f" * 64)
    rc, out = _build(tmp_path, [f"Qwen3-VL-30B (control)={rec}"])
    assert rc == 3
    assert not out.exists()  # a refused report must not leave a readable artifact
    err = capsys.readouterr().err
    assert "ffffffffffff" in err and _v3_sha()[:12] in err  # both shas named
    assert "--allow-foreign-run" in err  # the error tells the operator the way out


def test_missing_provenance_is_fatal_against_a_real_manifest(tmp_path: Path) -> None:
    rec = _run_record(tmp_path, "noprov.json", _v3_media_ids(), None)
    rc, _ = _build(tmp_path, [f"Candidate={rec}"])
    assert rc == 3


def test_consent_keeps_the_column_but_badges_it(tmp_path: Path) -> None:
    ids = _v3_media_ids()
    foreign = _run_record(tmp_path, "foreign2.json", ids, "a" * 64)
    native = _run_record(tmp_path, "native.json", ids, _v3_sha())
    rc, out = _build(tmp_path, [f"Control={foreign}", f"Candidate={native}"],
                     "--allow-foreign-run", "Control")
    assert rc == 0
    doc = out.read_text()
    assert "NOT COMPARABLE" in doc
    # The badge names the offending sha, and only the foreign column carries it.
    assert doc.count("NOT COMPARABLE") >= 1
    assert "aaaaaaaaaaaa" in doc


def test_non_v3_manifest_falls_back_to_cross_run_agreement(tmp_path: Path) -> None:
    mpath, _ = _write_fixtures(tmp_path)  # toy manifest: no manifest_version
    a = _run_record(tmp_path, "a.json", [1, 2], "1" * 64)
    b_same = _run_record(tmp_path, "b_same.json", [1, 2], "1" * 64)
    b_diff = _run_record(tmp_path, "b_diff.json", [1, 2], "2" * 64)

    from scripts.eval_harness.build_bakeoff_report import main as build_main

    out_ok = tmp_path / "ok.html"
    assert build_main(["--manifest", str(mpath), "--run", f"A={a}", "--run", f"B={b_same}",
                       "--media-ids", "1,2", "--out", str(out_ok)]) == 0
    assert "manifest identity: cross-run only" in out_ok.read_text()

    # Discrimination guard: same code path, one disagreeing sha => fatal.
    out_bad = tmp_path / "bad.html"
    assert build_main(["--manifest", str(mpath), "--run", f"A={a}", "--run", f"B={b_diff}",
                       "--media-ids", "1,2", "--out", str(out_bad)]) == 3
    assert not out_bad.exists()
