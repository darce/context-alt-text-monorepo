"""Deterministic, model-free DescriptionAdapter for the demo and tests.

Output is a stable function of ``sha256(image_hash : adapter_version :
model_version : prompt_or_task_version : context_hash)`` over a checked-in fixture
pool, so repeat calls on the same image+context+versions are byte-identical and a
version bump changes the result (and thus the cache row). No model runtime.
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Mapping
from typing import Any

from scene.application.description_adapter import AdapterResult
from scene.application.hashing import compute_context_hash, compute_image_hash
from scene.domain.description import DescriptionAdapterKind

_FIXTURE_POOL: tuple[dict[str, Any], ...] = (
    {"caption": "A person standing outdoors near greenery.", "objects": ("person", "plant", "sky"), "ocr_text": None},
    {"caption": "A plate of food on a wooden table.", "objects": ("food", "plate", "table"), "ocr_text": None},
    {"caption": "A scenic landscape with mountains under a clear sky.", "objects": ("mountain", "sky"), "ocr_text": None},
    {"caption": "A close-up of a small object on a neutral background.", "objects": ("object",), "ocr_text": None},
    {"caption": "A printed document with several lines of text.", "objects": ("document",), "ocr_text": "Sample text"},
    {"caption": "Two people seated indoors in conversation.", "objects": ("person", "chair"), "ocr_text": None},
    {"caption": "A building exterior seen from the street.", "objects": ("building", "sky"), "ocr_text": None},
    {"caption": "A pet animal resting on a soft surface.", "objects": ("animal",), "ocr_text": None},
)


class SeededDescriptionAdapter:
    """Implements ``DescriptionAdapter`` with deterministic fixture selection."""

    kind = DescriptionAdapterKind.SEEDED
    model_id = "seeded-fixtures"
    adapter_version = "1"

    def __init__(self, *, model_version: str = "1", prompt_or_task_version: str = "1") -> None:
        self.model_version = model_version
        self.prompt_or_task_version = prompt_or_task_version

    def describe(self, *, image_bytes: bytes, context: Mapping[str, Any] | None) -> AdapterResult:
        material = ":".join(
            (
                compute_image_hash(image_bytes),
                self.adapter_version,
                self.model_version,
                self.prompt_or_task_version,
                compute_context_hash(context),
            )
        )
        seed = int(hashlib.sha256(material.encode("utf-8")).hexdigest(), 16)
        fixture = _FIXTURE_POOL[random.Random(seed).randrange(len(_FIXTURE_POOL))]
        return AdapterResult(
            caption=fixture["caption"],
            objects=fixture["objects"],
            ocr_text=fixture["ocr_text"],
            alt_text_draft=fixture["caption"],
            context_sources=(),
            context_applied=False,
        )
