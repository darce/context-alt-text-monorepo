"""RED contract tests for the corpus646 catalog, resolver, verifier, and CLI.

The shared module ``scripts.eval_harness.corpus_catalog`` and the tracked catalog
``benchmarks/manifests/corpus-catalog-v1.json`` do not exist yet. The module is imported
inside each test, so this file collects cleanly and each test fails on the missing contract.
Fixtures are synthetic: raw bytes are hashed with ``hashlib`` as the oracle, and no image,
map, alias, or private filename is read or written.
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import importlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[2]
REPO = Path(__file__).resolve().parents[4]
MODULE_FILE = APP_DIR / "scripts" / "eval_harness" / "corpus_catalog.py"
CATALOG_REL = "benchmarks/manifests/corpus-catalog-v1.json"
MANIFEST_REL = "benchmarks/manifests/corpus-manifest-v3r-20260814.json"
ROOT_RELATIVE = "benchmarks/images/corpus646"
CORPUS_ID = "corpus646-originals"
SCHEMA = "benchmark-corpus-catalog/v1"
V3R_SHA256 = "2d9d5ba3e04bcfa7ea29f960b2fdc05431bdae7993bd22042a5369ceee7d9bff"
ENTRY = {
    "root_relative": ROOT_RELATIVE,
    "images_subdir": "originals",
    "provenance_file": "provenance.json",
    "manifest_path": MANIFEST_REL,
    "manifest_sha256": V3R_SHA256,
    "hash_field": "sha256_source",
    "hash_space": "original",
}
LOCATION_FIELDS = {
    "corpus_id",
    "corpus_root",
    "images_root",
    "provenance_path",
    "manifest_path",
    "manifest_sha256",
    "hash_field",
    "hash_space",
    "catalog_path",
    "catalog_sha256",
    "location_source",
}
COUNT_KEYS = {"entries", "present", "matched", "missing", "mismatched", "unsafe_paths"}
STALE_IMAGES_ROOT = "/nonexistent/stale-images-root"
PRIVATE_TOKEN = "private-token-b7e1"
A_REL = "celebs/synthetic-a1.bin"
B_REL = f"personal/{PRIVATE_TOKEN}.bin"
A_BYTES = b"synthetic-original-a1\x00\x01"
B_BYTES = b"synthetic-original-b2\x00\x02"


def _corpus_catalog():
    try:
        return importlib.import_module("scripts.eval_harness.corpus_catalog")
    except ModuleNotFoundError as exc:
        pytest.fail(f"scripts.eval_harness.corpus_catalog is not importable yet: {exc}", pytrace=False)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _same_path(left, right) -> bool:
    return Path(left).resolve() == Path(right).resolve()


def _expected_real_primary_root() -> Path:
    """Independent Git oracle for the real checkout's normal .git layout."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    result = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=REPO, env=env, check=True, capture_output=True, text=True, timeout=120,
    )
    common = Path(result.stdout.strip()).resolve()
    assert common.name == ".git" and common.is_dir(), "real checkout requires a normal .git layout"
    return common.parent


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


def _entry(rel: str, original: bytes, *, derived: bytes | None = None) -> dict:
    """Manifest row pinning the original bytes. The ``sha256`` field is the derived-space decoy."""
    derived = b"downscaled:" + original if derived is None else derived
    return {"path": rel, "bytes": len(original), "sha256_source": _sha(original), "sha256": _sha(derived)}


def _catalog_doc(manifest_sha256: str) -> dict:
    return {"schema": SCHEMA, "corpora": {CORPUS_ID: {**ENTRY, "manifest_sha256": manifest_sha256}}}


def _write_repo_files(root: Path, entries: list[dict], *, images_root: str = STALE_IMAGES_ROOT) -> None:
    manifest = _json_bytes(
        {
            "manifest_version": 3,
            "images_root": images_root,
            "sha256_space": "downscaled",
            "sha256_source_space": "original",
            "entries": entries,
        }
    )
    _write(root / MANIFEST_REL, manifest)
    _write(root / CATALOG_REL, _json_bytes(_catalog_doc(_sha(manifest))))


def _make_checkout(base: Path, entries: list[dict], *, images_root: str = STALE_IMAGES_ROOT) -> Path:
    """Normal .git checkout with the catalog and manifest committed. Images stay ignored, as in the real repo."""
    repo = base / "primary"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    _write(repo / ".gitignore", b"benchmarks/images/\n")
    _write_repo_files(repo, entries, images_root=images_root)
    _git(repo, "add", ".gitignore", "benchmarks")
    _git(repo, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "synthetic corpus fixture")
    return repo


def _write_corpus_tree(corpus_root: Path, files: dict[str, bytes]) -> None:
    """A corpus root holding ``originals/`` and provenance. The bytes are synthetic, never images."""
    (corpus_root / "originals").mkdir(parents=True, exist_ok=True)
    for rel, data in files.items():
        _write(corpus_root / "originals" / rel, data)
    _write(corpus_root / "provenance.json", b'{"synthetic": true}\n')


def _base_checkout(base: Path) -> Path:
    repo = _make_checkout(base, [_entry(A_REL, A_BYTES), _entry(B_REL, B_BYTES)])
    _write_corpus_tree(repo / ROOT_RELATIVE, {A_REL: A_BYTES, B_REL: B_BYTES})
    return repo


def _snapshot(root: Path) -> dict[str, tuple]:
    """Path -> (mode, size, mtime, digest) for everything under root. Read-only means this is unchanged."""
    state: dict[str, tuple] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for name in (*dirnames, *filenames):
            path = Path(dirpath, name)
            st = path.lstat()
            digest = _sha(path.read_bytes()) if path.is_file() and not path.is_symlink() else None
            state[path.relative_to(root).as_posix()] = (st.st_mode, st.st_size, st.st_mtime_ns, digest)
    return state


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


def _root_existence_flags(payload: dict) -> list:
    """Live existence flags for the corpus root, whatever the implementation names them."""
    return [
        value for key, value in payload.items() if "exist" in key and "catalog" not in key and "manifest" not in key
    ]


# --- committed catalog and pin (repo-level, read-only) -------------------------------------------


def test_committed_catalog_is_exactly_the_v1_root_descriptor():
    catalog_path = REPO / CATALOG_REL
    assert catalog_path.is_file(), f"tracked catalog {CATALOG_REL} is missing"
    doc = json.loads(catalog_path.read_text(encoding="utf-8"))
    assert set(doc) == {"schema", "corpora"}
    assert doc["schema"] == SCHEMA
    assert doc["corpora"] == {CORPUS_ID: ENTRY}


def test_committed_catalog_pins_the_tracked_v3r_manifest_bytes():
    catalog_path = REPO / CATALOG_REL
    assert catalog_path.is_file(), f"tracked catalog {CATALOG_REL} is missing"
    pin = json.loads(catalog_path.read_text(encoding="utf-8"))["corpora"][CORPUS_ID]["manifest_sha256"]
    assert pin == V3R_SHA256
    assert _sha((REPO / MANIFEST_REL).read_bytes()) == pin


def test_real_checkout_resolves_committed_root_metadata_only():
    cc = _corpus_catalog()
    loc = cc.resolve_corpus(CORPUS_ID, repo_root=REPO, require_exists=False)
    assert _same_path(loc.corpus_root, _expected_real_primary_root() / ROOT_RELATIVE)
    assert _same_path(loc.manifest_path, REPO / MANIFEST_REL)
    assert loc.manifest_sha256 == V3R_SHA256
    assert (loc.hash_field, loc.hash_space) == ("sha256_source", "original")
    assert loc.location_source == "primary_checkout"


def test_module_source_is_stdlib_only():
    assert MODULE_FILE.is_file(), f"{MODULE_FILE.relative_to(REPO)} is missing"
    imported: set[str] = set()
    for node in ast.walk(ast.parse(MODULE_FILE.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, f"relative import at line {node.lineno} couples the shared module"
            imported.add(node.module.split(".")[0])
    assert sorted(imported - set(sys.stdlib_module_names)) == []


def test_module_is_imported_from_this_worktree_source():
    cc = _corpus_catalog()
    assert _same_path(cc.__file__, MODULE_FILE)


# --- load_catalog validation ----------------------------------------------------------------------


def test_load_catalog_returns_the_validated_document(tmp_path):
    repo = _base_checkout(tmp_path)
    doc = _corpus_catalog().load_catalog(repo)
    assert doc == json.loads((repo / CATALOG_REL).read_text(encoding="utf-8"))


def test_load_catalog_rejects_non_json(tmp_path):
    repo = _base_checkout(tmp_path)
    _write(repo / CATALOG_REL, b'{"schema": ')
    cc = _corpus_catalog()
    with pytest.raises(cc.CatalogError):
        cc.load_catalog(repo)


CATALOG_MUTATIONS = {
    "unknown-schema": lambda d: d.update(schema="benchmark-corpus-catalog/v2"),
    "extra-top-level-key": lambda d: d.update(counts={}),
    "missing-corpora": lambda d: d.pop("corpora"),
    "availability-copied-into-entry": lambda d: d["corpora"][CORPUS_ID].update(exists=True),
    "stale-images-root-copied-into-entry": lambda d: d["corpora"][CORPUS_ID].update(images_root=STALE_IMAGES_ROOT),
    "entry-missing-hash-space": lambda d: d["corpora"][CORPUS_ID].pop("hash_space"),
    "unsafe-corpus-id": lambda d: d["corpora"].update({"../escape": d["corpora"][CORPUS_ID]}),
    "corpus-id-with-space": lambda d: d["corpora"].update({"corpus 646": d["corpora"][CORPUS_ID]}),
    "absolute-root-relative": lambda d: d["corpora"][CORPUS_ID].update(root_relative="/abs/corpus646"),
    "root-relative-escapes-checkout": lambda d: d["corpora"][CORPUS_ID].update(root_relative="../outside"),
    "images-subdir-escapes-root": lambda d: d["corpora"][CORPUS_ID].update(images_subdir="../originals"),
    "manifest-path-escapes-checkout": lambda d: d["corpora"][CORPUS_ID].update(manifest_path="../manifest.json"),
    "provenance-path-escapes-root": lambda d: d["corpora"][CORPUS_ID].update(provenance_file="a/../../p.json"),
    "malformed-manifest-digest": lambda d: d["corpora"][CORPUS_ID].update(manifest_sha256="not-a-digest"),
    "unknown-hash-space": lambda d: d["corpora"][CORPUS_ID].update(hash_space="bogus-space"),
}


@pytest.mark.parametrize("mutate", list(CATALOG_MUTATIONS.values()), ids=list(CATALOG_MUTATIONS))
def test_load_catalog_rejects_unknown_or_unsafe_descriptor(tmp_path, mutate):
    repo = _base_checkout(tmp_path)
    doc = json.loads((repo / CATALOG_REL).read_text(encoding="utf-8"))
    mutate(doc)
    _write(repo / CATALOG_REL, _json_bytes(doc))
    cc = _corpus_catalog()
    with pytest.raises(cc.CatalogError):
        cc.load_catalog(repo)


# --- resolve_corpus: roots, overrides, layouts ----------------------------------------------------


def test_default_root_is_the_primary_checkout_corpus(tmp_path):
    repo = _base_checkout(tmp_path)
    cc = _corpus_catalog()
    loc = cc.resolve_corpus(CORPUS_ID, repo_root=repo)
    corpus_root = repo / ROOT_RELATIVE
    assert loc.corpus_id == CORPUS_ID
    assert _same_path(loc.corpus_root, corpus_root)
    assert _same_path(loc.images_root, corpus_root / "originals")
    assert _same_path(loc.provenance_path, corpus_root / "provenance.json")
    assert _same_path(loc.manifest_path, repo / MANIFEST_REL)
    assert loc.manifest_sha256 == _sha((repo / MANIFEST_REL).read_bytes())
    assert _same_path(loc.catalog_path, repo / CATALOG_REL)
    assert loc.catalog_sha256 == _sha((repo / CATALOG_REL).read_bytes())
    assert (loc.hash_field, loc.hash_space) == ("sha256_source", "original")
    assert loc.location_source == "primary_checkout"


def test_linked_worktree_uses_primary_physical_corpus_not_a_worktree_copy(tmp_path):
    repo = _base_checkout(tmp_path)
    worktree = tmp_path / "feature-worktree"
    _git(repo, "worktree", "add", "-q", "-b", "feature/linked", str(worktree))
    # A stray wrong-bytes copy inside the linked checkout must never be picked up.
    _write_corpus_tree(worktree / ROOT_RELATIVE, {A_REL: b"stray-copy-a", B_REL: b"stray-copy-b"})
    cc = _corpus_catalog()
    loc = cc.resolve_corpus(CORPUS_ID, repo_root=worktree)
    assert _same_path(loc.corpus_root, repo / ROOT_RELATIVE)
    assert _same_path(loc.catalog_path, worktree / CATALOG_REL)
    assert loc.location_source == "primary_checkout"
    assert cc.verify_corpus(loc)["matched"] == 2


def test_explicit_override_wins_over_the_primary_default(tmp_path):
    repo = _base_checkout(tmp_path)
    override = tmp_path / "override-root"
    _write_corpus_tree(override, {A_REL: A_BYTES})
    cc = _corpus_catalog()
    loc = cc.resolve_corpus(CORPUS_ID, repo_root=repo, corpus_root=override)
    assert _same_path(loc.corpus_root, override)
    assert _same_path(loc.images_root, override / "originals")
    assert loc.location_source == "explicit_override"
    counts = cc.verify_corpus(loc)
    assert (counts["matched"], counts["missing"]) == (1, 1)


@pytest.mark.parametrize("layout", ["plain-directory", "separate-git-dir"])
def test_default_root_is_refused_without_a_normal_git_checkout(tmp_path, layout):
    entries = [_entry(A_REL, A_BYTES), _entry(B_REL, B_BYTES)]
    if layout == "plain-directory":
        checkout = tmp_path / "plain"
    else:
        checkout = tmp_path / "checkout"
        _git(tmp_path, "init", "-q", "--separate-git-dir", str(tmp_path / "gitdir.git"), str(checkout))
    _write_repo_files(checkout, entries)
    cc = _corpus_catalog()
    with pytest.raises(cc.CatalogError):
        cc.resolve_corpus(CORPUS_ID, repo_root=checkout, require_exists=False)
    override = tmp_path / "override-root"
    _write_corpus_tree(override, {A_REL: A_BYTES, B_REL: B_BYTES})
    loc = cc.resolve_corpus(CORPUS_ID, repo_root=checkout, corpus_root=override)
    assert _same_path(loc.corpus_root, override)
    assert loc.location_source == "explicit_override"


def test_corpus_location_is_frozen_with_exact_public_fields(tmp_path):
    repo = _base_checkout(tmp_path)
    cc = _corpus_catalog()
    loc = cc.resolve_corpus(CORPUS_ID, repo_root=repo)
    assert dataclasses.is_dataclass(loc)
    assert {f.name for f in dataclasses.fields(loc)} == LOCATION_FIELDS
    with pytest.raises(dataclasses.FrozenInstanceError):
        loc.corpus_root = tmp_path
    assert issubclass(cc.CatalogError, ValueError)


@pytest.mark.parametrize("use_override", [False, True], ids=["primary-default", "empty-override"])
def test_require_exists_rejects_an_absent_image_directory(tmp_path, use_override):
    repo = _make_checkout(tmp_path, [_entry(A_REL, A_BYTES)])
    corpus_root = None
    if use_override:
        corpus_root = tmp_path / "empty-override"
        corpus_root.mkdir()
    cc = _corpus_catalog()
    with pytest.raises(cc.CatalogError, match=CORPUS_ID):
        cc.resolve_corpus(CORPUS_ID, repo_root=repo, corpus_root=corpus_root, require_exists=True)


@pytest.mark.parametrize("use_override", [False, True], ids=["primary-default", "empty-override"])
def test_metadata_only_resolution_succeeds_without_image_bytes(tmp_path, use_override):
    repo = _make_checkout(tmp_path, [_entry(A_REL, A_BYTES)])
    corpus_root = None
    if use_override:
        corpus_root = tmp_path / "empty-override"
        corpus_root.mkdir()
    cc = _corpus_catalog()
    loc = cc.resolve_corpus(CORPUS_ID, repo_root=repo, corpus_root=corpus_root, require_exists=False)
    assert not Path(loc.images_root).is_dir()
    assert loc.manifest_sha256 == _sha((repo / MANIFEST_REL).read_bytes())
    expected_source = "explicit_override" if use_override else "primary_checkout"
    assert loc.location_source == expected_source


def test_resolution_and_catalog_load_never_write(tmp_path):
    repo = _make_checkout(tmp_path, [_entry(A_REL, A_BYTES)])
    before = _snapshot(repo / "benchmarks")
    cc = _corpus_catalog()
    cc.load_catalog(repo)
    cc.resolve_corpus(CORPUS_ID, repo_root=repo, require_exists=False)
    assert _snapshot(repo / "benchmarks") == before


@pytest.mark.parametrize("require_exists", [True, False], ids=["require-exists", "metadata-only"])
def test_manifest_bytes_must_match_the_catalog_pin(tmp_path, require_exists):
    repo = _base_checkout(tmp_path)
    manifest = repo / MANIFEST_REL
    manifest.write_bytes(manifest.read_bytes() + b"\n")
    cc = _corpus_catalog()
    with pytest.raises(cc.CatalogError):
        cc.resolve_corpus(CORPUS_ID, repo_root=repo, require_exists=require_exists)


def test_unknown_corpus_id_is_rejected(tmp_path):
    repo = _base_checkout(tmp_path)
    cc = _corpus_catalog()
    with pytest.raises(cc.CatalogError):
        cc.resolve_corpus("corpus-unknown", repo_root=repo)


def test_manifest_stale_images_root_is_ignored(tmp_path):
    decoy = tmp_path / "stale-decoy"
    _write_corpus_tree(decoy, {A_REL: A_BYTES, B_REL: B_BYTES})
    entries = [_entry(A_REL, A_BYTES), _entry(B_REL, B_BYTES)]
    repo = _make_checkout(tmp_path, entries, images_root=str(decoy / "originals"))
    cc = _corpus_catalog()
    loc = cc.resolve_corpus(CORPUS_ID, repo_root=repo, require_exists=False)
    assert _same_path(loc.images_root, repo / ROOT_RELATIVE / "originals")
    with pytest.raises(cc.CatalogError):
        cc.resolve_corpus(CORPUS_ID, repo_root=repo)


def test_no_ambient_environment_fallback(tmp_path, monkeypatch):
    decoy = tmp_path / "env-decoy"
    _write_corpus_tree(decoy, {A_REL: A_BYTES, B_REL: B_BYTES})
    monkeypatch.setenv("GOLDEN_IMAGES_DIR", str(decoy / "originals"))
    repo = _make_checkout(tmp_path, [_entry(A_REL, A_BYTES), _entry(B_REL, B_BYTES)])
    cc = _corpus_catalog()
    with pytest.raises(cc.CatalogError):
        cc.resolve_corpus(CORPUS_ID, repo_root=repo)
    loc = cc.resolve_corpus(CORPUS_ID, repo_root=repo, require_exists=False)
    assert not _same_path(loc.images_root, decoy / "originals")
    assert loc.location_source == "primary_checkout"


# --- verify_corpus: hash-only, read-only, live counts ---------------------------------------------


def test_verify_counts_declared_original_hashes_and_refuses_unsafe_paths(tmp_path):
    """Oracle is sha256 of the raw bytes. Derived bytes in an original slot are a mismatch.
    Escaping paths and escaping symlinks are unsafe. ``present`` counts safe, hashed regular files."""
    escape_bytes = b"synthetic-escape-bytes"
    secret_bytes = b"synthetic-secret-bytes"
    derived_b = b"synthetic-downscaled-b2"
    entries = [
        _entry(A_REL, A_BYTES),
        _entry(B_REL, B_BYTES, derived=derived_b),
        _entry("personal/synthetic-c3.bin", b"synthetic-original-c3"),
        _entry("celebs/synthetic-d4.bin", b"synthetic-original-d4"),
        _entry("../../escape.bin", escape_bytes),
        _entry("celebs/synthetic-link.bin", secret_bytes),
    ]
    repo = _make_checkout(tmp_path, entries)
    root = repo / ROOT_RELATIVE
    _write_corpus_tree(
        root,
        {A_REL: A_BYTES, B_REL: derived_b, "celebs/synthetic-d4.bin": b"synthetic-original-d4"},
    )
    _write(root.parent / "escape.bin", escape_bytes)
    _write(root / "secret.bin", secret_bytes)
    os.symlink(root / "secret.bin", root / "originals" / "celebs" / "synthetic-link.bin")
    cc = _corpus_catalog()
    counts = cc.verify_corpus(cc.resolve_corpus(CORPUS_ID, repo_root=repo))
    assert counts == {
        "entries": 6,
        "present": 3,
        "matched": 2,
        "missing": 1,
        "mismatched": 1,
        "unsafe_paths": 2,
    }


def test_verify_never_falls_back_to_the_derived_sha256_field(tmp_path):
    derived = b"synthetic-downscaled-only"
    repo = _make_checkout(tmp_path, [_entry(A_REL, A_BYTES, derived=derived)])
    _write_corpus_tree(repo / ROOT_RELATIVE, {A_REL: derived})
    cc = _corpus_catalog()
    counts = cc.verify_corpus(cc.resolve_corpus(CORPUS_ID, repo_root=repo))
    assert (counts["present"], counts["matched"], counts["mismatched"]) == (1, 0, 1)


def test_verify_counts_non_regular_entry_without_raising(tmp_path):
    repo = _make_checkout(tmp_path, [_entry(A_REL, A_BYTES)])
    _write_corpus_tree(repo / ROOT_RELATIVE, {})
    (repo / ROOT_RELATIVE / "originals" / A_REL).mkdir(parents=True)
    cc = _corpus_catalog()
    counts = cc.verify_corpus(cc.resolve_corpus(CORPUS_ID, repo_root=repo))
    assert set(counts) == COUNT_KEYS
    assert counts["entries"] == 1
    assert counts["matched"] == 0
    assert counts["entries"] == counts["matched"] + counts["mismatched"] + counts["missing"] + counts["unsafe_paths"]


def test_verify_inspects_files_live_without_cached_existence(tmp_path):
    repo = _base_checkout(tmp_path)
    cc = _corpus_catalog()
    loc = cc.resolve_corpus(CORPUS_ID, repo_root=repo)
    assert cc.verify_corpus(loc)["matched"] == 2
    (repo / ROOT_RELATIVE / "originals" / A_REL).unlink()
    after = cc.verify_corpus(loc)
    assert (after["matched"], after["missing"]) == (1, 1)


def test_verify_corpus_never_writes(tmp_path):
    repo = _base_checkout(tmp_path)
    cc = _corpus_catalog()
    loc = cc.resolve_corpus(CORPUS_ID, repo_root=repo)
    before = _snapshot(repo / "benchmarks")
    cc.verify_corpus(loc)
    assert _snapshot(repo / "benchmarks") == before


# --- CLI: show / check status and counts ----------------------------------------------------------


def test_cli_show_reports_metadata_and_fresh_root_existence(tmp_path):
    repo = _base_checkout(tmp_path)
    present = _run_cli("show", CORPUS_ID, "--repo-root", str(repo), cwd=tmp_path)
    assert present.returncode == 0, present.stderr
    payload = json.loads(present.stdout)
    assert payload["corpus_id"] == CORPUS_ID
    assert payload["manifest_sha256"] == _sha((repo / MANIFEST_REL).read_bytes())
    assert payload["hash_space"] == "original"
    assert payload["location_source"] == "primary_checkout"
    present_flags = _root_existence_flags(payload)
    assert present_flags and all(present_flags)
    assert PRIVATE_TOKEN not in present.stdout + present.stderr
    shutil.rmtree(repo / ROOT_RELATIVE)
    absent = _run_cli("show", CORPUS_ID, "--repo-root", str(repo), cwd=tmp_path)
    assert absent.returncode == 0, absent.stderr
    absent_flags = _root_existence_flags(json.loads(absent.stdout))
    assert absent_flags and not any(absent_flags)


def test_cli_corpus_root_override_is_reported_and_checked(tmp_path):
    repo = _make_checkout(tmp_path, [_entry(A_REL, A_BYTES), _entry(B_REL, B_BYTES)])
    override = tmp_path / "override-root"
    _write_corpus_tree(override, {A_REL: A_BYTES, B_REL: B_BYTES})
    shown = _run_cli("show", CORPUS_ID, "--repo-root", str(repo), "--corpus-root", str(override), cwd=tmp_path)
    assert shown.returncode == 0, shown.stderr
    payload = json.loads(shown.stdout)
    assert payload["location_source"] == "explicit_override"
    assert _same_path(payload["corpus_root"], override)
    checked = _run_cli("check", CORPUS_ID, "--repo-root", str(repo), "--corpus-root", str(override), cwd=tmp_path)
    assert checked.returncode == 0, checked.stderr
    assert json.loads(checked.stdout)["counts"] == {
        "entries": 2,
        "present": 2,
        "matched": 2,
        "missing": 0,
        "mismatched": 0,
        "unsafe_paths": 0,
    }


def test_cli_check_exits_zero_when_complete_and_is_byte_deterministic(tmp_path):
    repo = _base_checkout(tmp_path)
    first = _run_cli("check", CORPUS_ID, "--repo-root", str(repo), cwd=tmp_path)
    second = _run_cli("check", CORPUS_ID, "--repo-root", str(repo), cwd=tmp_path)
    assert first.returncode == 0, first.stderr
    assert json.loads(first.stdout)["counts"] == {
        "entries": 2,
        "present": 2,
        "matched": 2,
        "missing": 0,
        "mismatched": 0,
        "unsafe_paths": 0,
    }
    assert first.stdout == second.stdout
    assert PRIVATE_TOKEN not in first.stdout


def _checkout_missing_b(base: Path) -> Path:
    repo = _base_checkout(base)
    (repo / ROOT_RELATIVE / "originals" / B_REL).unlink()
    return repo


def _checkout_altered_b(base: Path) -> Path:
    repo = _base_checkout(base)
    (repo / ROOT_RELATIVE / "originals" / B_REL).write_bytes(b"synthetic-altered-b2")
    return repo


def _checkout_unsafe_escape(base: Path) -> Path:
    escape = b"synthetic-escape-bytes"
    repo = _make_checkout(base, [_entry(A_REL, A_BYTES), _entry(B_REL, B_BYTES), _entry("../../escape.bin", escape)])
    _write_corpus_tree(repo / ROOT_RELATIVE, {A_REL: A_BYTES, B_REL: B_BYTES})
    _write(repo / "benchmarks" / "images" / "escape.bin", escape)
    return repo


EXIT_ONE_SCENARIOS = [
    pytest.param(
        _checkout_missing_b,
        {"entries": 2, "present": 1, "matched": 1, "missing": 1, "mismatched": 0, "unsafe_paths": 0},
        id="incomplete",
    ),
    pytest.param(
        _checkout_altered_b,
        {"entries": 2, "present": 2, "matched": 1, "missing": 0, "mismatched": 1, "unsafe_paths": 0},
        id="mismatch",
    ),
    pytest.param(
        _checkout_unsafe_escape,
        {"entries": 3, "present": 2, "matched": 2, "missing": 0, "mismatched": 0, "unsafe_paths": 1},
        id="unsafe-path",
    ),
]


@pytest.mark.parametrize(("setup", "expected"), EXIT_ONE_SCENARIOS)
def test_cli_check_exits_one_with_counts_when_incomplete_mismatched_or_unsafe(tmp_path, setup, expected):
    repo = setup(tmp_path)
    result = _run_cli("check", CORPUS_ID, "--repo-root", str(repo), cwd=tmp_path)
    assert result.returncode == 1, result.stderr
    assert json.loads(result.stdout)["counts"] == expected
    assert PRIVATE_TOKEN not in result.stdout + result.stderr


def _rewrite_schema(base: Path) -> Path:
    repo = _base_checkout(base)
    doc = json.loads((repo / CATALOG_REL).read_text(encoding="utf-8"))
    doc["schema"] = "benchmark-corpus-catalog/v2"
    _write(repo / CATALOG_REL, _json_bytes(doc))
    return repo


def _tamper_manifest(base: Path) -> Path:
    repo = _base_checkout(base)
    manifest = repo / MANIFEST_REL
    manifest.write_bytes(manifest.read_bytes() + b"\n")
    return repo


def _remove_images(base: Path) -> Path:
    repo = _base_checkout(base)
    shutil.rmtree(repo / ROOT_RELATIVE / "originals")
    return repo


EXIT_TWO_SCENARIOS = [
    pytest.param(_rewrite_schema, CORPUS_ID, id="unknown-schema"),
    pytest.param(_base_checkout, "corpus-unknown", id="unknown-corpus-id"),
    pytest.param(_tamper_manifest, CORPUS_ID, id="manifest-pin-mismatch"),
    pytest.param(_remove_images, CORPUS_ID, id="absent-image-root"),
]


@pytest.mark.parametrize(("setup", "corpus_id"), EXIT_TWO_SCENARIOS)
def test_cli_check_exits_two_for_bad_catalog_unknown_id_bad_pin_or_absent_root(tmp_path, setup, corpus_id):
    repo = setup(tmp_path)
    result = _run_cli("check", corpus_id, "--repo-root", str(repo), cwd=tmp_path)
    assert result.returncode == 2, result.stdout + result.stderr
    assert result.stderr.strip()
    assert "Traceback" not in result.stderr
    assert PRIVATE_TOKEN not in result.stdout + result.stderr


def test_cli_default_repo_root_comes_from_module_source_not_caller_cwd(tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    result = _run_cli("show", CORPUS_ID, cwd=elsewhere)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert _same_path(payload["catalog_path"], REPO / CATALOG_REL)
    assert _same_path(payload["corpus_root"], _expected_real_primary_root() / ROOT_RELATIVE)
    assert payload["manifest_sha256"] == V3R_SHA256
