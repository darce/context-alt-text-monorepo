"""
Application-level settings objects for the recognition service.
"""

from recognition.application.settings.clustering import (
    ENROLLMENT_NOOP_CEILING_OCCLUSION,
    ENROLLMENT_NOOP_FLOOR_EMBEDDING_NORM,
    ENROLLMENT_NOOP_FLOOR_SHARPNESS,
    AutoLabelSettings,
    ClusteringSettings,
    HACSettings,
    MaturitySettings,
    QualitySettings,
)

__all__ = [
    "ClusteringSettings",
    "AutoLabelSettings",
    "ENROLLMENT_NOOP_CEILING_OCCLUSION",
    "ENROLLMENT_NOOP_FLOOR_EMBEDDING_NORM",
    "ENROLLMENT_NOOP_FLOOR_SHARPNESS",
    "HACSettings",
    "MaturitySettings",
    "QualitySettings",
]
