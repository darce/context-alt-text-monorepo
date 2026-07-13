"""N-view ensemble decoding for the GPU describe tier (VLM-4 Slice 2a + 2b).

Slice 2a is pure vote math — no I/O, no model calls. The logit-only vote is
the MANDATORY BASELINE: the live serving stack (llama.cpp ``server-cuda``,
VLM-3 golden image) exposes per-token logprobs (``n_probs``) but no
cross-attention, so attention weighting enters only through the optional
``weights`` parameter when a spike-gated alternative stack provides per-view
attention mass (arXiv 2505.17529).

Slice 2b adds ``EnsembleDescriptionAdapter``: a ``DescriptionAdapter`` wrapper
that runs the wrapped GPU adapter once per grid view and votes on the caption.
The token-level vote requires per-view token traces; llama.cpp provides them
via ``n_probs``, surfaced by ``GpuRemoteDescriptionAdapter.describe_with_trace``.
When the wrapped adapter exposes no traces, the vote degrades to caption-level
majority (earliest view breaks ties, so the full-image pass wins by default).

Caption-only scope (VLM4-PA-03): this module votes on caption token streams
only. ``objects``/``ocr_text``/``phrase_boxes`` and the ``context_*`` fields
always come from the designated full-image (first-view) pass so the
``AdapterResult`` contract stays intact.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from scene.application.description_adapter import AdapterResult, DescriptionAdapter

if TYPE_CHECKING:
    from scene.domain.description import DescriptionAdapterKind
    from scene.infrastructure.vlm.gpu_remote_adapter import GpuRemoteTokenTrace

# Hard cap on ensemble width: N views = N GPU passes = N x latency/VRAM
# (capacity multiplier); the async tier tolerates minutes, not unbounded N.
HARD_VIEW_CAP = 8

# A token absent from one view's top-k logprob map contributes this floor —
# effectively zero probability without poisoning the weighted mean with -inf.
MISSING_TOKEN_LOGPROB = -100.0


class ViewStrategy(StrEnum):
    """View-construction strategy. Pinned to GRID for the MVP (plan Slice 2)."""

    GRID = "grid"


class WeightingMode(StrEnum):
    UNIFORM = "uniform"
    CONFIDENCE = "confidence"


@dataclass(frozen=True)
class EnsembleDecodeConfig:
    """Bounded ensemble settings (plan: start N≈4, hard cap enforced)."""

    n_views: int = 4
    view_strategy: ViewStrategy = ViewStrategy.GRID
    plausibility_alpha: float = 0.1
    weighting_mode: WeightingMode = WeightingMode.UNIFORM

    def __post_init__(self) -> None:
        if not 1 <= self.n_views <= HARD_VIEW_CAP:
            raise ValueError(f"n_views must be within [1, {HARD_VIEW_CAP}], got {self.n_views}")
        if not 0.0 <= self.plausibility_alpha <= 1.0:
            raise ValueError(f"plausibility_alpha must be within [0.0, 1.0], got {self.plausibility_alpha}")


@dataclass(frozen=True)
class ViewBox:
    """Pixel crop box (left, top) inclusive to (right, bottom) exclusive."""

    left: int
    top: int
    right: int
    bottom: int


def build_grid_views(width: int, height: int, n_views: int) -> tuple[ViewBox, ...]:
    """Full image first, then ``n_views - 1`` grid sub-regions (pure geometry).

    The first view is always the whole image — it is the designated pass that
    supplies objects/ocr/phrase_boxes downstream (VLM4-PA-03). Callers crop.
    """
    if width <= 0 or height <= 0:
        raise ValueError(f"image dimensions must be positive, got {width}x{height}")
    if not 1 <= n_views <= HARD_VIEW_CAP:
        raise ValueError(f"n_views must be within [1, {HARD_VIEW_CAP}], got {n_views}")
    views = [ViewBox(0, 0, width, height)]
    n_sub = n_views - 1
    if n_sub == 0:
        return tuple(views)
    cols = math.ceil(math.sqrt(n_sub))
    rows = math.ceil(n_sub / cols)
    for idx in range(n_sub):
        r, c = divmod(idx, cols)
        left = (c * width) // cols
        right = ((c + 1) * width) // cols
        top = (r * height) // rows
        bottom = ((r + 1) * height) // rows
        views.append(ViewBox(left, top, right, bottom))
    return tuple(views)


def _resolve_weights(
    view_distributions: Sequence[Mapping[str, float]],
    weights: Sequence[float] | None,
    weighting_mode: WeightingMode,
) -> list[float]:
    n = len(view_distributions)
    if weights is not None:
        if len(weights) != n:
            raise ValueError(f"weights length {len(weights)} != view count {n}")
        if any(w < 0 for w in weights):
            raise ValueError("weights must be non-negative")
        total = sum(weights)
        if total <= 0:
            raise ValueError("weights must sum to a positive value")
        return [w / total for w in weights]
    if weighting_mode is WeightingMode.CONFIDENCE:
        # Confidence = each view's top-token probability: a view that is sure
        # of its next token gets a larger say in the vote.
        confidences = [math.exp(max(dist.values())) for dist in view_distributions]
        total = sum(confidences)
        return [c / total for c in confidences]
    return [1.0 / n] * n


def combine_token_distributions(
    view_distributions: Sequence[Mapping[str, float]],
    *,
    weights: Sequence[float] | None = None,
    plausibility_alpha: float = 0.0,
    weighting_mode: WeightingMode = WeightingMode.UNIFORM,
) -> dict[str, float]:
    """Combine one decode step's per-view ``token -> logprob`` maps into one.

    Weighted mean of per-view logprobs (uniform mean is the logit-only
    baseline; ``weights`` carries attention mass when a future stack exposes
    it). Then the adaptive plausibility constraint (arXiv 2505.17529) masks
    tokens whose best per-view probability falls below ``alpha`` times the
    global best candidate's — ``alpha=0.0`` disables masking.

    Returns tokens sorted by combined logprob descending, then token, so the
    result is deterministic and the first key is the vote winner.
    """
    if not view_distributions:
        raise ValueError("view_distributions must be non-empty")
    if any(not dist for dist in view_distributions):
        raise ValueError("every view distribution must be non-empty")
    if not 0.0 <= plausibility_alpha <= 1.0:
        raise ValueError(f"plausibility_alpha must be within [0.0, 1.0], got {plausibility_alpha}")

    resolved = _resolve_weights(view_distributions, weights, weighting_mode)
    vocabulary = sorted({token for dist in view_distributions for token in dist})

    combined: dict[str, float] = {}
    best_view_prob: dict[str, float] = {}
    for token in vocabulary:
        per_view = [dist.get(token, MISSING_TOKEN_LOGPROB) for dist in view_distributions]
        combined[token] = sum(w * lp for w, lp in zip(resolved, per_view, strict=True))
        best_view_prob[token] = math.exp(max(per_view))

    if plausibility_alpha > 0.0:
        global_best = max(best_view_prob.values())
        threshold = plausibility_alpha * global_best
        combined = {t: lp for t, lp in combined.items() if best_view_prob[t] >= threshold}

    return dict(sorted(combined.items(), key=lambda item: (-item[1], item[0])))


class EnsembleDescriptionAdapter:
    """N-view ensemble wrapper over a GPU ``DescriptionAdapter`` (VLM-4 Slice 2b).

    Identity fields delegate to the wrapped adapter so cache keys and
    provenance stay tied to the underlying model. ``describe`` runs one pass
    per grid view (full image first, ``EnsembleDecodeConfig.n_views`` bound)
    and votes on the caption:

    - token-level logit vote via :func:`combine_token_distributions` when the
      wrapped adapter exposes per-view token traces (``describe_with_trace``,
      llama.cpp ``n_probs``);
    - caption-level majority fallback otherwise (ties break to the earliest
      view, i.e. the full-image pass).

    ``objects``/``ocr_text``/``phrase_boxes``/``context_*`` always come
    verbatim from the full-image pass (VLM4-PA-03). Unreadable image bytes
    degrade to a single wrapped pass — the wrapped adapter stays the authority
    on whether the bytes are usable.
    """

    def __init__(
        self,
        *,
        wrapped: DescriptionAdapter,
        config: EnsembleDecodeConfig | None = None,
    ) -> None:
        self._wrapped = wrapped
        self._config = config if config is not None else EnsembleDecodeConfig()

    @property
    def kind(self) -> DescriptionAdapterKind:
        return self._wrapped.kind

    @property
    def model_id(self) -> str:
        return self._wrapped.model_id

    @property
    def model_version(self) -> str:
        return self._wrapped.model_version

    @property
    def prompt_or_task_version(self) -> str:
        return self._wrapped.prompt_or_task_version

    def describe(self, *, image_bytes: bytes, context: Mapping[str, Any] | None) -> AdapterResult:
        view_bytes = self._build_view_bytes(image_bytes)
        if view_bytes is None:
            return self._wrapped.describe(image_bytes=image_bytes, context=context)

        describe_with_trace = getattr(self._wrapped, "describe_with_trace", None)
        results: list[AdapterResult] = []
        traces: list[tuple[GpuRemoteTokenTrace, ...]] = []
        for single_view_bytes in view_bytes:
            if callable(describe_with_trace):
                result, trace = describe_with_trace(image_bytes=single_view_bytes, context=context)
            else:
                result, trace = self._wrapped.describe(image_bytes=single_view_bytes, context=context), ()
            results.append(result)
            traces.append(tuple(trace))

        full_image = results[0]
        caption = self._vote_caption(results, traces)
        return AdapterResult(
            caption=caption,
            objects=full_image.objects,
            ocr_text=full_image.ocr_text,
            alt_text_draft=caption,
            context_sources=full_image.context_sources,
            context_applied=full_image.context_applied,
            phrase_boxes=full_image.phrase_boxes,
        )

    def _build_view_bytes(self, image_bytes: bytes) -> list[bytes] | None:
        """Full-image bytes first, then lossless PNG crops per grid view.

        Returns None when the image cannot be read/cropped, so the caller
        degrades to a single wrapped pass instead of failing a describe the
        wrapped adapter might still serve.
        """
        from io import BytesIO

        try:
            from PIL import Image
        except ImportError:
            return None
        try:
            with Image.open(BytesIO(image_bytes)) as img:
                width, height = img.size
                views = build_grid_views(width, height, self._config.n_views)
                out = [image_bytes]
                for box in views[1:]:
                    buffer = BytesIO()
                    img.crop((box.left, box.top, box.right, box.bottom)).convert("RGB").save(buffer, format="PNG")
                    out.append(buffer.getvalue())
        except Exception:  # noqa: BLE001 - unreadable image degrades to single-pass
            return None
        return out

    def _vote_caption(
        self,
        results: Sequence[AdapterResult],
        traces: Sequence[tuple[GpuRemoteTokenTrace, ...]],
    ) -> str:
        if len(results) == 1:
            return results[0].caption
        if all(traces):
            voted = self._token_level_vote(traces)
            if voted:
                return voted
        return _caption_majority(results)

    def _token_level_vote(self, traces: Sequence[tuple[GpuRemoteTokenTrace, ...]]) -> str:
        """Step-wise logit vote across per-view token traces.

        At step ``i`` each view still decoding contributes its top-k
        ``token -> logprob`` map; :func:`combine_token_distributions` picks the
        step winner under the configured weighting + plausibility settings.
        Views that finished early simply drop out of later steps.
        """
        tokens: list[str] = []
        for step in range(max(len(trace) for trace in traces)):
            distributions: list[dict[str, float]] = []
            for trace in traces:
                if step >= len(trace):
                    continue
                entry = trace[step]
                distribution = dict(entry.top_logprobs)
                distribution.setdefault(entry.token, entry.logprob)
                if distribution:
                    distributions.append(distribution)
            if not distributions:
                break
            combined = combine_token_distributions(
                distributions,
                plausibility_alpha=self._config.plausibility_alpha,
                weighting_mode=self._config.weighting_mode,
            )
            tokens.append(next(iter(combined)))
        return "".join(tokens).strip()


def _caption_majority(results: Sequence[AdapterResult]) -> str:
    """Exact-caption majority; ties break to the earliest (full-image) view."""
    counts: dict[str, int] = {}
    for result in results:
        counts[result.caption] = counts.get(result.caption, 0) + 1
    best = max(counts.values())
    for result in results:
        if counts[result.caption] == best:
            return result.caption
    raise RuntimeError("unreachable: results is non-empty")
