"""Pure, dependency-free hashing helpers for the description cache key.

Isolated from HTTP/DB/model layers so they are unit-testable on their own and
reused by both the describe route and the VisualFactsService. The cache key is
``(tenant_id, image_hash, adapter, model_id, model_version, prompt_or_task_version,
context_hash)``; these helpers compute the two content-derived dimensions.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any


def compute_image_hash(data: bytes) -> str:
    """Return the sha256 hex digest of the raw image bytes."""
    return hashlib.sha256(data).hexdigest()


def compute_context_hash(context: Mapping[str, Any] | None) -> str:
    """Return the sha256 hex digest of the canonical-JSON-serialized context.

    Canonical JSON (``sort_keys=True``) makes the digest insensitive to mapping
    key ordering at every nesting level, so reordered-but-equivalent context
    dicts share one cache row. ``None`` is treated as the empty context. List
    order is preserved because it is semantically meaningful.
    """
    canonical = json.dumps(
        context or {},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
