"""VLM-4 Slice 2a+2b: ensemble-decode vote math and the adapter wrapper.

Slice 2a: logit-only baseline vote, explicit/attention weights path, adaptive
plausibility masking, bounded grid views, determinism [AGT-03].
Slice 2b: EnsembleDescriptionAdapter — N-view passes on a stub GPU adapter,
token-level vote via traces, caption-majority fallback, full-image-first
AdapterResult scope (VLM4-PA-03), protocol conformance.
"""

from __future__ import annotations

import io
import math

import pytest

from scene.application.description_adapter import AdapterResult, DescriptionAdapter
from scene.application.identity_merge.merge import NormalizedBox, PhraseBox
from scene.domain.description import DescriptionAdapterKind
from scene.infrastructure.vlm.ensemble_decode import (
    HARD_VIEW_CAP,
    EnsembleDecodeConfig,
    EnsembleDescriptionAdapter,
    ViewBox,
    ViewStrategy,
    WeightingMode,
    build_grid_views,
    combine_token_distributions,
)
from scene.infrastructure.vlm.gpu_remote_adapter import GpuRemoteTokenTrace


def _lp(p: float) -> float:
    return math.log(p)


def test_uniform_vote_prefers_token_agreed_across_views():
    """Two views agree on 'bicycle'; one view alone hallucinates 'table' hard."""
    views = [
        {"bicycle": _lp(0.6), "table": _lp(0.2)},
        {"bicycle": _lp(0.5), "table": _lp(0.3)},
        {"table": _lp(0.5), "bicycle": _lp(0.3)},
    ]
    combined = combine_token_distributions(views)
    winner = next(iter(combined))
    assert winner == "bicycle"
    expected_bicycle = (_lp(0.6) + _lp(0.5) + _lp(0.3)) / 3
    assert combined["bicycle"] == pytest.approx(expected_bicycle)


def test_explicit_weights_shift_the_vote():
    """A dominant per-view weight (attention-mass stand-in) flips the winner."""
    views = [
        {"a": _lp(0.9), "b": _lp(0.05)},
        {"b": _lp(0.9), "a": _lp(0.05)},
    ]
    uniform = combine_token_distributions(views)
    assert set(uniform) == {"a", "b"}
    weighted = combine_token_distributions(views, weights=[0.05, 0.95])
    assert next(iter(weighted)) == "b"


def test_confidence_weighting_favors_the_more_certain_view():
    views = [
        {"a": _lp(0.99), "b": _lp(0.005)},  # very confident in a
        {"b": _lp(0.4), "a": _lp(0.35)},  # lukewarm about b
    ]
    combined = combine_token_distributions(views, weighting_mode=WeightingMode.CONFIDENCE)
    assert next(iter(combined)) == "a"


def test_adaptive_plausibility_masks_globally_implausible_token():
    """'zebra' never exceeds alpha * global-best probability in ANY view -> masked."""
    views = [
        {"bicycle": _lp(0.8), "zebra": _lp(0.01)},
        {"bicycle": _lp(0.7), "zebra": _lp(0.02)},
    ]
    combined = combine_token_distributions(views, plausibility_alpha=0.1)
    assert "zebra" not in combined
    assert "bicycle" in combined
    unmasked = combine_token_distributions(views, plausibility_alpha=0.0)
    assert "zebra" in unmasked


def test_plausibility_keeps_token_plausible_in_one_view():
    """A token strong in a single view survives masking (per-view max governs)."""
    views = [
        {"sign": _lp(0.75), "mural": _lp(0.01)},
        {"mural": _lp(0.6), "sign": _lp(0.2)},
    ]
    combined = combine_token_distributions(views, plausibility_alpha=0.5)
    assert "mural" in combined and "sign" in combined


def test_combined_output_is_deterministic_and_sorted():
    views = [
        {"a": _lp(0.4), "b": _lp(0.4), "c": _lp(0.1)},
        {"b": _lp(0.4), "a": _lp(0.4), "c": _lp(0.1)},
    ]
    first = combine_token_distributions(views)
    second = combine_token_distributions(views)
    assert list(first) == list(second)
    scores = list(first.values())
    assert scores == sorted(scores, reverse=True)
    # Equal-score tokens tie-break lexicographically.
    assert list(first)[:2] == ["a", "b"]


def test_invalid_inputs_raise_explicit_errors():
    with pytest.raises(ValueError):
        combine_token_distributions([])
    with pytest.raises(ValueError):
        combine_token_distributions([{}])
    views = [{"a": _lp(0.5)}, {"a": _lp(0.5)}]
    with pytest.raises(ValueError):
        combine_token_distributions(views, weights=[1.0])
    with pytest.raises(ValueError):
        combine_token_distributions(views, weights=[-1.0, 2.0])
    with pytest.raises(ValueError):
        combine_token_distributions(views, weights=[0.0, 0.0])
    with pytest.raises(ValueError):
        combine_token_distributions(views, plausibility_alpha=1.5)


def test_config_enforces_hard_view_cap_and_alpha_range():
    assert EnsembleDecodeConfig().n_views == 4
    assert EnsembleDecodeConfig().view_strategy is ViewStrategy.GRID
    with pytest.raises(ValueError):
        EnsembleDecodeConfig(n_views=HARD_VIEW_CAP + 1)
    with pytest.raises(ValueError):
        EnsembleDecodeConfig(n_views=0)
    with pytest.raises(ValueError):
        EnsembleDecodeConfig(plausibility_alpha=1.01)


def test_build_grid_views_full_image_first_and_within_bounds():
    views = build_grid_views(400, 300, 4)
    assert len(views) == 4
    assert views[0] == ViewBox(0, 0, 400, 300)
    for box in views[1:]:
        assert 0 <= box.left < box.right <= 400
        assert 0 <= box.top < box.bottom <= 300


def test_build_grid_views_complete_grid_tiles_exactly():
    # 5 views = full image + a complete 2x2 grid partition.
    views = build_grid_views(400, 300, 5)
    assert len(views) == 5
    sub_area = sum((b.right - b.left) * (b.bottom - b.top) for b in views[1:])
    assert sub_area == 400 * 300


def test_build_grid_views_bounds():
    assert len(build_grid_views(100, 100, 1)) == 1
    with pytest.raises(ValueError):
        build_grid_views(100, 100, HARD_VIEW_CAP + 1)
    with pytest.raises(ValueError):
        build_grid_views(0, 100, 2)


# --------------------------------------- EnsembleDescriptionAdapter (Slice 2b)


def _png(width: int = 64, height: int = 48) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (128, 64, 32)).save(buffer, format="PNG")
    return buffer.getvalue()


_FULL_IMAGE_BOXES = (
    PhraseBox(phrase="bicycle", span_start=2, span_end=9, box=NormalizedBox(x=0.1, y=0.2, width=0.3, height=0.4)),
)


def _result(caption: str, *, first_view: bool) -> AdapterResult:
    """First-view results carry distinctive facts so verbatim passthrough is provable."""
    return AdapterResult(
        caption=caption,
        objects=("bicycle", "brick wall") if first_view else ("crop-artifact",),
        ocr_text="OPEN 9-5" if first_view else None,
        alt_text_draft=caption,
        context_sources=("context.caption",) if first_view else (),
        context_applied=first_view,
        phrase_boxes=_FULL_IMAGE_BOXES if first_view else (),
    )


class _StubGpuAdapter:
    """Trace-free GPU-kind stub: one canned caption per call, calls recorded."""

    kind = DescriptionAdapterKind.GPU
    model_id = "Qwen3-VL-30B-A3B-Instruct"
    model_version = "Q4_K_M"
    prompt_or_task_version = "3"

    def __init__(self, captions: list[str]) -> None:
        self._captions = captions
        self.calls: list[bytes] = []
        self.contexts: list[object] = []

    def describe(self, *, image_bytes: bytes, context) -> AdapterResult:
        index = len(self.calls)
        self.calls.append(image_bytes)
        self.contexts.append(context)
        return _result(self._captions[index], first_view=index == 0)


class _TracedStubGpuAdapter(_StubGpuAdapter):
    """Stub exposing describe_with_trace (the llama.cpp n_probs surface)."""

    def __init__(self, captions: list[str], traces: list[tuple[GpuRemoteTokenTrace, ...]]) -> None:
        super().__init__(captions)
        self._traces = traces

    def describe_with_trace(self, *, image_bytes: bytes, context):
        index = len(self.calls)
        result = self.describe(image_bytes=image_bytes, context=context)
        return result, self._traces[index]


def test_ensemble_adapter_satisfies_protocol_and_delegates_identity():
    stub = _StubGpuAdapter(["a"])
    adapter = EnsembleDescriptionAdapter(wrapped=stub)
    assert isinstance(adapter, DescriptionAdapter)
    assert adapter.kind is DescriptionAdapterKind.GPU
    assert adapter.model_id == stub.model_id
    assert adapter.model_version == stub.model_version
    assert adapter.prompt_or_task_version == stub.prompt_or_task_version


def test_ensemble_adapter_runs_one_pass_per_view_full_image_first():
    stub = _StubGpuAdapter(["a", "b", "b", "c"])
    adapter = EnsembleDescriptionAdapter(wrapped=stub, config=EnsembleDecodeConfig(n_views=4))
    image = _png()
    context = {"caption": "Launch day"}

    result = adapter.describe(image_bytes=image, context=context)

    assert len(stub.calls) == 4
    assert stub.calls[0] == image  # full-image pass gets the original bytes verbatim
    assert all(crop != image for crop in stub.calls[1:])
    assert all(ctx == context for ctx in stub.contexts)
    # Caption-level majority (no traces): 'b' wins 2-1-1 over the full-image 'a'.
    assert result.caption == "b"
    assert result.alt_text_draft == "b"


def test_ensemble_adapter_facts_come_verbatim_from_full_image_pass():
    stub = _StubGpuAdapter(["a", "b", "b"])
    adapter = EnsembleDescriptionAdapter(wrapped=stub, config=EnsembleDecodeConfig(n_views=3))

    result = adapter.describe(image_bytes=_png(), context={"caption": "x"})

    assert result.caption == "b"  # vote can override the caption...
    assert result.objects == ("bicycle", "brick wall")  # ...but never the facts (VLM4-PA-03)
    assert result.ocr_text == "OPEN 9-5"
    assert result.phrase_boxes == _FULL_IMAGE_BOXES
    assert result.context_sources == ("context.caption",)
    assert result.context_applied is True


def test_ensemble_adapter_caption_tie_breaks_to_full_image_view():
    stub = _StubGpuAdapter(["a", "b", "c"])
    adapter = EnsembleDescriptionAdapter(wrapped=stub, config=EnsembleDecodeConfig(n_views=3))

    result = adapter.describe(image_bytes=_png(), context=None)

    assert result.caption == "a"


def test_ensemble_adapter_single_view_is_one_wrapped_pass():
    stub = _StubGpuAdapter(["only"])
    adapter = EnsembleDescriptionAdapter(wrapped=stub, config=EnsembleDecodeConfig(n_views=1))

    result = adapter.describe(image_bytes=_png(), context=None)

    assert len(stub.calls) == 1
    assert result.caption == "only"


def test_ensemble_adapter_token_vote_wins_over_full_image_caption():
    """Cross-view logit agreement on ' cat' beats the full-image view's ' dog'."""
    trace_dog = (
        GpuRemoteTokenTrace(token="a", logprob=_lp(0.6), top_logprobs={"a": _lp(0.6), "the": _lp(0.3)}),
        GpuRemoteTokenTrace(token=" dog", logprob=_lp(0.5), top_logprobs={" dog": _lp(0.5), " cat": _lp(0.45)}),
    )
    trace_cat = (
        GpuRemoteTokenTrace(token="a", logprob=_lp(0.7), top_logprobs={"a": _lp(0.7)}),
        GpuRemoteTokenTrace(token=" cat", logprob=_lp(0.8), top_logprobs={" cat": _lp(0.8), " dog": _lp(0.1)}),
    )
    stub = _TracedStubGpuAdapter(["a dog", "a cat"], [trace_dog, trace_cat])
    adapter = EnsembleDescriptionAdapter(wrapped=stub, config=EnsembleDecodeConfig(n_views=2))

    result = adapter.describe(image_bytes=_png(), context=None)

    assert len(stub.calls) == 2
    assert result.caption == "a cat"
    assert result.alt_text_draft == "a cat"
    assert result.objects == ("bicycle", "brick wall")  # facts still full-image


def test_ensemble_adapter_falls_back_to_caption_vote_when_any_trace_missing():
    """Token-level vote needs traces from EVERY view; one empty trace degrades."""
    trace = (GpuRemoteTokenTrace(token="x", logprob=_lp(0.9), top_logprobs={"x": _lp(0.9)}),)
    stub = _TracedStubGpuAdapter(["a", "b", "b"], [trace, (), trace])
    adapter = EnsembleDescriptionAdapter(wrapped=stub, config=EnsembleDecodeConfig(n_views=3))

    result = adapter.describe(image_bytes=_png(), context=None)

    assert result.caption == "b"


def test_ensemble_adapter_unreadable_image_degrades_to_single_wrapped_pass():
    stub = _StubGpuAdapter(["only"])
    adapter = EnsembleDescriptionAdapter(wrapped=stub, config=EnsembleDecodeConfig(n_views=4))

    result = adapter.describe(image_bytes=b"not-an-image", context=None)

    assert len(stub.calls) == 1
    assert result.caption == "only"
