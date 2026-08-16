#!/usr/bin/env python3
"""Single source of truth for the bootstrap overlay clone/payload location.

Repo scripts must **not** hardcode overlay paths — they resolve the overlay through
this one seam so the repo→plugin coupling lives in exactly one place. Applying the
distilled concepts: Extract Constant + single-source-of-truth + Ports & Adapters
(callers depend on this seam, not a concrete path) + **fail fast** (Nygard §5.5).

Greenfield: the overlay is materialized at the canonical `.workbay/remote` home by
`workbay-bootstrap install`. There is **no legacy fallback** — if the canonical home is
absent the overlay is simply not materialized, and callers fail fast (no silent
degrade onto a stale clone). Resolution is harness-agnostic (the clone is shared across
Claude/Codex/Cursor/Grok).

`workbay` should own this resolution (expose the overlay home from the install ledger /
package) so consumers need neither this shim nor hoisted copies of the overlay tooling —
tracked as a request in agentic-protocol-monorepo/docs/upstream-requests/2026-06-28-…/.
This module is the thin interim seam until then.
"""

from __future__ import annotations

import os
from pathlib import Path

# The canonical (only) overlay payload root, relative to the repo root.
_CANONICAL_PAYLOAD_REL = ".workbay/remote/packages/workbay-system/workbay_system/payload"

# Depth of the payload dir below the clone root (`<clone>/remote`):
# remote / packages / <plugin-dir> / <plugin-module> / payload  -> 3 parents to `<clone>/remote`.
_PAYLOAD_TO_CLONE_PARENTS = 3
_PAYLOAD_TO_PACKAGES_PARENTS = 2


class OverlayNotMaterializedError(RuntimeError):
    """Raised when the canonical overlay home is absent (fail-fast accessor)."""


def overlay_payload_root(repo_root: Path) -> Path | None:
    """Resolve the canonical overlay payload root, or ``None`` if not materialized.

    Honors an explicit ``$WORKBAY_OVERLAY_PAYLOAD`` pin (set by the installer when known).
    """
    override = os.environ.get("WORKBAY_OVERLAY_PAYLOAD")
    if override:
        candidate = Path(override)
        return candidate if candidate.is_dir() else None
    candidate = repo_root / _CANONICAL_PAYLOAD_REL
    return candidate if candidate.is_dir() else None


def require_overlay_payload_root(repo_root: Path) -> Path:
    """Fail-fast accessor: raise ``OverlayNotMaterializedError`` if not materialized."""
    payload = overlay_payload_root(repo_root)
    if payload is None:
        raise OverlayNotMaterializedError(
            "workbay overlay is not materialized at .workbay/remote — run "
            "`workbay-bootstrap install`."
        )
    return payload


def overlay_clone_root(repo_root: Path) -> Path:
    """The canonical clone root (`<clone>/remote`) that shared surfaces symlink into.

    Always returns the canonical path so drift checks have a concrete comparison target:
    a surface symlinked anywhere else is loud drift, not a silent fallback.
    """
    payload = overlay_payload_root(repo_root)
    if payload is not None:
        return payload.parents[_PAYLOAD_TO_CLONE_PARENTS]
    return repo_root / ".workbay" / "remote"


def overlay_packages_root(repo_root: Path) -> Path | None:
    """The `<clone>/remote/packages` dir holding the hoisted packages, or ``None``."""
    payload = overlay_payload_root(repo_root)
    if payload is None:
        return None
    return payload.parents[_PAYLOAD_TO_PACKAGES_PARENTS]


def hoisted_generator_path(repo_root: Path) -> Path | None:
    """Absolute path to the hoisted ``generate_agent_workflows.py``, or ``None``."""
    payload = overlay_payload_root(repo_root)
    if payload is None:
        return None
    return payload / "scripts" / "generate_agent_workflows.py"
