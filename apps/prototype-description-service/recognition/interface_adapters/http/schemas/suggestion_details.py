"""Backward-compatible re-export for suggestion detail DTOs."""

from recognition.interface_adapters.schemas.suggestion_details import (
    FaceBox,
    MergeSuggestionDetails,
    SuggestionDetails,
)

__all__ = ["FaceBox", "SuggestionDetails", "MergeSuggestionDetails"]
