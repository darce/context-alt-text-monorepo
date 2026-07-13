"""N-view ensemble decoding for the GPU describe tier (VLM-4 Slice 2a + 2b).

Slice 2a is pure vote math — no I/O, no model calls. The logit-only vote is
the MANDATORY BASELINE: the live serving stack (llama.cpp ``server-cuda``,
VLM-3 golden image) exposes per-token logprobs (``n_probs``) but no
cross-attention, so attention weighting enters only through the optional
``weights`` parameter when a spike-gated alternative stack provides per-view
attention mass (arXiv 2505.17529).

Slice 2b adds ``EnsembleDescriptionAdapter``: a ``DescriptionAdapter`` wrapper
that runs the wrapped GPU adapter once per view and SELECTS a caption at
caption granularity (exact majority, then cross-view word-overlap consensus,
ties to the full-image view). Per-view token traces are deliberately NOT
zipped into a composed caption: each view's step-``i`` distribution is
conditioned on that view's own prefix, so merging independently decoded
traces manufactures word salad (VLM4-RA-BR-01). True step-wise ensemble
requires step-synchronized decoding, which the one-shot llama.cpp completion
API cannot provide; ``combine_token_distributions`` stays as the per-step
primitive for that spike-gated decoder.

Caption-only scope (VLM4-PA-03): this module votes on caption token streams
only. ``objects``/``ocr_text``/``phrase_boxes`` and the ``context_*`` fields
always come from the designated full-image (first-view) pass so the
``AdapterResult`` contract stays intact.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from scene.application.description_adapter import AdapterResult, DescriptionAdapter

if TYPE_CHECKING:
    from scene.domain.description import DescriptionAdapterKind

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
        if self.n_views == 2:
            raise ValueError("n_views=2 duplicates the full image as its only sub-view; use 1 or >= 3")
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
    """Full image first, then ``n_views - 1`` strip sub-regions (pure geometry).

    The first view is always the whole image — it is the designated pass that
    supplies objects/ocr/phrase_boxes downstream (VLM4-PA-03). Sub-views are
    equal strips along the wider axis, so they tile the image exactly for any
    ``n_views`` — no quadrant is ever left uncovered (VLM4-RA-BR-03).
    ``n_views=2`` is rejected: its sole sub-view would duplicate the full
    image, doubling GPU cost for a guaranteed no-op vote. Callers crop.
    """
    if width <= 0 or height <= 0:
        raise ValueError(f"image dimensions must be positive, got {width}x{height}")
    if not 1 <= n_views <= HARD_VIEW_CAP:
        raise ValueError(f"n_views must be within [1, {HARD_VIEW_CAP}], got {n_views}")
    if n_views == 2:
        raise ValueError("n_views=2 duplicates the full image as its only sub-view; use 1 or >= 3")
    views = [ViewBox(0, 0, width, height)]
    n_sub = n_views - 1
    if n_sub == 0:
        return tuple(views)
    horizontal = width >= height
    for idx in range(n_sub):
        if horizontal:
            views.append(ViewBox((idx * width) // n_sub, 0, ((idx + 1) * width) // n_sub, height))
        else:
            views.append(ViewBox(0, (idx * height) // n_sub, width, ((idx + 1) * height) // n_sub))
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
    per view (full image first, ``EnsembleDecodeConfig.n_views`` bound) and
    selects the caption at caption granularity via :func:`_select_caption` —
    never by zipping per-view token traces (VLM4-RA-BR-01: independently
    decoded traces are conditioned on divergent prefixes; composing them
    step-wise manufactures word salad).

    ``objects``/``ocr_text``/``phrase_boxes``/``context_*`` always come
    verbatim from the full-image pass (VLM4-PA-03). Unreadable image bytes
    degrade to a single wrapped pass — the wrapped adapter stays the authority
    on whether the bytes are usable.

    N sequential GPU passes are affordable only on the minutes-tolerant async
    GPU-final tier; routing lives in ``get_async_gpu_description_adapter``
    (VLM4-RA-BR-02) [RES-02].
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

    @property
    def n_passes(self) -> int:
        """GPU passes one describe costs — callers size job timeouts with this
        (VLM4-RC-BR-01): a fixed 2-pass budget times out every N-view job."""
        return self._config.n_views

    def describe(self, *, image_bytes: bytes, context: Mapping[str, Any] | None) -> AdapterResult:
        view_bytes = self._build_view_bytes(image_bytes)
        if view_bytes is None:
            return self._wrapped.describe(image_bytes=image_bytes, context=context)

        results = [
            self._wrapped.describe(image_bytes=single_view_bytes, context=context) for single_view_bytes in view_bytes
        ]
        full_image = results[0]
        caption = _select_caption(results)
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


def _select_caption(results: Sequence[AdapterResult]) -> str:
    """Caption-granularity consensus selection (VLM4-RA-BR-01 realignment).

    Exact-string majority first. When every caption is unique (the normal
    temp-0 multi-view case), the caption with the highest cross-view
    word-overlap consensus wins — a hallucinated unit appearing in only one
    view drags that caption's score down. All ties break to the earliest
    view, so the full-image pass wins by default.

    The output is ALWAYS one of the per-view captions verbatim — this
    function must never compose text across views.
    """
    captions = [result.caption for result in results]
    if len(captions) == 1:
        return captions[0]
    counts = Counter(captions)
    best_count = max(counts.values())
    if best_count > 1:
        for caption in captions:
            if counts[caption] == best_count:
                return caption

    word_sets = [set(caption.lower().split()) for caption in captions]
    scores: list[float] = []
    for i, words in enumerate(word_sets):
        score = 0.0
        for j, other in enumerate(word_sets):
            if i == j:
                continue
            union = words | other
            if union:
                score += len(words & other) / len(union)
        scores.append(score)
    best_score = max(scores)
    for caption, score in zip(captions, scores, strict=True):
        if score == best_score:
            return caption
    raise RuntimeError("unreachable: captions is non-empty")
