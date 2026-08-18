"""FIR-5 S2: face run-record schema, candidate walker, buffalo guard, isolation gates.

Heuristics: TEST-06/TEST-15 (assertions can go red), EMB-01, PROV-05, rg-007,
rg-015, ARCH-06 (walker fork covered by isolation tests, not caption client).
"""

from __future__ import annotations

import importlib
import inspect
import io
import json
import os
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
    build_occlusion_twin_pairs,
    walk_face_run_record,
)
from scripts.eval_harness.face_run_record import (
    FaceRunRecordError,
    build_face_detection,
    build_face_run_item,
    build_face_run_record,
    validate_face_run_item,
)
from scripts.eval_harness.landmark_cache import LandmarkCacheProvenance
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
                "provenance": {"source": "fixture", "license": "fixture"},
            }
        )
    # Distinct sha per entry
    for i, e in enumerate(entries):
        e["sha256"] = f"{i:02x}" * 32
    return GoldenManifest.model_validate(
        {"manifest_version": 3,
            "annotation_mode": "roster_only", "roster": ["Russet Fathom"], "entries": entries}
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
    # embed() returns EmbedBatchResult (vectors + pre-norm magnitudes), not a bare
    # ndarray — indexing/.shape on the dataclass raises AttributeError.
    assert a.vectors.shape == b.vectors.shape
    assert a.vectors.shape[1] == resolve_sface_embedding_dim()
    # Cosine of L2 vectors = dot product.
    cos = float(np.dot(a.vectors[0], b.vectors[0]))
    assert cos >= EMB_DET_TAU, f"cosine {cos} < EMB_DET_TAU {EMB_DET_TAU}"


# ---------------------------------------------------------------------------
# Buffalo fused baseline leg (FIR-1 head-to-head) — stubbed app, no insightface
# ---------------------------------------------------------------------------


def _import_buffalo(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("ACX_EVAL_BENCH", "1")
    sys.modules.pop("scripts.eval_harness.buffalo_bench", None)
    return importlib.import_module("scripts.eval_harness.buffalo_bench")


def _fake_face(*, dim: int = 8, seed: int = 3) -> Any:
    from types import SimpleNamespace

    rng = np.random.default_rng(seed)
    return SimpleNamespace(
        bbox=np.asarray([10.0, 20.0, 50.0, 80.0]),  # xyxy
        kps=np.asarray([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0], [7.0, 8.0], [9.0, 10.0]]),
        det_score=0.87,
        embedding=rng.normal(size=dim),
    )


class _FakeApp:
    """Pixel-blind FaceAnalysis stand-in: fixed faces per get() call."""

    def __init__(self, faces: list[Any]) -> None:
        self._faces = faces
        self.calls = 0

    def get(self, image: np.ndarray) -> list[Any]:
        self.calls += 1
        return list(self._faces)


def test_buffalo_adapter_maps_bbox_landmarks_score(monkeypatch: pytest.MonkeyPatch) -> None:
    bb = _import_buffalo(monkeypatch)
    face = _fake_face()
    leg = bb.BuffaloFusedLeg(app=_FakeApp([face]), embedding_dim=8)
    batches = leg.detect([np.zeros((32, 32, 3), dtype=np.uint8)])
    assert len(batches) == 1 and len(batches[0]) == 1
    det = batches[0][0]
    assert isinstance(det, RawDetection)
    # xyxy [10,20,50,80] → xywh [10,20,40,60]
    assert det.bbox.tolist() == [10.0, 20.0, 40.0, 60.0]
    assert det.landmarks.shape == (5, 2)
    assert det.landmarks.tolist() == face.kps.tolist()  # kps passthrough, index order kept
    assert det.score == pytest.approx(0.87)
    embs = leg.embed([np.zeros((112, 112, 3), dtype=np.uint8)])
    assert embs.shape == (1, 8)
    assert embs.dtype == np.float32
    assert float(np.linalg.norm(embs[0])) == pytest.approx(1.0, abs=1e-5)  # L2'd
    expected = np.asarray(face.embedding) / np.linalg.norm(face.embedding)
    assert float(np.dot(embs[0], expected)) == pytest.approx(1.0, abs=1e-5)


def test_buffalo_fused_cache_discipline(monkeypatch: pytest.MonkeyPatch) -> None:
    """embed() is fail-closed: only valid straight after detect(), counts must match."""
    bb = _import_buffalo(monkeypatch)
    leg = bb.BuffaloFusedLeg(app=_FakeApp([_fake_face()]), embedding_dim=8)
    crop = np.zeros((112, 112, 3), dtype=np.uint8)
    with pytest.raises(bb.FusedLegProtocolError, match="before detect"):
        leg.embed([crop])
    leg.detect([np.zeros((32, 32, 3), dtype=np.uint8)])
    with pytest.raises(bb.FusedLegProtocolError, match="crops"):
        leg.embed([crop, crop])  # count mismatch (1 detection cached)
    leg.detect([np.zeros((32, 32, 3), dtype=np.uint8)])
    assert leg.embed([crop]).shape == (1, 8)
    with pytest.raises(bb.FusedLegProtocolError, match="before detect"):
        leg.embed([crop])  # cache consumed — no silent reuse


def _assert_fused_box_embedding_pairing(
    embs: np.ndarray,
    faces: list[Any],
    *,
    dim: int = 8,
) -> None:
    """Discriminating guard: embs[i] matches faces[i] (distinct known embeddings)."""
    assert embs.shape == (len(faces), dim)
    expected = []
    for face in faces:
        vec = np.asarray(face.embedding, dtype=np.float64).reshape(-1)
        expected.append(vec / np.linalg.norm(vec))
    # Distinct known embeddings — otherwise pairing is unfalsifiable (TEST-15).
    assert float(np.dot(expected[0], expected[1])) < 0.99
    for i, exp in enumerate(expected):
        assert float(np.dot(embs[i], exp)) == pytest.approx(1.0, abs=1e-5)
        for j, other in enumerate(expected):
            if i != j:
                assert float(np.dot(embs[i], other)) < 0.99


def test_buffalo_fused_cache_pairing_n2(monkeypatch: pytest.MonkeyPatch) -> None:
    """BUFREV-01: N=2 distinct embeddings keep box_i↔embedding_i order (TEST-15)."""
    bb = _import_buffalo(monkeypatch)
    f0 = _fake_face(dim=8, seed=11)
    f0.bbox = np.asarray([10.0, 20.0, 50.0, 80.0])  # xyxy
    f1 = _fake_face(dim=8, seed=77)
    f1.bbox = np.asarray([100.0, 30.0, 140.0, 90.0])
    faces = [f0, f1]
    leg = bb.BuffaloFusedLeg(app=_FakeApp(faces), embedding_dim=8)
    img = np.zeros((32, 32, 3), dtype=np.uint8)
    crop = np.zeros((112, 112, 3), dtype=np.uint8)

    batches = leg.detect([img])
    assert len(batches[0]) == 2
    embs = leg.embed([crop, crop])
    _assert_fused_box_embedding_pairing(embs, faces)

    # Red-proof (TEST-15): transposed cache pairing makes the same assertion red.
    leg.detect([img])
    pending = leg._pending
    assert pending is not None and len(pending) == 2
    # Swap embeddings only (bbox keys stay) — simulates reverse-cache regression.
    leg._pending = [
        type(pending[0])(bbox_key=pending[0].bbox_key, embedding=pending[1].embedding),
        type(pending[1])(bbox_key=pending[1].bbox_key, embedding=pending[0].embedding),
    ]
    swapped = leg.embed([crop, crop])
    with pytest.raises(AssertionError):
        _assert_fused_box_embedding_pairing(swapped, faces)


def test_buffalo_fused_cache_reorder_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """BUFREV-02: same-count bbox reorder fails closed when boxes= is supplied (TEST-16)."""
    bb = _import_buffalo(monkeypatch)
    f0 = _fake_face(dim=8, seed=3)
    f0.bbox = np.asarray([10.0, 20.0, 50.0, 80.0])
    f1 = _fake_face(dim=8, seed=9)
    f1.bbox = np.asarray([100.0, 30.0, 140.0, 90.0])
    leg = bb.BuffaloFusedLeg(app=_FakeApp([f0, f1]), embedding_dim=8)
    img = np.zeros((32, 32, 3), dtype=np.uint8)
    crop = np.zeros((112, 112, 3), dtype=np.uint8)

    batches = leg.detect([img])
    b0 = np.asarray(batches[0][0].bbox, dtype=np.float32)
    b1 = np.asarray(batches[0][1].bbox, dtype=np.float32)
    # Correct order OK (injection via public boxes= kwarg — no private poke).
    embs = leg.embed([crop, crop], boxes=[b0, b1])
    assert embs.shape == (2, 8)

    leg.detect([img])
    with pytest.raises(bb.FusedLegProtocolError, match="bbox mismatch"):
        leg.embed([crop, crop], boxes=[b1, b0])  # same count, reversed identity


def test_buffalo_build_face_analysis_pins_ort_threads(monkeypatch: pytest.MonkeyPatch) -> None:
    """BUFREV-03: _build_face_analysis pins ORT threads + env (TEST-08)."""
    bb = _import_buffalo(monkeypatch)
    captured: dict[str, Any] = {}

    class _FakeFaceAnalysis:
        def __init__(self, **kwargs: Any) -> None:
            captured["fa_kwargs"] = kwargs

        def prepare(self, **kwargs: Any) -> None:
            captured["prepare"] = kwargs

    class _FakeSessOptions:
        def __init__(self) -> None:
            self.intra_op_num_threads = 0
            self.inter_op_num_threads = 0
            self.execution_mode = None

    class _FakeOrt:
        class ExecutionMode:
            ORT_SEQUENTIAL = "ORT_SEQUENTIAL"

        SessionOptions = _FakeSessOptions

    import types

    fake_app_mod = types.ModuleType("insightface.app")
    fake_app_mod.FaceAnalysis = _FakeFaceAnalysis  # type: ignore[attr-defined]
    fake_mz_mod = types.ModuleType("insightface.model_zoo.model_zoo")

    class _ModelRouter:
        def get_model(self, **kwargs: Any) -> Any:  # noqa: ANN001
            captured.setdefault("router_calls", []).append(kwargs)
            return None

    fake_mz_mod.ModelRouter = _ModelRouter  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "insightface", types.ModuleType("insightface"))
    monkeypatch.setitem(sys.modules, "insightface.app", fake_app_mod)
    monkeypatch.setitem(sys.modules, "insightface.model_zoo", types.ModuleType("insightface.model_zoo"))
    monkeypatch.setitem(sys.modules, "insightface.model_zoo.model_zoo", fake_mz_mod)
    monkeypatch.setitem(sys.modules, "onnxruntime", _FakeOrt)

    for var in bb._ORT_THREAD_ENV_PINS:
        monkeypatch.delenv(var, raising=False)

    # Fake FaceAnalysis skips model loading; still exercises pin + kwargs path.
    app = bb._build_face_analysis()
    assert isinstance(app, _FakeFaceAnalysis)
    assert captured["fa_kwargs"]["name"] == bb.BUFFALO_MODEL_ID
    assert captured["fa_kwargs"]["providers"] == ["CPUExecutionProvider"]
    assert captured["prepare"]["ctx_id"] == -1
    for var in bb._ORT_THREAD_ENV_PINS:
        assert os.environ[var] == "1"
    opts = bb._ort_session_options()
    assert opts.intra_op_num_threads == 1
    assert opts.inter_op_num_threads == 1


def test_buffalo_adapter_rejects_wrong_embedding_dim(monkeypatch: pytest.MonkeyPatch) -> None:
    bb = _import_buffalo(monkeypatch)
    leg = bb.BuffaloFusedLeg(app=_FakeApp([_fake_face(dim=7)]), embedding_dim=8)
    with pytest.raises(ValueError, match="dim"):
        leg.detect([np.zeros((32, 32, 3), dtype=np.uint8)])


def test_build_baseline_leg_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mirror of build_candidate_leg: (detector, aligner, embedder); fused = same object."""
    bb = _import_buffalo(monkeypatch)
    app = _FakeApp([_fake_face()])
    detector, aligner, embedder = bb.build_baseline_leg(app=app, embedding_dim=8)
    assert detector is embedder  # one fused adapter serves both protocol slots
    assert detector.leg_mode == "fused"
    assert detector.model_id == bb.BUFFALO_MODEL_ID == "buffalo_l"
    assert embedder.embedding_dim == 8
    # Default dim is the buffalo space (512), from the producer (rg-015).
    assert bb.BuffaloFusedLeg(app=app).embedding_dim == bb.BUFFALO_EMBEDDING_DIM == 512
    aligned = aligner.align(np.zeros((32, 32, 3), dtype=np.uint8), np.zeros((5, 2)))
    assert aligned.crop.shape == (112, 112, 3)  # placeholder crop keeps walker loop shape


def test_walker_stamps_buffalo_leg_provenance(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Leg-parameterized provenance: leg/model_id/dim/leg_mode from the buffalo leg."""
    bb = _import_buffalo(monkeypatch)
    detector, aligner, embedder = bb.build_baseline_leg(app=_FakeApp([_fake_face()]), embedding_dim=8)
    manifest = _tiny_manifest(2, tmp_path)
    record = walk_face_run_record(
        manifest,
        tmp_path,
        detector=detector,
        embedder=embedder,
        aligner=aligner,  # type: ignore[arg-type]
        model_id=bb.BUFFALO_MODEL_ID,
        head_sha="deadbeef",
        embedding_dim=embedder.embedding_dim,
        leg="buffalo",
        leg_mode=bb.BUFFALO_LEG_MODE,
    )
    prov = record["provenance"]
    assert prov["leg"] == "buffalo"
    assert prov["model_id"] == "buffalo_l"
    assert prov["embedding_dim"] == 8
    assert prov["leg_mode"] == "fused"
    assert all(item["model_id"] == "buffalo_l" for item in record["items"])
    assert all(len(f["embedding"]) == 8 for item in record["items"] for f in item["faces"])


def test_walker_provenance_defaults_stay_candidate(tmp_path: Path) -> None:
    """No leg args → leg='candidate' and NO leg_mode key (candidate is separable)."""
    manifest = _tiny_manifest(1, tmp_path)
    record = walk_face_run_record(
        manifest,
        tmp_path,
        detector=_MockDetector(),
        embedder=_MockEmbedder(),
        head_sha="deadbeef",
        embedding_dim=8,
    )
    assert record["provenance"]["leg"] == "candidate"
    assert "leg_mode" not in record["provenance"]


def test_twin_pass_with_fused_leg_and_pinned_cache_detector(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """build_occlusion_twin_pairs runs the fused buffalo adapters end-to-end while
    the landmark cache comes from a SEPARATE (candidate-family) cache_detector
    (EXP-08: same twin universe for both legs)."""
    import cv2

    bb = _import_buffalo(monkeypatch)

    img_dir = tmp_path / "celebs01"
    img_dir.mkdir()
    img = np.random.default_rng(5).integers(0, 256, size=(100, 100, 3)).astype(np.uint8)
    assert cv2.imwrite(str(img_dir / "alice.jpg"), img)
    manifest = GoldenManifest.model_validate(
        {
            "manifest_version": 3,
            "annotation_mode": "roster_only",
            "roster": ["Alice Q"],
            "entries": [
                {
                    "path": "celebs01/alice.jpg",
                    "sha256": "a" * 64,
                    "media_id": 1,
                    "face_count": 1,
                    "present_identities": ["Alice Q"],
                    "must_right": [],
                    "easy_wrong": [],
                    "policy": {"recognition_enabled": True},
                    "context_pack": {"caption": "x"},
                    "face_boxes": [
                        {
                            "x": 0.4,
                            "y": 0.4,
                            "w": 0.4,
                            "h": 0.4,
                            "name": "Alice Q",
                            "source": "iptc",
                            "lineage": {
                                "labeler_id": "test-labeler",
                                "batch_id": "test-batch",
                                "capture_session_id": "test-session",
                                "pass_index": 0,
                                "labeled_at": "2026-08-14T00:00:00Z",
                                "tool_version": "test",
                                "saw_machine_proposals": False,
                                "label_source": "operator_blind",
                                "decision": "named",
                                "confidence": "high",
                                "arbitration_of": None,
                            },
                        }
                    ],
                    "provenance": {"source": "celeb", "license": "public_domain", "publishable": True},
                }
            ],
        }
    )

    class _CacheDet:
        """Candidate-family stand-in: one detection exactly on the GT box."""

        calls = 0
        landmark_cache_provenance = LandmarkCacheProvenance.pinned_yunet()

        def detect(self, images: list[np.ndarray]) -> list[list[RawDetection]]:
            _CacheDet.calls += len(images)
            # GT boxes are normalized-CENTRE: (0.4,0.4,0.4,0.4)×100 → corner [20,20,40,40].
            det = RawDetection(
                bbox=np.asarray([20.0, 20.0, 40.0, 40.0], dtype=np.float32),
                landmarks=np.asarray(
                    [[30.0, 35.0], [50.0, 35.0], [40.0, 42.0], [32.0, 52.0], [48.0, 52.0]],
                    dtype=np.float32,
                ),
                score=0.9,
            )
            return [[det] for _ in images]

    fused_face = _fake_face(dim=8)
    fused_face.bbox = np.asarray([20.0, 20.0, 60.0, 60.0])  # xyxy → GT-exact xywh [20,20,40,40]
    detector, aligner, embedder = bb.build_baseline_leg(app=_FakeApp([fused_face]), embedding_dim=8)

    pairs_by_tag, prov = build_occlusion_twin_pairs(
        manifest,
        tmp_path,
        detector=detector,
        embedder=embedder,
        aligner=aligner,  # type: ignore[arg-type]
        cache_detector=_CacheDet(),
    )
    assert prov["errors"] == []
    assert prov["n_pairs"] == 3  # 1 named cached face × 3 occlusion kinds
    assert set(pairs_by_tag) == {"masked", "sunglasses", "occlusion_other"}
    assert _CacheDet.calls == 1  # cache built from the pinned detector, not the leg
    assert prov["landmark_cache"] == LandmarkCacheProvenance.pinned_yunet().to_dict()
    for pairs in pairs_by_tag.values():
        assert pairs[0]["true_name"] == "Alice Q"
        assert pairs[0]["embedding"] is not None and len(pairs[0]["embedding"]) == 8


def test_twin_pass_landmark_cache_provenance_from_detector(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """BUFREV-04: twin-pass landmark_cache provenance reflects injected detector (rg-015)."""
    import cv2

    bb = _import_buffalo(monkeypatch)
    img_dir = tmp_path / "celebs01"
    img_dir.mkdir()
    img = np.random.default_rng(6).integers(0, 256, size=(100, 100, 3)).astype(np.uint8)
    assert cv2.imwrite(str(img_dir / "bob.jpg"), img)
    manifest = GoldenManifest.model_validate(
        {
            "manifest_version": 3,
            "annotation_mode": "roster_only",
            "roster": ["Bob R"],
            "entries": [
                {
                    "path": "celebs01/bob.jpg",
                    "sha256": "b" * 64,
                    "media_id": 2,
                    "face_count": 1,
                    "present_identities": ["Bob R"],
                    "must_right": [],
                    "easy_wrong": [],
                    "policy": {"recognition_enabled": True},
                    "context_pack": {"caption": "x"},
                    "face_boxes": [
                        {
                            "x": 0.4,
                            "y": 0.4,
                            "w": 0.4,
                            "h": 0.4,
                            "name": "Bob R",
                            "source": "iptc",
                            "lineage": {
                                "labeler_id": "test-labeler",
                                "batch_id": "test-batch",
                                "capture_session_id": "test-session",
                                "pass_index": 0,
                                "labeled_at": "2026-08-14T00:00:00Z",
                                "tool_version": "test",
                                "saw_machine_proposals": False,
                                "label_source": "operator_blind",
                                "decision": "named",
                                "confidence": "high",
                                "arbitration_of": None,
                            },
                        }
                    ],
                    "provenance": {"source": "celeb", "license": "public_domain", "publishable": True},
                }
            ],
        }
    )

    distinct = LandmarkCacheProvenance(model_id="fake-cache-det", weights_sha256="c" * 64)

    class _LabeledCacheDet:
        landmark_cache_provenance = distinct

        def detect(self, images: list[np.ndarray]) -> list[list[RawDetection]]:
            det = RawDetection(
                bbox=np.asarray([20.0, 20.0, 40.0, 40.0], dtype=np.float32),
                landmarks=np.asarray(
                    [[30.0, 35.0], [50.0, 35.0], [40.0, 42.0], [32.0, 52.0], [48.0, 52.0]],
                    dtype=np.float32,
                ),
                score=0.9,
            )
            return [[det] for _ in images]

    fused_face = _fake_face(dim=8)
    fused_face.bbox = np.asarray([20.0, 20.0, 60.0, 60.0])
    detector, aligner, embedder = bb.build_baseline_leg(app=_FakeApp([fused_face]), embedding_dim=8)

    _pairs, prov = build_occlusion_twin_pairs(
        manifest,
        tmp_path,
        detector=detector,
        embedder=embedder,
        aligner=aligner,  # type: ignore[arg-type]
        cache_detector=_LabeledCacheDet(),
    )
    assert prov["errors"] == []
    assert prov["landmark_cache"] == distinct.to_dict()
    assert prov["landmark_cache"] != LandmarkCacheProvenance.pinned_yunet().to_dict()


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
