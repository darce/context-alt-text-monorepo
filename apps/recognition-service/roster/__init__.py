"""
Roster Service

A clean-slate rewrite of the roster microservice for managing identity records
and model-specific embedding stores in the CVLFace stack.

This service:
- Does NOT perform inference (handled by /recognition)
- Exposes hexagonal architecture
- Runs independently for orchestration by App and Analysis Service
- Manages identity records and embeddings per model
"""

__version__ = "1.0.0"
