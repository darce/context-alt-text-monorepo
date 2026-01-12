"""Experiment configuration for adaptive threshold testing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ExperimentVariant:
    name: str
    threshold: float
    weight: float


@dataclass(frozen=True)
class Experiment:
    id: str
    variants: list[ExperimentVariant]
    start_date: datetime
    end_date: datetime | None


ACTIVE_EXPERIMENTS: dict[str, Experiment] = {
    "threshold_v2_jan2026": Experiment(
        id="threshold_v2_jan2026",
        variants=[
            ExperimentVariant("control", threshold=0.72, weight=0.5),
            ExperimentVariant("aggressive", threshold=0.68, weight=0.25),
            ExperimentVariant("conservative", threshold=0.78, weight=0.25),
        ],
        start_date=datetime(2026, 1, 15),
        end_date=datetime(2026, 2, 15),
    ),
}
