"""Model-space identity.

This is a stdlib-only leaf because the aligner imports it and must remain
independent of the service's HTTP import graph.
"""

from __future__ import annotations

from enum import StrEnum


class ModelSpace(StrEnum):
    INSIGHTFACE = "insightface"
    FACE_PIPELINE = "face_pipeline"
    AURAFACE = "auraface"


class UnhandledModelSpaceError(Exception):
    """Fail closed on a model space this build does not handle."""
