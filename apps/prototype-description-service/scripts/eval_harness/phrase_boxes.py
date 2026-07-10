"""Shared validated loader for phrase_boxes.json (S7-02 / rg-008).

The E19-4a PA-01 gate and ``test_eval_harness_phrase_boxes`` both consume this
fixture; validating once here keeps schema/axis drift from being caught only as
incidental KeyErrors in ad-hoc tests.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .manifest import ManifestError

PHRASE_BOXES_SCHEMA = "phrase_boxes/v1"
_EXPECTED_AXIS = {
    "origin": "top-left",
    "x": "right",
    "y": "down",
    "units": "image_fraction_[0,1]",
}


class PhraseBoxesError(ManifestError):
    """Structural problem in phrase_boxes.json. Fail fast."""


class AxisSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    origin: str
    x: str
    y: str
    units: str


class FaceCenter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    center: list[float] = Field(min_length=2, max_length=2)

    @field_validator("center")
    @classmethod
    def _in_unit_square(cls, value: list[float]) -> list[float]:
        x, y = value
        if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
            raise ValueError(f"face center {value} outside unit square")
        return value


class PhraseBoxEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phrase: str
    box: list[float] = Field(min_length=4, max_length=4)

    @field_validator("box")
    @classmethod
    def _valid_box(cls, value: list[float]) -> list[float]:
        x_min, y_min, x_max, y_max = value
        if not (0.0 <= x_min < x_max <= 1.0 and 0.0 <= y_min < y_max <= 1.0):
            raise ValueError(f"phrase box {value} is not a valid unit-square AABB")
        return value


class ExpectedContainment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    face_center: list[float] = Field(min_length=2, max_length=2)
    resolved_identity: str | None = None


class SceneFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    media_id: int
    path: str
    face_centers: list[FaceCenter]
    phrase_boxes: list[PhraseBoxEntry]
    expected_containment: list[ExpectedContainment]

    @model_validator(mode="after")
    def _containment_aligns(self) -> SceneFixture:
        centers = [tuple(fc.center) for fc in self.face_centers]
        expected = [tuple(e.face_center) for e in self.expected_containment]
        if centers != expected:
            raise ValueError(
                f"media_id {self.media_id}: expected_containment face centers must "
                "echo face_centers 1:1"
            )
        return self


class PhraseBoxesDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_id: str = Field(alias="schema")
    axis: AxisSpec
    scenes: dict[str, SceneFixture]

    @field_validator("schema_id")
    @classmethod
    def _schema_supported(cls, value: str) -> str:
        if value != PHRASE_BOXES_SCHEMA:
            raise ValueError(f"unsupported phrase_boxes schema {value!r}; expected {PHRASE_BOXES_SCHEMA!r}")
        return value

    @model_validator(mode="after")
    def _axis_and_keys(self) -> PhraseBoxesDocument:
        axis = self.axis.model_dump()
        if axis != _EXPECTED_AXIS:
            raise ValueError(f"unexpected axis {axis}; expected {_EXPECTED_AXIS}")
        if not self.scenes:
            raise ValueError("phrase_boxes document has no scenes")
        for key, scene in self.scenes.items():
            if key != str(scene.media_id):
                raise ValueError(f"scene key {key!r} must equal stringified media_id {scene.media_id}")
        return self


def load_phrase_boxes(path: str | Path) -> dict[str, Any]:
    """Load and validate phrase_boxes.json; return a plain dict for callers.

    Raises PhraseBoxesError on missing file, malformed JSON, or schema violations.
    """
    fixture_path = Path(path)
    if not fixture_path.is_file():
        raise PhraseBoxesError(f"phrase_boxes fixture not found: {fixture_path}")
    try:
        raw = json.loads(fixture_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise PhraseBoxesError(f"phrase_boxes unreadable or malformed JSON: {exc}") from exc
    try:
        doc = PhraseBoxesDocument.model_validate(raw)
    except ValidationError as exc:
        raise PhraseBoxesError(f"phrase_boxes schema violation: {exc}") from exc
    return doc.model_dump(by_alias=True)
