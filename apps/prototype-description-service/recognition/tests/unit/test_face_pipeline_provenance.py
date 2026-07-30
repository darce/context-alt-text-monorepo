"""FIR-3 S1: face_pipeline model provenance loader (fail-closed, no network).

Synthetic hashes only in unit paths — never touches real ONNX model bytes.
Committed LICENSE.* files are hashed offline against production pins (local finding BR-04).
See docs/tasks/fir/FIR-3-yunet-sface-adapters-task-plan.md (S1).
Heuristics: rg-008 (config validate-at-load), AGT-02 (no unresolved anchors),
TEST-06/TEST-08, rg-015.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from recognition.infrastructure.face_pipeline.provenance import (
    DEFAULT_MODELS_DIR,
    MODEL_MANIFEST,
    PENDING_OPERATOR_FETCH,
    ModelIntegrityError,
    ModelMissingError,
    ModelProvenance,
    _file_sha256,
    load_verified_model,
)

_SERVICE_ROOT = Path(__file__).resolve().parents[3]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _make_entry(
    *,
    file_name: str,
    sha256: str,
    size_bytes: int,
    license_file: str = "LICENSE.yunet",
    license_sha256: str | None = None,
    license_payload: bytes = b"MIT",
    framework: str = "opencv",
    embedding_dim: int | None = None,
    normalization: str | None = None,
    metric: str | None = None,
    source_url: str = "https://example.test/model.onnx",
    source_ref: str = "deadbeef",
    license_id: str = "MIT",
) -> ModelProvenance:
    return ModelProvenance(
        file_name=file_name,
        sha256=sha256,
        source_url=source_url,
        source_ref=source_ref,
        license_id=license_id,
        license_file=license_file,
        license_sha256=license_sha256 if license_sha256 is not None else _sha256(license_payload),
        size_bytes=size_bytes,
        framework=framework,
        embedding_dim=embedding_dim,
        normalization=normalization,
        metric=metric,
    )


def _write_model(tmp_path: Path, name: str, payload: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(payload)
    return path


def _write_license(tmp_path: Path, name: str, payload: bytes = b"MIT") -> Path:
    path = tmp_path / name
    path.write_bytes(payload)
    return path


def test_load_verified_model_happy_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Temp file whose sha256 matches a synthetic manifest entry loads successfully."""
    payload = b"synthetic-yunet-bytes-v1"
    license_payload = b"MIT"
    digest = _sha256(payload)
    file_name = "face_detection_yunet_2026may.onnx"
    license_file = "LICENSE.yunet"
    _write_model(tmp_path, file_name, payload)
    _write_license(tmp_path, license_file, license_payload)

    entry = _make_entry(
        file_name=file_name,
        sha256=digest,
        size_bytes=len(payload),
        license_file=license_file,
        license_payload=license_payload,
        framework="opencv",
        embedding_dim=None,
        normalization=None,
        metric=None,
    )
    monkeypatch.setitem(MODEL_MANIFEST, "yunet", entry)

    path = load_verified_model("yunet", models_dir=tmp_path)
    assert path == tmp_path / file_name
    assert path.is_file()


def test_load_verified_model_tampered_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Tampered on-disk bytes refuse to load (rg-008 fail-closed)."""
    file_name = "face_detection_yunet_2026may.onnx"
    license_file = "LICENSE.yunet"
    expected = b"expected-model-bytes"
    # Same length as expected so the size gate does not short-circuit; sha256 must fail.
    tampered = b"TAMPERED-model-bytes"
    assert len(tampered) == len(expected)
    _write_model(tmp_path, file_name, tampered)
    _write_license(tmp_path, license_file)

    entry = _make_entry(
        file_name=file_name,
        sha256=_sha256(expected),
        size_bytes=len(expected),
        license_file=license_file,
    )
    monkeypatch.setitem(MODEL_MANIFEST, "yunet", entry)

    with pytest.raises(ModelIntegrityError, match="sha256 mismatch"):
        load_verified_model("yunet", models_dir=tmp_path)


def test_load_verified_model_missing_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing on-disk model refuses to load as ModelMissingError (non-integrity)."""
    file_name = "face_recognition_sface_2021dec.onnx"
    entry = _make_entry(
        file_name=file_name,
        sha256="a" * 64,
        size_bytes=1,
        license_file="LICENSE.sface",
        license_sha256="b" * 64,
        framework="opencv",
        embedding_dim=128,
        normalization="l2",
        metric="cosine",
        source_url="https://example.test/sface.onnx",
        license_id="Apache-2.0",
    )
    monkeypatch.setitem(MODEL_MANIFEST, "sface", entry)

    with pytest.raises(ModelMissingError, match="missing"):
        load_verified_model("sface", models_dir=tmp_path)
    # Not a sticky integrity failure class.
    assert not issubclass(ModelMissingError, ModelIntegrityError)


def test_load_verified_model_sentinel_hash_refuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """PENDING_OPERATOR_FETCH sentinel never returns a path (no unresolved pins)."""
    file_name = "face_detection_yunet_2026may.onnx"
    _write_model(tmp_path, file_name, b"any-bytes")

    entry = _make_entry(
        file_name=file_name,
        sha256=PENDING_OPERATOR_FETCH,
        size_bytes=0,
        license_sha256=PENDING_OPERATOR_FETCH,
        source_ref="unresolved",
    )
    monkeypatch.setitem(MODEL_MANIFEST, "yunet", entry)

    with pytest.raises(ModelMissingError, match=PENDING_OPERATOR_FETCH):
        load_verified_model("yunet", models_dir=tmp_path)


def test_load_verified_model_unknown_name_raises(tmp_path: Path) -> None:
    """Unknown logical name is fail-closed (not KeyError)."""
    with pytest.raises(ModelIntegrityError, match="unknown model"):
        load_verified_model("not-a-model", models_dir=tmp_path)


def test_load_verified_model_missing_license_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Load-time license presence is fail-closed (local finding BR-04)."""
    payload = b"model-ok-bytes"
    file_name = "face_detection_yunet_2026may.onnx"
    _write_model(tmp_path, file_name, payload)
    entry = _make_entry(
        file_name=file_name,
        sha256=_sha256(payload),
        size_bytes=len(payload),
        license_file="LICENSE.yunet",
        license_payload=b"MIT",
    )
    monkeypatch.setitem(MODEL_MANIFEST, "yunet", entry)

    with pytest.raises(ModelMissingError, match="license file missing"):
        load_verified_model("yunet", models_dir=tmp_path)


def test_load_verified_model_license_hash_mismatch_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Load-time license hash mismatch is fail-closed (local finding BR-04)."""
    payload = b"model-ok-bytes"
    file_name = "face_detection_yunet_2026may.onnx"
    license_file = "LICENSE.yunet"
    _write_model(tmp_path, file_name, payload)
    _write_license(tmp_path, license_file, b"WRONG-LICENSE")
    entry = _make_entry(
        file_name=file_name,
        sha256=_sha256(payload),
        size_bytes=len(payload),
        license_file=license_file,
        license_payload=b"MIT",  # expected hash is MIT, on disk is WRONG
    )
    monkeypatch.setitem(MODEL_MANIFEST, "yunet", entry)

    with pytest.raises(ModelIntegrityError, match="license sha256 mismatch"):
        load_verified_model("yunet", models_dir=tmp_path)


def test_module_manifest_covers_yunet_and_sface() -> None:
    """Production manifest registers both models with required provenance fields."""
    assert set(MODEL_MANIFEST) == {"yunet", "sface"}
    for _key, entry in MODEL_MANIFEST.items():
        assert isinstance(entry, ModelProvenance)
        assert entry.file_name.endswith(".onnx")
        assert entry.source_url
        assert entry.source_ref
        assert entry.license_id
        assert entry.license_file
        assert entry.sha256  # real hex or PENDING sentinel
        assert entry.license_sha256
        assert entry.size_bytes >= 0
        assert entry.framework
        # Never invent: either 64-hex or explicit pending sentinel.
        assert entry.sha256 == PENDING_OPERATOR_FETCH or (
            len(entry.sha256) == 64 and all(c in "0123456789abcdef" for c in entry.sha256)
        )

    yunet = MODEL_MANIFEST["yunet"]
    assert yunet.embedding_dim is None
    assert yunet.normalization is None
    assert yunet.metric is None
    assert yunet.framework == "opencv"

    sface = MODEL_MANIFEST["sface"]
    assert sface.embedding_dim == 128
    assert sface.normalization == "l2"
    assert sface.metric == "cosine"
    assert sface.framework == "opencv"


def test_committed_license_files_match_manifest() -> None:
    """Offline: committed LICENSE.* sha256 must match production pins (local finding BR-04, no network)."""
    for name, entry in MODEL_MANIFEST.items():
        if entry.license_sha256 == PENDING_OPERATOR_FETCH:
            pytest.skip(f"{name} license still PENDING_OPERATOR_FETCH")
        license_path = DEFAULT_MODELS_DIR / entry.license_file
        assert license_path.is_file(), f"missing committed license: {license_path}"
        actual = _file_sha256(license_path)
        assert actual == entry.license_sha256, (
            f"{name}: {entry.license_file} sha256 {actual} != manifest {entry.license_sha256}"
        )


def test_face_pipeline_import_purity() -> None:
    """Fresh subprocess import must not load cv2/onnxruntime/fastapi/worker/api (local finding BR-06)."""
    code = """
import sys
import recognition.infrastructure.face_pipeline  # noqa: F401
import recognition.infrastructure.face_pipeline.provenance  # noqa: F401
forbidden_prefixes = (
    "cv2",
    "onnxruntime",
    "fastapi",
    "starlette",
    "recognition.worker",
    "recognition.api",
)
for name in list(sys.modules):
    for bad in forbidden_prefixes:
        if name == bad or name.startswith(bad + "."):
            raise SystemExit(f"forbidden import present: {name}")
print("ok")
"""
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(_SERVICE_ROOT) if not existing else f"{_SERVICE_ROOT}{os.pathsep}{existing}"
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(_SERVICE_ROOT),
        check=False,
    )
    assert result.returncode == 0, (
        f"import purity failed rc={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    assert "ok" in result.stdout


def _load_fetch_script() -> ModuleType:
    path = _SERVICE_ROOT / "scripts" / "fetch_face_pipeline_models.py"
    spec = importlib.util.spec_from_file_location("fetch_face_pipeline_models", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fetch_script_download_failure_is_actionable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every I/O call has a degrade path: download failure raises typed error (not silent)."""
    fetch = _load_fetch_script()

    def _boom(*args, **kwargs):  # noqa: ANN002, ANN003
        raise fetch.ModelFetchError("download failed: boom")

    monkeypatch.setattr(fetch, "download_verified", _boom)
    with pytest.raises(fetch.ModelFetchError, match="download failed"):
        fetch.fetch_all(dest_dir=tmp_path)


def test_fetch_script_verifies_against_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Successful download of matching bytes lands files; hash mismatch refuses."""
    fetch = _load_fetch_script()
    yunet = MODEL_MANIFEST["yunet"]
    # Only exercise when real hashes are pinned (not pending sentinel).
    if yunet.sha256 == PENDING_OPERATOR_FETCH:
        pytest.skip("manifest still PENDING_OPERATOR_FETCH; operator fetch required")

    payload = b"x" * 16  # wrong bytes relative to production hash

    def _write_wrong(url: str, dest: Path, **kwargs) -> None:  # noqa: ARG001
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(payload)

    monkeypatch.setattr(fetch, "download_verified", _write_wrong)
    with pytest.raises((fetch.ModelFetchError, ModelIntegrityError)):
        fetch.fetch_all(dest_dir=tmp_path, models=("yunet",))


def test_fetch_script_size_ok_sha256_mismatch_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Correct size_bytes + wrong sha256 hits the hash-mismatch branch (local finding BR-08 mutant guard)."""
    fetch = _load_fetch_script()
    yunet = MODEL_MANIFEST["yunet"]
    if yunet.sha256 == PENDING_OPERATOR_FETCH:
        pytest.skip("manifest still PENDING_OPERATOR_FETCH")

    wrong_payload = b"Z" * yunet.size_bytes  # size matches, content does not

    def _write_size_ok(url: str, dest: Path, **kwargs) -> None:  # noqa: ARG001
        # Mimic publish-after-verify internals: write partial, verify, fail, cleanup.
        partial = dest.with_suffix(dest.suffix + ".partial")
        dest.parent.mkdir(parents=True, exist_ok=True)
        partial.write_bytes(wrong_payload)
        try:
            expected_sha256 = kwargs.get("expected_sha256", "")
            expected_size = kwargs.get("expected_size")
            label = kwargs.get("label", "artifact")
            if expected_size is not None and expected_size > 0 and partial.stat().st_size != expected_size:
                raise fetch.ModelFetchError(
                    f"{label}: size mismatch for {partial.name}: expected {expected_size}, got {partial.stat().st_size}"
                )
            actual = _sha256(partial.read_bytes())
            if actual != expected_sha256:
                raise fetch.ModelFetchError(
                    f"{label}: sha256 mismatch for {partial.name}: expected {expected_sha256}, got {actual}"
                )
            partial.replace(dest)
        finally:
            if partial.exists():
                partial.unlink()

    monkeypatch.setattr(fetch, "download_verified", _write_size_ok)
    with pytest.raises(fetch.ModelFetchError, match="sha256 mismatch"):
        fetch.fetch_one("yunet", dest_dir=tmp_path)


def test_fetch_script_license_hash_mismatch_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """License hash-verify path in fetch refuses bad license bytes (local finding BR-08)."""
    fetch = _load_fetch_script()
    yunet = MODEL_MANIFEST["yunet"]
    if yunet.sha256 == PENDING_OPERATOR_FETCH:
        pytest.skip("manifest still PENDING_OPERATOR_FETCH")

    good_model = b"M" * yunet.size_bytes
    # Force model pin to match our synthetic bytes so we reach the license step.
    synthetic = _make_entry(
        file_name=yunet.file_name,
        sha256=_sha256(good_model),
        size_bytes=len(good_model),
        license_file=yunet.license_file,
        license_payload=b"EXPECTED-LICENSE-TEXT",
        framework=yunet.framework,
        embedding_dim=yunet.embedding_dim,
        normalization=yunet.normalization,
        metric=yunet.metric,
        source_url=yunet.source_url,
        source_ref=yunet.source_ref,
        license_id=yunet.license_id,
    )
    monkeypatch.setitem(MODEL_MANIFEST, "yunet", synthetic)
    # fetch script imported MODEL_MANIFEST by name from provenance — rebind on module.
    monkeypatch.setitem(fetch.MODEL_MANIFEST, "yunet", synthetic)

    call_count = {"n": 0}

    def _download(url: str, dest: Path, **kwargs) -> None:  # noqa: ARG001
        call_count["n"] += 1
        dest.parent.mkdir(parents=True, exist_ok=True)
        expected_sha256 = kwargs["expected_sha256"]
        label = kwargs.get("label", "artifact")
        if call_count["n"] == 1:
            # model — publish verified synthetic bytes
            dest.write_bytes(good_model)
            assert _sha256(dest.read_bytes()) == expected_sha256
            return
        # license — wrong bytes of any size → hash mismatch
        bad = b"WRONG-LICENSE-BYTES"
        actual = _sha256(bad)
        if actual != expected_sha256:
            raise fetch.ModelFetchError(
                f"{label}: sha256 mismatch for {dest.name}: expected {expected_sha256}, got {actual}"
            )
        dest.write_bytes(bad)

    monkeypatch.setattr(fetch, "download_verified", _download)
    with pytest.raises(fetch.ModelFetchError, match="sha256 mismatch"):
        fetch.fetch_one("yunet", dest_dir=tmp_path)
    # Model may be cleaned up; license must not have been force-written as wrong final.
    # (verify-before-publish: wrong license never published)


def test_fetch_failure_preserves_preexisting_license(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Mid-run model verify failure never unlinks pre-existing license files (local finding BR-01)."""
    fetch = _load_fetch_script()
    yunet = MODEL_MANIFEST["yunet"]
    if yunet.sha256 == PENDING_OPERATOR_FETCH:
        pytest.skip("manifest still PENDING_OPERATOR_FETCH")

    license_path = tmp_path / yunet.license_file
    preexisting = b"GIT-TRACKED-LICENSE-BYTES-DO-NOT-DELETE"
    license_path.write_bytes(preexisting)

    def _fail_model(url: str, dest: Path, **kwargs) -> None:  # noqa: ARG001
        # Simulate failed model verify: write partial-like junk then raise.
        dest.parent.mkdir(parents=True, exist_ok=True)
        junk = dest.with_suffix(dest.suffix + ".partial")
        junk.write_bytes(b"partial-junk")
        raise fetch.ModelFetchError(f"model 'yunet': sha256 mismatch for {junk.name}: expected x, got y")

    monkeypatch.setattr(fetch, "download_verified", _fail_model)
    with pytest.raises(fetch.ModelFetchError, match="sha256 mismatch"):
        fetch.fetch_one("yunet", dest_dir=tmp_path)

    assert license_path.is_file(), "pre-existing license must remain after fetch failure"
    assert license_path.read_bytes() == preexisting
    # Model final path must not remain from a failed run.
    assert not (tmp_path / yunet.file_name).exists()


def test_download_verified_over_cap_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Stream byte cap aborts with ModelFetchError (local finding BR-09)."""
    fetch = _load_fetch_script()
    dest = tmp_path / "cap.onnx"

    class _Resp:
        def __init__(self, data: bytes) -> None:
            self._data = data
            self._pos = 0

        def read(self, n: int = -1) -> bytes:
            if self._pos >= len(self._data):
                return b""
            if n < 0:
                chunk = self._data[self._pos :]
                self._pos = len(self._data)
                return chunk
            chunk = self._data[self._pos : self._pos + n]
            self._pos += len(chunk)
            return chunk

        def __enter__(self) -> _Resp:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    def _fake_urlopen(url: str, timeout: float = 0):  # noqa: ARG001
        return _Resp(b"x" * 1000)

    monkeypatch.setattr(fetch.urllib.request, "urlopen", _fake_urlopen)
    with pytest.raises(fetch.ModelFetchError, match="exceeded cap"):
        fetch.download_verified(
            "https://example.test/big.onnx",
            dest,
            expected_sha256="a" * 64,
            expected_size=1000,
            max_bytes=100,  # far below payload
            label="cap-test",
        )
    assert not dest.exists()
    assert not dest.with_suffix(dest.suffix + ".partial").exists()


# ---------------------------------------------------------------------------
# FIR-4 S5: --verify-only (no network; exit non-zero on missing/hash mismatch)
# ---------------------------------------------------------------------------


def test_verify_only_missing_model_raises(tmp_path: Path) -> None:
    """Empty dest → ModelFetchError (missing), no network."""
    fetch = _load_fetch_script()
    with pytest.raises(fetch.ModelFetchError):
        fetch.verify_only(dest_dir=tmp_path, models=("yunet",))


def test_verify_only_hash_mismatch_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Present file with wrong sha256 fails closed (no download)."""
    fetch = _load_fetch_script()
    yunet = MODEL_MANIFEST["yunet"]
    if yunet.sha256 == PENDING_OPERATOR_FETCH:
        pytest.skip("manifest still PENDING_OPERATOR_FETCH")

    # Wrong model bytes + a license that would pass if we only checked presence.
    bad_model = b"wrong-yunet-bytes"
    _write_model(tmp_path, yunet.file_name, bad_model)
    license_payload = b"synthetic-license"
    synthetic = _make_entry(
        file_name=yunet.file_name,
        sha256=_sha256(b"expected-correct-bytes"),  # deliberately not bad_model
        size_bytes=len(b"expected-correct-bytes"),
        license_file=yunet.license_file,
        license_payload=license_payload,
        framework=yunet.framework,
        embedding_dim=yunet.embedding_dim,
        normalization=yunet.normalization,
        metric=yunet.metric,
        source_url=yunet.source_url,
        source_ref=yunet.source_ref,
        license_id=yunet.license_id,
    )
    monkeypatch.setitem(MODEL_MANIFEST, "yunet", synthetic)
    monkeypatch.setitem(fetch.MODEL_MANIFEST, "yunet", synthetic)
    _write_license(tmp_path, yunet.license_file, license_payload)

    with pytest.raises(fetch.ModelFetchError):
        fetch.verify_only(dest_dir=tmp_path, models=("yunet",))


def test_verify_only_happy_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Matching model + license returns paths; main --verify-only exits 0."""
    fetch = _load_fetch_script()
    payload = b"verified-yunet-v1"
    license_payload = b"MIT-ok"
    file_name = "face_detection_yunet_2026may.onnx"
    license_file = "LICENSE.yunet"
    entry = _make_entry(
        file_name=file_name,
        sha256=_sha256(payload),
        size_bytes=len(payload),
        license_file=license_file,
        license_payload=license_payload,
        framework="opencv",
        embedding_dim=None,
    )
    monkeypatch.setitem(MODEL_MANIFEST, "yunet", entry)
    monkeypatch.setitem(fetch.MODEL_MANIFEST, "yunet", entry)
    _write_model(tmp_path, file_name, payload)
    _write_license(tmp_path, license_file, license_payload)

    paths = fetch.verify_only(dest_dir=tmp_path, models=("yunet",))
    assert len(paths) == 1
    assert paths[0].name == file_name

    rc = fetch.main(["--dest", str(tmp_path), "--models", "yunet", "--verify-only"])
    assert rc == 0


def test_verify_only_main_exit_nonzero_on_missing(tmp_path: Path) -> None:
    """CLI --verify-only returns 1 when models are absent (no network)."""
    fetch = _load_fetch_script()
    rc = fetch.main(["--dest", str(tmp_path), "--models", "yunet", "--verify-only"])
    assert rc == 1


def test_verify_only_license_mismatch_raises_no_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S5CR-05: valid model bytes + wrong license_sha256 → verify fails, no network."""
    fetch = _load_fetch_script()

    def _network_forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("verify-only must not call urlopen / network")

    # Patch wherever the fetch script would reach the network.
    monkeypatch.setattr(fetch.urllib.request, "urlopen", _network_forbidden)

    payload = b"verified-yunet-license-mismatch"
    license_payload = b"actual-license-bytes"
    file_name = "face_detection_yunet_2026may.onnx"
    license_file = "LICENSE.yunet"
    entry = _make_entry(
        file_name=file_name,
        sha256=_sha256(payload),
        size_bytes=len(payload),
        license_file=license_file,
        license_payload=license_payload,
        license_sha256="a" * 64,  # wrong on purpose
        framework="opencv",
        embedding_dim=None,
    )
    monkeypatch.setitem(MODEL_MANIFEST, "yunet", entry)
    monkeypatch.setitem(fetch.MODEL_MANIFEST, "yunet", entry)
    _write_model(tmp_path, file_name, payload)
    _write_license(tmp_path, license_file, license_payload)

    with pytest.raises(fetch.ModelFetchError):
        fetch.verify_only(dest_dir=tmp_path, models=("yunet",))

    rc = fetch.main(["--dest", str(tmp_path), "--models", "yunet", "--verify-only"])
    assert rc == 1


# ---------------------------------------------------------------------------
# numeric_runtime_fingerprint (CVUP-1 findings LC-02 / HARM-01 / HARM-02)
# ---------------------------------------------------------------------------


def test_numeric_runtime_fingerprint_reads_live_versions(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fingerprint is a pure function of installed package version sources."""
    from recognition.infrastructure.face_pipeline import provenance as prov

    monkeypatch.setattr(prov, "_opencv_version", lambda: "5.0.0")
    monkeypatch.setattr(prov, "_onnxruntime_version", lambda: "1.28.0")
    monkeypatch.setattr(prov, "_numpy_version", lambda: "2.5.1")

    fp = prov.numeric_runtime_fingerprint()
    assert fp.opencv_version == "5.0.0"
    assert fp.opencv_major == 5
    assert fp.onnxruntime_version == "1.28.0"
    assert fp.numpy_version == "2.5.1"
    # OpenCV full version + ORT major.minor (patch omitted — see space_token WHY).
    assert fp.space_token == "cv5.0.0/ort1.28"
    assert "opencv=5.0.0" in fp.compact
    assert "onnxruntime=1.28.0" in fp.compact
    assert "numpy=2.5.1" in fp.compact

    # Monkeypatch change must re-read (no process-global cache of literals).
    monkeypatch.setattr(prov, "_opencv_version", lambda: "4.13.0.92")
    monkeypatch.setattr(prov, "_onnxruntime_version", lambda: "1.22.0")
    monkeypatch.setattr(prov, "_numpy_version", lambda: "2.0.0")
    fp2 = prov.numeric_runtime_fingerprint()
    assert fp2.opencv_major == 4
    assert fp2.space_token == "cv4.13.0.92/ort1.22"
    assert fp2.compact != fp.compact


def test_numeric_runtime_fingerprint_exported_from_package() -> None:
    """Canonical symbol is importable from the face_pipeline package root."""
    from recognition.infrastructure.face_pipeline import (
        NumericRuntimeFingerprint,
        numeric_runtime_fingerprint,
    )

    fp = numeric_runtime_fingerprint()
    assert isinstance(fp, NumericRuntimeFingerprint)
    assert fp.opencv_major >= 1
    assert fp.onnxruntime_version
    assert fp.numpy_version


def test_sface_model_id_differs_across_opencv_version(monkeypatch: pytest.MonkeyPatch) -> None:
    """OpenCV full version alone must flip the SFace embedding-space model_id."""
    from recognition.infrastructure.embeddings import face_pipeline_adapter as fpa
    from recognition.infrastructure.face_pipeline import provenance as prov

    monkeypatch.setattr(prov, "_opencv_version", lambda: "5.0.0")
    monkeypatch.setattr(prov, "_onnxruntime_version", lambda: "1.28.0")
    monkeypatch.setattr(prov, "_numpy_version", lambda: "2.5.1")
    id_cv5 = fpa.sface_embedding_model_manifest().model_id

    monkeypatch.setattr(prov, "_opencv_version", lambda: "4.13.0.92")
    id_cv4 = fpa.sface_embedding_model_manifest().model_id

    assert id_cv5 != id_cv4
    assert "cv5.0.0/" in id_cv5
    assert "cv4.13.0.92/" in id_cv4
    assert id_cv5.endswith("@128d/l2/cosine")
    assert id_cv4.endswith("@128d/l2/cosine")

    # Intra-major OpenCV bump must also partition (full-version space key).
    monkeypatch.setattr(prov, "_opencv_version", lambda: "5.1.0")
    id_cv51 = fpa.sface_embedding_model_manifest().model_id
    assert id_cv51 != id_cv5
    assert "cv5.1.0/" in id_cv51


def test_sface_model_id_differs_across_onnxruntime_minor(monkeypatch: pytest.MonkeyPatch) -> None:
    """onnxruntime major.minor alone must flip the SFace embedding-space model_id."""
    from recognition.infrastructure.embeddings import face_pipeline_adapter as fpa
    from recognition.infrastructure.face_pipeline import provenance as prov

    monkeypatch.setattr(prov, "_opencv_version", lambda: "5.0.0")
    monkeypatch.setattr(prov, "_onnxruntime_version", lambda: "1.28.0")
    monkeypatch.setattr(prov, "_numpy_version", lambda: "2.5.1")
    id_ort_new = fpa.sface_embedding_model_manifest().model_id

    monkeypatch.setattr(prov, "_onnxruntime_version", lambda: "1.22.0")
    id_ort_old = fpa.sface_embedding_model_manifest().model_id

    assert id_ort_new != id_ort_old
    assert "ort1.28" in id_ort_new
    assert "ort1.22" in id_ort_old
    # Same OpenCV full version — only ORT minor moved.
    assert "cv5.0.0/" in id_ort_new and "cv5.0.0/" in id_ort_old

    # ORT patch alone must NOT partition (same major.minor → same space).
    monkeypatch.setattr(prov, "_onnxruntime_version", lambda: "1.28.1")
    id_ort_patch = fpa.sface_embedding_model_manifest().model_id
    assert id_ort_patch == id_ort_new
