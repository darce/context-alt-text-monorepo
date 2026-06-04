"""Tests for scripts/check_overrides_lock_digest.py (MAINT-FB-B-05 / MAINT-FB-A-02).

Digest convention under test: each overrides.lock.json component's
``upstream_digest`` is the whole-file sha256 of the materialized upstream base
copy (``base_path``, e.g. SKILL.base.md) inside the plugin overrides directory.
The generated base surface under .workstate/generated/ is NOT the digest
subject — the generator injects harness-specific sections (Global
Instructions), so its hash legitimately differs.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.check_overrides_lock_digest import check_overrides_locks

REPO_ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _write_lock(plugin_dir: Path, components: list[dict]) -> Path:
    lock = {
        "schema_version": 1,
        "plugin": plugin_dir.name,
        "base_remote_sha": "0" * 40,
        "components": components,
    }
    lock_path = plugin_dir / "overrides.lock.json"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(json.dumps(lock, indent=2))
    return lock_path


def _component(base_path: str, digest: str) -> dict:
    return {
        "component_kind": "skill",
        "name": "branch-review",
        "mode": "patch",
        "local_path": "skills/branch-review/SKILL.md",
        "base_path": base_path,
        "patch_path": None,
        "upstream_digest": digest,
        "last_accept_upstream": None,
    }


def test_matching_digest_passes(tmp_path: Path) -> None:
    plugin = tmp_path / "workstate-system"
    base = plugin / "skills" / "branch-review" / "SKILL.base.md"
    base.parent.mkdir(parents=True)
    base.write_text("---\nname: demo\n---\nbody\n")
    _write_lock(plugin, [_component("skills/branch-review/SKILL.base.md", _sha256(base))])
    assert check_overrides_locks(tmp_path) == []


def test_mismatched_digest_fails_with_component_and_hashes(tmp_path: Path) -> None:
    plugin = tmp_path / "workstate-system"
    base = plugin / "skills" / "branch-review" / "SKILL.base.md"
    base.parent.mkdir(parents=True)
    base.write_text("drifted upstream body\n")
    _write_lock(plugin, [_component("skills/branch-review/SKILL.base.md", "sha256:" + "a" * 64)])
    errors = check_overrides_locks(tmp_path)
    assert len(errors) == 1
    assert "branch-review" in errors[0]
    assert "sha256:" + "a" * 64 in errors[0]
    assert _sha256(base) in errors[0]


def test_missing_base_file_fails(tmp_path: Path) -> None:
    plugin = tmp_path / "workstate-system"
    plugin.mkdir(parents=True)
    _write_lock(plugin, [_component("skills/branch-review/SKILL.base.md", "sha256:" + "a" * 64)])
    errors = check_overrides_locks(tmp_path)
    assert len(errors) == 1
    assert "SKILL.base.md" in errors[0]
    assert "missing" in errors[0].lower()


def test_malformed_lock_fails_fast(tmp_path: Path) -> None:
    plugin = tmp_path / "workstate-system"
    plugin.mkdir(parents=True)
    (plugin / "overrides.lock.json").write_text(json.dumps({"schema_version": 1}))
    errors = check_overrides_locks(tmp_path)
    assert len(errors) == 1
    assert "components" in errors[0]


def test_component_missing_digest_fails_fast(tmp_path: Path) -> None:
    plugin = tmp_path / "workstate-system"
    base = plugin / "skills" / "branch-review" / "SKILL.base.md"
    base.parent.mkdir(parents=True)
    base.write_text("body\n")
    component = _component("skills/branch-review/SKILL.base.md", "sha256:" + "a" * 64)
    del component["upstream_digest"]
    _write_lock(plugin, [component])
    errors = check_overrides_locks(tmp_path)
    assert len(errors) == 1
    assert "upstream_digest" in errors[0]


def test_no_lock_files_is_ok(tmp_path: Path) -> None:
    assert check_overrides_locks(tmp_path) == []


def test_repo_overrides_lock_is_consistent() -> None:
    """The committed workstate-overrides tree must satisfy its own digests."""
    overrides_root = REPO_ROOT / "workstate-overrides"
    assert overrides_root.is_dir()
    assert check_overrides_locks(overrides_root) == []
