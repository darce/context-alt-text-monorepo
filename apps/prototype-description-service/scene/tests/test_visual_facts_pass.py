"""E20-FUSION S1: Stage-1 visual prior — isolation pass and caption-derived fast tier."""

from __future__ import annotations

import pytest

from scene.application.description_adapter import AdapterResult
from scene.application.seeded_adapter import SeededDescriptionAdapter
from scene.application.visual_facts_pass import (
    ASYNC_ISOLATION_PROFILES,
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
    assert prior.derived_from_context_applied_caption is False


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


def test_from_caption_derives_prior_from_result_fields():
    result = SeededDescriptionAdapter().describe(image_bytes=IMG, context=None)
    prior = VisualFactsPass.from_caption(result=result)
    assert prior.source is VisualFactsPriorSource.CAPTION_DERIVED
    assert prior.caption == result.caption
    assert prior.objects == list(result.objects)
    assert prior.text == result.ocr_text


def test_from_caption_flags_context_applied_contamination():
    result = AdapterResult(
        caption="A cat sitting on a windowsill.",
        objects=("cat", "window"),
        ocr_text=None,
        alt_text_draft="Cat. A cat sitting on a windowsill.",
        context_sources=("title",),
        context_applied=True,
        phrase_boxes=(),
    )
    prior = VisualFactsPass.from_caption(result=result)
    assert prior.derived_from_context_applied_caption is True


def test_from_caption_clean_result_is_not_flagged():
    result = SeededDescriptionAdapter().describe(image_bytes=IMG, context=None)
    assert result.context_applied is False
    prior = VisualFactsPass.from_caption(result=result)
    assert prior.derived_from_context_applied_caption is False


def test_isolation_pass_is_never_flagged_contaminated():
    prior = VisualFactsPass.describe(adapter=StubAdapter(), image_bytes=IMG)
    assert prior.derived_from_context_applied_caption is False


@pytest.mark.parametrize(
    "profile",
    [
        DescriptionProfile.SEEDED,
        DescriptionProfile.FLORENCE_SMALL,
        DescriptionProfile.HOSTED_GPT4O,
    ],
)
def test_fast_tier_uses_caption_derived_without_second_pass(profile):
    seeded = SeededDescriptionAdapter()
    main_result = seeded.describe(image_bytes=IMG, context=None)
    stub = StubAdapter()
    prior = VisualFactsPass.obtain(
        adapter=stub,
        image_bytes=IMG,
        profile=profile,
        adapter_result=main_result,
    )
    assert stub.calls == 0
    assert prior.source is VisualFactsPriorSource.CAPTION_DERIVED
    assert prior.caption == main_result.caption


@pytest.mark.parametrize(
    "profile",
    [
        DescriptionProfile.SEEDED,
        DescriptionProfile.FLORENCE_SMALL,
        DescriptionProfile.HOSTED_GPT4O,
    ],
)
def test_fast_tier_requires_adapter_result(profile):
    with pytest.raises(ValueError, match="adapter_result"):
        VisualFactsPass.obtain(
            adapter=StubAdapter(),
            image_bytes=IMG,
            profile=profile,
            adapter_result=None,
        )


@pytest.mark.parametrize(
    "profile",
    [DescriptionProfile.FLORENCE_LARGE, DescriptionProfile.GPU_PHI4],
)
def test_async_tier_runs_isolation_pass(profile):
    adapter = StubAdapter()
    prior = VisualFactsPass.obtain(
        adapter=adapter,
        image_bytes=IMG,
        profile=profile,
        adapter_result=None,
    )
    assert adapter.calls == 1
    assert prior.source is VisualFactsPriorSource.ISOLATION_PASS


def test_tier_classification_covers_every_profile():
    assert {
        DescriptionProfile.FLORENCE_LARGE,
        DescriptionProfile.GPU_PHI4,
    } == ASYNC_ISOLATION_PROFILES
    for profile in DescriptionProfile:
        assert is_fast_tier_profile(profile) is (profile not in ASYNC_ISOLATION_PROFILES)
