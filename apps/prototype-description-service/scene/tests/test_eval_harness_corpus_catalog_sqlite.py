"""CLI contract for the private evidence DB v0 (``db-import`` and ``--evidence-db`` show/check).

Every fixture is synthetic. Checkouts live under pytest's ``tmp_path``; evidence DBs live in a fresh
directory under ``EVIDENCE_SCRATCH``, because the DB must sit outside every Git-marked ancestor.
The pinned manifest bytes, the image bytes, and the private filename token are invented here and
are never read from the real corpus. Hashes are computed with ``hashlib`` as the oracle.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[2]
# /tmp holds an empty stray .git directory on this host, so an evidence DB there is refused as inside a
# Git-marked ancestor. /var/tmp has no .git ancestor and holds only this test's synthetic DB directory.
EVIDENCE_SCRATCH = Path("/var/tmp")
CATALOG_REL = "benchmarks/manifests/corpus-catalog-v1.json"
MANIFEST_REL = "benchmarks/manifests/corpus-manifest-v3r-20260814.json"
ROOT_RELATIVE = "benchmarks/images/corpus646"
CORPUS_ID = "corpus646-originals"
SCHEMA = "benchmark-corpus-catalog/v1"
ENTRY = {
    "root_relative": ROOT_RELATIVE,
    "images_subdir": "originals",
    "provenance_file": "provenance.json",
    "manifest_path": MANIFEST_REL,
    "hash_field": "sha256_source",
    "hash_space": "original",
}
PRIVATE_TOKEN = "private-token-b7e1"
A_REL = "celebs/synthetic-a1.bin"
B_REL = f"personal/{PRIVATE_TOKEN}.bin"
A_BYTES = b"synthetic-original-a1\x00\x01"
B_BYTES = b"synthetic-original-b2\x00\x02"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(doc) -> bytes:
    return (json.dumps(doc, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _git(cwd: Path, *args: str) -> None:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_NOSYSTEM="1",
        GIT_AUTHOR_NAME="synthetic",
        GIT_AUTHOR_EMAIL="synthetic@example.invalid",
        GIT_COMMITTER_NAME="synthetic",
        GIT_COMMITTER_EMAIL="synthetic@example.invalid",
    )
    subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True)


def _entry(rel: str, original: bytes) -> dict:
    return {"path": rel, "bytes": len(original), "sha256_source": _sha(original), "sha256": _sha(b"d:" + original)}


def _base_checkout(base: Path) -> Path:
    """Normal .git checkout whose committed catalog pins a synthetic manifest; images stay ignored."""
    repo = base / "primary"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    _write(repo / ".gitignore", b"benchmarks/images/\n")
    manifest = _json_bytes(
        {
            "manifest_version": 3,
            "images_root": "/nonexistent/stale-images-root",
            "sha256_space": "downscaled",
            "sha256_source_space": "original",
            "entries": [_entry(A_REL, A_BYTES), _entry(B_REL, B_BYTES)],
        }
    )
    catalog = {"schema": SCHEMA, "corpora": {CORPUS_ID: {**ENTRY, "manifest_sha256": _sha(manifest)}}}
    _write(repo / MANIFEST_REL, manifest)
    _write(repo / CATALOG_REL, _json_bytes(catalog))
    _git(repo, "add", ".gitignore", "benchmarks")
    _git(repo, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "synthetic corpus fixture")
    _write(repo / ROOT_RELATIVE / "originals" / A_REL, A_BYTES)
    _write(repo / ROOT_RELATIVE / "originals" / B_REL, B_BYTES)
    _write(repo / ROOT_RELATIVE / "provenance.json", b'{"synthetic": true}\n')
    return repo


def _run_cli(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "GOLDEN_IMAGES_DIR"}
    env["PYTHONPATH"] = str(APP_DIR)
    return subprocess.run(
        [sys.executable, "-m", "scripts.eval_harness.corpus_catalog", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


@pytest.fixture
def private_dir():
    """Directory for an evidence DB that is not inside any Git-marked ancestor. The DB itself is never created here."""
    scratch = Path(tempfile.mkdtemp(prefix="fb1-e0-evidence-", dir=EVIDENCE_SCRATCH))
    try:
        yield scratch / "private"
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def test_cli_private_db_import_then_show_and_check_survive_manifest_deletion(tmp_path, private_dir):
    repo = _base_checkout(tmp_path)
    pin = _sha((repo / MANIFEST_REL).read_bytes())
    db = private_dir / "evidence.sqlite3"
    local_manifest = tmp_path / "local" / "manifest.json"
    _write(local_manifest, (repo / MANIFEST_REL).read_bytes())

    imported = _run_cli(
        "db-import",
        CORPUS_ID,
        "--repo-root",
        str(repo),
        "--evidence-db",
        str(db),
        "--manifest",
        str(local_manifest),
        cwd=tmp_path,
    )
    assert imported.returncode == 0, imported.stderr
    assert json.loads(imported.stdout) == {
        "corpus_id": CORPUS_ID,
        "entries": 2,
        "manifest_sha256": pin,
        "status": "imported",
    }
    assert stat.S_IMODE(db.stat().st_mode) == 0o600
    assert stat.S_IMODE(db.parent.stat().st_mode) == 0o700

    (repo / MANIFEST_REL).unlink()
    shown = _run_cli("show", CORPUS_ID, "--repo-root", str(repo), "--evidence-db", str(db), cwd=tmp_path)
    assert shown.returncode == 0, shown.stderr
    shown_payload = json.loads(shown.stdout)
    assert shown_payload["manifest_source"] == "evidence_db"
    assert shown_payload["manifest_sha256"] == pin

    checked = _run_cli("check", CORPUS_ID, "--repo-root", str(repo), "--evidence-db", str(db), cwd=tmp_path)
    assert checked.returncode == 0, checked.stderr
    assert json.loads(checked.stdout)["counts"] == {
        "entries": 2,
        "present": 2,
        "matched": 2,
        "missing": 0,
        "mismatched": 0,
        "unsafe_paths": 0,
    }

    for result in (imported, shown, checked):
        assert PRIVATE_TOKEN not in result.stdout + result.stderr
    db_bytes = db.read_bytes()
    assert A_BYTES not in db_bytes and B_BYTES not in db_bytes


def _db_import_cli(repo: Path, db: Path, manifest: Path, cwd: Path) -> subprocess.CompletedProcess[str]:
    return _run_cli(
        "db-import", CORPUS_ID, "--repo-root", str(repo), "--evidence-db", str(db), "--manifest", str(manifest), cwd=cwd
    )


def _repin(repo: Path, manifest: bytes) -> None:
    """Replace the tracked manifest and move the catalog pin to match it."""
    _write(repo / MANIFEST_REL, manifest)
    catalog = json.loads((repo / CATALOG_REL).read_text(encoding="utf-8"))
    catalog["corpora"][CORPUS_ID]["manifest_sha256"] = _sha(manifest)
    _write(repo / CATALOG_REL, _json_bytes(catalog))


@pytest.mark.parametrize("command", ["show", "check"])
def test_show_and_check_never_create_a_missing_db(tmp_path, private_dir, command):
    repo = _base_checkout(tmp_path)
    result = _run_cli(command, CORPUS_ID, "--repo-root", str(repo), "--evidence-db", str(private_dir / "evidence.sqlite3"), cwd=tmp_path)
    assert result.returncode == 2
    assert result.stderr.startswith("error: ")
    assert "Traceback" not in result.stderr
    assert not private_dir.exists()


@pytest.mark.parametrize("case", ["wrong-pin", "malformed"])
def test_wrong_pin_or_malformed_import_refuses_before_any_write(tmp_path, private_dir, case):
    repo = _base_checkout(tmp_path)
    local = tmp_path / "local.json"
    if case == "wrong-pin":
        _write(local, (repo / MANIFEST_REL).read_bytes() + b"\n")
    else:
        _repin(repo, b"{not json")
        _write(local, b"{not json")
    result = _db_import_cli(repo, private_dir / "evidence.sqlite3", local, tmp_path)
    assert result.returncode == 2
    assert result.stderr.startswith("error: ")
    assert PRIVATE_TOKEN not in result.stderr
    assert not private_dir.exists()


def test_identical_reimport_is_idempotent_and_changed_bytes_are_refused(tmp_path, private_dir):
    repo = _base_checkout(tmp_path)
    db = private_dir / "evidence.sqlite3"
    local = tmp_path / "local.json"
    _write(local, (repo / MANIFEST_REL).read_bytes())
    assert _db_import_cli(repo, db, local, tmp_path).returncode == 0
    before = _sha(db.read_bytes())
    again = _db_import_cli(repo, db, local, tmp_path)
    assert again.returncode == 0, again.stderr
    assert json.loads(again.stdout)["status"] == "already_imported"
    assert _sha(db.read_bytes()) == before

    changed = _json_bytes({"manifest_version": 3, "entries": [_entry(A_REL, A_BYTES)]})
    _repin(repo, changed)
    _write(local, changed)
    refused = _db_import_cli(repo, db, local, tmp_path)
    assert refused.returncode == 2
    assert "refusing to overwrite" in refused.stderr
    assert _sha(db.read_bytes()) == before


def test_db_inside_a_git_directory_or_worktree_is_refused_before_writing(tmp_path):
    repo = _base_checkout(tmp_path)
    local = tmp_path / "local.json"
    _write(local, (repo / MANIFEST_REL).read_bytes())
    worktree = tmp_path / "linked"
    _git(repo, "worktree", "add", "-q", "-b", "feature/linked", str(worktree))
    for db in (repo / ".git" / "evidence.sqlite3", worktree / "private" / "evidence.sqlite3"):
        result = _db_import_cli(repo, db, local, tmp_path)
        assert result.returncode == 2
        assert "inside a Git checkout" in result.stderr
        assert not db.exists()
    assert not (worktree / "private").exists()


@pytest.mark.parametrize("damage", ["corrupt", "unsupported-version", "stale-pin"])
def test_damaged_unsupported_or_stale_db_is_refused_and_left_intact(tmp_path, private_dir, damage):
    repo = _base_checkout(tmp_path)
    db = private_dir / "evidence.sqlite3"
    local = tmp_path / "local.json"
    _write(local, (repo / MANIFEST_REL).read_bytes())
    assert _db_import_cli(repo, db, local, tmp_path).returncode == 0
    if damage == "corrupt":
        db.write_bytes(b"not a sqlite database\n" * 64)
    elif damage == "unsupported-version":
        conn = sqlite3.connect(db)
        try:
            conn.execute("PRAGMA user_version = 2")
            conn.commit()
        finally:
            conn.close()
    else:
        catalog = json.loads((repo / CATALOG_REL).read_text(encoding="utf-8"))
        catalog["corpora"][CORPUS_ID]["manifest_sha256"] = "0" * 64
        _write(repo / CATALOG_REL, _json_bytes(catalog))
    before = _sha(db.read_bytes())
    results = [
        _run_cli(command, CORPUS_ID, "--repo-root", str(repo), "--evidence-db", str(db), cwd=tmp_path)
        for command in ("show", "check")
    ]
    results.append(_db_import_cli(repo, db, local, tmp_path))
    for result in results:
        assert result.returncode == 2, result.stdout
        assert result.stderr.startswith("error: ")
        assert "Traceback" not in result.stderr
        assert PRIVATE_TOKEN not in result.stderr
    assert _sha(db.read_bytes()) == before


def test_legacy_show_and_check_without_the_flag_still_read_the_tracked_manifest(tmp_path):
    repo = _base_checkout(tmp_path)
    shown = _run_cli("show", CORPUS_ID, "--repo-root", str(repo), cwd=tmp_path)
    assert shown.returncode == 0, shown.stderr
    payload = json.loads(shown.stdout)
    assert "manifest_source" not in payload
    assert Path(payload["manifest_path"]) == repo / MANIFEST_REL
    checked = _run_cli("check", CORPUS_ID, "--repo-root", str(repo), cwd=tmp_path)
    assert checked.returncode == 0, checked.stderr
    assert set(json.loads(checked.stdout)) == {
        "catalog_sha256",
        "corpus_id",
        "counts",
        "hash_field",
        "hash_space",
        "location_source",
        "manifest_sha256",
        "status",
    }
    (repo / MANIFEST_REL).unlink()
    assert _run_cli("check", CORPUS_ID, "--repo-root", str(repo), cwd=tmp_path).returncode == 2
