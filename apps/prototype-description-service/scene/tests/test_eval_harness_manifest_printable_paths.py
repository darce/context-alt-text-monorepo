"""VLM6-W19F2: manifest.py operator-path emission must use printable paths.

Lane F2 owns this file and scripts/eval_harness/manifest.py. Do not edit
cli.py / _pathtext.py / README.md / test_eval_harness_cli_*.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.eval_harness.manifest import (
    ManifestError,
    load_legacy_manifest,
    load_manifest,
    resolve_verified_image,
)

_SERVICE_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST_PY = _SERVICE_ROOT / "scripts" / "eval_harness" / "manifest.py"
_FIXTURE = (
    _SERVICE_ROOT
    / "scripts"
    / "eval_harness"
    / "tests"
    / "fixtures"
    / "provenanced_min.json"
)
_ASCII_LOCALE_ENV = {
    "LC_ALL": "C",
    "LANG": "C",
    "PYTHONUTF8": "0",
    "PYTHONCOERCECLOCALE": "0",
}
_ASCII_PARENT_KEYS = (
    "LC_ALL",
    "LANG",
    "LC_CTYPE",
    "LC_MESSAGES",
    "LANGUAGE",
    "PYTHONUTF8",
    "PYTHONCOERCECLOCALE",
)
_UNDECODABLE = b"undecodable:"
_SURROGATE_LEAK = b"\\udc"
_CAFE_LATIN1 = b"caf\xe9"
# JSON / argv threat is latin-1 0xe9 as U+DCE9, NEVER U+00E9 (café masks the defect).
_SURROGATE_LEAF = "caf\udce9"
_SURROGATE_REL = f"{_SURROGATE_LEAF}.jpg"
_SURROGATE_JSON = f"{_SURROGATE_LEAF}.json"
_SHA_FAKE = hashlib.sha256(b"fake image bytes").hexdigest()
_SURROGATE_ARGV_SKIP = (
    "host C-locale child does not produce PEP 383 surrogate-escaped argv "
    "for latin-1 0xe9 (measured: byte arrives as clean unicode, not surrogates); "
    "product manifest printable-path latin-1 recovery is untested "
    "(AGT-06 / VLM6-RV16-B-05)"
)
_SURROGATE_ARGV_PROBE: bool | None = None

_LOAD_METADATA_ONLY = b"""
import os, sys, warnings
warnings.simplefilter("always")
os.environ.pop("GOLDEN_IMAGES_DIR", None)
from scripts.eval_harness.manifest import load_manifest
load_manifest(
    sys.argv[1],
    skip_hash_verification=True,
    hash_skip_reason="probe",
    metadata_only=True,
)
"""
_LOAD_SKIP_HASH = b"""
import os, sys, warnings
warnings.simplefilter("always")
os.environ.pop("GOLDEN_IMAGES_DIR", None)
from scripts.eval_harness.manifest import load_manifest
load_manifest(sys.argv[1], skip_hash_verification=True, hash_skip_reason="probe")
"""
_LOAD_MISSING = b"""
import sys
from scripts.eval_harness.manifest import ManifestError, load_manifest
try:
    load_manifest(sys.argv[1])
except ManifestError as exc:
    print(str(exc), file=sys.stderr)
"""
_LOAD_UNREADABLE = b"""
import sys
from scripts.eval_harness.manifest import ManifestError, load_manifest
try:
    load_manifest(sys.argv[1], skip_hash_verification=True)
except ManifestError as exc:
    print(str(exc), file=sys.stderr)
"""
_LOAD_LEGACY_MISSING = b"""
import sys
from scripts.eval_harness.manifest import ManifestError, load_legacy_manifest
try:
    load_legacy_manifest(sys.argv[1])
except ManifestError as exc:
    print(str(exc), file=sys.stderr)
"""
_LOAD_LEGACY_UNREADABLE = b"""
import sys
from scripts.eval_harness.manifest import ManifestError, load_legacy_manifest
try:
    load_legacy_manifest(sys.argv[1])
except ManifestError as exc:
    print(str(exc), file=sys.stderr)
"""
_LOAD_IDENTITY = b"""
import sys
from scripts.eval_harness.manifest import ManifestError, load_manifest
try:
    load_manifest(sys.argv[1], skip_hash_verification=True)
except ManifestError as exc:
    print(str(exc), file=sys.stderr)
"""
_RESOLVE_MISSING_ROOT = b"""
import sys
from scripts.eval_harness.manifest import ManifestError, load_manifest, resolve_verified_image
man = load_manifest(sys.argv[1], skip_hash_verification=True)
try:
    resolve_verified_image(man.entries[0], sys.argv[2])
except ManifestError as exc:
    print(str(exc), file=sys.stderr)
"""
_LOAD_VERIFY_MISSING_ROOT = b"""
import sys
from scripts.eval_harness.manifest import ManifestError, load_manifest
try:
    load_manifest(sys.argv[1], images_dir=sys.argv[2])
except ManifestError as exc:
    print(str(exc), file=sys.stderr)
"""

_LINEAGE = {
    "labeler_id": "legacy-import",
    "batch_id": "fir-11-slice-2-v3-migration",
    "pass_index": 0,
    "labeled_at": "1970-01-01T00:00:00Z",
    "tool_version": "legacy-import",
    "saw_machine_proposals": True,
    "label_source": "legacy_import",
    "confidence": "low",
    "arbitration_of": None,
    "decision": "named",
    "capture_session_id": "test-session",
}

_PROVENANCE = {
    "source": "operator",
    "license": "consented",
    "note": "synthetic fixture",
}

# JoinedStr slots that are not operator path interpolations (VLM6-W17-C-03).
# Silence about a new slot is a fail: add it here with a reason or wrap it.
_AUDITED_NON_PATH_EXPRS = frozenset(
    {
        "invariant",
        "member",
        "value",
        "[member.value for member in AnnotationMode]",
        "index",
        "entry.face_count",
        "n_ids",
        "n_boxes",
        "box_index",
        "detail",
        "field",
        "', '.join(STRATIFICATION_INVENTORY_FIELDS)",
        "pop.populated",
        "pop.total",
        "gap_hint",
        "exc",
        "type(raw).__name__",
        "version",
        "SUPPORTED_MANIFEST_VERSION",
        "type(entries_raw).__name__",
        "type(raw_entry).__name__",
        "raw_entry.get('media_id')",
        "len(missing_provenance)",
        "listed",
        "entry.media_id",
        "name",
        "cohort_key",
        "hash_skip_reason",
        "skip_hash_verification",
        "reason",
        "LEGACY_MANIFEST_VERSION",
        "entry.sha256",
        "digest",
        "exc.strerror",
    }
)


def _c_locale_child_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in _ASCII_PARENT_KEYS:
        env.pop(key, None)
    env.update(_ASCII_LOCALE_ENV)
    extra = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(_SERVICE_ROOT) + (os.pathsep + extra if extra else "")
    env["PYTHONWARNINGS"] = "always"
    env.pop("GOLDEN_IMAGES_DIR", None)
    return env


def _run_c_child(script: bytes, argv: list[bytes]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [os.fsencode(sys.executable), b"-c", script, *argv],
        cwd=os.fsencode(_SERVICE_ROOT),
        env=_c_locale_child_env(),
        capture_output=True,
    )


def _host_can_produce_latin1_surrogate_argv() -> bool:
    """Measure whether a C-locale child receives 0xe9 as a PEP 383 surrogate.

    Do not branch on sys.platform — probe a real child argv (AGT-06).
    """
    global _SURROGATE_ARGV_PROBE
    if _SURROGATE_ARGV_PROBE is None:
        script = (
            b"import sys;"
            b"p=sys.argv[1];"
            b"sys.stdout.buffer.write("
            b"b'1' if any(0xDC00 <= ord(c) <= 0xDCFF for c in p) else b'0')"
        )
        proc = _run_c_child(script, [_CAFE_LATIN1])
        _SURROGATE_ARGV_PROBE = proc.returncode == 0 and proc.stdout == b"1"
    return _SURROGATE_ARGV_PROBE


def _require_surrogate_argv() -> None:
    if _host_can_produce_latin1_surrogate_argv():
        return
    pytest.skip(_SURROGATE_ARGV_SKIP)


def _latin1_cafe_dir(tmp_path: Path) -> bytes:
    dir_b = os.fsencode(tmp_path) + b"/latin1-" + _CAFE_LATIN1
    os.mkdir(dir_b)
    return dir_b


def _write_latin1_manifest(tmp_path: Path) -> bytes:
    man_b = _latin1_cafe_dir(tmp_path) + b"/man-" + _CAFE_LATIN1 + b".json"
    with open(man_b, "wb") as fh:
        fh.write(_FIXTURE.read_bytes())
    return man_b


def _assert_printable_stderr(stderr: bytes) -> None:
    """OBS-08 / TEST-15: operator path on C-locale stderr is printable bytes."""
    assert _SURROGATE_LEAK not in stderr, stderr
    assert _UNDECODABLE in stderr, stderr
    assert b"\xe9" not in stderr, stderr
    assert b"\\xe9" in stderr, stderr


def _assert_printable_text(text: str) -> bytes:
    """Same wire checks on an in-process ManifestError message.

    Catches both leak forms: a lone surrogate (utf-8 encode fails or
    backslashreplaces to \\udc) and OSError-repr flattening (literal ASCII \\udce9).
    """
    encoded = text.encode("utf-8", errors="backslashreplace")
    assert _SURROGATE_LEAK not in encoded, encoded
    assert _UNDECODABLE in encoded, encoded
    assert b"\\xe9" in encoded, encoded
    text.encode("utf-8")  # must be strict-encodable after wrapping
    return encoded


def _box(**over: object) -> dict:
    box = {
        "x": 0.5,
        "y": 0.4,
        "w": 0.2,
        "h": 0.3,
        "name": "Ada Example",
        "source": "operator",
        "lineage": dict(_LINEAGE),
    }
    box.update(over)
    return box


def _entry(path: str, **over: object) -> dict:
    entry = {
        "path": path,
        "sha256": _SHA_FAKE,
        "media_id": 1,
        "face_count": 1,
        "present_identities": ["Ada Example"],
        "base_caption": "Ada looks at the camera.",
        "must_right": ["Ada Example"],
        "easy_wrong": [],
        "policy": {"recognition_enabled": True},
        "provenance": dict(_PROVENANCE),
        "face_boxes": [],
    }
    entry.update(over)
    return entry


def _v3(*entries: dict, **over: object) -> dict:
    data: dict = {
        "manifest_version": 3,
        "annotation_mode": "roster_only",
        "roster": ["Ada Example"],
        "entries": list(entries) if entries else [_entry("fixtures/ada.jpg")],
    }
    data.update(over)
    return data


def _v2(*entries: dict, **over: object) -> dict:
    data = _v3(*entries, **over)
    data["manifest_version"] = 2
    return data


def _write_json(tmp_path: Path, data: dict, name: str = "man.json") -> str:
    path = tmp_path / name
    path.write_bytes(json.dumps(data).encode("ascii"))
    return str(path)


def _load(path: str, loader_name: str) -> None:
    if loader_name == "load_legacy_manifest":
        load_legacy_manifest(path)
        return
    load_manifest(path, skip_hash_verification=True)


def _raises_printable(tmp_path: Path, data: dict, loader_name: str) -> bytes:
    path = _write_json(tmp_path, data)
    with pytest.raises(ManifestError) as ei:
        _load(path, loader_name)
    return _assert_printable_text(str(ei.value))


# ---------------------------------------------------------------------------
# Wave-16 argv oracles (latin-1 filename via C-locale child)
# ---------------------------------------------------------------------------


def test_hash_skip_warning_metadata_only_latin1_path_is_printable(tmp_path: Path) -> None:
    """MUT manifest.py hash-skip metadata_only — raw {path} leaks \\udc."""
    _require_surrogate_argv()
    man_b = _write_latin1_manifest(tmp_path)
    proc = _run_c_child(_LOAD_METADATA_ONLY, [man_b])
    assert proc.returncode == 0, proc.stderr
    _assert_printable_stderr(proc.stderr)


def test_hash_skip_warning_skip_hash_latin1_path_is_printable(tmp_path: Path) -> None:
    """MUT manifest.py hash-skip skip_hash — raw {path} leaks \\udc."""
    _require_surrogate_argv()
    man_b = _write_latin1_manifest(tmp_path)
    proc = _run_c_child(_LOAD_SKIP_HASH, [man_b])
    assert proc.returncode == 0, proc.stderr
    _assert_printable_stderr(proc.stderr)


def test_missing_manifest_error_latin1_path_is_printable(tmp_path: Path) -> None:
    """MUT load_manifest missing-file — raw {manifest_path} leaks \\udc."""
    _require_surrogate_argv()
    missing_b = _latin1_cafe_dir(tmp_path) + b"/missing-" + _CAFE_LATIN1 + b".json"
    proc = _run_c_child(_LOAD_MISSING, [missing_b])
    assert proc.returncode == 0, proc.stderr
    assert b"golden manifest not found:" in proc.stderr, proc.stderr
    _assert_printable_stderr(proc.stderr)


# ---------------------------------------------------------------------------
# VLM6-RV18-04 / VLM6-W17-C-01 — OSError at construction; legacy missing
# ---------------------------------------------------------------------------


def test_unreadable_golden_manifest_oserror_names_printable_path(tmp_path: Path) -> None:
    """MUT load_manifest OSError {exc} — str(OSError) repr-flattens filename to \\udce9.

    chmod 000 on a latin-1-named golden. Re-encoding the finished OSError
    message is a no-op; the path must be named via _printable_path at construction.
    """
    _require_surrogate_argv()
    man_b = _write_latin1_manifest(tmp_path)
    os.chmod(man_b, 0)
    try:
        proc = _run_c_child(_LOAD_UNREADABLE, [man_b])
    finally:
        os.chmod(man_b, 0o644)
    assert proc.returncode == 0, proc.stderr
    assert b"unreadable or malformed JSON" in proc.stderr, proc.stderr
    _assert_printable_stderr(proc.stderr)


def test_unreadable_golden_manifest_oserror_inprocess_surrogate_filename(
    tmp_path: Path,
) -> None:
    """Same OSError construction leak without argv (explicit U+DCE9 Path)."""
    man = tmp_path / _SURROGATE_JSON
    man.write_bytes(_FIXTURE.read_bytes())
    os.chmod(man, 0)
    try:
        with pytest.raises(ManifestError) as ei:
            load_manifest(str(man), skip_hash_verification=True)
        encoded = _assert_printable_text(str(ei.value))
    finally:
        os.chmod(man, 0o644)
    assert b"unreadable or malformed JSON" in encoded


def test_legacy_manifest_missing_latin1_path_is_printable(tmp_path: Path) -> None:
    """MUT load_legacy_manifest missing-file — raw {manifest_path} (VLM6-W17-C-01)."""
    _require_surrogate_argv()
    missing_b = _latin1_cafe_dir(tmp_path) + b"/missing-" + _CAFE_LATIN1 + b".json"
    proc = _run_c_child(_LOAD_LEGACY_MISSING, [missing_b])
    assert proc.returncode == 0, proc.stderr
    assert b"legacy manifest not found:" in proc.stderr, proc.stderr
    _assert_printable_stderr(proc.stderr)


def test_unreadable_legacy_manifest_oserror_names_printable_path(tmp_path: Path) -> None:
    """MUT load_legacy_manifest OSError {exc} — same construction leak as golden."""
    _require_surrogate_argv()
    man_b = _write_latin1_manifest(tmp_path)
    os.chmod(man_b, 0)
    try:
        proc = _run_c_child(_LOAD_LEGACY_UNREADABLE, [man_b])
    finally:
        os.chmod(man_b, 0o644)
    assert proc.returncode == 0, proc.stderr
    assert b"unreadable or malformed JSON" in proc.stderr, proc.stderr
    _assert_printable_stderr(proc.stderr)


# ---------------------------------------------------------------------------
# VLM6-RV18-06 / VLM6-W17-C-02 — images root / missing file / sha mismatch
# ---------------------------------------------------------------------------


def test_resolve_verified_image_missing_root_is_printable(tmp_path: Path) -> None:
    """MUT resolve_verified_image images-dir-missing raw {root} (VLM6-W17-C-02)."""
    path = _write_json(tmp_path, _v3(_entry("fixtures/ada.jpg")))
    man = load_manifest(path, skip_hash_verification=True, hash_skip_reason="probe")
    with pytest.raises(ManifestError) as ei:
        resolve_verified_image(man.entries[0], str(tmp_path / _SURROGATE_LEAF))
    encoded = _assert_printable_text(str(ei.value))
    assert b"images directory not found:" in encoded


def test_resolve_verified_image_missing_root_c_child_latin1_argv(tmp_path: Path) -> None:
    """C-parent wire for C-02: latin-1 argv root through resolve_verified_image."""
    _require_surrogate_argv()
    man_b = os.fsencode(_write_json(tmp_path, _v3(_entry("fixtures/ada.jpg"))))
    missing_root = _latin1_cafe_dir(tmp_path) + b"-missing-root"
    proc = _run_c_child(_RESOLVE_MISSING_ROOT, [man_b, missing_root])
    assert proc.returncode == 0, proc.stderr
    assert b"images directory not found:" in proc.stderr, proc.stderr
    _assert_printable_stderr(proc.stderr)
    # Em-dash U+2014 in this message is non-path Unicode. Under a C parent
    # stderr it backslashreplaces to \\u2014 via the stdio error handler.
    # In-contract: not a path slot; _printable_path must not wrap the whole
    # message. Do not treat \\u2014 as a surrogate leak.
    assert b"\\udc" not in proc.stderr


def test_verify_hashes_missing_root_is_printable(tmp_path: Path) -> None:
    """MUT _verify_hashes images-dir-missing raw {images_root} (RV18-06 / 1445)."""
    path = _write_json(tmp_path, _v3(_entry("fixtures/ada.jpg")))
    with pytest.raises(ManifestError) as ei:
        load_manifest(path, images_dir=str(tmp_path / _SURROGATE_LEAF))
    encoded = _assert_printable_text(str(ei.value))
    assert b"images directory not found:" in encoded


def test_verify_hashes_missing_root_c_child_latin1_argv(tmp_path: Path) -> None:
    """C-parent wire for _verify_hashes {images_root} via load_manifest."""
    _require_surrogate_argv()
    man_b = os.fsencode(_write_json(tmp_path, _v3(_entry("fixtures/ada.jpg"))))
    missing_root = _latin1_cafe_dir(tmp_path) + b"-missing-root"
    proc = _run_c_child(_LOAD_VERIFY_MISSING_ROOT, [man_b, missing_root])
    assert proc.returncode == 0, proc.stderr
    assert b"images directory not found:" in proc.stderr, proc.stderr
    _assert_printable_stderr(proc.stderr)


def test_image_file_missing_surrogate_entry_path_is_printable(tmp_path: Path) -> None:
    """MUT image-file-missing {entry.path} (RV18-06 / 1089 path slot)."""
    images = tmp_path / "images"
    images.mkdir()
    path = _write_json(tmp_path, _v3(_entry(_SURROGATE_REL)))
    man = load_manifest(path, skip_hash_verification=True, hash_skip_reason="probe")
    with pytest.raises(ManifestError) as ei:
        resolve_verified_image(man.entries[0], str(images))
    encoded = _assert_printable_text(str(ei.value))
    assert b"image file missing:" in encoded


def test_image_file_missing_surrogate_images_root_is_printable(tmp_path: Path) -> None:
    """MUT image-file-missing {root} (RV18-06 / 1089 root slot). Root exists."""
    root = tmp_path / _SURROGATE_LEAF
    root.mkdir()
    path = _write_json(tmp_path, _v3(_entry("fixtures/ada.jpg")))
    man = load_manifest(path, skip_hash_verification=True, hash_skip_reason="probe")
    with pytest.raises(ManifestError) as ei:
        resolve_verified_image(man.entries[0], str(root))
    encoded = _assert_printable_text(str(ei.value))
    assert b"image file missing:" in encoded
    assert b"under" in encoded


def test_sha256_mismatch_surrogate_entry_path_is_printable(tmp_path: Path) -> None:
    """MUT sha256-mismatch {entry.path} (RV18-06 / 1095)."""
    images = tmp_path / "images"
    images.mkdir()
    with open(os.fsencode(images) + b"/" + _CAFE_LATIN1 + b".jpg", "wb") as fh:
        fh.write(b"tampered bytes")
    path = _write_json(tmp_path, _v3(_entry(_SURROGATE_REL)))
    man = load_manifest(path, skip_hash_verification=True, hash_skip_reason="probe")
    with pytest.raises(ManifestError) as ei:
        resolve_verified_image(man.entries[0], str(images))
    encoded = _assert_printable_text(str(ei.value))
    assert b"sha256 mismatch" in encoded


# ---------------------------------------------------------------------------
# VLM6-RV18-05 — json.loads unpaired-surrogate entry.path family
# ---------------------------------------------------------------------------


def test_identity_not_in_roster_json_surrogate_path_is_printable(tmp_path: Path) -> None:
    """MUT load_manifest identity-not-in-roster {entry.path} (RV18-05 / 1264)."""
    data = _v3(
        _entry(
            _SURROGATE_REL,
            present_identities=["NotInRoster"],
            must_right=[],
        )
    )
    encoded = _raises_printable(tmp_path, data, "load_manifest")
    assert b"is not in the roster" in encoded
    assert b"NotInRoster" in encoded


def test_identity_not_in_roster_json_surrogate_c_child_stderr(tmp_path: Path) -> None:
    """Lens V4 wire: identity in caf\\udce9.jpg must not leak \\udc on C stderr."""
    data = _v3(
        _entry(
            _SURROGATE_REL,
            present_identities=["NotInRoster"],
            must_right=[],
        )
    )
    man = _write_json(tmp_path, data)
    proc = _run_c_child(_LOAD_IDENTITY, [os.fsencode(man)])
    assert proc.returncode == 0, proc.stderr
    assert b"is not in the roster" in proc.stderr, proc.stderr
    _assert_printable_stderr(proc.stderr)


def test_legacy_identity_not_in_roster_json_surrogate_path_is_printable(
    tmp_path: Path,
) -> None:
    """MUT load_legacy_manifest identity-not-in-roster {entry.path} (RV18-05 / 1430)."""
    data = _v2(
        _entry(
            _SURROGATE_REL,
            present_identities=["NotInRoster"],
            must_right=[],
        )
    )
    encoded = _raises_printable(tmp_path, data, "load_legacy_manifest")
    assert b"is not in the roster" in encoded


def test_duplicate_path_json_surrogate_is_printable(tmp_path: Path) -> None:
    """MUT load_manifest duplicate-path {entry.path}."""
    data = _v3(
        _entry(_SURROGATE_REL, media_id=1),
        _entry(_SURROGATE_REL, media_id=2, must_right=[], present_identities=[]),
    )
    encoded = _raises_printable(tmp_path, data, "load_manifest")
    assert b"duplicate path" in encoded


def test_legacy_duplicate_path_json_surrogate_is_printable(tmp_path: Path) -> None:
    """MUT load_legacy_manifest duplicate-path {entry.path}."""
    data = _v2(
        _entry(_SURROGATE_REL, media_id=1),
        _entry(_SURROGATE_REL, media_id=2, must_right=[], present_identities=[]),
    )
    encoded = _raises_printable(tmp_path, data, "load_legacy_manifest")
    assert b"duplicate path" in encoded


def test_duplicate_media_id_json_surrogate_path_is_printable(tmp_path: Path) -> None:
    """MUT load_manifest duplicate-media_id ({entry.path})."""
    data = _v3(
        _entry("fixtures/ada.jpg", media_id=1),
        _entry(_SURROGATE_REL, media_id=1, must_right=[], present_identities=[]),
    )
    encoded = _raises_printable(tmp_path, data, "load_manifest")
    assert b"duplicate media_id" in encoded


def test_legacy_duplicate_media_id_json_surrogate_path_is_printable(
    tmp_path: Path,
) -> None:
    """MUT load_legacy_manifest duplicate-media_id ({entry.path})."""
    data = _v2(
        _entry("fixtures/ada.jpg", media_id=1),
        _entry(_SURROGATE_REL, media_id=1, must_right=[], present_identities=[]),
    )
    encoded = _raises_printable(tmp_path, data, "load_legacy_manifest")
    assert b"duplicate media_id" in encoded


def test_missing_base_caption_json_surrogate_path_is_printable(tmp_path: Path) -> None:
    """MUT v3 missing base_caption raw_entry.get('path')."""
    entry = _entry(_SURROGATE_REL)
    del entry["base_caption"]
    encoded = _raises_printable(tmp_path, _v3(entry), "load_manifest")
    assert b"base_caption" in encoded


def test_legacy_missing_base_caption_json_surrogate_path_is_printable(
    tmp_path: Path,
) -> None:
    """MUT v2 missing base_caption raw_entry.get('path')."""
    entry = _entry(_SURROGATE_REL)
    del entry["base_caption"]
    encoded = _raises_printable(tmp_path, _v2(entry), "load_legacy_manifest")
    assert b"base_caption" in encoded


def test_null_base_caption_json_surrogate_path_is_printable(tmp_path: Path) -> None:
    """MUT v3 null base_caption raw_entry.get('path')."""
    encoded = _raises_printable(
        tmp_path, _v3(_entry(_SURROGATE_REL, base_caption=None)), "load_manifest"
    )
    assert b"base_caption" in encoded


def test_legacy_null_base_caption_json_surrogate_path_is_printable(
    tmp_path: Path,
) -> None:
    """MUT v2 null base_caption raw_entry.get('path')."""
    encoded = _raises_printable(
        tmp_path,
        _v2(_entry(_SURROGATE_REL, base_caption=None)),
        "load_legacy_manifest",
    )
    assert b"base_caption" in encoded


def test_missing_provenance_json_surrogate_path_is_printable(tmp_path: Path) -> None:
    """MUT missing-provenance label interpolates raw entry_path."""
    entry = _entry(_SURROGATE_REL)
    del entry["provenance"]
    encoded = _raises_printable(tmp_path, _v3(entry), "load_manifest")
    assert b"provenance is required" in encoded


def test_per_entry_annotation_mode_json_surrogate_path_is_printable(
    tmp_path: Path,
) -> None:
    """MUT _reject_per_entry_annotation_mode {label} from raw path."""
    encoded = _raises_printable(
        tmp_path,
        _v3(_entry(_SURROGATE_REL, annotation_mode="roster_only")),
        "load_manifest",
    )
    assert b"annotation_mode is document-level" in encoded


def test_present_identities_fit_face_count_json_surrogate_path_is_printable(
    tmp_path: Path,
) -> None:
    """MUT _present_identities_fit_face_count {entry.path}."""
    encoded = _raises_printable(
        tmp_path,
        _v3(_entry(_SURROGATE_REL, face_count=0, present_identities=["Ada Example"])),
        "load_manifest",
    )
    assert b"present_identities_fit_face_count" in encoded


def test_exhaustive_boxes_cover_json_surrogate_path_is_printable(tmp_path: Path) -> None:
    """MUT _boxes_cover_face_count exhaustive {entry.path}."""
    encoded = _raises_printable(
        tmp_path,
        _v3(
            _entry(_SURROGATE_REL, face_count=2, face_boxes=[_box()]),
            annotation_mode="exhaustive",
        ),
        "load_manifest",
    )
    assert b"boxes_cover_face_count" in encoded
    assert b"exhaustive" in encoded


def test_roster_only_boxes_cover_json_surrogate_path_is_printable(
    tmp_path: Path,
) -> None:
    """MUT _boxes_cover_face_count roster_only {entry.path}."""
    encoded = _raises_printable(
        tmp_path,
        _v3(
            _entry(
                _SURROGATE_REL,
                face_count=0,
                present_identities=[],
                must_right=[],
                face_boxes=[_box()],
            )
        ),
        "load_manifest",
    )
    assert b"boxes_cover_face_count" in encoded
    assert b"roster_only" in encoded


def test_label_lineage_required_json_surrogate_path_is_printable(
    tmp_path: Path,
) -> None:
    """MUT _lineage_required_on_boxes {entry.path}."""
    box = _box()
    del box["lineage"]
    encoded = _raises_printable(
        tmp_path,
        _v3(_entry(_SURROGATE_REL, face_boxes=[box])),
        "load_manifest",
    )
    assert b"label_lineage_required" in encoded


def test_capture_session_required_json_surrogate_path_is_printable(
    tmp_path: Path,
) -> None:
    """MUT _capture_session_required_when_exhaustive {entry.path}."""
    lineage = dict(_LINEAGE)
    lineage["capture_session_id"] = None
    encoded = _raises_printable(
        tmp_path,
        _v3(
            _entry(_SURROGATE_REL, face_boxes=[_box(lineage=lineage)]),
            annotation_mode="exhaustive",
        ),
        "load_manifest",
    )
    assert b"capture_session_id_required" in encoded


# ---------------------------------------------------------------------------
# VLM6-W17-C-03 — AST census of every operator-facing emission
# ---------------------------------------------------------------------------


def _call_name(func: ast.AST) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ast.unparse(func)


def _is_printable_path_call(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and _call_name(node.func) == "_printable_path"


def _formatted_is_wrapped(node: ast.AST) -> bool:
    if _is_printable_path_call(node):
        return True
    if isinstance(node, ast.IfExp):
        return _formatted_is_wrapped(node.body)
    return False


def _is_path_like_unwrapped(node: ast.AST) -> bool:
    if _formatted_is_wrapped(node):
        return False
    text = ast.unparse(node)
    if text in _AUDITED_NON_PATH_EXPRS:
        return False
    if isinstance(node, ast.Attribute) and node.attr in {"path", "filename"}:
        return True
    if isinstance(node, ast.Name) and node.id in {
        "root",
        "manifest_path",
        "images_root",
        "entry_path",
        "path",
        "label",
    }:
        return True
    if "get('path')" in text or 'get("path")' in text:
        return True
    return False


def _operator_joined_slots() -> list[tuple[int, str, str, ast.AST]]:
    tree = ast.parse(_MANIFEST_PY.read_text(encoding="utf-8"))
    hits: list[tuple[int, str, str, ast.AST]] = []

    class Walker(ast.NodeVisitor):
        def __init__(self) -> None:
            self.stack: list[ast.AST] = []
            self.func = "<module>"

        def generic_visit(self, node: ast.AST) -> None:
            self.stack.append(node)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                prev = self.func
                self.func = node.name
                super().generic_visit(node)
                self.func = prev
                self.stack.pop()
                return
            super().generic_visit(node)
            self.stack.pop()

        def visit_JoinedStr(self, node: ast.JoinedStr) -> None:
            kind = "other"
            for parent in reversed(self.stack):
                if isinstance(parent, ast.Call) and _call_name(parent.func) in {
                    "ManifestError",
                    "warn",
                }:
                    kind = "call:" + _call_name(parent.func)
                    break
                if isinstance(parent, ast.Call) and _call_name(parent.func) == "append":
                    kind = "append"
                    break
            if kind == "other":
                self.generic_visit(node)
                return
            for value in node.values:
                if isinstance(value, ast.FormattedValue):
                    hits.append(
                        (node.lineno, self.func, ast.unparse(value.value), value.value)
                    )
            self.generic_visit(node)

    Walker().visit(tree)
    return hits


def test_operator_path_census_every_slot_is_audited() -> None:
    """VLM6-W17-C-03: every operator JoinedStr slot is wrapped or allowlisted.

    Path-like interpolations must go through _printable_path (visible in the
    FormattedValue, or IfExp body). Non-path slots must be named in
    _AUDITED_NON_PATH_EXPRS. A new silent slot fails this test.
    """
    slots = _operator_joined_slots()
    assert slots, "census found no operator JoinedStr slots"
    unwrapped_paths: list[str] = []
    unaudited: list[str] = []
    seen_non_path: set[str] = set()
    for lineno, func, text, node in slots:
        loc = f"{func}:{lineno}:{text}"
        if _is_path_like_unwrapped(node):
            unwrapped_paths.append(loc)
            continue
        if _formatted_is_wrapped(node):
            continue
        if text in _AUDITED_NON_PATH_EXPRS:
            seen_non_path.add(text)
            continue
        unaudited.append(loc)
    assert not unwrapped_paths, (
        "operator path slot interpolated without _printable_path: "
        f"{unwrapped_paths}"
    )
    assert not unaudited, (
        "operator JoinedStr slot neither wrapped nor in _AUDITED_NON_PATH_EXPRS: "
        f"{unaudited}"
    )
    unused = _AUDITED_NON_PATH_EXPRS - seen_non_path
    assert not unused, f"stale census allowlist entries: {sorted(unused)}"


def test_missing_provenance_loop_calls_printable_path() -> None:
    """listed is joined pre-wrapped labels; the loop must call _printable_path."""
    tree = ast.parse(_MANIFEST_PY.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "load_manifest":
            calls = [
                n
                for n in ast.walk(node)
                if _is_printable_path_call(n)
                and any(
                    isinstance(arg, ast.Name) and arg.id == "entry_path"
                    for arg in n.args
                )
            ]
            assert calls, (
                "load_manifest missing-provenance loop does not wrap entry_path "
                "with _printable_path"
            )
            return
    raise AssertionError("load_manifest not found")


def test_oserror_handlers_name_filename_through_printable_path() -> None:
    """VLM6-RV18-04: OSError handlers must not interpolate {exc} for the path."""
    tree = ast.parse(_MANIFEST_PY.read_text(encoding="utf-8"))
    found = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        type_text = ast.unparse(node.type) if node.type is not None else ""
        if "OSError" not in type_text:
            continue
        if not any(_is_printable_path_call(n) for n in ast.walk(node)):
            continue
        found += 1
        has_filename_wrap = False
        for inner in ast.walk(node):
            if not _is_printable_path_call(inner):
                continue
            args = inner.args
            if args and ast.unparse(args[0]) in {"exc.filename", "filename"}:
                has_filename_wrap = True
        assert has_filename_wrap, (
            f"OSError handler at line {node.lineno} does not wrap exc.filename "
            "with _printable_path"
        )
        for inner in ast.walk(node):
            if isinstance(inner, ast.JoinedStr):
                for value in inner.values:
                    if not isinstance(value, ast.FormattedValue):
                        continue
                    expr = ast.unparse(value.value)
                    assert expr != "exc", (
                        f"OSError handler still interpolates {{exc}} at line "
                        f"{inner.lineno}; name the path through _printable_path "
                        "(str(OSError) repr-flattens filename to \\\\udce9)"
                    )
    assert found >= 2, (
        f"expected load_manifest and load_legacy_manifest OSError handlers "
        f"to call _printable_path; found {found}"
    )
