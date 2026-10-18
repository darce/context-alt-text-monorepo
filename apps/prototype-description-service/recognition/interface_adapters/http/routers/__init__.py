"""
Grouped routers for recognition HTTP API.
"""

from recognition.interface_adapters.http.routers import (
    analyze,
    clusters_admission,
    clusters_maintenance,
    clusters_snapshot,
    clusters_topology,
    diagnostics,
    retention,
    suggestions,
)

__all__ = [
    "analyze",
    "clusters_admission",
    "clusters_maintenance",
    "clusters_snapshot",
    "clusters_topology",
    "diagnostics",
    "retention",
    "suggestions",
]
