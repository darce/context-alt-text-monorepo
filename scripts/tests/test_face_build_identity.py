"""C76 ABI-11 source/build and identity-only repair contracts, no image calls.

All identities here are synthetic test data; no pin is a loaded observation.
PROV-01: https://github.com/darce/heuristics-canon/blob/v0.25.6/lexicons/ml-systems.md#prov-01
"""
from __future__ import annotations

import ast
import dataclasses
import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / "apps/prototype-description-service"
FIELDS = {"source_identity_version", "source_git_sha", "source_tree",
          "build_context_manifest_sha256", "service_lock_sha256", "image_variant",
          "build_time", "identity_document_sha256"}
LOADED_FIELDS = {"model_id", "profile", "effective_profile", "embedding_dimension",
                 "declared_embedding_dimension", "observed_embedding_dimension",
                 "loaded_weight_hashes", "loaded_license_hashes", "sessions",
                 "runtime_generation_id", "preprocessing_contract", "adapter_observations",
                 "execution_receipt", "serving_catalog", "auth", "database", "effective_settings"}


def module(name="source_identity"):
    path = ROOT / f"shared/{name}.py"
    assert path.is_file(), f"CAUSAL_RED: missing shared/{name}.py (ABI-11)"
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    spec = importlib.util.spec_from_file_location(f"shared.{name}", path)
    result = importlib.util.module_from_spec(spec)
    # dataclasses resolve their defining module from sys.modules.
    sys.modules[spec.name] = result
    spec.loader.exec_module(result)
    return result


def plain(value):
    if dataclasses.is_dataclass(value):
        return plain(dataclasses.asdict(value))
    if isinstance(value, dict):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "model_dump"):
        return plain(value.model_dump())
    return value


def identity_args():
    return dict(source_identity_version=1, source_git_sha="1" * 40, source_tree="2" * 40,
                build_context_manifest_sha256="3" * 64, service_lock_sha256="4" * 64,
                image_variant="recognition", build_time="2026-01-01T00:00:00Z",
                identity_document_sha256="5" * 64)


def identity_type():
    result = getattr(module(), "SourceIdentityV1", None)
    assert callable(result), "CAUSAL_RED: missing SourceIdentityV1 (ABI-11)"
    return result


def test_positive_baked_identity_preserves_distinct_source_and_tree(monkeypatch):
    cls = identity_type()
    monkeypatch.setenv("GIT_COMMIT_SHA", "runtime-override")
    result = plain(cls(**identity_args()))
    assert set(result) == FIELDS
    assert result == identity_args()
    assert result["source_git_sha"] != result["source_tree"]
    assert "runtime-override" not in json.dumps(result)


@pytest.mark.parametrize("version", [None, True, "1", 0, 2])
def test_source_identity_version_is_closed(version):
    cls = identity_type()
    args = identity_args()
    args["source_identity_version"] = version
    with pytest.raises((ValueError, TypeError)):
        cls(**args)


@pytest.mark.parametrize("field", ["source_tree", "build_context_manifest_sha256", "service_lock_sha256"])
def test_missing_build_binding_cannot_form_complete_identity(field):
    cls = identity_type()
    args = identity_args()
    del args[field]
    with pytest.raises((ValueError, TypeError)):
        cls(**args)


def test_identity_excludes_unknown_runtime_configuration():
    cls = identity_type()
    with pytest.raises((ValueError, TypeError)):
        cls(**identity_args(), raw_environment={"uncontrolled": "REJECTED_SENTINEL"})


def test_source_identity_never_invokes_runtime_git():
    module()
    node = ast.parse((ROOT / "shared/source_identity.py").read_text())
    forbidden_imports = {"subprocess", "git", "dulwich", "pygit2"}
    imports = {n.name.split(".")[0] for p in ast.walk(node) if isinstance(p, ast.Import) for n in p.names}
    imports |= {p.module.split(".")[0] for p in ast.walk(node) if isinstance(p, ast.ImportFrom) and p.module}
    assert not imports & forbidden_imports
    forbidden_calls = {"system", "popen", "spawn", "execv", "execve"}
    assert not {n.func.attr for n in ast.walk(node) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)} & forbidden_calls


def test_runtime_image_bakes_identity_document_instead_of_only_env_sha():
    lines = (ROOT / "Dockerfile").read_text().splitlines()
    instructions = "\n".join(line for line in lines if not line.lstrip().startswith("#"))
    assert ".source-identity.json" in instructions, "CAUSAL_RED: no baked /app/.source-identity.json (ABI-11)"
    assert any(line.lstrip().startswith(("COPY", "RUN")) and ".source-identity.json" in line for line in lines)


def test_positive_repair_identity_carries_only_identity_metadata():
    source = identity_type()(**identity_args())
    cls = getattr(module("face_role_snapshot"), "RepairIdentityRecordV1", None)
    assert callable(cls), "CAUSAL_RED: missing RepairIdentityRecordV1 (ABI-11)"
    image = dict(role="fix-blob-ownership", registry_manifest_digest="sha256:" + "6" * 64,
                 digest_type="manifest", platform="linux/amd64", image_config_digest="sha256:" + "7" * 64,
                 identity_document_sha256="5" * 64)
    result = plain(cls(producer_abi_version=1, role="fix-blob-ownership",
                       captured_at=datetime(2026, 1, 1, tzinfo=UTC), repair_invocation_id="repair-run",
                       source_identity=source, image_record=image,
                       collection_status="complete", reason_code=None))
    assert result["role"] == "fix-blob-ownership"
    assert result["source_identity"]["source_git_sha"] == "1" * 40
    assert result["image_record"]["registry_manifest_digest"] == "sha256:" + "6" * 64
    assert not set(result) & LOADED_FIELDS


@pytest.mark.parametrize("field", sorted(LOADED_FIELDS))
def test_repair_identity_rejects_every_loaded_or_serving_field(field):
    cls = getattr(module("face_role_snapshot"), "RepairIdentityRecordV1", None)
    assert callable(cls), "CAUSAL_RED: missing RepairIdentityRecordV1 (ABI-11)"
    with pytest.raises((ValueError, TypeError)):
        cls(producer_abi_version=1, role="fix-blob-ownership",
            captured_at=datetime(2026, 1, 1, tzinfo=UTC), repair_invocation_id="repair-run",
            source_identity=identity_type()(**identity_args()), image_record=None,
            collection_status="incomplete", reason_code="image_missing", **{field: "fabricated"})


def test_synthetic_identity_fixture_has_all_frozen_fields():
    assert set(identity_args()) == FIELDS
    assert len(identity_args()["source_git_sha"]) == 40
    assert len(identity_args()["identity_document_sha256"]) == 64
