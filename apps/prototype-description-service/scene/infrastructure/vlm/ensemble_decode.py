"""N-view ensemble decoding core for the GPU describe tier (VLM-4 Slice 2a).

Pure vote math — no I/O, no model calls, no adapter coupling. The logit-only
vote is the MANDATORY BASELINE: the live serving stack (llama.cpp
``server-cuda``, VLM-3 golden image) exposes per-token logprobs (``n_probs``)
but no cross-attention, so attention weighting enters only through the
optional ``weights`` parameter when a spike-gated alternative stack provides
per-view attention mass (arXiv 2505.17529).

Caption-only scope (VLM4-PA-03): this module votes on caption token streams
only. ``objects``/``ocr_text``/``phrase_boxes`` always come from the
designated full-image pass so the ``AdapterResult`` contract stays intact.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

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
