"""Fixed offline GT-landmark cache for synthetic occlusion (FIR-5 S4).

Runs a detector **once** over un-occluded originals, associates detections to
named GT boxes via §C, and freezes 5-point landmarks keyed by
``(media_id, GT-box index)``. Synthetic generation must never call a leg
detector live — placement reads this cache only.

Heuristics (docs/workbay/rules/engineering-heuristics.md — ids only):
- PROV-01: cache pins model_id + weights sha256
- TRACK-09: offline placement so occlusion is a degradation measurement
- REF-15: consume face_pipeline RawDetection / OrtYuNetDetector shapes
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from recognition.infrastructure.face_pipeline._common import RawDetection
from recognition.infrastructure.face_pipeline.provenance import MODEL_MANIFEST

from .face_assignment import associate_detections

# Pinned detector identity for the offline cache pass (PROV-01).
# EXP-08 / FIR5V11-04: this is the *candidate* YuNet family. Occlusion twin
# eligibility for BOTH legs is conditioned on this cache — faces only YuNet
# detects enter the twin universe; the comparison population is correlated
# with the candidate detection distribution (surfaced in protocol disclosures).
LANDMARK_CACHE_MODEL_ID = "yunet"
LANDMARK_CACHE_WEIGHTS_SHA256 = MODEL_MANIFEST["yunet"].sha256
LANDMARK_CACHE_LEG_ASYMMETRY_DISCLOSURE = (
    "occlusion twin eligibility for BOTH legs is conditioned on the frozen "
    "YuNet (candidate-family) landmark cache — faces only the incumbent "
    "detects are structurally excluded; the comparison population is "
    "correlated with the candidate detection distribution (EXP-08)"
)


class FaceDetector(Protocol):
    """Injectable detector seam (TEST-04): no real weights required in tests."""

    def detect(self, images: Sequence[np.ndarray]) -> list[list[RawDetection]]: ...


@dataclass(frozen=True)
class LandmarkCacheProvenance:
    """Pinned detector provenance recorded in the frozen artifact."""

    model_id: str
    weights_sha256: str

    def to_dict(self) -> dict[str, str]:
        return {
            "model_id": self.model_id,
            "weights_sha256": self.weights_sha256,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> LandmarkCacheProvenance:
        return cls(
            model_id=str(data["model_id"]),
            weights_sha256=str(data["weights_sha256"]),
        )

    @classmethod
    def pinned_yunet(cls) -> LandmarkCacheProvenance:
        return cls(
            model_id=LANDMARK_CACHE_MODEL_ID,
            weights_sha256=LANDMARK_CACHE_WEIGHTS_SHA256,
        )


@dataclass(frozen=True)
class CachedLandmark:
    """One named GT face with detector landmarks frozen offline."""

    media_id: int
    box_index: int  # GT face_boxes index
    name: str
    landmarks_px: tuple[tuple[float, float], ...]  # 5×(x,y) YuNet order
    bbox_px: tuple[float, float, float, float]  # detector xywh pixels
    det_score: float

    def landmarks_array(self) -> np.ndarray:
        return np.asarray(self.landmarks_px, dtype=np.float64).reshape(5, 2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "media_id": self.media_id,
            "box_index": self.box_index,
            "name": self.name,
            "landmarks_px": [list(p) for p in self.landmarks_px],
            "bbox_px": list(self.bbox_px),
            "det_score": self.det_score,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CachedLandmark:
        lm = data["landmarks_px"]
        bbox = data["bbox_px"]
        return cls(
            media_id=int(data["media_id"]),
            box_index=int(data["box_index"]),
            name=str(data["name"]),
            landmarks_px=tuple((float(p[0]), float(p[1])) for p in lm),
            bbox_px=(float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])),
            det_score=float(data["det_score"]),
        )


@dataclass(frozen=True)
class LandmarkCache:
    """Frozen artifact: provenance + landmarks keyed by (media_id, box_index)."""

    provenance: LandmarkCacheProvenance
    entries: tuple[CachedLandmark, ...]

    def key_map(self) -> dict[tuple[int, int], CachedLandmark]:
        return {(e.media_id, e.box_index): e for e in self.entries}

    def get(self, media_id: int, box_index: int) -> CachedLandmark | None:
        return self.key_map().get((int(media_id), int(box_index)))

    def named_roster_entries(self) -> tuple[CachedLandmark, ...]:
        """Every cache-detected named roster face (twin generation universe)."""
        return tuple(e for e in self.entries if e.name)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provenance": self.provenance.to_dict(),
            "entries": [e.to_dict() for e in self.entries],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> LandmarkCache:
        entries = tuple(
            CachedLandmark.from_dict(e)
            for e in sorted(
                data.get("entries") or [],
                key=lambda d: (int(d["media_id"]), int(d["box_index"])),
            )
        )
        return cls(
            provenance=LandmarkCacheProvenance.from_dict(data["provenance"]),
            entries=entries,
        )

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), sort_keys=True, indent=2) + "\n")

    @classmethod
    def load(cls, path: str | Path) -> LandmarkCache:
        return cls.from_dict(json.loads(Path(path).read_text()))


def _default_detector() -> FaceDetector:
    """Lazy import so unit tests never construct OrtYuNetDetector without weights."""
    from recognition.infrastructure.face_pipeline.ort_adapters import OrtYuNetDetector

    return OrtYuNetDetector()


def build_landmark_cache(
    *,
    images_by_media: Mapping[int, np.ndarray],
    gt_by_media: Mapping[int, Sequence[Any]],
    image_sizes: Mapping[int, Sequence[int]] | None = None,
    detector: FaceDetector | None = None,
    provenance: LandmarkCacheProvenance | None = None,
) -> LandmarkCache:
    """Offline pass: detect → §C associate → freeze named-GT landmarks.

    Only **named** GT associations are stored (roster faces for twin generation).
    Stranger matches are ignored. Call this **before** synthetic generation;
    do not pass a live leg detector into generators.

    ``detector`` defaults to ``OrtYuNetDetector`` (loads verified yunet weights).
    Tests inject a fake (TEST-04). Provenance always records the pinned yunet
    model_id + MODEL_MANIFEST sha256 (PROV-01), independent of the inject.
    """
    det = detector if detector is not None else _default_detector()
    prov = provenance if provenance is not None else LandmarkCacheProvenance.pinned_yunet()

    cached: list[CachedLandmark] = []
    for media_id in sorted(images_by_media.keys()):
        image = images_by_media[media_id]
        gt_boxes = list(gt_by_media.get(media_id, ()))
        if image_sizes is not None and media_id in image_sizes:
            size = image_sizes[media_id]
            width, height = int(size[0]), int(size[1])
        else:
            height, width = int(image.shape[0]), int(image.shape[1])

        batch = det.detect([image])
        detections = batch[0] if batch else []
        det_bboxes = [
            [
                float(np.asarray(d.bbox, dtype=np.float64).reshape(4)[0]),
                float(np.asarray(d.bbox, dtype=np.float64).reshape(4)[1]),
                float(np.asarray(d.bbox, dtype=np.float64).reshape(4)[2]),
                float(np.asarray(d.bbox, dtype=np.float64).reshape(4)[3]),
            ]
            for d in detections
        ]
        assoc = associate_detections(det_bboxes, gt_boxes, [width, height])
        for pair in assoc.pairs:
            name = pair.name
            if name is None:
                continue  # strangers excluded from landmark cache / twin universe
            raw = detections[pair.det_index]
            lm = np.asarray(raw.landmarks, dtype=np.float64).reshape(5, 2)
            bbox = np.asarray(raw.bbox, dtype=np.float64).reshape(4)
            cached.append(
                CachedLandmark(
                    media_id=int(media_id),
                    box_index=int(pair.gt_index),
                    name=str(name),
                    landmarks_px=tuple((float(lm[i, 0]), float(lm[i, 1])) for i in range(5)),
                    bbox_px=(float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])),
                    det_score=float(raw.score),
                )
            )

    cached.sort(key=lambda e: (e.media_id, e.box_index))
    return LandmarkCache(provenance=prov, entries=tuple(cached))


__all__ = [
    "LANDMARK_CACHE_MODEL_ID",
    "LANDMARK_CACHE_WEIGHTS_SHA256",
    "FaceDetector",
    "LandmarkCacheProvenance",
    "CachedLandmark",
    "LandmarkCache",
    "build_landmark_cache",
]
