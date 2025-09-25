"""Unit tests validating AdapterFactory behaviour."""

import sys
import types

import pytest

from shared.startup.adapter_factory import AdapterFactory


class CustomCaptionAdapter:
    def __init__(self, device="cpu", model_name="custom-model"):
        self.device = device
        self.model_name = model_name
        self._ready = False

    def initialize(self):
        self._ready = True

    def is_ready(self):
        return self._ready

    def generate_caption(self, image, prompt=None, **kwargs):
        return f"caption from {self.model_name}"


@pytest.fixture(autouse=True)
def register_custom_adapter(monkeypatch):
    module = types.ModuleType("custom_caption")
    module.CustomCaptionAdapter = CustomCaptionAdapter
    monkeypatch.setitem(sys.modules, "custom_caption", module)


def test_create_caption_generator_phi3():
    config = {
        "type": "phi3",
        "config": {
            "model_id": "microsoft/Phi-3.5-vision-instruct",
            "device": "cpu",
        },
    }
    adapter = AdapterFactory._create_caption_generator(config)
    from analysis.adapters.phi3_caption_adapter import Phi3CaptionAdapter

    assert isinstance(adapter, Phi3CaptionAdapter)


def test_create_caption_generator_custom_class_path():
    config = {
        "type": "custom",
        "class_path": "custom_caption.CustomCaptionAdapter",
        "config": {
            "init_kwargs": {
                "model_name": "gpt-test",
            }
        },
    }
    adapter = AdapterFactory._create_caption_generator(config)
    assert isinstance(adapter, CustomCaptionAdapter)
    assert adapter.model_name == "gpt-test"


def test_create_caption_generator_none_when_missing_type():
    adapter = AdapterFactory._create_caption_generator({})
    assert adapter is None
