"""FIR-5 S2: face run-record schema, candidate walker, buffalo guard, isolation gates.

Heuristics: TEST-06/TEST-15 (assertions can go red), EMB-01, PROV-05, rg-007,
rg-015, ARCH-06 (walker fork covered by isolation tests, not caption client).
"""

from __future__ import annotations

import importlib
import inspect
import io
import json
import subprocess
import sys
import tokenize
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from recognition.infrastructure.face_pipeline._common import (
    RawDetection,
    resolve_sface_embedding_dim,
)
from scripts.eval_harness.face_bakeoff import (
    DEFAULT_STALL_LIMIT,
    BoundedStallError,
    walk_face_run_record,
)
from scripts.eval_harness.face_run_record import (
    FaceRunRecordError,
    build_face_detection,
    build_face_run_item,
    build_face_run_record,
    validate_face_run_item,
)
from scripts.eval_harness.manifest import GoldenManifest
from scripts.eval_harness.schema import SCHEMA, DocKind

EMB_DET_TAU = 0.9999

_SERVICE_ROOT = Path(__file__).resolve().parents[2]  # apps/prototype-description-service
_HARNESS_DIR = _SERVICE_ROOT / "scripts" / "eval_harness"
_FIXTURE_DIR = _SERVICE_ROOT / "recognition" / "tests" / "fixtures" / "face_pipeline"
_SYNTH_CROP = _FIXTURE_DIR / "synthetic_112_crop.npy"

_FORBIDDEN_MODULE_SUFFIXES = ("face_pass", "seed_roster", "remote_client")
_FORBIDDEN_EMBEDDINGS_PREFIX = "recognition.infrastructure.embeddings"
_FORBIDDEN_SOURCE_SYMBOLS = (
    "RemoteSceneClient",
    "media_identities",
    "InsightFaceAdapter",
    "get_shared_insightface_adapter",
)
_S2_SOURCE_FILES = (
    _HARNESS_DIR / "face_bakeoff.py",
    _HARNESS_DIR / "face_run_record.py",
    _HARNESS_DIR / "buffalo_bench.py",
)


def _unit_vec(dim: int, seed: int = 0) -> list[float]:
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(dim).astype(np.float64)
    v = v / np.linalg.norm(v)
    return [float(x) for x in v]


def _landmarks5() -> list[list[float]]:
    return [[10.0 + i, 20.0 + i] for i in range(5)]


def _well_formed_item(*, dim: int | None = None) -> dict[str, Any]:
    embedding_dim = int(dim if dim is not None else resolve_sface_embedding_dim())
    return build_face_run_item(
        media_id=42,
        path="mock/alice.jpg",
        model_id="ort-yunet-sface",
        embedding_dim=embedding_dim,
        image_size=[640, 480],
        faces=[
            build_face_detection(
                bbox_px=[10.0, 20.0, 100.0, 120.0],
                landmarks_px=_landmarks5(),
                embedding=_unit_vec(embedding_dim, seed=1),
                det_score=0.97,
            )
        ],
    )


# ---------------------------------------------------------------------------
# §B run-record validation
# ---------------------------------------------------------------------------


def test_face_run_item_well_formed_passes() -> None:
    item = _well_formed_item()
    assert item["media_id"] == 42
    assert item["image_size"] == [640, 480]
    assert len(item["faces"]) == 1
    assert len(item["faces"][0]["embedding"]) == item["embedding_dim"]
    assert "assignment" not in item
    assert "matched_name" not in item
    assert "gallery" not in item


def test_face_run_item_embedding_dim_mismatch_rejected() -> None:
    dim = resolve_sface_embedding_dim()
    bad = _well_formed_item(dim=dim)
    bad["faces"][0]["embedding"] = _unit_vec(dim)[:-1]  # wrong length
    with pytest.raises(FaceRunRecordError, match="embedding"):
        validate_face_run_item(bad)


def test_face_run_item_missing_image_size_rejected() -> None:
    dim = resolve_sface_embedding_dim()
    raw = {
        "media_id": 1,
        "path": "x.jpg",
        "model_id": "m",
        "embedding_dim": dim,
        "faces": [],
    }
    with pytest.raises(FaceRunRecordError, match="image_size"):
        validate_face_run_item(raw)


def test_face_run_record_document_kind() -> None:
    item = _well_formed_item()
    record = build_face_run_record([item], provenance={"head_sha": "0" * 40})
    assert record["schema"] == SCHEMA
    assert record["kind"] == DocKind.FACE_RUN_RECORD.value
    assert DocKind.FACE_RUN_RECORD == "face_run_record"


def test_error_item_empty_faces() -> None:
    item = build_face_run_item(
        media_id=7,
        path="bad.jpg",
        model_id="ort-yunet-sface",
        embedding_dim=resolve_sface_embedding_dim(),
        image_size=[1, 1],
        error="RuntimeError: boom",
    )
    assert item["error"] == "RuntimeError: boom"
    assert item["faces"] == []


# ---------------------------------------------------------------------------
# Walker: per-item isolation + bounded stall (rg-007)
# ---------------------------------------------------------------------------


def _tiny_manifest(n: int, tmp_path: Path) -> GoldenManifest:
    entries = []
    for i in range(n):
        name = f"img{i}.jpg"
        # Minimal valid JPEG so decode can succeed when the detector is the failure.
        # Pure bytes "fake" will fail decode; for isolation we mock after decode
        # by using a real tiny PNG via cv2.
        path = tmp_path / name
        import cv2

        img = np.zeros((32, 32, 3), dtype=np.uint8)
        img[8:24, 8:24] = 200
        ok, buf = cv2.imencode(".jpg", img)
        assert ok
        path.write_bytes(buf.tobytes())
        entries.append(
            {
                "path": name,
                "sha256": f"{i:064d}"[:64] if False else ("a" * 64),
                "media_id": 100 + i,
                "face_count": 0,
                "present_identities": [],
                "context_pack": {"caption": "x"},
                "must_right": [],
                "easy_wrong": [],
                "policy": {"recognition_enabled": True},
            }
        )
    # Distinct sha per entry
    for i, e in enumerate(entries):
        e["sha256"] = f"{i:02x}" * 32
    return GoldenManifest.model_validate(
        {"manifest_version": 2, "roster": ["Caitlin Weaver"], "entries": entries}
    )


class _MockDetector:
    """Real-shape detector: detect(images) -> list[list[RawDetection]]."""

    def __init__(self, *, fail_on_media: set[int] | None = None, always_fail: bool = False) -> None:
        self.fail_on_media = fail_on_media or set()
        self.always_fail = always_fail
        self.calls = 0

    def detect(self, images: list[np.ndarray]) -> list[list[RawDetection]]:
        self.calls += 1
        # Caller processes one image at a time; media id is stashed on self by tests.
        mid = getattr(self, "_current_media_id", None)
        if self.always_fail or (mid is not None and mid in self.fail_on_media):
            raise RuntimeError(f"detector boom media={mid}")
        # Empty detections — still a successful item.
        return [[] for _ in images]


class _MediaAwareDetector(_MockDetector):
    """Wraps walk so fail_on_media works: process_image is not media-aware.

    Instead, raise on a call index tracked by the walk order.
    """

    def __init__(self, *, fail_on_call_indices: set[int] | None = None) -> None:
        super().__init__()
        self.fail_on_call_indices = fail_on_call_indices or set()

    def detect(self, images: list[np.ndarray]) -> list[list[RawDetection]]:
        idx = self.calls
        self.calls += 1
        if idx in self.fail_on_call_indices:
            raise RuntimeError(f"detector boom call={idx}")
        det = RawDetection(
            bbox=np.array([1.0, 2.0, 30.0, 40.0], dtype=np.float32),
            landmarks=np.array(
                [[5.0, 5.0], [25.0, 5.0], [15.0, 15.0], [8.0, 28.0], [22.0, 28.0]],
                dtype=np.float32,
            ),
            score=0.95,
        )
        return [[det] for _ in images]


class _MockEmbedder:
    """Real-shape embedder: embed(crops) -> (N, dim) L2-normalized float32."""

    def __init__(self, dim: int | None = None) -> None:
        self.embedding_dim = int(dim if dim is not None else resolve_sface_embedding_dim())

    def embed(self, crops: list[np.ndarray]) -> np.ndarray:
        out = []
        for i, _crop in enumerate(crops):
            v = np.asarray(_unit_vec(self.embedding_dim, seed=10 + i), dtype=np.float32)
            out.append(v)
        if not out:
            return np.zeros((0, self.embedding_dim), dtype=np.float32)
        return np.stack(out, axis=0)


def test_walker_isolates_per_item_failure(tmp_path: Path) -> None:
    """One detector failure becomes an error-item; walk continues (rg-007)."""
    manifest = _tiny_manifest(3, tmp_path)
    detector = _MediaAwareDetector(fail_on_call_indices={1})  # middle item
    embedder = _MockEmbedder()
    # Real aligner needs cv2; use a tiny stub that returns a 112 crop.
    from types import SimpleNamespace

    class _StubAligner:
        def align(self, image: np.ndarray, landmarks: np.ndarray) -> Any:
            return SimpleNamespace(crop=np.zeros((112, 112, 3), dtype=np.uint8))

    record = walk_face_run_record(
        manifest,
        tmp_path,
        detector=detector,
        embedder=embedder,
        aligner=_StubAligner(),  # type: ignore[arg-type]
        head_sha="deadbeef",
        embedding_dim=embedder.embedding_dim,
    )
    assert len(record["items"]) == 3
    assert record["items"][0].get("error") is None
    assert "error" in record["items"][1] and record["items"][1]["error"] is not None
    assert "RuntimeError" in record["items"][1]["error"]
    assert record["items"][1]["faces"] == []
    assert record["items"][2].get("error") is None
    assert record["kind"] == DocKind.FACE_RUN_RECORD.value


def test_walker_bounded_stall_aborts(tmp_path: Path) -> None:
    """DEFAULT_STALL_LIMIT consecutive failures abort with partial_record (rg-007)."""
    assert DEFAULT_STALL_LIMIT == 5
    n = DEFAULT_STALL_LIMIT + 1
    manifest = _tiny_manifest(n, tmp_path)
    detector = _MediaAwareDetector(fail_on_call_indices=set(range(n)))
    embedder = _MockEmbedder()
    from types import SimpleNamespace

    class _StubAligner:
        def align(self, image: np.ndarray, landmarks: np.ndarray) -> Any:
            return SimpleNamespace(crop=np.zeros((112, 112, 3), dtype=np.uint8))

    with pytest.raises(BoundedStallError) as excinfo:
        walk_face_run_record(
            manifest,
            tmp_path,
            detector=detector,
            embedder=embedder,
            aligner=_StubAligner(),  # type: ignore[arg-type]
            head_sha="deadbeef",
            stall_limit=DEFAULT_STALL_LIMIT,
            embedding_dim=embedder.embedding_dim,
        )
    partial = excinfo.value.partial_record
    assert partial["aborted"] is True
    assert len(partial["items"]) == DEFAULT_STALL_LIMIT
    assert all(item.get("error") for item in partial["items"])


# ---------------------------------------------------------------------------
# Buffalo env guard (SC-1) — no insightface required
# ---------------------------------------------------------------------------


def test_buffalo_import_fails_without_eval_bench(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ACX_EVAL_BENCH", raising=False)
    sys.modules.pop("scripts.eval_harness.buffalo_bench", None)
    with pytest.raises(Exception, match="ACX_EVAL_BENCH"):
        importlib.import_module("scripts.eval_harness.buffalo_bench")


def test_buffalo_import_fails_when_eval_bench_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACX_EVAL_BENCH", "0")
    sys.modules.pop("scripts.eval_harness.buffalo_bench", None)
    with pytest.raises(Exception, match="ACX_EVAL_BENCH"):
        importlib.import_module("scripts.eval_harness.buffalo_bench")


# ---------------------------------------------------------------------------
# Negative-import gate (a) module graph + (b) source symbols — TEST-15
# ---------------------------------------------------------------------------


def test_negative_import_module_graph() -> None:
    """(a) The THREE S2 modules' OWN transitive import closure excludes
    face_pass / seed_roster / remote_client and recognition.infrastructure.embeddings.*.

    Runs in a FRESH subprocess (clean interpreter). Checking the parent pytest
    session's global ``sys.modules`` is wrong: sibling test modules
    (test_eval_harness_face_pass / _remote_client / _seed_roster) import the
    forbidden modules at collection time, so a global check is spurious-red in
    the full-suite gate yet vacuous in isolation. A clean interpreter attributes
    every loaded module to what these three actually import — the gate goes red
    only on a real S2 leak (TEST-15; SC-1/PROV-05).
    """
    code = (
        "import os, sys, json, importlib\n"
        "os.environ['ACX_EVAL_BENCH'] = '1'\n"
        "for _m in ('scripts.eval_harness.face_run_record',\n"
        "           'scripts.eval_harness.face_bakeoff',\n"
        "           'scripts.eval_harness.buffalo_bench'):\n"
        "    importlib.import_module(_m)\n"
        "_forbidden = ('face_pass', 'seed_roster', 'remote_client')\n"
        "_prefix = 'recognition.infrastructure.embeddings'\n"
        "_off = sorted({n for n in sys.modules\n"
        "               if any(p in _forbidden for p in n.split('.'))\n"
        "               or n == _prefix or n.startswith(_prefix + '.')})\n"
        "print(json.dumps(_off))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=str(_SERVICE_ROOT),
    )
    assert proc.returncode == 0, f"import-graph subprocess failed: {proc.stderr}"
    offenders = json.loads(proc.stdout.strip().splitlines()[-1])
    assert not offenders, f"forbidden modules in S2 import graph: {offenders}"


def _name_tokens(src: str) -> list[tuple[int, str]]:
    """Return (lineno, name) for NAME tokens — strings/comments excluded (TEST-15)."""
    out: list[tuple[int, str]] = []
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.NAME:
            out.append((tok.start[0], tok.string))
    return out


def test_negative_import_source_symbols() -> None:
    """(b) Source NAME tokens must not include leak symbols (module-graph alone is vacuous).

    tokenize NAME skips string/docstring contents so ban-documentation may name the
    symbols; bare imports/calls still fail (TEST-15 non-vacuous).
    """
    for path in _S2_SOURCE_FILES:
        src = path.read_text(encoding="utf-8")
        for lineno, name in _name_tokens(src):
            if name in _FORBIDDEN_SOURCE_SYMBOLS:
                pytest.fail(f"{path.name}:{lineno} NAME token is forbidden symbol {name!r}")


def test_negative_import_gate_is_non_vacuous() -> None:
    """Prove the source gate would catch a bare import leak (TEST-15)."""
    leak = "from x import RemoteSceneClient\n"
    names = [n for _, n in _name_tokens(leak)]
    assert "RemoteSceneClient" in names
    # String-only mention does not produce a NAME token.
    doc_only = '"""do not import RemoteSceneClient"""\n'
    assert "RemoteSceneClient" not in [n for _, n in _name_tokens(doc_only)]


# ---------------------------------------------------------------------------
# Determinism layer 3: embedder-only cosine ≥ EMB_DET_TAU on frozen crop
# ---------------------------------------------------------------------------


def test_embedder_only_determinism_layer3() -> None:
    """Identical frozen 112×112 crops → cosine ≥ EMB_DET_TAU on the REAL SFace embedder.

    Real-ORT-only (TEST-15). A synthetic stand-in embedder is deterministic by
    construction, so cosine ≡ 1.0 can never go red and would certify the layer-3
    constraint without ever exercising OrtSFaceEmbedder. When the SFace ONNX
    weights are absent we SKIP (naming the remedy, AGT-06) — the posture FIR-3
    uses (pytest.mark.skipif MODELS_PRESENT) — rather than assert a vacuous truth.
    """
    if not _SYNTH_CROP.is_file():
        pytest.skip(f"missing frozen crop fixture {_SYNTH_CROP}")

    from recognition.infrastructure.face_pipeline.ort_adapters import OrtSFaceEmbedder
    from recognition.tests.unit.face_pipeline_support import DEFAULT_MODELS_DIR, MODELS_PRESENT

    if not MODELS_PRESENT:
        pytest.skip(
            "ORT SFace weights unavailable; layer-3 determinism requires the real "
            "OrtSFaceEmbedder (a synthetic embedder is trivially deterministic — "
            "TEST-15). Fetch the face_pipeline models before running this gate."
        )

    crop = np.load(_SYNTH_CROP)
    assert crop.shape == (112, 112, 3)
    emb = OrtSFaceEmbedder(models_dir=DEFAULT_MODELS_DIR)
    a = emb.embed([crop])
    b = emb.embed([crop])
    assert a.shape == b.shape
    assert a.shape[1] == resolve_sface_embedding_dim()
    # Cosine of L2 vectors = dot product.
    cos = float(np.dot(a[0], b[0]))
    assert cos >= EMB_DET_TAU, f"cosine {cos} < EMB_DET_TAU {EMB_DET_TAU}"


def test_raw_detection_attribute_contract() -> None:
    """Ground RawDetection attribute names used by the walker (anchor check)."""
    det = RawDetection(
        bbox=np.zeros(4, dtype=np.float32),
        landmarks=np.zeros((5, 2), dtype=np.float32),
        score=0.5,
    )
    assert hasattr(det, "bbox")
    assert hasattr(det, "landmarks")
    assert hasattr(det, "score")
    # Walker maps these — not alternate names.
    assert not hasattr(det, "bbox_px")
    assert inspect.signature(walk_face_run_record).parameters["stall_limit"].default == DEFAULT_STALL_LIMIT
