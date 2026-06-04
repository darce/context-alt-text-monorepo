#!/usr/bin/env python3
"""Validate overrides.lock.json upstream digests against materialized bases.

MAINT-FB-B-05 drift-detection check (encodes the MAINT-FB-A-02 convention):
each component's ``upstream_digest`` in a plugin ``overrides.lock.json`` is
the whole-file sha256 of the materialized upstream base copy referenced by
``base_path`` (e.g. ``skills/branch-review/SKILL.base.md``), resolved
relative to the plugin overrides directory.

The generated base surface under ``.workstate/generated/plugins/*/base/`` is
deliberately NOT the digest subject: the generator injects harness-specific
sections (e.g. ``## Global Instructions``), so its hash legitimately differs
from the upstream body. Without this check, digest drift only surfaces on the
next manual workstate-bootstrap update.

Wired into ``make check-all`` via the ``check-overrides-digest`` target.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OVERRIDES_ROOT = REPO_ROOT / "workstate-overrides"


def _sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _check_lock(lock_path: Path) -> list[str]:
    plugin_dir = lock_path.parent
    rel_lock = (
        lock_path.relative_to(REPO_ROOT) if lock_path.is_relative_to(REPO_ROOT) else lock_path
    )
    try:
        payload = json.loads(lock_path.read_text())
    except json.JSONDecodeError as exc:
        return [f"{rel_lock}: invalid JSON: {exc}"]

    components = payload.get("components")
    if not isinstance(components, list):
        return [f"{rel_lock}: missing or non-list 'components' key"]

    errors: list[str] = []
    for index, component in enumerate(components):
        label = component.get("name") or f"components[{index}]"
        base_rel = component.get("base_path")
        digest = component.get("upstream_digest")
        if not base_rel:
            errors.append(f"{rel_lock}: component '{label}' missing base_path")
            continue
        if not digest:
            errors.append(f"{rel_lock}: component '{label}' missing upstream_digest")
            continue
        base_file = plugin_dir / base_rel
        if not base_file.is_file():
            errors.append(
                f"{rel_lock}: component '{label}' base file missing: {base_rel}"
            )
            continue
        actual = _sha256_file(base_file)
        if actual != digest:
            errors.append(
                f"{rel_lock}: component '{label}' upstream_digest mismatch — "
                f"lock has {digest}, materialized {base_rel} hashes to {actual}. "
                f"Re-run the overrides update flow or recompute the digest from "
                f"the upstream base copy (whole-file sha256 of {base_rel})."
            )
    return errors


def check_overrides_locks(overrides_root: Path) -> list[str]:
    """Return a list of digest/contract violations under ``overrides_root``."""
    errors: list[str] = []
    for lock_path in sorted(overrides_root.glob("*/overrides.lock.json")):
        errors.extend(_check_lock(lock_path))
    return errors


def main() -> int:
    overrides_root = Path(sys.argv[1]) if len(sys.argv) > 1 else OVERRIDES_ROOT
    if not overrides_root.is_dir():
        print(f"check-overrides-digest: no overrides directory at {overrides_root}; nothing to check.")
        return 0
    errors = check_overrides_locks(overrides_root)
    if errors:
        print("check-overrides-digest: FAIL", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    lock_count = len(list(overrides_root.glob("*/overrides.lock.json")))
    print(f"check-overrides-digest: OK ({lock_count} lock file(s) checked)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
