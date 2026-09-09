"""VLM-6 S1: model-derived face counts for the people/faces/crowds strata."""

import hashlib
import json

import pytest

from scripts.eval_harness.corpus_inventory import ImageRecord
from scripts.eval_harness.face_pass import (
    MEDIA_ID_BASE,
    MEDIA_ID_CEILING,
    FacePassRow,
    FacePassStalledError,
    SeededTenantError,
    assert_scratch_tenant,
    assign_media_ids,
    load_face_counts,
    load_face_pass_rows,
    run_face_pass,
    select_candidates,
    summarize,
    write_rows,
)
from scripts.eval_harness.strata import Source


def rec(path="a.jpg", **over) -> ImageRecord:
    """A full-shape ImageRecord; override only what a test is about."""
    base = {
        "path": path,
        "sha256": f"sha-{path}",
        "width": 800,
        "height": 600,
        "mean_saturation": 0.4,
        "mean_value": 0.5,
        "aspect_ratio": 1.3333,
        "celeb_name": None,
        "xmp_names": [],
        "xmp_face_count": 0,
        "bw_candidate": False,
        "low_light_candidate": False,
        "flat_color_coverage": 0.1,
        "flat_color_candidate": False,
        "edge_density": 0.2,
    }
    base.update(over)
    return ImageRecord(**base)


class FakeClient:
    """Records calls; returns one identity row per face in ``faces_by_media_id``."""

    def __init__(self, faces_by_media_id=None, labeled_clusters=(), fail_on=()):
        self.faces = faces_by_media_id or {}
        self.labeled_clusters = list(labeled_clusters)
        self.fail_on = set(fail_on)
        self.analyzed: list[int] = []
        self.closed = False

    def analyze(self, images):
        media_id = images[0][0]
        self.analyzed.append(media_id)
        if media_id in self.fail_on:
            raise RuntimeError(f"boom on {media_id}")
        return f"job-{media_id}"

    def wait_job(self, job_id):
        return {"status": "completed"}

    def media_identities(self, media_ids):
        media_id = media_ids[0]
        return [
            {"media_id": media_id, "cluster_label": None, "is_auto_label": None}
            for _ in range(self.faces.get(media_id, 0))
        ]

    def clusters(self, labeled_only=False):
        return self.labeled_clusters if labeled_only else []

    def close(self):
        self.closed = True


def write_images(tmp_path, *names) -> None:
    for name in names:
        (tmp_path / name).write_bytes(b"fake-image-bytes")


# --- tenant guard -----------------------------------------------------------


def test_refuses_a_tenant_that_has_labeled_clusters():
    # The roster-seeded eval tenant's fingerprint. Writing face rows here would let
    # the next clustering run merge strangers into labeled celeb clusters.
    client = FakeClient(labeled_clusters=[{"id": "c1", "label": "al_pacino"}])
    with pytest.raises(SeededTenantError, match="roster-seeded"):
        assert_scratch_tenant(client)


def test_accepts_a_tenant_with_no_labeled_clusters():
    assert_scratch_tenant(FakeClient())  # does not raise


# --- selection --------------------------------------------------------------


def test_selects_only_uploads_lacking_xmp_face_data():
    rows = [
        (rec("has-xmp.jpg", xmp_face_count=2), Source.LOCALWP_UPLOADS),  # XMP wins; don't spend a call
        (rec("no-xmp.jpg"), Source.LOCALWP_UPLOADS),
        (rec("celeb.jpg"), Source.CELEBS01),  # identification set, not the gap
    ]
    assert [r.path for r, _ in select_candidates(rows)] == ["no-xmp.jpg"]


def test_selection_skips_already_completed_images():
    rows = [(rec("a.jpg"), Source.LOCALWP_UPLOADS), (rec("b.jpg"), Source.LOCALWP_UPLOADS)]
    picked = select_candidates(rows, done_sha256=frozenset({"sha-a.jpg"}))
    assert [r.path for r, _ in picked] == ["b.jpg"]


def test_selection_dedupes_identical_bytes():
    rows = [
        (rec("one.jpg", sha256="same"), Source.LOCALWP_UPLOADS),
        (rec("two.jpg", sha256="same"), Source.LOCALWP_UPLOADS),
    ]
    assert len(select_candidates(rows)) == 1


def hashed(path: str) -> ImageRecord:
    """A record with a REALISTIC content hash — selection order depends on hashes
    being uniformly distributed, which `sha-<path>` is not."""
    return rec(path, sha256=hashlib.sha256(path.encode()).hexdigest())


def test_a_bounded_limit_samples_folders_in_proportion_to_their_size():
    # The real uploads tree has a 142-image folder beside a 3088-image one. Strata's
    # round-robin browse order would hand the small folder a third of the budget; a
    # sample meant to find people at their base rate must mirror the pool instead.
    rows = [(hashed(f"big/{i}.jpg"), Source.LOCALWP_UPLOADS) for i in range(300)]
    rows += [(hashed(f"small/{i}.jpg"), Source.LOCALWP_UPLOADS) for i in range(30)]

    picked = select_candidates(rows, limit=110)  # a third of a 330-image pool
    small = sum(1 for r, _ in picked if r.path.startswith("small/"))

    assert 3 <= small <= 20  # ~10 expected (9%); round-robin would give 55
    assert len(picked) == 110


def test_selection_is_deterministic_across_runs():
    rows = [(hashed(f"a/{i}.jpg"), Source.LOCALWP_UPLOADS) for i in range(50)]
    assert [r.path for r, _ in select_candidates(rows, limit=10)] == [
        r.path for r, _ in select_candidates(list(reversed(rows)), limit=10)
    ]


def test_excludes_images_below_the_resolution_floor():
    # The uploads tree holds 217 ~80x112 face crops: derivatives of photos already in
    # the corpus, trivially one face, and undescribable by any model under test.
    rows = [
        (rec("crop.jpg", width=79, height=112), Source.LOCALWP_UPLOADS),
        (rec("photo.jpg", width=1080, height=1350), Source.LOCALWP_UPLOADS),
    ]
    assert [r.path for r, _ in select_candidates(rows)] == ["photo.jpg"]


def test_excludes_unreadable_images():
    rows = [
        (rec("broken.jpg", width=None, height=None), Source.LOCALWP_UPLOADS),
        (rec("photo.jpg"), Source.LOCALWP_UPLOADS),
    ]
    assert [r.path for r, _ in select_candidates(rows)] == ["photo.jpg"]


# --- media id assignment ----------------------------------------------------


def test_media_ids_start_at_the_base_and_are_stable():
    rows = [(rec("a.jpg"), Source.LOCALWP_UPLOADS), (rec("b.jpg"), Source.LOCALWP_UPLOADS)]
    assert [mid for _, _, mid in assign_media_ids(rows)] == [MEDIA_ID_BASE, MEDIA_ID_BASE + 1]


def test_checkpointed_media_id_wins_so_a_resume_rewrites_the_same_server_rows():
    rows = [(rec("a.jpg"), Source.LOCALWP_UPLOADS), (rec("b.jpg"), Source.LOCALWP_UPLOADS)]
    assigned = assign_media_ids(rows, existing={"sha-a.jpg": 900_042})
    assert [mid for _, _, mid in assigned] == [900_042, MEDIA_ID_BASE]


def test_fresh_ids_never_collide_with_a_checkpointed_one():
    rows = [(rec("a.jpg"), Source.LOCALWP_UPLOADS), (rec("b.jpg"), Source.LOCALWP_UPLOADS)]
    assigned = assign_media_ids(rows, existing={"sha-b.jpg": MEDIA_ID_BASE})
    assert [mid for _, _, mid in assigned] == [MEDIA_ID_BASE + 1, MEDIA_ID_BASE]


def test_rejects_a_media_id_the_analyze_route_would_truncate():
    # `_extract_media_id` keeps only the last 6 digits, so a 7-digit id silently
    # becomes another image's id instead of erroring. Refuse to emit one.
    rows = [(rec("a.jpg"), Source.LOCALWP_UPLOADS)]
    with pytest.raises(ValueError, match="truncates"):
        assign_media_ids(rows, existing={"sha-a.jpg": MEDIA_ID_CEILING + 1})


# --- the pass ---------------------------------------------------------------


def test_records_a_face_count_per_image(tmp_path):
    write_images(tmp_path, "a.jpg", "b.jpg")
    candidates = [
        (rec("a.jpg"), Source.LOCALWP_UPLOADS, 900_000),
        (rec("b.jpg"), Source.LOCALWP_UPLOADS, 900_001),
    ]
    client = FakeClient({900_000: 3, 900_001: 0})
    out = tmp_path / "faces.jsonl"

    rows = run_face_pass(candidates, client, roots={Source.LOCALWP_UPLOADS: tmp_path}, out=out)

    assert [r.face_count for r in rows] == [3, 0]
    assert load_face_counts(out) == {"sha-a.jpg": 3, "sha-b.jpg": 0}


def test_a_failed_item_is_isolated_and_never_reads_as_zero_faces(tmp_path):
    # A network failure must not enter the corpus as "this image has no people".
    write_images(tmp_path, "a.jpg", "b.jpg")
    candidates = [
        (rec("a.jpg"), Source.LOCALWP_UPLOADS, 900_000),
        (rec("b.jpg"), Source.LOCALWP_UPLOADS, 900_001),
    ]
    client = FakeClient({900_001: 2}, fail_on={900_000})
    out = tmp_path / "faces.jsonl"

    rows = run_face_pass(candidates, client, roots={Source.LOCALWP_UPLOADS: tmp_path}, out=out)

    assert rows[0].error is not None and rows[0].face_count is None
    assert rows[1].face_count == 2  # the pass continued
    assert "sha-a.jpg" not in load_face_counts(out)


def test_a_missing_file_is_an_item_error_not_a_crash(tmp_path):
    candidates = [(rec("gone.jpg"), Source.LOCALWP_UPLOADS, 900_000)]
    out = tmp_path / "faces.jsonl"
    rows = run_face_pass(candidates, FakeClient(), roots={Source.LOCALWP_UPLOADS: tmp_path}, out=out)
    assert "FileNotFoundError" in rows[0].error


def test_consecutive_failures_abort_the_pass_with_the_checkpoint_named(tmp_path):
    # A dead tunnel or expired key would otherwise write 800 error rows and exit 0.
    names = [f"{i}.jpg" for i in range(6)]
    write_images(tmp_path, *names)
    candidates = [(rec(n), Source.LOCALWP_UPLOADS, 900_000 + i) for i, n in enumerate(names)]
    client = FakeClient(fail_on={900_000 + i for i in range(6)})
    out = tmp_path / "faces.jsonl"

    with pytest.raises(FacePassStalledError) as excinfo:
        run_face_pass(candidates, client, roots={Source.LOCALWP_UPLOADS: tmp_path}, out=out, stall_limit=3)

    assert excinfo.value.checkpoint == out
    assert len(client.analyzed) == 3  # stopped at the limit, did not walk all six
    assert len(load_face_pass_rows(out)) == 3  # the failures are durable, not lost


def test_a_success_resets_the_stall_counter(tmp_path):
    names = [f"{i}.jpg" for i in range(4)]
    write_images(tmp_path, *names)
    candidates = [(rec(n), Source.LOCALWP_UPLOADS, 900_000 + i) for i, n in enumerate(names)]
    # fail, fail, ok, fail -> never 3 in a row
    client = FakeClient({900_002: 1}, fail_on={900_000, 900_001, 900_003})
    rows = run_face_pass(
        candidates, client, roots={Source.LOCALWP_UPLOADS: tmp_path}, out=tmp_path / "f.jsonl", stall_limit=3
    )
    assert len(rows) == 4


def test_rows_checkpoint_as_they_complete(tmp_path):
    # A kill mid-pass must leave completed work on disk, not in a lost buffer.
    write_images(tmp_path, "a.jpg", "b.jpg")
    out = tmp_path / "faces.jsonl"
    seen: list[int] = []

    def spy(index, row):
        seen.append(len(load_face_pass_rows(out)))

    candidates = [
        (rec("a.jpg"), Source.LOCALWP_UPLOADS, 900_000),
        (rec("b.jpg"), Source.LOCALWP_UPLOADS, 900_001),
    ]
    run_face_pass(
        candidates,
        FakeClient({900_000: 1, 900_001: 1}),
        roots={Source.LOCALWP_UPLOADS: tmp_path},
        out=out,
        on_progress=spy,
    )
    assert seen == [1, 2]


def test_resume_keeps_earlier_rows_and_only_analyzes_the_rest(tmp_path):
    write_images(tmp_path, "b.jpg")
    done = [FacePassRow("sha-a.jpg", "a.jpg", "localwp_uploads", 900_000, 2, [], None)]
    out = tmp_path / "faces.jsonl"
    write_rows(out, done)

    client = FakeClient({900_001: 1})
    rows = run_face_pass(
        [(rec("b.jpg"), Source.LOCALWP_UPLOADS, 900_001)],
        client,
        roots={Source.LOCALWP_UPLOADS: tmp_path},
        out=out,
        resume_rows=done,
    )

    assert client.analyzed == [900_001]  # a.jpg was not re-fetched
    assert {r.sha256 for r in rows} == {"sha-a.jpg", "sha-b.jpg"}
    assert load_face_counts(out) == {"sha-a.jpg": 2, "sha-b.jpg": 1}


def test_resume_drops_stale_error_rows_so_retries_do_not_double_count(tmp_path):
    # An errored resume row is re-selected and retried by _main (done_sha excludes it);
    # run_face_pass must not carry the old error row forward, else a retried-then-succeeded
    # image counts as both an error and an ok and grows the checkpoint each cycle (B-01).
    write_images(tmp_path, "b.jpg")
    errored = FacePassRow("sha-b.jpg", "b.jpg", "localwp_uploads", 900_001, None, [], "TimeoutError: boom")
    out = tmp_path / "faces.jsonl"
    write_rows(out, [errored])

    rows = run_face_pass(
        [(rec("b.jpg"), Source.LOCALWP_UPLOADS, 900_001)],
        FakeClient({900_001: 1}),
        roots={Source.LOCALWP_UPLOADS: tmp_path},
        out=out,
        resume_rows=[errored],
    )

    # exactly one row for the sha — the stale error row is gone, only the fresh success remains
    assert [r.sha256 for r in rows] == ["sha-b.jpg"]
    assert [r.face_count for r in rows] == [1]
    on_disk = load_face_pass_rows(out)
    assert len(on_disk) == 1 and on_disk[0].error is None


def test_resume_preserves_errored_rows_not_retried_this_run(tmp_path):
    # An errored resume row whose sha is NOT in this bounded run's candidates (e.g. beyond
    # --limit) must stay on disk — it hasn't been re-attempted, so dropping it would silently
    # lose outstanding failures from the checkpoint on a bounded/repeated resume (MRG-B-01).
    write_images(tmp_path, "c.jpg")
    errored_a = FacePassRow("sha-a.jpg", "a.jpg", "localwp_uploads", 900_000, None, [], "TimeoutError: boom")
    ok_b = FacePassRow("sha-b.jpg", "b.jpg", "localwp_uploads", 900_001, 2, [], None)
    out = tmp_path / "faces.jsonl"
    write_rows(out, [errored_a, ok_b])

    # this run's candidates = only C; A is NOT retried here
    rows = run_face_pass(
        [(rec("c.jpg"), Source.LOCALWP_UPLOADS, 900_002)],
        FakeClient({900_002: 1}),
        roots={Source.LOCALWP_UPLOADS: tmp_path},
        out=out,
        resume_rows=[errored_a, ok_b],
    )

    assert {r.sha256 for r in rows} == {"sha-a.jpg", "sha-b.jpg", "sha-c.jpg"}
    on_disk = {r.sha256: r for r in load_face_pass_rows(out)}
    assert on_disk["sha-a.jpg"].error is not None  # outstanding failure preserved, not dropped
    assert on_disk["sha-c.jpg"].face_count == 1


# --- execution stats -------------------------------------------------------------


def test_summarize_reports_latency_percentiles():
    # Execution stats: per-call analyze latency as PERCENTILES (PERF-01), from open-loop timing.
    # elapsed_ms is converted to seconds for the shared latency_summary schema (VLM6-RH-04).
    rows = [
        FacePassRow("s1", "a.jpg", "localwp_uploads", 900_000, 2, [], None, elapsed_ms=100.0),
        FacePassRow("s2", "b.jpg", "localwp_uploads", 900_001, 0, [], None, elapsed_ms=300.0),
        FacePassRow("s3", "c.jpg", "localwp_uploads", 900_002, None, [], "TimeoutError: x", elapsed_ms=50.0),
    ]
    s = summarize(rows)
    assert (s["scanned"], s["ok"], s["errors"]) == (3, 2, 1)
    lat = s["latency"]
    assert lat is not None
    assert lat["unit"] == "s"
    assert lat["n"] == 3  # latency measured on ok AND errored calls
    assert lat["p50"] == 0.1 and lat["p95"] == 0.3 and lat["max"] == 0.3
    assert lat["p99"] == 0.3 and lat["min"] == 0.05


def test_summarize_latency_none_on_legacy_rows_without_timing():
    # Rows from the pre-elapsed_ms schema carry no timing -> latency is None, not a crash.
    s = summarize([FacePassRow("s1", "a.jpg", "localwp_uploads", 900_000, 2, [], None)])
    assert s["latency"] is None and s["ok"] == 1


def test_load_face_pass_rows_backfills_missing_elapsed_ms(tmp_path):
    # A checkpoint written by the pre-elapsed_ms schema must still load (elapsed_ms -> None),
    # or a schema addition would silently drop the whole pass on the next --resume (A-06).
    out = tmp_path / "faces.jsonl"
    legacy = {
        "sha256": "s1",
        "path": "a.jpg",
        "source": "localwp_uploads",
        "media_id": 900_000,
        "face_count": 2,
        "names": [],
        "error": None,  # no elapsed_ms key
    }
    out.write_text(json.dumps(legacy) + "\n")
    rows = load_face_pass_rows(out)
    assert len(rows) == 1 and rows[0].elapsed_ms is None and rows[0].face_count == 2


def test_a_truncated_final_line_is_dropped_rather_than_crashing_the_resume(tmp_path):
    out = tmp_path / "faces.jsonl"
    good = FacePassRow("sha-a.jpg", "a.jpg", "localwp_uploads", 900_000, 1, [], None)
    out.write_text(json.dumps(good.__dict__) + "\n" + '{"sha256": "sha-b.jpg", "path": "b.jp')
    assert [r.sha256 for r in load_face_pass_rows(out)] == ["sha-a.jpg"]


def test_summary_counts_crowds_and_errors():
    rows = [
        FacePassRow("s1", "a.jpg", "localwp_uploads", 900_000, 4, [], None),
        FacePassRow("s2", "b.jpg", "localwp_uploads", 900_001, 0, [], None),
        FacePassRow("s3", "c.jpg", "localwp_uploads", 900_002, None, [], "RuntimeError: boom"),
    ]
    assert summarize(rows) == {
        "scanned": 3,
        "ok": 2,
        "errors": 1,
        "with_faces": 1,
        "crowds": 1,
        "faces_found": 4,
        "latency": None,  # these rows carry no elapsed_ms (legacy shape)
    }


# --- A-01: names element type (dict rows, not bare strings) -------------------


def test_face_pass_row_names_type_is_list_of_dict():
    """FacePassRow.names is list[dict], matching _extract_identities output."""
    from typing import get_type_hints

    hints = get_type_hints(FacePassRow)
    # Annotated as list[dict[str, Any]] (or equivalent); not list[str].
    assert "dict" in str(hints["names"]).lower()
    assert "str" not in str(hints["names"]).replace("dict[str", "")


def test_load_face_pass_rows_rejects_bare_string_names(tmp_path):
    """A-01: wrong element shape fails loudly — no silent dual-shape load."""
    out = tmp_path / "faces.jsonl"
    out.write_text(
        json.dumps(
            {
                "sha256": "s1",
                "path": "a.jpg",
                "source": "localwp_uploads",
                "media_id": 900_000,
                "face_count": 1,
                "names": ["Amy"],  # legacy bare-string shape
                "error": None,
            }
        )
        + "\n"
    )
    with pytest.raises(ValueError, match="names\\[0\\] must be a dict"):
        load_face_pass_rows(out)


def test_load_face_pass_rows_accepts_dict_identity_names(tmp_path):
    """A-01: positional dict rows load cleanly."""
    out = tmp_path / "faces.jsonl"
    names = [{"name": "Amy", "bbox": {"x": 1, "y": 2, "width": 3, "height": 4}, "unpositioned": False}]
    out.write_text(
        json.dumps(
            {
                "sha256": "s1",
                "path": "a.jpg",
                "source": "localwp_uploads",
                "media_id": 900_000,
                "face_count": 1,
                "names": names,
                "error": None,
            }
        )
        + "\n"
    )
    rows = load_face_pass_rows(out)
    assert len(rows) == 1
    assert rows[0].names == names
