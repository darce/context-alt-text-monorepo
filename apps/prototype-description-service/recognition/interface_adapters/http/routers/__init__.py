"""
Grouped routers for recognition HTTP API.
"""

from recognition.interface_adapters.http.routers import analyze, clusters, diagnostics, suggestions

__all__ = ["analyze", "clusters", "diagnostics", "suggestions"]
