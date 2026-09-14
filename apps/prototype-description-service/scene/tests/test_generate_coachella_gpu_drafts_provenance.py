from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from scene.config.profiles import PROFILE_SPECS, DescriptionProfile
from scene.domain.description import DescriptionAdapterKind


_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "generate_coachella_gpu_drafts.py"
_SCRIPT_SPEC = importlib.util.spec_from_file_location("generate_coachella_gpu_drafts", _SCRIPT_PATH)
assert _SCRIPT_SPEC is not None and _SCRIPT_SPEC.loader is not None
_SCRIPT_MODULE = importlib.util.module_from_spec(_SCRIPT_SPEC)
_SCRIPT_SPEC.loader.exec_module(_SCRIPT_MODULE)
_model_metadata = _SCRIPT_MODULE._model_metadata


def _gpu_adapter(**fields: object) -> SimpleNamespace:
    values = {
        "kind": DescriptionAdapterKind.GPU,
        "model_id": "Qwen3-VL-30B-A3B-Instruct",
        "model_revision": "0af19e7479857aa7f3246466a4ad16c7e7299639",
        "model_version": "1",
        "prompt_or_task_version": "3",
    }
    values.update(fields)
    return SimpleNamespace(**values)


def test_model_metadata_uses_explicit_quantization_attribute() -> None:
    metadata = _model_metadata(_gpu_adapter(quantization="Q4_K_M", model_version="1"))

    assert metadata["quantization"] == "Q4_K_M"
    assert metadata["model_version"] == "1"


def test_model_metadata_fails_closed_when_quantization_is_missing() -> None:
    adapter = _gpu_adapter()

    with pytest.raises(RuntimeError, match="quantization"):
        _model_metadata(adapter)


def test_gpu_qwen30b_profile_declares_quantization() -> None:
    assert PROFILE_SPECS[DescriptionProfile.GPU_QWEN30B].quantization == "Q4_K_M"
