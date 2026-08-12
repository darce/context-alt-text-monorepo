"""VLM-6 la3: describe_baseline fail-closed corpus + tenant + no silent clobber.

Findings: VLM6-RH-01 (empty corpus clobbers committed reports), VLM6-RH-02
(unguarded tenant write vs face_pass.assert_scratch_tenant).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.eval_harness import describe_baseline as db
from scripts.eval_harness.face_pass import SeededTenantError

# --- helpers -----------------------------------------------------------------


def _seed_report(path: Path, body: str = '{"summary":{"total":99},"items":[{"media_id":1}]}\n') -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)


def _write_tsv(path: Path, rows: list[tuple[int, Path]]) -> None:
    path.write_text("".join(f"{mid}\t{p}\n" for mid, p in rows))


def _patch_report_paths(monkeypatch, tmp_path: Path) -> dict[str, Path]:
    paths = {
        "jsonl": tmp_path / "scratch" / "baseline.jsonl",
        "report_json": tmp_path / "results" / "baseline.json",
        "report_md": tmp_path / "results" / "baseline.md",
        "tsv": tmp_path / "attachments.tsv",
        "uploads": tmp_path / "uploads",
    }
    paths["jsonl"].parent.mkdir(parents=True, exist_ok=True)
    paths["report_json"].parent.mkdir(parents=True, exist_ok=True)
    paths["uploads"].mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(db, "JSONL", paths["jsonl"])
    monkeypatch.setattr(db, "REPORT_JSON", paths["report_json"])
    monkeypatch.setattr(db, "REPORT_MD", paths["report_md"])
    monkeypatch.setattr(db, "ATTACH_TSV", paths["tsv"])
    monkeypatch.setattr(db, "RESULTS", paths["report_json"].parent)
    monkeypatch.setattr(db, "SCRATCH", paths["jsonl"].parent)
    return paths


class _FakeRemoteClient:
    """RemoteSceneClient stand-in: records analyze writes; clusters for tenant guard."""

    def __init__(self, labeled_clusters=()):
        self.labeled_clusters = list(labeled_clusters)
        self.analyzed: list[int] = []
        self.closed = False
        self.base_url = "https://example.test"

    def describe(self, *, image_bytes, filename, media_id, context_pack):
        return {
            "alt_text_draft": "a photo",
            "model_id": "test-model",
            "cached": False,
        }

    def analyze(self, images):
        media_id = images[0][0]
        self.analyzed.append(media_id)
        return f"job-{media_id}"

    def wait_job(self, job_id):
        return {"status": "completed"}

    def media_identities(self, media_ids):
        return []

    def clusters(self, labeled_only=False):
        return self.labeled_clusters if labeled_only else []

    def close(self):
        self.closed = True


# --- VLM6-RH-01: zero corpus must fail closed, never clobber -----------------


def test_resolve_uploads_requires_flag_or_env(monkeypatch):
    monkeypatch.delenv("BASELINE_UPLOADS", raising=False)
    with pytest.raises(SystemExit, match="BASELINE_UPLOADS|--uploads"):
        db.resolve_uploads_root(None)


def test_resolve_uploads_rejects_missing_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("BASELINE_UPLOADS", raising=False)
    missing = tmp_path / "no-such-uploads"
    with pytest.raises(SystemExit, match="does not exist"):
        db.resolve_uploads_root(str(missing))


def test_resolve_uploads_accepts_env(tmp_path, monkeypatch):
    monkeypatch.setenv("BASELINE_UPLOADS", str(tmp_path))
    assert db.resolve_uploads_root(None) == tmp_path.resolve()


def test_main_zero_corpus_exits_nonzero_and_names_remedy(tmp_path, monkeypatch, capsys):
    """OBS-04 / RH-01: missing images => non-zero exit naming path + flag/env."""
    paths = _patch_report_paths(monkeypatch, tmp_path)
    # TSV points at absolute operator-style paths that do not exist here.
    _write_tsv(
        paths["tsv"],
        [(1, Path("/Volumes/Butter/WP/vlm/app/public/wp-content/uploads/2026/07/a.jpg"))],
    )
    # Pre-seed a non-empty committed-style report that must survive.
    original = '{"summary":{"total":42},"items":[{"media_id":42,"path":"keep-me"}]}\n'
    _seed_report(paths["report_json"], original)
    _seed_report(paths["report_md"], "# keep me\n")

    monkeypatch.delenv("BAKEOFF_BASE_URL", raising=False)
    monkeypatch.setenv("BASELINE_UPLOADS", str(paths["uploads"]))
    # Creds present so failure is about corpus, not auth (if code reaches client).
    monkeypatch.setenv("ACX_EVAL_BASE_URL", "https://example.test")
    monkeypatch.setenv("ACX_EVAL_API_KEY", "test-key-not-secret")
    monkeypatch.setenv("ACX_EVAL_TENANT_ID", "scratch-tenant")

    rc = db.main([])

    assert rc != 0
    err = capsys.readouterr().err
    assert str(paths["uploads"]) in err
    assert "--uploads" in err or "BASELINE_UPLOADS" in err
    # Report must be untouched (no silent empty clobber).
    assert paths["report_json"].read_text() == original
    assert "keep me" in paths["report_md"].read_text()


def test_write_report_refuses_empty_clobber_of_nonempty(tmp_path, monkeypatch):
    """Even if something calls _write_report with empty JSONL, refuse clobber."""
    paths = _patch_report_paths(monkeypatch, tmp_path)
    original = '{"summary":{"total":7},"items":[{"media_id":7}]}\n'
    _seed_report(paths["report_json"], original)
    _seed_report(paths["report_md"], "# non-empty\n")
    # Empty / missing JSONL => empty items.
    if paths["jsonl"].exists():
        paths["jsonl"].unlink()

    with pytest.raises(RuntimeError, match="refusing to overwrite|empty"):
        db._write_report(cost_per_image_usd=None, uploads=paths["uploads"])

    assert paths["report_json"].read_text() == original


def test_write_report_atomic_success_leaves_no_tmp(tmp_path, monkeypatch):
    paths = _patch_report_paths(monkeypatch, tmp_path)
    paths["jsonl"].write_text(
        json.dumps(
            {
                "media_id": 1,
                "path": "a.jpg",
                "error": None,
                "describe": {"alt_text_draft": "x", "model_id": "m"},
                "identities": [],
                "face_count": 0,
                "latency_s": 1.0,
                "completed_at": 1.0,
            }
        )
        + "\n"
    )
    db._write_report(cost_per_image_usd=0.1, uploads=paths["uploads"])
    assert paths["report_json"].is_file()
    assert not list(paths["report_json"].parent.glob("*.tmp"))
    report = json.loads(paths["report_json"].read_text())
    assert report["summary"]["total"] == 1


# --- VLM6-RH-02: tenant guard on write path ----------------------------------


def test_main_calls_assert_scratch_tenant_before_analyze(tmp_path, monkeypatch):
    """RH-02: roster-seeded tenant must be refused before any analyze write."""
    paths = _patch_report_paths(monkeypatch, tmp_path)
    img = paths["uploads"] / "2026" / "07" / "a.jpg"
    img.parent.mkdir(parents=True, exist_ok=True)
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    # TSV uses operator absolute form; re-anchor under --uploads / BASELINE_UPLOADS.
    _write_tsv(
        paths["tsv"],
        [(1, Path("/Volumes/Butter/WP/vlm/app/public/wp-content/uploads/2026/07/a.jpg"))],
    )
    _seed_report(paths["report_json"], '{"summary":{"total":1},"items":[{"media_id":1}]}\n')

    fake = _FakeRemoteClient(labeled_clusters=[{"id": "c1", "label": "seeded_person"}])

    def _client_factory(*_a, **_k):
        return fake

    monkeypatch.delenv("BAKEOFF_BASE_URL", raising=False)
    monkeypatch.setenv("BASELINE_UPLOADS", str(paths["uploads"]))
    monkeypatch.setenv("ACX_EVAL_BASE_URL", "https://example.test")
    monkeypatch.setenv("ACX_EVAL_API_KEY", "test-key-not-secret")
    monkeypatch.setenv("ACX_EVAL_TENANT_ID", "roster-seeded-tenant")
    import scripts.eval_harness.remote_client as rc_mod

    monkeypatch.setattr(rc_mod, "RemoteSceneClient", _client_factory)

    rc = db.main([])

    assert rc != 0
    assert fake.analyzed == []  # never wrote face rows


def test_main_happy_path_with_scratch_tenant(tmp_path, monkeypatch):
    paths = _patch_report_paths(monkeypatch, tmp_path)
    img = paths["uploads"] / "2026" / "07" / "a.jpg"
    img.parent.mkdir(parents=True, exist_ok=True)
    # Minimal PNG so PIL can open dimensions if code path needs it.
    try:
        import io

        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", (8, 8), color=(1, 2, 3)).save(buf, format="PNG")
        img.write_bytes(buf.getvalue())
    except Exception:  # noqa: BLE001
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 128)

    _write_tsv(
        paths["tsv"],
        [(1, Path("/Volumes/Butter/WP/vlm/app/public/wp-content/uploads/2026/07/a.jpg"))],
    )

    fake = _FakeRemoteClient(labeled_clusters=())

    def _client_factory(*_a, **_k):
        return fake

    monkeypatch.delenv("BAKEOFF_BASE_URL", raising=False)
    monkeypatch.setenv("BASELINE_UPLOADS", str(paths["uploads"]))
    monkeypatch.setenv("ACX_EVAL_BASE_URL", "https://example.test")
    monkeypatch.setenv("ACX_EVAL_API_KEY", "test-key-not-secret")
    monkeypatch.setenv("ACX_EVAL_TENANT_ID", "scratch-tenant")
    import scripts.eval_harness.remote_client as rc_mod

    monkeypatch.setattr(rc_mod, "RemoteSceneClient", _client_factory)

    rc = db.main(["--uploads", str(paths["uploads"])])

    assert rc == 0
    assert fake.analyzed == [1]
    assert paths["report_json"].is_file()
    report = json.loads(paths["report_json"].read_text())
    assert report["summary"]["total"] == 1


def test_main_force_skips_tenant_guard(tmp_path, monkeypatch):
    paths = _patch_report_paths(monkeypatch, tmp_path)
    img = paths["uploads"] / "2026" / "07" / "a.jpg"
    img.parent.mkdir(parents=True, exist_ok=True)
    try:
        import io

        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", (8, 8), color=(1, 2, 3)).save(buf, format="PNG")
        img.write_bytes(buf.getvalue())
    except Exception:  # noqa: BLE001
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 128)

    _write_tsv(
        paths["tsv"],
        [(1, Path("/Volumes/Butter/WP/vlm/app/public/wp-content/uploads/2026/07/a.jpg"))],
    )
    fake = _FakeRemoteClient(labeled_clusters=[{"id": "c1", "label": "seeded"}])

    def _client_factory(*_a, **_k):
        return fake

    monkeypatch.delenv("BAKEOFF_BASE_URL", raising=False)
    monkeypatch.setenv("BASELINE_UPLOADS", str(paths["uploads"]))
    monkeypatch.setenv("ACX_EVAL_BASE_URL", "https://example.test")
    monkeypatch.setenv("ACX_EVAL_API_KEY", "test-key-not-secret")
    monkeypatch.setenv("ACX_EVAL_TENANT_ID", "roster-seeded-tenant")
    import scripts.eval_harness.remote_client as rc_mod

    monkeypatch.setattr(rc_mod, "RemoteSceneClient", _client_factory)

    rc = db.main(["--force"])

    assert rc == 0
    assert fake.analyzed == [1]


def test_no_hardcoded_operator_uploads_constant():
    """RH-01: module must not ship a laptop-absolute UPLOADS default."""
    uploads = getattr(db, "UPLOADS", None)
    if uploads is not None:
        text = str(uploads)
        assert "/Volumes/Butter" not in text
        assert not (Path(text).is_absolute() and "Butter" in text)
