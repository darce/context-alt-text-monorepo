"""Regression coverage for DAG path-resolution diagnostics."""

from __future__ import annotations

import errno
from pathlib import Path

import pytest

import scripts.eval_harness.manifest as manifest_module
from scripts.eval_harness._pathtext import _printable_message, _printable_path
from scripts.eval_harness.manifest import (
    GoldenEntry,
    ManifestError,
    _resolve_image,
    resolve_verified_image,
)

_SURROGATE = chr(0xDCE9)


def _entry(path: str) -> GoldenEntry:
    return GoldenEntry(
        path=path,
        sha256="0" * 64,
        media_id=1,
        face_count=0,
        present_identities=[],
        must_right=[],
        easy_wrong=[],
        policy={"recognition_enabled": True},
        provenance={
            "source": "operator",
            "license": "consented",
            "note": "path diagnostic regression",
        },
    )


def test_read_failure_preserves_filename_filename2_and_cause(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "images"
    root.mkdir()
    entry_path = f"entry-{_SURROGATE}.jpg"
    image_path = root / f"resolved-{_SURROGATE}.jpg"
    filename = root / f"reported-{_SURROGATE}.jpg"
    filename2 = root / f"reported-again-{_SURROGATE}.jpg"
    failure = OSError(
        errno.EIO,
        f"read failed-{_SURROGATE}",
        str(filename),
        None,
        str(filename2),
    )

    monkeypatch.setattr(manifest_module, "_resolve_image", lambda _root, _path: image_path)

    def fail_read_bytes(path: Path) -> bytes:
        assert path == image_path
        raise failure

    monkeypatch.setattr(Path, "read_bytes", fail_read_bytes)

    with pytest.raises(ManifestError) as caught:
        resolve_verified_image(_entry(entry_path), root)

    message = str(caught.value)
    message.encode("utf-8")
    assert "\\udc" not in message
    assert f"image file unreadable: {str(_printable_path(entry_path))}" in message
    assert f"(under {str(_printable_path(root))})" in message
    assert str(_printable_message(failure.strerror)) in message
    assert f"filename={str(_printable_path(filename))}" in message
    assert f"filename2={str(_printable_path(filename2))}" in message
    assert caught.value.__cause__ is failure
    assert caught.value.invariant is None
    assert caught.value.entry_index is None
    assert caught.value.entry_path is None


def test_root_resolve_oserror_preserves_filename_filename2_invariant_and_cause(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / f"root-{_SURROGATE}"
    rel_path = f"child-{_SURROGATE}.jpg"
    filename = tmp_path / f"reported-root-{_SURROGATE}"
    filename2 = tmp_path / f"reported-root-again-{_SURROGATE}"
    failure = OSError(
        errno.EACCES,
        f"root denied-{_SURROGATE}",
        str(filename),
        None,
        str(filename2),
    )
    original_resolve = Path.resolve

    def fail_root_resolve(path: Path, strict: bool = False) -> Path:
        if path == root:
            raise failure
        return original_resolve(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", fail_root_resolve)

    with pytest.raises(ManifestError) as caught:
        _resolve_image(root, rel_path)

    message = str(caught.value)
    message.encode("utf-8")
    assert "\\udc" not in message
    assert f"image root cannot be resolved: {str(_printable_path(root))}" in message
    assert str(_printable_message(failure.strerror)) in message
    assert f"filename={str(_printable_path(filename))}" in message
    assert f"filename2={str(_printable_path(filename2))}" in message
    assert caught.value.invariant == "image_path_containment"
    assert caught.value.entry_path == rel_path
    assert caught.value.__cause__ is failure


@pytest.mark.parametrize("error_type", [RuntimeError, ValueError])
def test_root_resolve_non_oserror_uses_context_path_and_safe_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[Exception],
) -> None:
    root = tmp_path / f"root-{_SURROGATE}"
    rel_path = f"child-{_SURROGATE}.jpg"
    failure = error_type(f"root failure-{_SURROGATE}")
    original_resolve = Path.resolve

    def fail_root_resolve(path: Path, strict: bool = False) -> Path:
        if path == root:
            raise failure
        return original_resolve(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", fail_root_resolve)

    with pytest.raises(ManifestError) as caught:
        _resolve_image(root, rel_path)

    message = str(caught.value)
    message.encode("utf-8")
    assert "\\udc" not in message
    assert f"filename={str(_printable_path(root))}" in message
    assert str(_printable_message(str(failure))) in message
    assert "filename2=" not in message
    assert caught.value.invariant == "image_path_containment"
    assert caught.value.entry_path == rel_path
    assert caught.value.__cause__ is failure


def test_child_resolve_oserror_preserves_filename_filename2_invariant_and_cause(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "images"
    root.mkdir()
    rel_path = f"child-{_SURROGATE}.jpg"
    candidate = root / rel_path
    filename = tmp_path / f"reported-child-{_SURROGATE}"
    filename2 = tmp_path / f"reported-child-again-{_SURROGATE}"
    failure = OSError(
        errno.ELOOP,
        f"child denied-{_SURROGATE}",
        str(filename),
        None,
        str(filename2),
    )
    original_resolve = Path.resolve

    def fail_child_resolve(path: Path, strict: bool = False) -> Path:
        if path == candidate:
            raise failure
        return original_resolve(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", fail_child_resolve)

    with pytest.raises(ManifestError) as caught:
        _resolve_image(root, rel_path)

    message = str(caught.value)
    message.encode("utf-8")
    assert "\\udc" not in message
    assert f"image path is outside corpus root: {str(_printable_path(rel_path))}" in message
    assert f"root={str(_printable_path(root))}" in message
    assert str(_printable_message(failure.strerror)) in message
    assert f"filename={str(_printable_path(filename))}" in message
    assert f"filename2={str(_printable_path(filename2))}" in message
    assert caught.value.invariant == "image_path_containment"
    assert caught.value.entry_path == rel_path
    assert caught.value.__cause__ is failure


@pytest.mark.parametrize("error_type", [RuntimeError, ValueError])
def test_child_resolve_non_oserror_uses_context_path_and_safe_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[Exception],
) -> None:
    root = tmp_path / "images"
    root.mkdir()
    rel_path = f"child-{_SURROGATE}.jpg"
    candidate = root / rel_path
    failure = error_type(f"child failure-{_SURROGATE}")
    original_resolve = Path.resolve

    def fail_child_resolve(path: Path, strict: bool = False) -> Path:
        if path == candidate:
            raise failure
        return original_resolve(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", fail_child_resolve)

    with pytest.raises(ManifestError) as caught:
        _resolve_image(root, rel_path)

    message = str(caught.value)
    message.encode("utf-8")
    assert "\\udc" not in message
    assert f"filename={str(_printable_path(candidate))}" in message
    assert str(_printable_message(str(failure))) in message
    assert "filename2=" not in message
    assert caught.value.invariant == "image_path_containment"
    assert caught.value.entry_path == rel_path
    assert caught.value.__cause__ is failure
