"""
Recognition Ports Module

Port layer for the recognition service (FastAPI routes and adapters).
"""

from .api_routes import router

__all__ = [
    "router"
]
