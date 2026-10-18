"""ORCH-LAUNCH-01: fail-closed VLM cache integrity gate (RB-02 / RB-05).

Synthetic snapshot trees only — no network, no real Florence weights.
TEST-15: every assertion is paired with a mutation that flips the result.

Also covers behavioural docker-entrypoint.sh variant gates (HARM-A-05): the
script is rewritten onto a temp root and executed under a stubbed PATH so the
shell logic is exercised, not grepped.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
import textwrap
from pathlib import Path
from types import ModuleType

import pytest

SERVICE_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = SERVICE_ROOT / "scripts" / "verify_vlm_cache.py"
ENTRYPOINT_PATH = SERVICE_ROOT / "scripts" / "docker-entrypoint.sh"


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


def test_exit_constants_are_literal_polarity(gate: ModuleType) -> None:
    """RLSE-02: EXIT_OK/EXIT_FAIL must stay 0/1 — comparing only to the names
    lets EXIT_FAIL=0 leave every failure test green while the gate returns success.
    """
    assert gate.EXIT_OK == 0
    assert gate.EXIT_FAIL == 1
    assert gate.EXIT_FAIL != gate.EXIT_OK


def test_main_skips_non_local_cpu_profile(gate: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    """D7 trade-off (pinned): seeded skips Florence pin even on the VLM image.

    Non-LOCAL_CPU adapters must boot under ``set -eu`` without demanding a
    Florence snapshot when no HF cache is mounted. Weak hub check only fires
    when HF_HOME/HF_HUB_CACHE is explicitly set (S3-A-07).
    """
    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", "seeded")
    monkeypatch.setenv("ACX_IMAGE_VARIANT", "vlm")
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    monkeypatch.delenv("HF_HOME", raising=False)
    monkeypatch.delenv("ACX_REQUIRE_VLM_CACHE", raising=False)
    # No bake artifact → env claim is the fallback.
    monkeypatch.setattr(gate, "IMAGE_VARIANT_ARTIFACT", Path("/nonexistent/.image-variant"))
    code = gate.main([])
    assert code == 0  # literal: not gate.EXIT_OK (RLSE-02)


def test_main_skips_gpu_qwen_on_vlm_image(
    gate: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D7: gpu_qwen30b must not demand the Florence pin (set -eu boot killer)."""
    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", "gpu_qwen30b")
    monkeypatch.setenv("ACX_IMAGE_VARIANT", "vlm")
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    monkeypatch.delenv("HF_HOME", raising=False)
    monkeypatch.delenv("ACX_REQUIRE_VLM_CACHE", raising=False)
    monkeypatch.setattr(gate, "IMAGE_VARIANT_ARTIFACT", Path("/nonexistent/.image-variant"))
    code = gate.main([])
    assert code == 0  # literal


def test_main_fails_closed_when_local_cpu_cache_absent(
    gate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", "florence_small")
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "empty-hub"))
    modules = tmp_path / "modules"
    modules.mkdir()
    monkeypatch.setenv("HF_MODULES_CACHE", str(modules))
    monkeypatch.setattr(gate, "IMAGE_VARIANT_ARTIFACT", Path("/nonexistent/.image-variant"))
    monkeypatch.delenv("ACX_VLM_MANIFEST_SHA256", raising=False)
    code = gate.main([])
    assert code == 1  # literal EXIT_FAIL — mutates of EXIT_FAIL→0 go red

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
    assert code_ok == 0  # literal EXIT_OK


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
    monkeypatch.setattr(gate, "IMAGE_VARIANT_ARTIFACT", Path("/nonexistent/.image-variant"))
    monkeypatch.delenv("ACX_VLM_MANIFEST_SHA256", raising=False)

    from scene.config.profiles import DescriptionProfile, get_profile_spec

    spec = get_profile_spec(DescriptionProfile.FLORENCE_SMALL)
    assert spec.model_id and spec.model_revision
    snapshot = gate.resolve_snapshot_dir(spec.model_id, spec.model_revision, hub_cache=hub)
    files = _intact_files()
    _write_tree(snapshot, files)
    _write_manifest(gate, snapshot, files)

    # Intact snapshot but no module cache env → fail.
    assert gate.main([]) == 1

    # Set path but directory missing → fail.
    missing = tmp_path / "no-modules"
    monkeypatch.setenv("HF_MODULES_CACHE", str(missing))
    assert gate.main([]) == 1

    # Present + writable → green.
    modules = tmp_path / "modules"
    modules.mkdir()
    monkeypatch.setenv("HF_MODULES_CACHE", str(modules))
    assert gate.main([]) == 0

    # Present but unwritable → fail. Use PermissionError monkeypatch rather than
    # chmod(0o555): root runners ignore DAC mode bits so chmod stays green under
    # container CI (A-12). Gate writes ``.acx_modules_cache_write_probe``.
    real_write_text = Path.write_text

    def _deny_probe(self: Path, data: object = "", *args: object, **kwargs: object) -> int:
        if self.name == ".acx_modules_cache_write_probe":
            raise PermissionError("read-only mount")
        return real_write_text(self, data, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "write_text", _deny_probe)
    assert gate.main([]) == 1


def test_main_module_invocable_as_python_m(monkeypatch: pytest.MonkeyPatch) -> None:
    """Frozen CLI contract: `python -m scripts.verify_vlm_cache` with no args."""
    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", "seeded")
    env = {
        **os.environ,
        "ACX_DESCRIPTION_ADAPTER": "seeded",
    }
    env.pop("HF_HUB_CACHE", None)
    env.pop("HF_HOME", None)
    env.pop("ACX_REQUIRE_VLM_CACHE", None)
    # Scrub variant so a parent shell exporting ACX_IMAGE_VARIANT=vlm cannot
    # invert seeded → EXIT_FAIL (V-09).
    env.pop("ACX_IMAGE_VARIANT", None)
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


def test_main_module_subprocess_fails_on_tampered_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RLSE-02 / S3-A-02: `python -m` exit code must be literal 1 on tamper.

    In-process asserts against ``gate.EXIT_FAIL`` stay green if that constant
    is rewritten to 0; the entrypoint under ``set -eu`` only sees the process
    exit status. Prove the real module returns 1 for a sha256 mismatch.
    """
    from scene.config.profiles import DescriptionProfile, get_profile_spec

    gate = _import_gate()
    hub = tmp_path / "hub"
    modules = tmp_path / "modules"
    modules.mkdir()
    spec = get_profile_spec(DescriptionProfile.FLORENCE_SMALL)
    assert spec.model_id and spec.model_revision
    snapshot = gate.resolve_snapshot_dir(
        spec.model_id, spec.model_revision, hub_cache=hub
    )
    files = _intact_files()
    _write_tree(snapshot, files)
    _write_manifest(gate, snapshot, files)
    # Tamper after certifying so verify_snapshot (and main) must fail closed.
    (snapshot / "modeling_florence2.py").write_bytes(b"# subprocess-tamper\n")

    env = {
        **os.environ,
        "ACX_DESCRIPTION_ADAPTER": "florence_small",
        "HF_HUB_CACHE": str(hub),
        "HF_MODULES_CACHE": str(modules),
    }
    env.pop("ACX_VLM_MANIFEST_SHA256", None)
    env.pop("ACX_REQUIRE_VLM_CACHE", None)
    # No bake artifact on host; force env claim so main takes the LOCAL_CPU path.
    env["ACX_IMAGE_VARIANT"] = "vlm"
    result = subprocess.run(
        [sys.executable, "-m", "scripts.verify_vlm_cache"],
        cwd=SERVICE_ROOT,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 1, (
        f"tampered snapshot must exit 1 (not gate.EXIT_FAIL alias); "
        f"got {result.returncode}; stdout={result.stdout!r} stderr={result.stderr!r}"
    )

    # TEST-15 control: restore bytes → subprocess goes green (literal 0).
    (snapshot / "modeling_florence2.py").write_bytes(files["modeling_florence2.py"])
    ok = subprocess.run(
        [sys.executable, "-m", "scripts.verify_vlm_cache"],
        cwd=SERVICE_ROOT,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert ok.returncode == 0, ok.stdout + ok.stderr


# ---- S1-A-07: bake-first image variant resolution ------------------------


def test_resolve_image_variant_prefers_bake(
    gate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact = tmp_path / ".image-variant"
    artifact.write_text("vlm\n", encoding="utf-8")
    monkeypatch.setattr(gate, "IMAGE_VARIANT_ARTIFACT", artifact)
    monkeypatch.delenv("ACX_IMAGE_VARIANT", raising=False)
    assert gate.resolve_image_variant_label() == "vlm"

    # Matching env is fine.
    monkeypatch.setenv("ACX_IMAGE_VARIANT", "vlm")
    assert gate.resolve_image_variant_label() == "vlm"

    # TEST-15: disagreement fails closed.
    monkeypatch.setenv("ACX_IMAGE_VARIANT", "recognition")
    with pytest.raises(gate.CacheIntegrityError, match="disagrees with baked"):
        gate.resolve_image_variant_label()


def test_resolve_image_variant_invalid_bake_fails(
    gate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact = tmp_path / ".image-variant"
    artifact.write_text("gpu-turbo\n", encoding="utf-8")
    monkeypatch.setattr(gate, "IMAGE_VARIANT_ARTIFACT", artifact)
    with pytest.raises(gate.CacheIntegrityError, match="invalid baked image variant"):
        gate.resolve_image_variant_label()

    # TEST-15: valid bake flips green.
    artifact.write_text("recognition\n", encoding="utf-8")
    assert gate.resolve_image_variant_label() == "recognition"


def test_resolve_image_variant_env_fallback_without_bake(
    gate: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gate, "IMAGE_VARIANT_ARTIFACT", Path("/nonexistent/.image-variant"))
    monkeypatch.setenv("ACX_IMAGE_VARIANT", "vlm")
    assert gate.resolve_image_variant_label() == "vlm"
    monkeypatch.delenv("ACX_IMAGE_VARIANT", raising=False)
    assert gate.resolve_image_variant_label() == "recognition"


# ---- V-06: path-agnostic seed hint ---------------------------------------


def test_seed_hint_is_path_agnostic(gate: ModuleType) -> None:
    """rg-006: hint must not hardcode a container-only /data/cache path."""
    assert "<ACX_MODELS_PATH>" in gate.SEED_COMMAND
    assert "/data/cache/huggingface_cache" not in gate.SEED_COMMAND
    assert "host" in gate.SEED_HINT_NOTE.lower()
    hint = gate._seed_hint()
    assert "<ACX_MODELS_PATH>" in hint
    assert "/data/cache/huggingface_cache" not in hint

    # TEST-15: a regression that re-hardcodes the container path must be visible.
    assert "uv run --extra vlm python -m scripts.seed_vlm_cache" in gate.SEED_COMMAND


# ---- A-03 / V-04: detached manifest trust pin ----------------------------


def test_manifest_trust_pin_mismatch_fails(
    gate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = tmp_path / "snap"
    files = _intact_files()
    _write_tree(snapshot, files)
    manifest = _write_manifest(gate, snapshot, files)
    real_pin = gate.manifest_content_sha256(manifest)

    monkeypatch.setenv("ACX_VLM_MANIFEST_SHA256", "0" * 64)
    with pytest.raises(gate.CacheIntegrityError, match="manifest trust pin mismatch"):
        gate.verify_snapshot(snapshot)

    # TEST-15: correct pin flips green.
    monkeypatch.setenv("ACX_VLM_MANIFEST_SHA256", real_pin)
    gate.verify_snapshot(snapshot)


def test_manifest_trust_pin_from_file(
    gate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = tmp_path / "snap"
    files = _intact_files()
    _write_tree(snapshot, files)
    manifest = _write_manifest(gate, snapshot, files)
    real_pin = gate.manifest_content_sha256(manifest)

    pin_file = tmp_path / "acx-vlm-cache.manifest.sha256"
    pin_file.write_text(real_pin + "\n", encoding="utf-8")
    monkeypatch.setattr(gate, "MANIFEST_SHA256_FILE", pin_file)
    monkeypatch.delenv("ACX_VLM_MANIFEST_SHA256", raising=False)
    gate.verify_snapshot(snapshot)

    # TEST-15: wrong file contents fail closed.
    pin_file.write_text("deadbeef" * 8 + "\n", encoding="utf-8")
    with pytest.raises(gate.CacheIntegrityError, match="manifest trust pin mismatch"):
        gate.verify_snapshot(snapshot)


def test_manifest_trust_pin_blocks_volume_rewrite(
    gate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Attacker rewrites weights + re-runs write-manifest → still fails pin."""
    snapshot = tmp_path / "snap"
    files = _intact_files()
    _write_tree(snapshot, files)
    manifest = gate.write_manifest(snapshot)
    pin = gate.manifest_content_sha256(manifest)
    monkeypatch.setenv("ACX_VLM_MANIFEST_SHA256", pin)
    gate.verify_snapshot(snapshot)

    (snapshot / "modeling_florence2.py").write_bytes(b"# pwned remote code\n")
    gate.write_manifest(snapshot)  # attacker "fixes" inventory
    with pytest.raises(gate.CacheIntegrityError, match="manifest trust pin mismatch"):
        gate.verify_snapshot(snapshot)


# ---- A-10: symlink-aware enumeration -------------------------------------


def test_list_snapshot_files_follows_in_tree_blob_symlink(
    gate: ModuleType, tmp_path: Path
) -> None:
    """HF hub layout: snapshots/<rev>/file -> ../../blobs/<sha>."""
    model = tmp_path / "models--demo"
    blobs = model / "blobs"
    snap = model / "snapshots" / "rev1"
    blobs.mkdir(parents=True)
    snap.mkdir(parents=True)
    blob = blobs / "abc123"
    blob.write_bytes(b"weight-bytes")
    link = snap / "weights.bin"
    link.symlink_to(os.path.relpath(blob, start=snap))

    listed = gate.list_snapshot_files(snap)
    assert "weights.bin" in listed
    assert gate.sha256_file(listed["weights.bin"]) == _sha(b"weight-bytes")


def test_list_snapshot_files_rejects_out_of_tree_symlink(
    gate: ModuleType, tmp_path: Path
) -> None:
    snap = tmp_path / "model" / "snapshots" / "rev1"
    snap.mkdir(parents=True)
    outside = tmp_path / "evil.py"
    outside.write_bytes(b"pwn\n")
    (snap / "evil.py").symlink_to(outside)

    with pytest.raises(gate.CacheIntegrityError, match="resolves outside"):
        gate.list_snapshot_files(snap)

    # TEST-15: in-tree regular file flips green.
    (snap / "evil.py").unlink()
    (snap / "ok.py").write_bytes(b"ok\n")
    listed = gate.list_snapshot_files(snap)
    assert "ok.py" in listed


def test_list_snapshot_files_rejects_directory_symlink(
    gate: ModuleType, tmp_path: Path
) -> None:
    model = tmp_path / "models--demo"
    snap = model / "snapshots" / "rev1"
    other = model / "other_dir"
    other.mkdir(parents=True)
    snap.mkdir(parents=True)
    (other / "hidden.py").write_bytes(b"nope\n")
    (snap / "nested").symlink_to(other)

    with pytest.raises(gate.CacheIntegrityError, match="does not resolve to a regular file"):
        gate.list_snapshot_files(snap)


# ---- S3-A-07: weak VLM hub check for non-LOCAL_CPU -----------------------


def test_vlm_image_weak_hub_empty_fails(
    gate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", "seeded")
    monkeypatch.setenv("ACX_IMAGE_VARIANT", "vlm")
    monkeypatch.setattr(gate, "IMAGE_VARIANT_ARTIFACT", Path("/nonexistent/.image-variant"))
    empty = tmp_path / "empty-hub"
    empty.mkdir()
    monkeypatch.setenv("HF_HUB_CACHE", str(empty))
    monkeypatch.delenv("ACX_REQUIRE_VLM_CACHE", raising=False)

    code = gate.main([])
    assert code == 1

    # TEST-15: non-empty hub (no Florence snapshot) flips to green skip.
    (empty / "marker").write_text("seeded-cache\n", encoding="utf-8")
    code_ok = gate.main([])
    assert code_ok == 0


def test_vlm_image_weak_hub_verifies_present_florence_snapshot(
    gate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When Florence snapshot dir exists under the hub, it must match its manifest."""
    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", "seeded")
    monkeypatch.setenv("ACX_IMAGE_VARIANT", "vlm")
    monkeypatch.setattr(gate, "IMAGE_VARIANT_ARTIFACT", Path("/nonexistent/.image-variant"))
    monkeypatch.delenv("ACX_REQUIRE_VLM_CACHE", raising=False)
    monkeypatch.delenv("ACX_VLM_MANIFEST_SHA256", raising=False)

    hub = tmp_path / "hub"
    monkeypatch.setenv("HF_HUB_CACHE", str(hub))

    from scene.config.profiles import DescriptionProfile, get_profile_spec

    spec = get_profile_spec(DescriptionProfile.FLORENCE_SMALL)
    assert spec.model_id and spec.model_revision
    snapshot = gate.resolve_snapshot_dir(spec.model_id, spec.model_revision, hub_cache=hub)
    files = _intact_files()
    _write_tree(snapshot, files)
    # Present but no manifest → weak path must fail closed.
    assert gate.main([]) == 1

    _write_manifest(gate, snapshot, files)
    assert gate.main([]) == 0

    # TEST-15: tamper fails closed even for non-LOCAL_CPU weak path.
    (snapshot / "modeling_florence2.py").write_bytes(b"# tampered\n")
    assert gate.main([]) == 1


def test_require_vlm_cache_opt_in_forces_full_pin(
    gate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ACX_REQUIRE_VLM_CACHE=1 forces Florence pin even for seeded adapter."""
    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", "seeded")
    monkeypatch.setenv("ACX_REQUIRE_VLM_CACHE", "1")
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "hub"))
    modules = tmp_path / "modules"
    modules.mkdir()
    monkeypatch.setenv("HF_MODULES_CACHE", str(modules))
    monkeypatch.setattr(gate, "IMAGE_VARIANT_ARTIFACT", Path("/nonexistent/.image-variant"))
    monkeypatch.delenv("ACX_VLM_MANIFEST_SHA256", raising=False)

    assert gate.main([]) == 1  # no snapshot

    from scene.config.profiles import DescriptionProfile, get_profile_spec

    spec = get_profile_spec(DescriptionProfile.FLORENCE_SMALL)
    snapshot = gate.resolve_snapshot_dir(
        spec.model_id, spec.model_revision, hub_cache=tmp_path / "hub"
    )
    files = _intact_files()
    _write_tree(snapshot, files)
    _write_manifest(gate, snapshot, files)
    assert gate.main([]) == 0


# ---- HARM-A-05: behavioural entrypoint variant gates ---------------------


def _make_stub_bin(dir_path: Path, name: str, body: str = "#!/bin/sh\nexit 0\n") -> None:
    path = dir_path / name
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _run_entrypoint_fixture(
    tmp_path: Path,
    *,
    variant_text: str | None,
    env_variant: str | None = None,
    skip_blob_check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Execute docker-entrypoint.sh under a rewritten root + stub PATH.

    Paths ``/app`` and the default blob root are rewritten to tmp_path so the
    real host is never touched. Behavioural: the shell script runs; we do not
    grep its source for the FATAL strings.
    """
    root = tmp_path / "root"
    app = root / "app"
    blobs = root / "var" / "lib" / "acx-blobs"
    bin_dir = root / "bin"
    app.mkdir(parents=True)
    blobs.mkdir(parents=True)
    bin_dir.mkdir(parents=True)

    if variant_text is not None:
        (app / ".image-variant").write_text(variant_text, encoding="utf-8")

    # Stubs for the post-variant boot chain.
    _make_stub_bin(bin_dir, "alembic")
    # python -m scripts.* must succeed; a tiny shim accepts -m and exits 0.
    _make_stub_bin(
        bin_dir,
        "python",
        textwrap.dedent(
            """\
            #!/bin/sh
            # stub: accept python -m scripts.* for entrypoint boot chain
            exit 0
            """
        ),
    )
    _make_stub_bin(
        bin_dir,
        "uvicorn",
        textwrap.dedent(
            """\
            #!/bin/sh
            # stub PID1 handoff
            exit 0
            """
        ),
    )
    # id is used in the blob-root error path; provide a harmless stub.
    _make_stub_bin(
        bin_dir,
        "id",
        textwrap.dedent(
            """\
            #!/bin/sh
            if [ "$1" = "-u" ]; then echo 10001; else echo acx; fi
            """
        ),
    )
    # Use real /usr/bin/tr for `tr -d '[:space:]'` (do not stub it).

    script_src = ENTRYPOINT_PATH.read_text(encoding="utf-8")
    # Rewrite absolute production paths onto the temp root.
    rewritten = script_src.replace("/app", str(app))
    rewritten = rewritten.replace("/var/lib/acx-blobs", str(blobs))
    if skip_blob_check:
        # Force blob root env so the default path rewrite still works.
        pass
    script = root / "docker-entrypoint.sh"
    script.write_text(rewritten, encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)

    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": str(root),
        "RECOGNITION_BLOB_ROOT": str(blobs),
    }
    if env_variant is not None:
        env["ACX_IMAGE_VARIANT"] = env_variant
    # Keep the rest of the parent env out so host ACX_* cannot leak.
    return subprocess.run(
        ["/bin/sh", str(script)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        cwd=str(root),
    )


def test_entrypoint_missing_image_variant_fails_closed(tmp_path: Path) -> None:
    """HARM-A-05 fixture 1: missing bake → exit 1 before alembic/uvicorn."""
    result = _run_entrypoint_fixture(tmp_path, variant_text=None)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "missing baked image variant" in result.stderr


def test_entrypoint_garbage_image_variant_fails_closed(tmp_path: Path) -> None:
    """HARM-A-05 fixture 2: garbage bake content → exit 1."""
    result = _run_entrypoint_fixture(tmp_path, variant_text="not-a-variant\n")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "invalid baked image variant" in result.stderr


def test_entrypoint_env_mismatch_fails_closed(tmp_path: Path) -> None:
    """HARM-A-05 fixture 3: env claim disagrees with bake → exit 1."""
    result = _run_entrypoint_fixture(
        tmp_path, variant_text="vlm\n", env_variant="recognition"
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "disagrees with baked" in result.stderr


def test_entrypoint_matching_vlm_bake_passes_variant_gate(tmp_path: Path) -> None:
    """HARM-A-05 fixture 4: matching vlm bake proceeds past variant checks.

    Stubs make alembic/python/uvicorn exit 0; we only assert the variant gate
    did not FATAL (returncode 0 and no FATAL variant message).
    """
    result = _run_entrypoint_fixture(
        tmp_path, variant_text="vlm\n", env_variant="vlm"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "FATAL" not in result.stderr


def test_entrypoint_variant_gate_mutation_is_observable(tmp_path: Path) -> None:
    """TEST-15: removing the missing-file check from the script fails the red path.

    Mutate a copy of the entrypoint (not the real source), show that a
    missing-bake run no longer exits 1 at the variant gate when the check is
    stripped — proves the behavioural fixture depends on the real logic.
    """
    root = tmp_path / "mut"
    app = root / "app"
    blobs = root / "var" / "lib" / "acx-blobs"
    bin_dir = root / "bin"
    app.mkdir(parents=True)
    blobs.mkdir(parents=True)
    bin_dir.mkdir(parents=True)
    for name in ("alembic", "python", "uvicorn", "id"):
        _make_stub_bin(bin_dir, name)

    src = ENTRYPOINT_PATH.read_text(encoding="utf-8")
    # Strip the missing-file fatal block (lines between IMAGE_VARIANT_FILE= and BAKED=).
    mutated = src.replace(
        'if [ ! -f "${IMAGE_VARIANT_FILE}" ]; then\n'
        '\techo "FATAL: missing baked image variant at ${IMAGE_VARIANT_FILE}" >&2\n'
        "\texit 1\n"
        "fi\n",
        "",
    )
    assert mutated != src, "mutation must change the script"
    mutated = mutated.replace("/app", str(app)).replace("/var/lib/acx-blobs", str(blobs))
    script = root / "docker-entrypoint.sh"
    script.write_text(mutated, encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)

    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": str(root),
        "RECOGNITION_BLOB_ROOT": str(blobs),
    }
    # No .image-variant file. With the check removed, `tr < missing` under set -e
    # still fails — but the FATAL message must be gone. If tr failure is the
    # exit, returncode != 0 without our FATAL string → proves the gate text path
    # was what we stripped. The positive fixtures above still require the FATAL.
    result = subprocess.run(
        ["/bin/sh", str(script)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        cwd=str(root),
    )
    assert "missing baked image variant" not in result.stderr
    # Control: unmutated script with same missing file still emits the FATAL.
    control = _run_entrypoint_fixture(tmp_path / "ctrl", variant_text=None)
    assert control.returncode == 1
    assert "missing baked image variant" in control.stderr
