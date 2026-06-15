"""Florence-2 local-CPU DescriptionAdapter (E19-1 S9).

Implements the same ``DescriptionAdapter`` protocol as the seeded adapter, so it
is a drop-in swap behind ``get_description_adapter``. torch/transformers are
imported lazily (``[vlm]`` extra) and the model is loaded once via
``ensure_loaded``; a missing extra raises ``LocalVlmUnavailableError`` naming
``[vlm]`` rather than crashing import.

Runs CPU-only by default to mirror the OCI A1 target (no GPU); the image is
downsampled to ``max_image_edge_px`` first. Inference is synchronous (the
protocol's ``describe`` is sync) — for the request path this must run off the
event loop / in a worker (S9 async branch); the benchmark CLI calls it directly.
"""

from __future__ import annotations

import io
import threading
from collections.abc import Mapping, Sequence
from typing import Any

from scene.application.description_adapter import AdapterResult
from scene.domain.description import DescriptionAdapterKind

# Florence-2 task tokens. MORE_DETAILED_CAPTION drives the caption + alt-text
# draft; OD supplies inspectable object labels.
_CAPTION_TASK = "<MORE_DETAILED_CAPTION>"
_OD_TASK = "<OD>"
_DEFAULT_TASKS = (_CAPTION_TASK, _OD_TASK)
_DEFAULT_MODEL_ID = "microsoft/Florence-2-base-ft"


class LocalVlmUnavailableError(RuntimeError):
    """Raised when the [vlm] extra is missing or the model cannot be loaded."""


class LocalCpuDescriptionAdapter:
    kind = DescriptionAdapterKind.LOCAL_CPU

    def __init__(
        self,
        *,
        device: str = "cpu",
        tasks: Sequence[str] = _DEFAULT_TASKS,
        max_image_edge_px: int = 1024,
        num_beams: int = 3,
        max_new_tokens: int = 512,
        model_id: str = _DEFAULT_MODEL_ID,
        model_revision: str | None = None,
        model_version: str = "florence-2-base-ft",
    ) -> None:
        self.model_id = model_id
        self._revision = model_revision
        self._device = device
        self._tasks = tuple(tasks)
        self._max_edge = max_image_edge_px
        self._num_beams = num_beams
        self._max_new_tokens = max_new_tokens
        self.model_version = model_version
        # Encode the task set + decoding params so a different configuration is a
        # distinct cache key.
        self.prompt_or_task_version = f"{'+'.join(t.strip('<>').lower() for t in self._tasks)}.b{num_beams}.v1"
        self._model: Any = None
        self._processor: Any = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ loading
    def ensure_loaded(self) -> None:
        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:
                return
            try:
                import torch
                from transformers import AutoModelForCausalLM, AutoProcessor
            except ModuleNotFoundError as exc:  # pragma: no cover - env-dependent
                raise LocalVlmUnavailableError(
                    f"local_cpu adapter requires the '[vlm]' extra (torch/transformers): {exc}. "
                    "Install with `uv sync --extra vlm`."
                ) from exc
            try:
                if self._device == "cpu":
                    torch.set_num_threads(max(1, torch.get_num_threads()))
                self._model = AutoModelForCausalLM.from_pretrained(
                    self.model_id, revision=self._revision, trust_remote_code=True, torch_dtype=torch.float32
                ).to(self._device)
                self._model.eval()
                self._processor = AutoProcessor.from_pretrained(
                    self.model_id, revision=self._revision, trust_remote_code=True
                )
            except Exception as exc:  # noqa: BLE001 - surface any load failure uniformly
                raise LocalVlmUnavailableError(f"failed to load {self.model_id}: {exc}") from exc

    # --------------------------------------------------------------- inference
    def _downsample(self, image):
        w, h = image.size
        longest = max(w, h)
        if longest <= self._max_edge:
            return image
        scale = self._max_edge / float(longest)
        return image.resize((max(1, int(w * scale)), max(1, int(h * scale))))

    def _run_task(self, image, task: str) -> Any:
        import torch

        inputs = self._processor(text=task, images=image, return_tensors="pt").to(self._device)
        with torch.no_grad():
            generated_ids = self._model.generate(
                input_ids=inputs["input_ids"],
                pixel_values=inputs["pixel_values"],
                max_new_tokens=self._max_new_tokens,
                num_beams=self._num_beams,
                do_sample=False,
            )
        text = self._processor.batch_decode(generated_ids, skip_special_tokens=False)[0]
        return self._processor.post_process_generation(text, task=task, image_size=(image.width, image.height))

    def describe(self, *, image_bytes: bytes, context: Mapping[str, Any] | None) -> AdapterResult:
        from PIL import Image

        self.ensure_loaded()
        image = self._downsample(Image.open(io.BytesIO(image_bytes)).convert("RGB"))

        caption = ""
        objects: tuple[str, ...] = ()
        for task in self._tasks:
            parsed = self._run_task(image, task)
            value = parsed.get(task, parsed)
            if task == _CAPTION_TASK and isinstance(value, str):
                caption = value.strip()
            elif task == _OD_TASK and isinstance(value, dict):
                labels = value.get("labels") or []
                # de-dupe preserving order
                seen: dict[str, None] = {}
                for label in labels:
                    seen.setdefault(str(label), None)
                objects = tuple(seen.keys())

        if not caption:
            caption = "An image."
        return AdapterResult(
            caption=caption,
            objects=objects,
            ocr_text=None,
            alt_text_draft=caption,
            context_sources=(),
            context_applied=False,
        )
