"""ORCH-LAUNCH-01: fail-closed VLM cache integrity gate (RB-02 / RB-05).

Synthetic snapshot trees only — no network, no real Florence weights.
TEST-15: every assertion is paired with a mutation that flips the result.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from types import ModuleType

import pytest

SERVICE_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = SERVICE_ROOT / "scripts" / "verify_vlm_cache.py"


def _import_gate() -> ModuleType:
    spec = importlib.util.spec_from_file_location("verify_vlm_cache_gate", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register under a stable name so dataclasses/enums reloads are happy if any.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gate() -> ModuleType:
    return _import_gate()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_tree(root: Path, files: dict[str, bytes]) -> None:
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def _write_manifest(gate: ModuleType, snapshot: Path, files: dict[str, bytes]) -> Path:
    payload = {rel: _sha(content) for rel, content in files.items()}
    path = snapshot / gate.MANIFEST_FILENAME
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _intact_files() -> dict[str, bytes]:
    return {
        "config.json": b'{"model_type":"florence2"}\n',
        "modeling_florence2.py": b"# trusted remote code stub\n",
        "weights/shard.bin": b"tiny-weight-bytes",
    }


def test_verify_ok_on_intact_manifest_and_tree(gate: ModuleType, tmp_path: Path) -> None:
    snapshot = tmp_path / "snap"
    files = _intact_files()
    _write_tree(snapshot, files)
    _write_manifest(gate, snapshot, files)

    gate.verify_snapshot(snapshot)  # must not raise

    # TEST-15: tampering flips the result.
    (snapshot / "modeling_florence2.py").write_bytes(b"# tampered\n")
    with pytest.raises(gate.CacheIntegrityError, match="sha256 mismatch"):
        gate.verify_snapshot(snapshot)


def test_verify_fails_missing_directory(gate: ModuleType, tmp_path: Path) -> None:
    missing = tmp_path / "no-such-snapshot"
    with pytest.raises(gate.CacheIntegrityError, match="snapshot directory missing"):
        gate.verify_snapshot(missing)

    # TEST-15: creating the dir + intact tree flips to green.
    files = _intact_files()
    _write_tree(missing, files)
    _write_manifest(gate, missing, files)
    gate.verify_snapshot(missing)


def test_verify_fails_empty_directory(gate: ModuleType, tmp_path: Path) -> None:
    snapshot = tmp_path / "empty"
    snapshot.mkdir()
    with pytest.raises(gate.CacheIntegrityError, match="snapshot directory is empty"):
        gate.verify_snapshot(snapshot)

    # TEST-15: populate + manifest flips to green.
    files = _intact_files()
    _write_tree(snapshot, files)
    _write_manifest(gate, snapshot, files)
    gate.verify_snapshot(snapshot)


def test_verify_fails_missing_manifest(gate: ModuleType, tmp_path: Path) -> None:
    snapshot = tmp_path / "snap"
    files = _intact_files()
    _write_tree(snapshot, files)
    with pytest.raises(gate.CacheIntegrityError, match="manifest missing"):
        gate.verify_snapshot(snapshot)

    # TEST-15: writing the manifest flips to green.
    _write_manifest(gate, snapshot, files)
    gate.verify_snapshot(snapshot)


def test_verify_fails_missing_listed_file(gate: ModuleType, tmp_path: Path) -> None:
    snapshot = tmp_path / "snap"
    files = _intact_files()
    _write_tree(snapshot, files)
    _write_manifest(gate, snapshot, files)
    (snapshot / "weights" / "shard.bin").unlink()

    with pytest.raises(gate.CacheIntegrityError, match="file listed in manifest is missing"):
        gate.verify_snapshot(snapshot)

    # TEST-15: restore the file flips to green.
    (snapshot / "weights" / "shard.bin").write_bytes(files["weights/shard.bin"])
    gate.verify_snapshot(snapshot)


def test_verify_fails_modified_file_digest_mismatch(gate: ModuleType, tmp_path: Path) -> None:
    snapshot = tmp_path / "snap"
    files = _intact_files()
    _write_tree(snapshot, files)
    _write_manifest(gate, snapshot, files)

    gate.verify_snapshot(snapshot)  # baseline green

    (snapshot / "config.json").write_bytes(b'{"model_type":"EVIL"}\n')
    with pytest.raises(gate.CacheIntegrityError, match="sha256 mismatch"):
        gate.verify_snapshot(snapshot)


def test_verify_fails_extra_unlisted_file(gate: ModuleType, tmp_path: Path) -> None:
    """RB-02: attacker ADDS a .py without modifying listed entries."""
    snapshot = tmp_path / "snap"
    files = _intact_files()
    _write_tree(snapshot, files)
    _write_manifest(gate, snapshot, files)

    gate.verify_snapshot(snapshot)  # baseline green

    (snapshot / "evil_payload.py").write_bytes(b"print('pwn')\n")
    with pytest.raises(gate.CacheIntegrityError, match="unlisted file"):
        gate.verify_snapshot(snapshot)

    # TEST-15: removing the extra file flips back to green.
    (snapshot / "evil_payload.py").unlink()
    gate.verify_snapshot(snapshot)


def test_write_manifest_then_verify_roundtrip(gate: ModuleType, tmp_path: Path) -> None:
    snapshot = tmp_path / "snap"
    files = _intact_files()
    _write_tree(snapshot, files)

    out = gate.write_manifest(snapshot)
    assert out.name == gate.MANIFEST_FILENAME
    assert out.is_file()
    gate.verify_snapshot(snapshot)

    # TEST-15: extra file after certifying fails closed.
    (snapshot / "sneaky.py").write_bytes(b"# no\n")
    with pytest.raises(gate.CacheIntegrityError, match="unlisted file"):
        gate.verify_snapshot(snapshot)


def test_write_manifest_refuses_empty_or_missing(gate: ModuleType, tmp_path: Path) -> None:
    missing = tmp_path / "gone"
    with pytest.raises(gate.CacheIntegrityError, match="snapshot directory missing"):
        gate.write_manifest(missing)

    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(gate.CacheIntegrityError, match="snapshot directory is empty"):
        gate.write_manifest(empty)


def test_resolve_snapshot_dir_hub_layout(gate: ModuleType, tmp_path: Path) -> None:
    hub = tmp_path / "hub"
    path = gate.resolve_snapshot_dir(
        "microsoft/Florence-2-base-ft",
        "f6c1a25888ffc1d945ee8a1a77ac833c7303d46e",
        hub_cache=hub,
    )
    assert path == (
        hub
        / "models--microsoft--Florence-2-base-ft"
        / "snapshots"
        / "f6c1a25888ffc1d945ee8a1a77ac833c7303d46e"
    )


def test_main_skips_non_local_cpu_profile(gate: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    """D7: seeded / non-Florence adapters skip even on the VLM image."""
    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", "seeded")
    monkeypatch.setenv("ACX_IMAGE_VARIANT", "vlm")
    code = gate.main([])
    assert code == gate.EXIT_OK


def test_main_skips_gpu_qwen_on_vlm_image(
    gate: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D7: gpu_qwen30b must not demand the Florence pin (set -eu boot killer)."""
    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", "gpu_qwen30b")
    monkeypatch.setenv("ACX_IMAGE_VARIANT", "vlm")
    code = gate.main([])
    assert code == gate.EXIT_OK


def test_main_fails_closed_when_local_cpu_cache_absent(
    gate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", "florence_small")
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "empty-hub"))
    modules = tmp_path / "modules"
    modules.mkdir()
    monkeypatch.setenv("HF_MODULES_CACHE", str(modules))
    code = gate.main([])
    assert code == gate.EXIT_FAIL

    # TEST-15: seed a matching tree + manifest under the pin, gate goes green.
    from scene.config.profiles import DescriptionProfile, get_profile_spec

    spec = get_profile_spec(DescriptionProfile.FLORENCE_SMALL)
    assert spec.model_id and spec.model_revision
    snapshot = gate.resolve_snapshot_dir(
        spec.model_id, spec.model_revision, hub_cache=tmp_path / "empty-hub"
    )
    files = _intact_files()
    _write_tree(snapshot, files)
    _write_manifest(gate, snapshot, files)
    code_ok = gate.main([])
    assert code_ok == gate.EXIT_OK


def test_modules_cache_required_present_and_writable(
    gate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D2: snapshot-only green is not enough — HF_MODULES_CACHE must be writable.

    Before: gate inspected only snapshots/<revision> and reported ok while
    trust_remote_code imports failed. After: missing/unwritable module cache
    fails closed; a present writable dir (e.g. private tmpfs) passes.
    """
    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", "florence_small")
    hub = tmp_path / "hub"
    monkeypatch.setenv("HF_HUB_CACHE", str(hub))
    monkeypatch.delenv("HF_MODULES_CACHE", raising=False)

    from scene.config.profiles import DescriptionProfile, get_profile_spec

    spec = get_profile_spec(DescriptionProfile.FLORENCE_SMALL)
    assert spec.model_id and spec.model_revision
    snapshot = gate.resolve_snapshot_dir(spec.model_id, spec.model_revision, hub_cache=hub)
    files = _intact_files()
    _write_tree(snapshot, files)
    _write_manifest(gate, snapshot, files)

    # Intact snapshot but no module cache env → fail.
    assert gate.main([]) == gate.EXIT_FAIL

    # Set path but directory missing → fail.
    missing = tmp_path / "no-modules"
    monkeypatch.setenv("HF_MODULES_CACHE", str(missing))
    assert gate.main([]) == gate.EXIT_FAIL

    # Present + writable → green.
    modules = tmp_path / "modules"
    modules.mkdir()
    monkeypatch.setenv("HF_MODULES_CACHE", str(modules))
    assert gate.main([]) == gate.EXIT_OK

    # Present but unwritable → fail (simulates read-only mount of module cache).
    modules.chmod(0o555)
    try:
        assert gate.main([]) == gate.EXIT_FAIL
    finally:
        modules.chmod(0o755)


def test_main_module_invocable_as_python_m(monkeypatch: pytest.MonkeyPatch) -> None:
    """Frozen CLI contract: `python -m scripts.verify_vlm_cache` with no args."""
    import subprocess

    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", "seeded")
    env = {**os.environ, "ACX_DESCRIPTION_ADAPTER": "seeded"}
    result = subprocess.run(
        [sys.executable, "-m", "scripts.verify_vlm_cache"],
        cwd=SERVICE_ROOT,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "skipped" in result.stdout.lower() or "does not need" in result.stdout.lower()
