"""Face bake-off run-record schema + builder (FIR-5 S2 / §B).

Walk-time artifact only: detector boxes/landmarks + L2 embeddings per face.
No assignment, gallery, threshold, or matched name (those are score-time, S3).

Heuristics: PROV-01/PROV-06 (model_id + embedding_dim provenance),
rg-015 (dim from producer, never invented at validation), EMB-01 (one space
per leg — dim is recorded, never crossed here).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .schema import SCHEMA, DocKind


class FaceRunRecordError(ValueError):
    """Structural problem in a face run-record item or document."""


class FaceDetection(BaseModel):
    """One detected face in pixel-corner detector form (§A0 / §B)."""

    model_config = ConfigDict(extra="forbid")

    bbox_px: list[float] = Field(min_length=4, max_length=4)
    landmarks_px: list[list[float]] = Field(min_length=5, max_length=5)
    embedding: list[float]
    det_score: float
    quality: float | None = None

    @field_validator("landmarks_px")
    @classmethod
    def _landmarks_xy(cls, value: list[list[float]]) -> list[list[float]]:
        for i, pt in enumerate(value):
            if len(pt) != 2:
                raise ValueError(f"landmarks_px[{i}] must be [x, y], got length {len(pt)}")
        return value


class FaceRunItem(BaseModel):
    """Per-media-item face run-record payload (§B)."""

    model_config = ConfigDict(extra="forbid")

    media_id: int
    path: str
    model_id: str
    embedding_dim: int = Field(gt=0)
    image_size: list[int] = Field(min_length=2, max_length=2)
    faces: list[FaceDetection] = Field(default_factory=list)
    error: str | None = None

    @field_validator("image_size")
    @classmethod
    def _positive_size(cls, value: list[int]) -> list[int]:
        w, h = value
        if w < 1 or h < 1:
            raise ValueError(f"image_size must be positive [W, H] pixels, got {value}")
        return value

    @model_validator(mode="after")
    def _embedding_dim_matches(self) -> FaceRunItem:
        for i, face in enumerate(self.faces):
            if len(face.embedding) != self.embedding_dim:
                raise ValueError(
                    f"faces[{i}].embedding length {len(face.embedding)} "
                    f"!= embedding_dim {self.embedding_dim}"
                )
        if self.error is not None and self.faces:
            raise ValueError("error-item must carry empty faces list")
        return self


class FaceRunRecordDocument(BaseModel):
    """Envelope for a face walk artifact."""

    model_config = ConfigDict(extra="forbid")

    schema_id: str = Field(alias="schema")
    kind: str
    provenance: dict[str, Any] = Field(default_factory=dict)
    items: list[FaceRunItem] = Field(default_factory=list)
    aborted: bool | None = None

    @field_validator("schema_id")
    @classmethod
    def _schema_ok(cls, value: str) -> str:
        if value != SCHEMA:
            raise ValueError(f"unsupported schema {value!r}; expected {SCHEMA!r}")
        return value

    @field_validator("kind")
    @classmethod
    def _kind_ok(cls, value: str) -> str:
        if value != DocKind.FACE_RUN_RECORD.value:
            raise ValueError(
                f"expected kind {DocKind.FACE_RUN_RECORD.value!r}, got {value!r}"
            )
        return value


def build_face_detection(
    *,
    bbox_px: list[float] | tuple[float, ...],
    landmarks_px: list[list[float]] | list[tuple[float, float]],
    embedding: list[float] | tuple[float, ...],
    det_score: float,
    quality: float | None = None,
) -> dict[str, Any]:
    """Build one face dict (§B faces[] element)."""
    face: dict[str, Any] = {
        "bbox_px": [float(x) for x in bbox_px],
        "landmarks_px": [[float(x), float(y)] for x, y in landmarks_px],
        "embedding": [float(v) for v in embedding],
        "det_score": float(det_score),
    }
    if quality is not None:
        face["quality"] = float(quality)
    return face


def build_face_run_item(
    *,
    media_id: int,
    path: str,
    model_id: str,
    embedding_dim: int,
    image_size: list[int] | tuple[int, int],
    faces: list[dict[str, Any]] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Build a validated per-media face run-record item (§B).

    Error items must pass ``error`` and leave ``faces`` empty.
    """
    item: dict[str, Any] = {
        "media_id": int(media_id),
        "path": str(path),
        "model_id": str(model_id),
        "embedding_dim": int(embedding_dim),
        "image_size": [int(image_size[0]), int(image_size[1])],
        "faces": list(faces) if faces is not None else [],
    }
    if error is not None:
        item["error"] = str(error)
        item["faces"] = []
    return validate_face_run_item(item)


def build_face_run_record(
    items: list[dict[str, Any]],
    *,
    provenance: dict[str, Any] | None = None,
    aborted: bool = False,
) -> dict[str, Any]:
    """Build a validated face run-record document envelope."""
    record: dict[str, Any] = {
        "schema": SCHEMA,
        "kind": DocKind.FACE_RUN_RECORD.value,
        "provenance": dict(provenance or {}),
        "items": list(items),
    }
    if aborted:
        record["aborted"] = True
    return validate_face_run_record(record)


def validate_face_run_item(item: dict[str, Any]) -> dict[str, Any]:
    """Validate one §B item; return a plain dict. Raises FaceRunRecordError."""
    try:
        return FaceRunItem.model_validate(item).model_dump(exclude_none=True)
    except ValidationError as exc:
        raise FaceRunRecordError(f"face run-record item invalid: {exc}") from exc


def validate_face_run_record(record: dict[str, Any]) -> dict[str, Any]:
    """Validate a full face run-record document; return a plain dict."""
    try:
        doc = FaceRunRecordDocument.model_validate(record)
    except ValidationError as exc:
        raise FaceRunRecordError(f"face run-record invalid: {exc}") from exc
    dumped = doc.model_dump(by_alias=True, exclude_none=True)
    # model_dump renames schema_id -> schema via by_alias when Field alias is set
    if "schema_id" in dumped and "schema" not in dumped:
        dumped["schema"] = dumped.pop("schema_id")
    return dumped


__all__ = [
    "FaceDetection",
    "FaceRunItem",
    "FaceRunRecordDocument",
    "FaceRunRecordError",
    "build_face_detection",
    "build_face_run_item",
    "build_face_run_record",
    "validate_face_run_item",
    "validate_face_run_record",
]
