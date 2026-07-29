"""CVU-02V / CVUP1-LC-05/06: golden toolchain stamps + cv2 distribution guards.

- Golden metas must record which OpenCV/numpy produced them (majors only).
- Conflicting opencv-python* distributions in one env must fail closed.
- Probe DEFAULT_MATCH_THRESHOLD must track settings _LEGACY_SIMILARITY_THRESHOLD.
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import re
import sys
from pathlib import Path

import cv2
import pytest

from recognition.config import settings as settings_mod

_SERVICE_ROOT = Path(__file__).resolve().parents[3]
_FIXTURE_DIR = _SERVICE_ROOT / "recognition" / "tests" / "fixtures" / "face_pipeline"
_REGENERATE_CMD = (
    "uv run python recognition/tests/fixtures/face_pipeline/generate_goldens.py"
)

_PROVENANCE_KEYS = ("opencv_version", "numpy_version", "generator")
_GOLDEN_METAS = (
    "detector_faces.json",
    "embedding_meta.json",
    "aligner_meta.json",
    "aligner_composed_embedding_meta.json",
)


def _load_meta(name: str) -> dict:
    path = _FIXTURE_DIR / name
    assert path.is_file(), f"missing golden meta: {path}"
    return json.loads(path.read_text(encoding="utf-8"))


def _major(version: str) -> str:
    """First numeric component of a PEP 440-ish version string."""
    match = re.match(r"(\d+)", str(version).strip())
    assert match is not None, f"unparseable version: {version!r}"
    return match.group(1)


def test_golden_metas_carry_toolchain_provenance() -> None:
    """Every golden meta records opencv/numpy/generator with non-empty values."""
    for name in _GOLDEN_METAS:
        meta = _load_meta(name)
        for key in _PROVENANCE_KEYS:
            assert key in meta, f"{name} missing provenance key {key!r}"
            value = meta[key]
            assert isinstance(value, str) and value.strip(), (
                f"{name}.{key} must be a non-empty string, got {value!r}"
            )


def test_golden_opencv_major_matches_runtime() -> None:
    """Running cv2 major must match the major stamped into the goldens.

    Compare majors only — patch bumps must not fail CI. On mismatch, the
    message names the regenerate command so the fix is copy-pasteable.
    """
    runtime_major = _major(cv2.__version__)
    for name in _GOLDEN_METAS:
        recorded = _load_meta(name)["opencv_version"]
        recorded_major = _major(recorded)
        assert recorded_major == runtime_major, (
            f"{name} was generated under OpenCV major {recorded_major} "
            f"(opencv_version={recorded!r}) but runtime is major "
            f"{runtime_major} (cv2.__version__={cv2.__version__!r}). "
            f"Regenerate goldens from apps/prototype-description-service:\n"
            f"  {_REGENERATE_CMD}"
        )


def _opencv_python_distributions() -> list[tuple[str, str]]:
    """Installed distributions whose name starts with ``opencv-python``."""
    found: list[tuple[str, str]] = []
    for dist in importlib.metadata.distributions():
        name = None
        if dist.metadata is not None:
            name = dist.metadata["Name"]
        if not name:
            name = getattr(dist, "name", None)
        if not name:
            continue
        if str(name).lower().startswith("opencv-python"):
            found.append((str(name), dist.version))
    return found


def test_no_conflicting_cv2_distributions() -> None:
    """All installed opencv-python* distributions must report the same version.

    opencv-python and opencv-python-headless both unpack into top-level cv2/;
    install order, not the constraint, decides which one imports. Default env
    typically has only one — the test passes trivially and fires under
    ``--extra bench`` when both are present at different versions.
    """
    dists = _opencv_python_distributions()
    if not dists:
        pytest.skip("no opencv-python* distribution installed")
    versions = {version for _name, version in dists}
    assert len(versions) == 1, (
        "conflicting opencv-python* distributions share top-level cv2/ and "
        f"must pin the same version; found {sorted(dists)!r}"
    )


def _load_probe_module():
    """Load probe script as a module to read DEFAULT_MATCH_THRESHOLD."""
    probe_path = _SERVICE_ROOT / "scripts" / "probe_opencv_embedding_drift.py"
    mod_name = "_probe_opencv_embedding_drift_under_test"
    if mod_name in sys.modules:
        del sys.modules[mod_name]
    if str(_SERVICE_ROOT) not in sys.path:
        sys.path.insert(0, str(_SERVICE_ROOT))
    spec = importlib.util.spec_from_file_location(mod_name, probe_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


def test_probe_match_threshold_tracks_settings() -> None:
    """Probe DEFAULT_MATCH_THRESHOLD must equal settings legacy threshold.

    The probe duplicates the constant because its baseline pass runs in a bare
    cv2+numpy env that cannot import pydantic-settings. This pin prevents silent
    drift between the two definitions.
    """
    probe = _load_probe_module()
    assert probe.DEFAULT_MATCH_THRESHOLD == settings_mod._LEGACY_SIMILARITY_THRESHOLD, (
        f"probe DEFAULT_MATCH_THRESHOLD={probe.DEFAULT_MATCH_THRESHOLD!r} drifted "
        f"from settings._LEGACY_SIMILARITY_THRESHOLD="
        f"{settings_mod._LEGACY_SIMILARITY_THRESHOLD!r}"
    )
