"""Face-recognition P/R as pure functions over recorded responses (no network).

Two levels (scope note definitions):
- detection: faces found vs faces labeled present, identity-agnostic, count-based.
- identification: named-identity assertions vs labeled identities. Wrong-name
  (asserted name not labeled present) is the top-severity error class — every
  instance is listed individually, never only aggregated.

Edge ledger: zero-face precision is None (never 1.0); stranger true rejection
counted, not penalized; duplicate identities deduped (by identity, not face);
policy-disabled images excluded; micro AND per-identity macro (Fair-SA: one
over-represented person must not mask another's failures).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ImageDetection:
    image: str
    pred_faces: int
    labeled_faces: int


@dataclass(frozen=True)
class ImageIdentities:
    image: str
    predicted: Sequence[str]
    labeled: Sequence[str]
    recognition_enabled: bool = True
    stranger_faces: int = 0


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


@dataclass(frozen=True)
class IdentityPr:
    true_positives: int
    false_positives: int
    false_negatives: int

    @property
    def precision(self) -> float | None:
        return _ratio(self.true_positives, self.true_positives + self.false_positives)

    @property
    def recall(self) -> float | None:
        return _ratio(self.true_positives, self.true_positives + self.false_negatives)


@dataclass(frozen=True)
class PrResult:
    true_positives: int
    false_positives: int
    false_negatives: int
    true_rejections: int = 0
    wrong_names: list[tuple[str, str]] = field(default_factory=list)
    per_identity: dict[str, IdentityPr] = field(default_factory=dict)
    excluded_images: list[str] = field(default_factory=list)

    @property
    def precision(self) -> float | None:
        return _ratio(self.true_positives, self.true_positives + self.false_positives)

    @property
    def recall(self) -> float | None:
        return _ratio(self.true_positives, self.true_positives + self.false_negatives)

    @property
    def macro_precision(self) -> float | None:
        values = [pr.precision for pr in self.per_identity.values() if pr.precision is not None]
        return sum(values) / len(values) if values else None

    @property
    def macro_recall(self) -> float | None:
        values = [pr.recall for pr in self.per_identity.values() if pr.recall is not None]
        return sum(values) / len(values) if values else None


def detection_pr(items: Sequence[ImageDetection]) -> PrResult:
    """Count-based detection P/R: per image TP=min(pred,labeled), overshoot=FP, undershoot=FN."""
    tp = fp = fn = 0
    for item in items:
        tp += min(item.pred_faces, item.labeled_faces)
        fp += max(item.pred_faces - item.labeled_faces, 0)
        fn += max(item.labeled_faces - item.pred_faces, 0)
    return PrResult(true_positives=tp, false_positives=fp, false_negatives=fn)


def identification_pr(items: Sequence[ImageIdentities]) -> PrResult:
    tp = fp = fn = true_rejections = 0
    wrong_names: list[tuple[str, str]] = []
    excluded: list[str] = []
    per_identity_counts: dict[str, dict[str, int]] = {}

    def counts(name: str) -> dict[str, int]:
        return per_identity_counts.setdefault(name, {"tp": 0, "fp": 0, "fn": 0})

    for item in items:
        if not item.recognition_enabled:
            excluded.append(item.image)
            continue
        predicted = sorted(set(item.predicted))
        labeled = set(item.labeled)
        if not predicted and not labeled:
            if item.stranger_faces > 0:
                true_rejections += 1
            continue
        for name in predicted:
            if name in labeled:
                tp += 1
                counts(name)["tp"] += 1
            else:
                fp += 1
                counts(name)["fp"] += 1
                wrong_names.append((item.image, name))
        for name in labeled:
            if name not in predicted:
                fn += 1
                counts(name)["fn"] += 1

    per_identity = {
        name: IdentityPr(true_positives=c["tp"], false_positives=c["fp"], false_negatives=c["fn"])
        for name, c in sorted(per_identity_counts.items())
    }
    return PrResult(
        true_positives=tp,
        false_positives=fp,
        false_negatives=fn,
        true_rejections=true_rejections,
        wrong_names=wrong_names,
        per_identity=per_identity,
        excluded_images=excluded,
    )
