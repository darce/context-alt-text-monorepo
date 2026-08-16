"""Shared fixtures for FIR-8 bench unit tests (union API for both test styles)."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

PRIMARY = "detection_recall@frame_e2e/label_map_primary"
LEGAL_SECONDARIES = [
    "detection_precision@frame_e2e/label_map_primary",
    "identification_recall@frame_e2e/label_map_primary",
    "identification_precision@frame_e2e/label_map_primary",
]

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64

INSIGHTFACE_STACK = {
    "stack_id": "acx-dev-insightface",
    "role": "insightface_judge",
    "base_url": "https://dev.api.altcontext.com",
    "expected_profile": "insightface",
    "expected_pgvector_dim": 512,
    "opencv_major": 5,
    "api_key_env": "ACX_BENCH_DEV_API_KEY",
    "tenant_id_env": "ACX_BENCH_DEV_TENANT_ID",
}

FIR_STACK = {
    "stack_id": "acx-dev-fir",
    "role": "face_pipeline_candidate",
    "base_url": "https://fir.api.altcontext.com",
    "expected_profile": "face_pipeline",
    "expected_pgvector_dim": 128,
    "opencv_major": 5,
    "api_key_env": "ACX_BENCH_FIR_API_KEY",
    "tenant_id_env": "ACX_BENCH_FIR_TENANT_ID",
}


def valid_pair_dict(**overrides: Any) -> dict[str, Any]:
    cfg: dict[str, Any] = {
        "wall_clock_timeout_sec": 3600,
        "job_poll_timeout_sec": 600,
        "item_max_attempts": 2,
        "accepted_set_floor": 0.90,
        "max_differential_attrition": 0.05,
        "allow_private_source": False,
        "head_to_head_delta": 0.10,
        "bootstrap_seed": 20260729,
        "primary_endpoint": PRIMARY,
        "secondary_endpoints": list(LEGAL_SECONDARIES),
        "stacks": [copy.deepcopy(INSIGHTFACE_STACK), copy.deepcopy(FIR_STACK)],
    }
    cfg.update(overrides)
    return cfg


def write_pair(path: Path, payload: dict | None = None) -> Path:
    data = valid_pair_dict() if payload is None else payload
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def write_pair_json(path: Path, payload: dict | None = None) -> Path:
    data = valid_pair_dict() if payload is None else payload
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def write_pair_yaml(path: Path, **overrides: Any) -> Path:
    return write_pair(path, valid_pair_dict(**overrides))


# v3 on-disk contract (ADR-015): document-level annotation_mode, provenance
# on every entry, LabelLineage on every box. Bench fixtures never invent
# exhaustiveness at score time.
BENCH_TEST_PROVENANCE: dict[str, str] = {"source": "fixture", "license": "fixture"}


def bench_test_lineage(*, name: str | None) -> dict[str, object]:
    return {
        "labeler_id": "bench-test",
        "batch_id": "fir-11-bench-v3",
        "capture_session_id": "bench-test-session",
        "pass_index": 0,
        "labeled_at": "2026-08-16T00:00:00Z",
        "tool_version": "bench-test",
        "saw_machine_proposals": False,
        "label_source": "gold_reference",
        "decision": "named" if name else "stranger",
        "confidence": "high",
        "arbitration_of": None,
    }


def _with_box_lineage(box: dict[str, Any]) -> dict[str, Any]:
    if "lineage" in box:
        return box
    stamped = dict(box)
    stamped["lineage"] = bench_test_lineage(name=box.get("name"))
    return stamped


def golden_entry(
    media_id: int,
    *,
    path: str | None = None,
    sha256: str | None = None,
    face_count: int = 1,
    present_identities: list[str] | None = None,
    face_boxes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    names = present_identities if present_identities is not None else ["Alice Q"]
    boxes = face_boxes if face_boxes is not None else []
    return {
        "path": path or f"fixtures/m{media_id}.jpg",
        "sha256": sha256 or (f"{media_id:064x}"),
        "media_id": media_id,
        "face_count": face_count,
        "present_identities": names,
        "base_caption": "",
        "must_right": [],
        "easy_wrong": [],
        "policy": {"recognition_enabled": True},
        "face_boxes": [_with_box_lineage(box) for box in boxes],
        "provenance": dict(BENCH_TEST_PROVENANCE),
    }


def minimal_entry(
    media_id: int,
    path: str = "img.jpg",
    sha256: str = SHA_A,
    *,
    face_count: int = 0,
    present_identities: list[str] | None = None,
    face_boxes: list[dict] | None = None,
) -> dict:
    entry = {
        "path": path,
        "sha256": sha256,
        "media_id": media_id,
        "face_count": face_count,
        "present_identities": present_identities or [],
        "base_caption": "",
        "must_right": [],
        "easy_wrong": [],
        "policy": {"recognition_enabled": True},
    }
    if face_boxes is not None:
        entry["face_boxes"] = [_with_box_lineage(box) for box in face_boxes]
    entry["provenance"] = dict(BENCH_TEST_PROVENANCE)
    return entry


def write_manifest(
    path: Path,
    media_ids: list[int],
    *,
    roster: list[str] | None = None,
    annotation_mode: str = "exhaustive",
) -> Path:
    shas = {1: SHA_A, 2: SHA_B, 3: SHA_C}
    entries = [
        golden_entry(
            mid,
            path=f"fixtures/m{mid}.jpg",
            sha256=shas.get(mid, f"{mid:064x}"),
            face_count=0,
            present_identities=[],
        )
        for mid in media_ids
    ]
    body = {
        "manifest_version": 3,
        "annotation_mode": annotation_mode,
        "roster": roster or [],
        "entries": entries,
    }
    path.write_text(json.dumps(body, indent=2), encoding="utf-8")
    return path


def png_bytes(width: int = 8, height: int = 8) -> bytes:
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (width, height), color=(10, 20, 30)).save(buf, format="PNG")
    return buf.getvalue()


def write_png(path: Path, width: int = 8, height: int = 8) -> str:
    data = png_bytes(width, height)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def ready_payload(*, dim: int, status: str = "ok", detail: str | None = None) -> dict[str, Any]:
    return {
        "status": "ok",
        "checks": [
            {
                "name": "database",
                "status": status,
                "detail": detail if detail is not None else f"reachable; pgvector_dimension={dim}",
            }
        ],
        "timestamp": "2026-07-23T00:00:00Z",
    }


def health_payload(*, profile: str) -> dict[str, Any]:
    return {
        "model_cache": {
            "model_name": "buffalo_l" if profile == "insightface" else "sface",
            "cache_dir": "/models",
            "bundle_files": ["a.onnx"],
            "status": "ok",
            "detail": "ready",
            "profile": profile,
        }
    }


def write_image_corpus(images_dir: Path, media_ids: list[int]) -> dict[int, str]:
    images_dir.mkdir(parents=True, exist_ok=True)
    shas: dict[int, str] = {}
    data = png_bytes(100, 100)
    digest = hashlib.sha256(data).hexdigest()
    for mid in media_ids:
        dest = images_dir / f"img_{mid}.jpg"
        dest.write_bytes(data)
        shas[mid] = digest
    return shas


def write_hashed_manifest(path: Path, images_dir: Path, media_ids: list[int]) -> Path:
    shas = write_image_corpus(images_dir, media_ids)
    entries = [
        minimal_entry(
            mid,
            path=f"img_{mid}.jpg",
            sha256=shas[mid],
            face_count=1,
            present_identities=["Alice Q"],
            face_boxes=[{"x": 0.05, "y": 0.05, "w": 0.1, "h": 0.1, "name": "Alice Q", "source": "iptc"}],
        )
        for mid in media_ids
    ]
    payload = {
        "manifest_version": 3,
        "annotation_mode": "exhaustive",
        "roster": ["Alice Q"],
        "entries": entries,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


class FakeClient:
    """In-memory RemoteSceneClient stand-in. Records analyze POSTs."""

    STACK_ID_OFFSET = 10_000

    def __init__(self, *, analyze_ok: bool = True, cluster_status: str = "completed") -> None:
        self.analyze_calls: list[list[tuple[int, str, bytes]]] = []
        self.cluster_calls = 0
        self.analyze_ok = analyze_ok
        self.cluster_status = cluster_status
        self.identities: list[dict] = []
        self.cluster_list: list[dict] = [{"id": "cl1", "label": "Alice Q", "is_auto_label": False}]
        self.members: dict = {"members": []}
        self._stack_ids: dict[int, int] = {}

    def analyze(self, images: list[tuple[int, str, bytes]]) -> str:
        self.analyze_calls.append(list(images))
        if not self.analyze_ok:
            raise RuntimeError("analyze failed")
        for mid, _name, _data in images:
            self._stack_ids[mid] = mid + self.STACK_ID_OFFSET
        return f"job-{len(self.analyze_calls)}"

    def wait_job(self, job_id: str) -> dict:
        last = self.analyze_calls[-1] if self.analyze_calls else []
        mid = last[0][0] if last else 0
        stack_mid = self._stack_ids.get(mid, mid + self.STACK_ID_OFFSET)
        return {"status": "completed", "id": job_id, "media_id": stack_mid}

    def clustering_job(self, tenant_id: str, mode: str = "sync") -> dict:
        self.cluster_calls += 1
        return {
            "status": self.cluster_status,
            "id": "cluster-1",
            "mode": mode,
            "tenant_id": tenant_id,
        }

    def media_identities(self, media_ids: list[int]) -> object:
        if self.identities:
            return self.identities
        return [
            {
                "identity_id": f"id-{m}",
                "media_id": m,
                "cluster_id": "cl1",
                "cluster_label": "Alice Q",
                "is_auto_label": False,
                "bbox": {"x": 0, "y": 0, "width": 10, "height": 10},
            }
            for m in media_ids
        ]

    def clusters(self, labeled_only: bool = False) -> list[dict]:
        return list(self.cluster_list)

    def cluster_members(self, cluster_id: str) -> dict:
        return dict(self.members)


def write_stub_preflight(run_dir: Path, stack_id: str) -> Path:
    dest = Path(run_dir) / "legs" / stack_id / "preflight.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    insight = "insight" in stack_id
    dest.write_text(
        json.dumps(
            {
                "stack_id": stack_id,
                "base_url": "https://dev.api.altcontext.com" if insight else "https://fir.api.altcontext.com",
                "expected_profile": "insightface" if insight else "face_pipeline",
                "expected_pgvector_dim": 512 if insight else 128,
                "resolved_profile": "insightface" if insight else "face_pipeline",
                "resolved_pgvector_dim": 512 if insight else 128,
                "opencv_major": 5,
                "opencv_major_source": "operator_attested",
                "checked_at": "2026-07-29T00:00:00Z",
                "ready_excerpt": {},
                "health_detailed_excerpt": {},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return dest


@pytest.fixture
def pair_yaml(tmp_path: Path) -> Path:
    return write_pair_yaml(tmp_path / "stack-pair.yaml")


@pytest.fixture
def pair_path(tmp_path: Path) -> Path:
    return write_pair(tmp_path / "stack-pair.yaml")
