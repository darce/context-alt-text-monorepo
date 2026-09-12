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


def test_confidence_weighting_flips_the_uniform_winner():
    """VLM4-RB-BR-02: the fixture discriminates — uniform picks b, confidence picks a.

    One very confident view backs 'a'; two lukewarm views back 'b'. The uniform
    mean lets the lukewarm majority win; confidence weighting hands the vote to
    the certain view.
    """
    views = [
        {"a": _lp(0.95), "b": _lp(0.01)},
        {"b": _lp(0.45), "a": _lp(0.02)},
        {"b": _lp(0.45), "a": _lp(0.02)},
    ]
    uniform = combine_token_distributions(views, weighting_mode=WeightingMode.UNIFORM)
    assert next(iter(uniform)) == "b"
    confident = combine_token_distributions(views, weighting_mode=WeightingMode.CONFIDENCE)
    assert next(iter(confident)) == "a"


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
        EnsembleDecodeConfig(n_views=2)  # sole sub-view would duplicate the full image
    with pytest.raises(ValueError):
        EnsembleDecodeConfig(plausibility_alpha=1.01)


@pytest.mark.parametrize("n_views", [3, 4, 5, HARD_VIEW_CAP])
def test_build_grid_views_sub_views_tile_exactly_for_any_n(n_views):
    """VLM4-RA-BR-03: strips tile the image exactly — no uncovered region, any n."""
    views = build_grid_views(400, 300, n_views)
    assert len(views) == n_views
    assert views[0] == ViewBox(0, 0, 400, 300)
    for box in views[1:]:
        assert 0 <= box.left < box.right <= 400
        assert 0 <= box.top < box.bottom <= 300
    sub_area = sum((b.right - b.left) * (b.bottom - b.top) for b in views[1:])
    assert sub_area == 400 * 300


def test_build_grid_views_strips_follow_the_wider_axis():
    wide = build_grid_views(400, 300, 3)
    assert all(box.top == 0 and box.bottom == 300 for box in wide[1:])  # vertical strips
    tall = build_grid_views(300, 400, 3)
    assert all(box.left == 0 and box.right == 300 for box in tall[1:])  # horizontal strips


def test_build_grid_views_bounds():
    assert len(build_grid_views(100, 100, 1)) == 1
    with pytest.raises(ValueError):
        build_grid_views(100, 100, 2)  # duplicate-of-full-image no-op rejected
    with pytest.raises(ValueError):
        build_grid_views(100, 100, HARD_VIEW_CAP + 1)
    with pytest.raises(ValueError):
        build_grid_views(0, 100, 3)


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


def test_async_gpu_resolver_wraps_available_adapter_and_preserves_unavailable(monkeypatch):
    from scene.infrastructure.vlm.unavailable_adapter import UnavailableDescriptionAdapter
    from scene.interface_adapters.http import deps

    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", "gpu_qwen30b_ensemble")
    stub = _StubGpuAdapter(["only"])
    monkeypatch.setattr(deps, "get_gpu_description_adapter", lambda: stub)

    adapter = deps.get_async_gpu_description_adapter()

    assert isinstance(adapter, EnsembleDescriptionAdapter)
    adapter.describe(image_bytes=b"unreadable-image", context=None)
    assert stub.calls == [b"unreadable-image"]

    unavailable = UnavailableDescriptionAdapter("GPU offline", kind=DescriptionAdapterKind.GPU)
    monkeypatch.setattr(deps, "get_gpu_description_adapter", lambda: unavailable)

    assert deps.get_async_gpu_description_adapter() is unavailable


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


def test_ensemble_adapter_consensus_beats_hallucinated_outlier():
    """VLM4-RA-BR-01: unique captions select by cross-view word overlap.

    Two views agree on the bicycle scene; one crop hallucinates a dining
    table. The hallucinated caption shares almost no words with the others
    and must lose.
    """
    stub = _StubGpuAdapter(
        [
            "a red bicycle against a wall",
            "a red bicycle near a brick wall",
            "a dining table with flowers",
        ]
    )
    adapter = EnsembleDescriptionAdapter(wrapped=stub, config=EnsembleDecodeConfig(n_views=3))

    result = adapter.describe(image_bytes=_png(), context=None)

    assert result.caption == "a red bicycle against a wall"
    assert result.alt_text_draft == result.caption


def test_ensemble_adapter_never_composes_text_across_views():
    """VLM4-RA-BR-01/RB-BR-01: output is ALWAYS one per-view caption verbatim.

    The stub exposes describe_with_trace with wildly misaligned, unequal-length
    traces — exactly the divergent-prefix case where step-zipping manufactures
    word salad. The adapter must ignore traces for caption assembly.
    """
    misaligned_a = (
        GpuRemoteTokenTrace(token="A", logprob=_lp(0.9), top_logprobs={"A": _lp(0.9)}),
        GpuRemoteTokenTrace(token=" mural", logprob=_lp(0.8), top_logprobs={" mural": _lp(0.8)}),
    )
    misaligned_b = (
        GpuRemoteTokenTrace(token="Bright", logprob=_lp(0.95), top_logprobs={"Bright": _lp(0.95)}),
        GpuRemoteTokenTrace(token=" red", logprob=_lp(0.9), top_logprobs={" red": _lp(0.9)}),
        GpuRemoteTokenTrace(token=" paint", logprob=_lp(0.85), top_logprobs={" paint": _lp(0.85)}),
    )
    misaligned_c = (GpuRemoteTokenTrace(token="Wall", logprob=_lp(0.99), top_logprobs={"Wall": _lp(0.99)}),)
    captions = ["A mural", "Bright red paint", "Wall"]
    stub = _TracedStubGpuAdapter(captions, [misaligned_a, misaligned_b, misaligned_c])
    adapter = EnsembleDescriptionAdapter(wrapped=stub, config=EnsembleDecodeConfig(n_views=3))

    result = adapter.describe(image_bytes=_png(), context=None)

    assert result.caption in captions


def test_ensemble_adapter_unreadable_image_degrades_to_single_wrapped_pass():
    stub = _StubGpuAdapter(["only"])
    adapter = EnsembleDescriptionAdapter(wrapped=stub, config=EnsembleDecodeConfig(n_views=4))

    result = adapter.describe(image_bytes=b"not-an-image", context=None)

    assert len(stub.calls) == 1
    assert result.caption == "only"


def test_ensemble_adapter_reports_n_passes_for_timeout_sizing():
    """VLM4-RC-BR-01: job timeouts scale by 1 + n_passes; raw adapters default to 1."""
    stub = _StubGpuAdapter(["a"])
    adapter = EnsembleDescriptionAdapter(wrapped=stub, config=EnsembleDecodeConfig(n_views=4))
    assert adapter.n_passes == 4
    assert getattr(stub, "n_passes", 1) == 1
