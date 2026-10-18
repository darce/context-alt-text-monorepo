"""Storage seam for analyze image bytes (E15-11).

Public exports:

- ``ObjectStore`` — Protocol implemented by every backing store
- ``ObjectStoreError`` — raised on contract violations (tenant escape,
  bad URI, traversal attempt)
- ``FilesystemObjectStore`` — Slice A reference implementation
"""

from __future__ import annotations

from .filesystem import FilesystemObjectStore
from .object_store import ObjectStore, ObjectStoreError

__all__ = ["FilesystemObjectStore", "ObjectStore", "ObjectStoreError"]
