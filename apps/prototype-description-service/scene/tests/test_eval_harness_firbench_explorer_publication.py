"""Public API publication checks; null clustering isolates filesystem behavior.

This self-contained, synthetic wire does not prove non-null producer interoperability.
"""

from __future__ import annotations

import ctypes
import errno
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.eval_harness import firbench_explorer as explorer


def _input(directory: Path) -> Path:
    artifact_id = "synthetic-publication"
    digest = "a" * 64
    source = {
        "artifact_id": artifact_id, "file_sha256": digest, "kind": "report-json",
        "manifest_hash_kind": None, "manifest_sha256": None,
        "qualification": "partial", "source_sha": None,
    }
    report = {
        "artifact_id": artifact_id, "file_sha256": digest,
        "pipeline": "sface", "model_id": "ort-yunet-sface", "embedding_dim": 128,
        "counts": {"total": 1, "scored": 1, "failed": 0, "matched_faces": 1,
                   "named_matched": 1, "stranger_matched": 0},
        "detection": {"tp": 1, "fp": 0, "fn": 0, "precision": 1.0, "recall": 1.0},
        "unknown_rejection": None, "clustering": None, "identification": None,
        "slice_sections": [], "compatibility": "unknown", "qualification": "partial",
    }
    wire = {
        "schema": "firbench/comparison-explorer-export-v1", "schema_version": 1,
        "sources": [source], "reports": [report],
        "dedup": [{"file_sha256": digest, "artifact_ids": [artifact_id]}],
    }
    path = directory / "input.json"
    path.write_text(json.dumps(wire), encoding="utf-8")
    return path


def test_render_never_exposes_an_empty_final_directory(tmp_path: Path, monkeypatch) -> None:
    data = _input(tmp_path)
    out = tmp_path / "explorer"
    expected = explorer.render_explorer(data, tmp_path / "reference").read_bytes()
    original_mkdir = os.mkdir
    observed = []
    concurrent_bytes = b"concurrent creator owns this index"

    def observe_mkdir(path, *args, **kwargs):
        result = original_mkdir(path, *args, **kwargs)
        if Path(path) == out:
            observed.append(tuple(out.iterdir()))
            (out / "index.html").write_bytes(concurrent_bytes)
        return result

    monkeypatch.setattr(os, "mkdir", observe_mkdir)
    page = explorer.render_explorer(data, out)

    # Check actual bytes as well as the publication window: another creator must survive.
    assert page.read_bytes() == (concurrent_bytes if observed else expected)
    assert observed == [], "publication exposed the final directory before its page was ready"
    assert sorted(path.name for path in out.iterdir()) == ["index.html"]
    assert sorted(path.name for path in tmp_path.iterdir()) == ["explorer", "input.json", "reference"]


def test_render_sanitizes_a_regular_file_output_parent(tmp_path: Path) -> None:
    data = _input(tmp_path)
    parent = tmp_path / "sensitive-parent-name"
    parent.write_bytes(b"keep parent")

    with pytest.raises(explorer.ExplorerError) as caught:
        explorer.render_explorer(data, parent / "explorer")

    assert str(tmp_path) not in str(caught.value)
    assert parent.name not in str(caught.value)
    assert parent.read_bytes() == b"keep parent"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["input.json", parent.name]


def _create_competitor(out: Path, kind: str) -> None:
    if kind == "file":
        out.write_bytes(b"other creator file")
    elif kind == "empty-directory":
        out.mkdir()
    elif kind == "directory":
        out.mkdir()
        (out / "index.html").write_bytes(b"other creator index")
        (out / "other.txt").write_bytes(b"other creator extra")
    else:
        out.symlink_to("input.json" if kind == "symlink" else "absent-target")


def _entry_bytes(out: Path):
    if out.is_symlink():
        return ("symlink", os.readlink(out))
    if out.is_file():
        return ("file", out.read_bytes())
    return ("directory", {path.name: path.read_bytes() for path in out.iterdir()})


@pytest.mark.parametrize("kind", ["file", "empty-directory", "directory", "symlink", "dangling-symlink"])
@pytest.mark.parametrize("concurrent", [False, True], ids=["existing", "concurrent"])
def test_native_publication_preserves_every_competing_entry(tmp_path: Path, monkeypatch, kind, concurrent) -> None:
    data = _input(tmp_path)
    input_bytes = data.read_bytes()
    out = tmp_path / "explorer"
    native_publish = explorer._publish_staged_directory
    snapshots = []

    def create_competitor_then_publish(staging, destination):
        assert destination == out
        assert not out.exists() and not out.is_symlink()
        staged_page = (staging / "index.html").read_bytes()
        assert staged_page.startswith(b"<!doctype html>") and staged_page.endswith(b"</html>\n")
        _create_competitor(out, kind)
        snapshots.append(_entry_bytes(out))
        # Real native filesystem no-replace operation, including the empty-directory case.
        return native_publish(staging, destination)

    if concurrent:
        monkeypatch.setattr(explorer, "_publish_staged_directory", create_competitor_then_publish)
    else:
        _create_competitor(out, kind)
        snapshots.append(_entry_bytes(out))

    with pytest.raises(explorer.ExplorerError, match="^output directory already exists; choose a new --out path$"):
        explorer.render_explorer(data, out)

    assert _entry_bytes(out) == snapshots[0]
    assert data.read_bytes() == input_bytes
    assert sorted(path.name for path in tmp_path.iterdir()) == ["explorer", "input.json"]


def test_failed_publication_never_deletes_concurrent_files(tmp_path: Path, monkeypatch) -> None:
    data = _input(tmp_path)
    out = tmp_path / "explorer"
    keep = tmp_path / "user-file"
    keep.write_bytes(b"user owns parent contents")
    staged = []

    def fail_after_competing_creator(staging, destination):
        staged.append(staging)
        assert (staging / "index.html").read_bytes().startswith(b"<!doctype html>")
        _create_competitor(destination, "directory")
        raise OSError(errno.EIO, str(tmp_path / "sensitive-error-detail"))

    monkeypatch.setattr(explorer, "_publish_staged_directory", fail_after_competing_creator)
    with pytest.raises(explorer.ExplorerError) as caught:
        explorer.render_explorer(data, out)

    assert str(caught.value) == "cannot publish explorer output; choose a writable --out path"
    assert _entry_bytes(out) == ("directory", {"index.html": b"other creator index", "other.txt": b"other creator extra"})
    assert keep.read_bytes() == b"user owns parent contents"
    assert staged and not staged[0].exists()
    assert sorted(path.name for path in tmp_path.iterdir()) == ["explorer", "input.json", "user-file"]


def test_success_does_not_clean_a_reused_staging_name(tmp_path: Path, monkeypatch) -> None:
    data = _input(tmp_path)
    out = tmp_path / "explorer"
    native_publish = explorer._publish_staged_directory
    reused = []

    def publish_then_reuse_name(staging, destination):
        assert not destination.exists()
        complete_page = (staging / "index.html").read_bytes()
        native_publish(staging, destination)
        assert (destination / "index.html").read_bytes() == complete_page
        staging.mkdir()
        (staging / "other-creator").write_bytes(b"keep reused name")
        reused.append(staging)

    monkeypatch.setattr(explorer, "_publish_staged_directory", publish_then_reuse_name)
    assert explorer.render_explorer(data, out) == out / "index.html"
    assert (reused[0] / "other-creator").read_bytes() == b"keep reused name"


@pytest.mark.parametrize("failure", ["staging-permission", "write-permission", "missing-api", "unsupported-platform"])
def test_expected_filesystem_failures_are_sanitized_and_leave_no_output(tmp_path: Path, monkeypatch, failure) -> None:
    data = _input(tmp_path)
    out = tmp_path / "explorer"

    def deny(*args, **kwargs):
        raise PermissionError(errno.EACCES, str(tmp_path / "sensitive-detail"))

    if failure == "staging-permission":
        monkeypatch.setattr(explorer.tempfile, "mkdtemp", deny)
    elif failure == "write-permission":
        original_open = Path.open

        def deny_page(path, *args, **kwargs):
            if path.name == "index.html":
                return deny()
            return original_open(path, *args, **kwargs)

        monkeypatch.setattr(Path, "open", deny_page)
    elif failure == "missing-api":
        monkeypatch.setattr(explorer.ctypes, "CDLL", lambda *args, **kwargs: SimpleNamespace())
    else:
        monkeypatch.setattr(explorer, "sys", SimpleNamespace(platform="unsupported"))

    with pytest.raises(explorer.ExplorerError) as caught:
        explorer.render_explorer(data, out)

    assert str(caught.value) == "cannot publish explorer output; choose a writable --out path"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["input.json"]


def test_darwin_publication_uses_the_declared_exclusive_abi(tmp_path: Path, monkeypatch) -> None:
    """ABI verification only; this is not an actual Darwin runtime test."""
    data = _input(tmp_path)
    out = tmp_path / "explorer"
    calls = []

    def renamex_np(source, destination, flags):
        calls.append((source, destination, flags))
        assert Path(os.fsdecode(source), "index.html").read_bytes().startswith(b"<!doctype html>")
        ctypes.set_errno(errno.EEXIST)
        return -1

    def load_libc(name, *, use_errno):
        assert name is None and use_errno is True
        return SimpleNamespace(renamex_np=renamex_np)

    monkeypatch.setattr(explorer, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(explorer.ctypes, "CDLL", load_libc)
    with pytest.raises(explorer.ExplorerError, match="output directory already exists"):
        explorer.render_explorer(data, out)

    assert len(calls) == 1
    assert calls[0][1:] == (os.fsencode(out), 0x4)
    assert renamex_np.argtypes == [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
    assert renamex_np.restype is ctypes.c_int
    assert sorted(path.name for path in tmp_path.iterdir()) == ["input.json"]


def test_input_and_serialization_refusals_precede_output_writes(tmp_path: Path, monkeypatch) -> None:
    data = _input(tmp_path)
    out = tmp_path / "uncreated-parent" / "explorer"
    original = data.read_bytes()
    data.write_text('{"schema_version": 2}', encoding="utf-8")
    with pytest.raises(explorer.ExplorerError):
        explorer.render_explorer(data, out)
    assert not out.parent.exists()
    data.write_bytes(original)

    def serialization_error(*args, **kwargs):
        raise TypeError("injected serialization programming error")

    monkeypatch.setattr(explorer.json, "dumps", serialization_error)
    with pytest.raises(TypeError, match="injected serialization programming error"):
        explorer.render_explorer(data, out)
    assert not out.parent.exists()
    assert sorted(path.name for path in tmp_path.iterdir()) == ["input.json"]


def test_unwritable_parent_is_a_sanitized_refusal(tmp_path: Path) -> None:
    data = _input(tmp_path)
    parent = tmp_path / "unwritable-parent"
    parent.mkdir()
    keep = parent / "user-file"
    keep.write_bytes(b"keep parent contents")
    parent.chmod(0o500)
    try:
        with pytest.raises(explorer.ExplorerError) as caught:
            explorer.render_explorer(data, parent / "explorer")
        assert str(caught.value) == "cannot publish explorer output; choose a writable --out path"
        assert list(parent.iterdir()) == [keep]
        assert keep.read_bytes() == b"keep parent contents"
    finally:
        parent.chmod(0o700)
