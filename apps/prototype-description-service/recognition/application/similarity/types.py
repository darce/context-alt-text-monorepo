"""Shared types for similarity search."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MatchResult:
    """Best match for a query against a cluster."""

    cluster_id: str
    similarity: float
