"""E20-FUSION S1: Stage-1 visual prior — isolation pass and caption-derived fast tier."""

from __future__ import annotations

import pytest

from scene.application.description_adapter import AdapterResult
from scene.application.seeded_adapter import SeededDescriptionAdapter
from scene.application.visual_facts_pass import (
    VisualFactsPass,
    VisualFactsPrior,
    VisualFactsPriorSource,
    is_fast_tier_profile,
)
from scene.config.profiles import DescriptionProfile
from scene.domain.description import DescriptionAdapterKind

IMG = b"\x89PNG\r\n visual facts pass test bytes"


class StubAdapter:
    """Minimal DescriptionAdapter stub with real ``AdapterResult`` shape."""

    kind = DescriptionAdapterKind.SEEDED
    model_id = "stub"
    model_version = "1"
    prompt_or_task_version = "1"

    def __init__(self, *, result: AdapterResult | None = None, fail: bool = False) -> None:
        self._result = result or AdapterResult(
            caption="A person standing outdoors near greenery.",
            objects=("person", "plant", "sky"),
            ocr_text=None,
            alt_text_draft="A person standing outdoors near greenery.",
            context_sources=(),
            context_applied=False,
            phrase_boxes=(),
        )
        self._fail = fail
        self.calls = 0

    def describe(self, *, image_bytes: bytes, context) -> AdapterResult:
        self.calls += 1
        if self._fail:
            raise RuntimeError("adapter unavailable")
        assert context is None
        return self._result


def test_isolation_pass_invokes_adapter_without_context():
    adapter = StubAdapter()
    prior = VisualFactsPass.describe(adapter=adapter, image_bytes=IMG)
    assert adapter.calls == 1
    assert isinstance(prior, VisualFactsPrior)
    assert prior.source is VisualFactsPriorSource.ISOLATION_PASS
    assert prior.caption == "A person standing outdoors near greenery."
    assert prior.objects == ["person", "plant", "sky"]
    assert prior.text is None
    assert prior.attributes == []
    assert prior.spatial == []


def test_isolation_pass_maps_ocr_text():
    adapter = StubAdapter(
        result=AdapterResult(
            caption="A printed document with several lines of text.",
            objects=("document",),
            ocr_text="Sample text",
            alt_text_draft="A printed document with several lines of text.",
            context_sources=(),
            context_applied=False,
            phrase_boxes=(),
        )
    )
    prior = VisualFactsPass.describe(adapter=adapter, image_bytes=IMG)
    assert prior.text == "Sample text"


def test_isolation_pass_degrades_when_adapter_raises():
    adapter = StubAdapter(fail=True)
    with pytest.raises(RuntimeError, match="adapter unavailable"):
        VisualFactsPass.describe(adapter=adapter, image_bytes=IMG)
    assert adapter.calls == 1


def test_from_caption_derives_prior_without_adapter_call():
    result = SeededDescriptionAdapter().describe(image_bytes=IMG, context={"title": "Cat"})
    adapter = StubAdapter()
    prior = VisualFactsPass.from_caption(result=result)
    assert adapter.calls == 0
    assert prior.source is VisualFactsPriorSource.CAPTION_DERIVED
    assert prior.caption == result.caption
    assert prior.objects == list(result.objects)
    assert prior.text == result.ocr_text


def test_fast_tier_uses_caption_derived_without_second_pass():
    seeded = SeededDescriptionAdapter()
    main_result = seeded.describe(image_bytes=IMG, context=None)
    stub = StubAdapter()
    prior = VisualFactsPass.obtain(
        adapter=stub,
        image_bytes=IMG,
        profile=DescriptionProfile.FLORENCE_SMALL,
        adapter_result=main_result,
    )
    assert stub.calls == 0
    assert prior.source is VisualFactsPriorSource.CAPTION_DERIVED
    assert prior.caption == main_result.caption


def test_fast_tier_requires_adapter_result():
    with pytest.raises(ValueError, match="adapter_result"):
        VisualFactsPass.obtain(
            adapter=StubAdapter(),
            image_bytes=IMG,
            profile=DescriptionProfile.FLORENCE_SMALL,
            adapter_result=None,
        )


def test_async_tier_runs_isolation_pass():
    adapter = StubAdapter()
    prior = VisualFactsPass.obtain(
        adapter=adapter,
        image_bytes=IMG,
        profile=DescriptionProfile.FLORENCE_LARGE,
        adapter_result=None,
    )
    assert adapter.calls == 1
    assert prior.source is VisualFactsPriorSource.ISOLATION_PASS


def test_is_fast_tier_profile():
    assert is_fast_tier_profile(DescriptionProfile.FLORENCE_SMALL) is True
    assert is_fast_tier_profile(DescriptionProfile.FLORENCE_LARGE) is False
    assert is_fast_tier_profile(DescriptionProfile.GPU_PHI4) is False
    assert is_fast_tier_profile(DescriptionProfile.SEEDED) is False
