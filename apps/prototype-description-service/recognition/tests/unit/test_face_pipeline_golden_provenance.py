"""CVU-02V / CVUP1-LC-05/06: golden toolchain stamps + cv2 distribution guards.

- Golden metas must record OpenCV / onnxruntime / numpy / generator stamps.
- Live runtime is compared to committed stamps at pin-meaningful granularity.
- Conflicting opencv-python* distributions in one env must fail closed.
- Probe DEFAULT_MATCH_THRESHOLD must track settings _LEGACY_SIMILARITY_THRESHOLD.
- Committed fixtures must match what generate_goldens.py currently emits (CVUP-1-BR-03).
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytest

from recognition.config import settings as settings_mod
from recognition.infrastructure.face_pipeline.provenance import numeric_runtime_fingerprint

_SERVICE_ROOT = Path(__file__).resolve().parents[3]
_FIXTURE_DIR = _SERVICE_ROOT / "recognition" / "tests" / "fixtures" / "face_pipeline"
_REGENERATE_CMD = "uv run python recognition/tests/fixtures/face_pipeline/generate_goldens.py"

# Keys stamped by generate_goldens.toolchain_provenance(); schema-compared always.
# Version stamps are value-compared only by test_golden_toolchain_stamps_match_runtime
# at pin-meaningful granularity; assert_meta_values_equal skips them so a routine
# ORT/numpy patch resolve cannot force regenerating fixtures whose bytes cannot move.
_PROVENANCE_KEYS = ("opencv_version", "onnxruntime_version", "numpy_version", "generator")
_TOOLCHAIN_STAMP_KEYS = frozenset({"opencv_version", "onnxruntime_version", "numpy_version"})
_GOLDEN_METAS = (
    "detector_faces.json",
    "embedding_meta.json",
    "aligner_meta.json",
    "aligner_composed_embedding_meta.json",
)
# Metas whose golden bytes are produced through an ORT inference path.
# Empty today: all four goldens come from the OpenCV reference oracle
# (FaceRecognizerSF.alignCrop / FaceDetectorYN / OpenCVSFaceEmbedder). When an
# ORT-generated golden is added, name it here so the runtime ORT stamp assert
# turns on for that meta only.
_ORT_DERIVED_GOLDEN_METAS: frozenset[str] = frozenset()

# Same floors as test_face_pipeline_opencv_ref.py golden compares — do not invent new ones.
_GOLDEN_COSINE_MIN = 0.99999999
_ALIGN_AFFINE_ATOL = 1e-4
_ALIGN_CROP_MAX_ABS = 1.0
_ALIGN_CROP_MAE = 0.05

# Generator-produced arrays under face_pipeline/ (relative names).
_GOLDEN_NPY = (
    "synthetic_112_crop.npy",
    "synthetic_112_embedding.npy",
    "aligner_source_image.npy",
    "aligner_landmarks.npy",
    "aligner_affine.npy",
    "aligner_crop.npy",
    "aligner_composed_embedding.npy",
)


def _load_meta(name: str) -> dict:
    path = _FIXTURE_DIR / name
    assert path.is_file(), f"missing golden meta: {path}"
    loaded: dict = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def _version_components(version: str, n: int) -> tuple[int, ...]:
    """First ``n`` numeric components of a PEP 440-ish version string."""
    parts = [int(p) for p in re.findall(r"\d+", str(version).strip())]
    assert parts, f"unparseable version: {version!r}"
    if len(parts) < n:
        parts.extend([0] * (n - len(parts)))
    return tuple(parts[:n])


def test_golden_metas_carry_toolchain_provenance() -> None:
    """Every golden meta records opencv/onnxruntime/numpy/generator with non-empty values."""
    for name in _GOLDEN_METAS:
        meta = _load_meta(name)
        for key in _PROVENANCE_KEYS:
            assert key in meta, f"{name} missing provenance key {key!r}"
            value = meta[key]
            assert isinstance(value, str) and value.strip(), f"{name}.{key} must be a non-empty string, got {value!r}"


def test_golden_toolchain_stamps_match_runtime() -> None:
    """Live numeric runtimes must match golden stamps at pin-meaningful granularity.

    Granularity mirrors how each package participates in the golden protocol and
    in production ``space_token`` (``cv{full opencv}/ort{major.minor}``):

    - OpenCV: full version. Pin is exact (``opencv-python==5.0.0.93`` /
      ``opencv-python-headless==5.0.0.93``) and ``space_token`` embeds the full
      OpenCV version string, so a 5.0.0.x → 5.1.0.x bump must fail this guard
      the same way it partitions the persisted corpus.
    - onnxruntime: major.minor, and only for metas in
      ``_ORT_DERIVED_GOLDEN_METAS``. Floor is ``>=1.28.0,<2.0.0``; ``space_token``
      folds ORT major.minor. Patch bumps under the floor are not a golden-protocol
      event. Today no golden crosses an ORT inference path (all four use the
      OpenCV reference oracle), so the ORT assert is dormant until an ORT-derived
      golden is added and listed in that set.
    - numpy: major.minor. Floor is ``>=2.5.1,<3.0.0``; not in ``space_token`` but
      stamped because array ABI can move clustering. Patch bumps under 2.5.x
      allowed.
    - generator: exact path equality (not a package version).

    On mismatch the message names the regenerate command.
    """
    fp = numeric_runtime_fingerprint()
    for name in _GOLDEN_METAS:
        meta = _load_meta(name)
        recorded_cv = meta["opencv_version"]
        assert recorded_cv == fp.opencv_version, (
            f"{name} was generated under OpenCV {recorded_cv!r} "
            f"but runtime is {fp.opencv_version!r}. "
            f"Regenerate goldens from apps/prototype-description-service:\n"
            f"  {_REGENERATE_CMD}"
        )
        if name in _ORT_DERIVED_GOLDEN_METAS:
            recorded_ort = meta["onnxruntime_version"]
            assert _version_components(recorded_ort, 2) == _version_components(fp.onnxruntime_version, 2), (
                f"{name} was generated under onnxruntime major.minor "
                f"{'.'.join(str(x) for x in _version_components(recorded_ort, 2))} "
                f"(onnxruntime_version={recorded_ort!r}) but runtime is "
                f"{fp.onnxruntime_version!r}. "
                f"Regenerate goldens from apps/prototype-description-service:\n"
                f"  {_REGENERATE_CMD}"
            )
        recorded_np = meta["numpy_version"]
        assert _version_components(recorded_np, 2) == _version_components(fp.numpy_version, 2), (
            f"{name} was generated under numpy major.minor "
            f"{'.'.join(str(x) for x in _version_components(recorded_np, 2))} "
            f"(numpy_version={recorded_np!r}) but runtime is {fp.numpy_version!r}. "
            f"Regenerate goldens from apps/prototype-description-service:\n"
            f"  {_REGENERATE_CMD}"
        )
        assert meta["generator"] == ("recognition/tests/fixtures/face_pipeline/generate_goldens.py"), (
            f"{name}.generator drifted: {meta['generator']!r}"
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
    # Not a skip. opencv-python is a hard dependency; finding zero of them means
    # cv2 arrived from somewhere this guard cannot see, which is the failure mode,
    # not an excuse to stand down. A skip here would reproduce the remote-gate
    # greenwash exactly: green output, nothing checked.
    assert dists, (
        "no opencv-python* distribution found via importlib.metadata, yet "
        f"cv2 imports as {cv2.__version__!r} — the pin in pyproject.toml is not "
        "what this environment is running"
    )
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
    """Probe DEFAULT_* decision-boundary fallbacks must track ClusteringSettings.

    The probe duplicates the constants because its baseline pass runs in a bare
    cv2+numpy env that cannot import pydantic-settings. This pin prevents silent
    drift between the two definitions.
    """
    from recognition.application.settings.clustering import ClusteringSettings

    probe = _load_probe_module()
    settings = ClusteringSettings()
    assert probe.DEFAULT_MATCH_THRESHOLD == settings_mod._LEGACY_SIMILARITY_THRESHOLD, (
        f"probe DEFAULT_MATCH_THRESHOLD={probe.DEFAULT_MATCH_THRESHOLD!r} drifted "
        f"from settings._LEGACY_SIMILARITY_THRESHOLD="
        f"{settings_mod._LEGACY_SIMILARITY_THRESHOLD!r}"
    )
    assert settings.suggestion_floor == probe.DEFAULT_SUGGESTION_FLOOR, (
        f"probe DEFAULT_SUGGESTION_FLOOR={probe.DEFAULT_SUGGESTION_FLOOR!r} drifted "
        f"from ClusteringSettings.suggestion_floor={settings.suggestion_floor!r}"
    )
    assert settings.low_confidence_band_width == probe.DEFAULT_LOW_CONFIDENCE_BAND_WIDTH, (
        f"probe DEFAULT_LOW_CONFIDENCE_BAND_WIDTH="
        f"{probe.DEFAULT_LOW_CONFIDENCE_BAND_WIDTH!r} drifted from "
        f"ClusteringSettings.low_confidence_band_width="
        f"{settings.low_confidence_band_width!r}"
    )


def _synthetic_pass_pair(*, nn_cosine: float) -> tuple[Any, Any]:
    """Build three-face Pass pair with a single NN flip at ``nn_cosine``.

    Face 0's baseline NN is face 1; current NN is face 2. Both neighbour
    cosines equal ``nn_cosine``. Self-similarity stays near 1 so impostor
    separation is not the deciding factor.
    """
    probe = _load_probe_module()
    dim = 128
    ortho = float(math.sqrt(max(0.0, 1.0 - nn_cosine * nn_cosine)))
    low = 0.20
    ortho_low = float(math.sqrt(max(0.0, 1.0 - low * low)))

    base_emb = np.zeros((3, dim), dtype=np.float64)
    cur_emb = np.zeros((3, dim), dtype=np.float64)
    # face 0: same unit vector across versions
    base_emb[0, 0] = 1.0
    cur_emb[0, 0] = 1.0
    # baseline: face0·face1 = nn_cosine, face0·face2 = low
    base_emb[1, 0] = nn_cosine
    base_emb[1, 1] = ortho
    base_emb[2, 0] = low
    base_emb[2, 2] = ortho_low
    # current: face0·face2 = nn_cosine, face0·face1 = low  (NN flip)
    cur_emb[1, 0] = low
    cur_emb[1, 1] = ortho_low
    cur_emb[2, 0] = nn_cosine
    cur_emb[2, 2] = ortho

    boxes = np.asarray(
        [[0.0, 0.0, 10.0, 10.0], [20.0, 0.0, 10.0, 10.0], [40.0, 0.0, 10.0, 10.0]],
        dtype=np.float64,
    )
    # Distinct images so cross-face pairs count as impostors (not same-image).
    images = ["a.jpg", "b.jpg", "c.jpg"]
    keys = [f"{img}#0" for img in images]
    digest = "synthetic-corpus-digest"
    base = probe.Pass(
        keys=keys,
        boxes=boxes,
        embeddings=base_emb,
        images=images,
        opencv_version="4.0.0",
        numpy_version=np.__version__,
        corpus_digest=digest,
    )
    cur = probe.Pass(
        keys=keys,
        boxes=boxes.copy(),
        embeddings=cur_emb,
        images=list(images),
        opencv_version="5.0.0",
        numpy_version=np.__version__,
        corpus_digest=digest,
    )
    return base, cur


def test_probe_analyse_suggestion_band_nn_flip_is_nonfatal() -> None:
    """NN flip at cosine 0.38 lands in suggestion band; verdict stays PASS."""
    probe = _load_probe_module()
    base, cur = _synthetic_pass_pair(nn_cosine=0.38)
    stats = probe.analyse(
        base,
        cur,
        min_iou=0.5,
        suggestion_ceiling=0.55,
        suggestion_floor=0.35,
        suggestion_band_floor=0.30,
    )
    assert len(stats["suggestion_band_nn_flips"]) >= 1
    assert stats["decisive_nn_flips"] == []
    assert stats["subthreshold_nn_flips"] == []
    ok, _why = probe.verdict(stats)
    assert ok is True


def test_probe_analyse_decisive_nn_flip_fails_verdict() -> None:
    """NN flip at cosine above suggestion_ceiling lands decisive; verdict FAIL."""
    probe = _load_probe_module()
    base, cur = _synthetic_pass_pair(nn_cosine=0.60)
    stats = probe.analyse(
        base,
        cur,
        min_iou=0.5,
        suggestion_ceiling=0.55,
        suggestion_floor=0.35,
        suggestion_band_floor=0.30,
    )
    assert len(stats["decisive_nn_flips"]) >= 1
    assert stats["suggestion_band_nn_flips"] == []
    ok, _why = probe.verdict(stats)
    assert ok is False


# ---------------------------------------------------------------------------
# CVUP-1-BR-03: generator-vs-fixture drift guard
# ---------------------------------------------------------------------------


def _load_generate_goldens():
    """Load generate_goldens.py as a module (same pattern as face_pipeline_support)."""
    gen_path = _FIXTURE_DIR / "generate_goldens.py"
    mod_name = "_face_pipeline_generate_goldens_under_test"
    if mod_name in sys.modules:
        del sys.modules[mod_name]
    if str(_SERVICE_ROOT) not in sys.path:
        sys.path.insert(0, str(_SERVICE_ROOT))
    spec = importlib.util.spec_from_file_location(mod_name, gen_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


def collect_schema_key_mismatches(
    committed: Any,
    generated: Any,
    *,
    path: str = "",
) -> list[str]:
    """Recursive key-set diff for nested dicts. Missing and extra keys both report.

    Non-dict leaves are not type-checked here — only the schema (key topology).
    Lists are walked positionally so nested dicts inside lists still get keys.
    """
    mismatches: list[str] = []
    label = path or "<root>"

    if isinstance(committed, dict) and isinstance(generated, dict):
        committed_keys = set(committed)
        generated_keys = set(generated)
        missing = sorted(committed_keys - generated_keys)
        extra = sorted(generated_keys - committed_keys)
        for key in missing:
            mismatches.append(f"missing key {path + '.' if path else ''}{key}")
        for key in extra:
            mismatches.append(f"extra key {path + '.' if path else ''}{key}")
        for key in sorted(committed_keys & generated_keys):
            child = f"{path}.{key}" if path else key
            mismatches.extend(collect_schema_key_mismatches(committed[key], generated[key], path=child))
        return mismatches

    if isinstance(committed, list) and isinstance(generated, list):
        # A length change is drift in its own right (e.g. the detector starts
        # emitting a second face); zip alone would silently ignore the tail.
        if len(committed) != len(generated):
            mismatches.append(
                f"list length {label or '<root>'}: committed {len(committed)}, generated {len(generated)}"
            )
        for i, (c_item, g_item) in enumerate(zip(committed, generated, strict=False)):
            mismatches.extend(collect_schema_key_mismatches(c_item, g_item, path=f"{label}[{i}]"))
        return mismatches

    return mismatches


def assert_meta_schema_equal(
    committed: dict,
    generated: dict,
    *,
    meta_name: str,
) -> None:
    """HARD assertion: generator meta keys must equal committed meta keys (recursive)."""
    mismatches = collect_schema_key_mismatches(committed, generated)
    detail = "; ".join(mismatches)
    assert not mismatches, (
        f"{meta_name} schema drifted between committed fixtures and "
        f"generate_goldens.py output ({detail}). "
        f"Regenerate goldens from apps/prototype-description-service:\n"
        f"  {_REGENERATE_CMD}"
    )


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def assert_meta_values_equal(
    committed: Any,
    generated: Any,
    *,
    path: str = "",
    meta_name: str = "",
    detector_tol: dict | None = None,
) -> None:
    """Compare meta values; version stamps deferred to the granularity guard.

    OpenCV / ORT / numpy stamps are excluded from exact value compare — those
    are owned by ``test_golden_toolchain_stamps_match_runtime`` at pin-meaningful
    granularity. ``generator`` still compares exact so a path drift fails closed.
    Numeric detection fields use the committed detector tolerances when present;
    other numbers use a tight float compare.
    """
    label = path or meta_name or "<root>"

    if isinstance(committed, dict) and isinstance(generated, dict):
        # Schema already asserted equal; walk shared keys only. Skip package
        # version stamps at the meta root — exact-string compare would contradict
        # the major.minor (ORT/numpy) / full-version (OpenCV) policy above.
        for key in sorted(set(committed) & set(generated)):
            if not path and key in _TOOLCHAIN_STAMP_KEYS:
                continue
            child = f"{path}.{key}" if path else key
            assert_meta_values_equal(
                committed[key],
                generated[key],
                path=child,
                meta_name=meta_name,
                detector_tol=detector_tol,
            )
        return

    if isinstance(committed, list) and isinstance(generated, list):
        assert len(committed) == len(generated), (
            f"{label}: list length {len(generated)} != committed {len(committed)}. Regenerate:\n  {_REGENERATE_CMD}"
        )
        # Homogeneous numeric lists (bbox, coords): bulk allclose.
        if committed and all(_is_number(x) for x in committed) and all(_is_number(x) for x in generated):
            atol = _numeric_list_atol(path, detector_tol)
            np.testing.assert_allclose(
                np.asarray(generated, dtype=np.float64),
                np.asarray(committed, dtype=np.float64),
                atol=atol,
                rtol=0.0,
                err_msg=f"{label} numeric list drifted. Regenerate:\n  {_REGENERATE_CMD}",
            )
            return
        # Nested lists (e.g. landmarks_xy as list-of-pairs).
        if committed and all(isinstance(x, list) for x in committed):
            flat_c = np.asarray(committed, dtype=np.float64)
            flat_g = np.asarray(generated, dtype=np.float64)
            if flat_c.shape == flat_g.shape and np.issubdtype(flat_c.dtype, np.number):
                atol = _numeric_list_atol(path, detector_tol)
                np.testing.assert_allclose(
                    flat_g,
                    flat_c,
                    atol=atol,
                    rtol=0.0,
                    err_msg=f"{label} nested numeric list drifted. Regenerate:\n  {_REGENERATE_CMD}",
                )
                return
        for i, (c_item, g_item) in enumerate(zip(committed, generated, strict=True)):
            assert_meta_values_equal(
                c_item,
                g_item,
                path=f"{label}[{i}]",
                meta_name=meta_name,
                detector_tol=detector_tol,
            )
        return

    if _is_number(committed) and _is_number(generated):
        atol = 0.0
        # detection.score only — not tolerances.score.
        if detector_tol is not None and path == "detection.score":
            atol = float(detector_tol.get("score", 0.0))
        if atol > 0.0:
            assert generated == pytest.approx(committed, abs=atol), (
                f"{label}: generated {generated!r} != committed {committed!r} "
                f"(atol={atol}). Regenerate:\n  {_REGENERATE_CMD}"
            )
        else:
            assert math.isclose(float(generated), float(committed), rel_tol=0.0, abs_tol=1e-9), (
                f"{label}: generated {generated!r} != committed {committed!r}. Regenerate:\n  {_REGENERATE_CMD}"
            )
        return

    assert generated == committed, (
        f"{label}: generated {generated!r} != committed {committed!r}. Regenerate:\n  {_REGENERATE_CMD}"
    )


def _numeric_list_atol(path: str, detector_tol: dict | None) -> float:
    if detector_tol is None:
        return 0.0
    if path == "detection.bbox_xywh":
        return float(detector_tol.get("bbox_px", 0.0))
    if path == "detection.landmarks_xy" or path.startswith("detection.landmarks_xy"):
        return float(detector_tol.get("landmarks_px", 0.0))
    return 0.0


def _embedding_cosine(a: np.ndarray, b: np.ndarray) -> float:
    a = np.asarray(a, dtype=np.float64).reshape(-1)
    b = np.asarray(b, dtype=np.float64).reshape(-1)
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))


def assert_npy_matches_golden(name: str, committed: np.ndarray, generated: np.ndarray) -> None:
    """Compare one generator-produced .npy using existing unit-test tolerances."""
    if name in ("synthetic_112_embedding.npy", "aligner_composed_embedding.npy"):
        meta_name = "embedding_meta.json" if name.startswith("synthetic") else "aligner_composed_embedding_meta.json"
        meta = _load_meta(meta_name)
        cosine_min = float(meta.get("cosine_min", _GOLDEN_COSINE_MIN))
        cos = _embedding_cosine(generated[0], committed[0])
        assert cos >= cosine_min, (
            f"{name}: cosine(generated, committed)={cos} < {cosine_min}. Regenerate:\n  {_REGENERATE_CMD}"
        )
        return

    if name == "aligner_affine.npy":
        np.testing.assert_allclose(
            generated,
            committed,
            atol=_ALIGN_AFFINE_ATOL,
            err_msg=f"{name} drifted. Regenerate:\n  {_REGENERATE_CMD}",
        )
        return

    if name == "aligner_crop.npy":
        # Cross-host crop budgets from test_aligner_affine_and_crop_match_goldens.
        diff = np.abs(generated.astype(np.float32) - committed.astype(np.float32))
        assert float(diff.max()) <= _ALIGN_CROP_MAX_ABS, (
            f"{name}: max abs pixel diff {float(diff.max())} > {_ALIGN_CROP_MAX_ABS}. Regenerate:\n  {_REGENERATE_CMD}"
        )
        assert float(diff.mean()) <= _ALIGN_CROP_MAE, (
            f"{name}: mean abs pixel diff {float(diff.mean())} > {_ALIGN_CROP_MAE}. Regenerate:\n  {_REGENERATE_CMD}"
        )
        return

    # Seed-deterministic images / landmarks: exact match on same host.
    np.testing.assert_array_equal(
        generated,
        committed,
        err_msg=f"{name} drifted. Regenerate:\n  {_REGENERATE_CMD}",
    )


def test_meta_schema_equal_red_on_extra_and_missing_keys() -> None:
    """TEST-15: schema helper goes red on synthetic extra + missing keys (hermetic)."""
    committed = {
        "kind": "synthetic",
        "stable": 1,
        "nested": {"keep": True, "gone": 2},
    }
    # One extra key (new_field) and one missing key (gone) vs committed.
    generated = {
        "kind": "synthetic",
        "stable": 1,
        "nested": {"keep": True, "new_field": 3},
    }
    mismatches = collect_schema_key_mismatches(committed, generated)
    assert any("gone" in m for m in mismatches), mismatches
    assert any("new_field" in m for m in mismatches), mismatches

    with pytest.raises(AssertionError) as ei:
        assert_meta_schema_equal(committed, generated, meta_name="synthetic_meta.json")
    msg = str(ei.value)
    assert "gone" in msg
    assert "new_field" in msg
    assert _REGENERATE_CMD in msg


def test_committed_fixtures_match_current_generator(tmp_path: Path) -> None:
    """Run generate_goldens into tmp_path; schema + values must match committed fixtures.

    No skip: missing models fail via load_verified_model (fail closed, not greenwash).
    """
    from recognition.infrastructure.face_pipeline.provenance import load_verified_model

    # Fail loud if ONNX bytes are absent or corrupt — never skip.
    load_verified_model("sface")
    load_verified_model("yunet")

    gen = _load_generate_goldens()
    out = tmp_path / "goldens"
    out.mkdir()
    gen.write_embedding_goldens(output_dir=out)
    gen.write_aligner_goldens(output_dir=out)
    gen.write_composed_aligner_embedder_goldens(output_dir=out)
    gen.write_detector_goldens(output_dir=out)

    for name in _GOLDEN_METAS:
        committed_path = _FIXTURE_DIR / name
        generated_path = out / name
        assert committed_path.is_file(), f"missing committed golden meta: {committed_path}"
        assert generated_path.is_file(), (
            f"generator did not write {name} under {out} "
            f"(detector may have written a skip note instead). "
            f"Regenerate:\n  {_REGENERATE_CMD}"
        )
        committed = json.loads(committed_path.read_text(encoding="utf-8"))
        generated = json.loads(generated_path.read_text(encoding="utf-8"))
        assert_meta_schema_equal(committed, generated, meta_name=name)
        det_tol = committed.get("tolerances") if name == "detector_faces.json" else None
        assert_meta_values_equal(
            committed,
            generated,
            meta_name=name,
            detector_tol=det_tol if isinstance(det_tol, dict) else None,
        )

    for name in _GOLDEN_NPY:
        committed_path = _FIXTURE_DIR / name
        generated_path = out / name
        assert committed_path.is_file(), f"missing committed golden array: {committed_path}"
        assert generated_path.is_file(), f"generator did not write {name} under {out}"
        assert_npy_matches_golden(name, np.load(committed_path), np.load(generated_path))
