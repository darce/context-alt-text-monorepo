"""Application-layer services.

These coordinate infrastructure repositories (SQLAlchemy/db) on behalf of the
HTTP routers. They live in the application layer — not ``domain`` — because they
depend on infrastructure, so they are not technology-agnostic domain services.
"""
