"""C76 ABI-11 source/build and identity-only repair contracts, no image calls.

All identities here are synthetic test data; no pin is a loaded observation.
PROV-01: https://github.com/darce/heuristics-canon/blob/v0.25.6/lexicons/ml-systems.md#prov-01
"""
from __future__ import annotations

import ast
import dataclasses
import importlib.util
import json
import posixpath
import shlex
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
BAKED_IDENTITY_LOADER = None  # C-10: parent has not frozen the loader symbol/signature.
IMAGE_FIELDS = {"role", "registry_manifest_digest", "digest_type", "platform",
                "image_config_digest", "identity_document_sha256"}


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


def test_baked_loader_refuses_conflicting_environment(monkeypatch, tmp_path):
    if BAKED_IDENTITY_LOADER is None:
        pytest.skip("C-10 / ABI-11: baked identity loader name and signature not frozen by parent")
    loader = getattr(module(), BAKED_IDENTITY_LOADER, None)
    assert callable(loader), "CAUSAL_RED: frozen baked identity loader is missing"
    path = tmp_path / ".source-identity.json"
    path.write_text(json.dumps(identity_args()))
    monkeypatch.delenv("GIT_COMMIT_SHA", raising=False)
    monkeypatch.delenv("APP_GIT_COMMIT_SHA", raising=False)
    assert plain(loader(path)) == identity_args()
    for variable in ("GIT_COMMIT_SHA", "APP_GIT_COMMIT_SHA"):
        with monkeypatch.context() as conflict:
            conflict.setenv(variable, "fixture-conflicting-source")
            with pytest.raises((ValueError, TypeError)):
                loader(path)


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


def docker_instructions(source):
    """Join physical continuations before interpreting instruction arguments."""
    escape = "\\"
    pending = []
    for raw in source.splitlines():
        line = raw.strip()
        if not pending and line.lower().startswith("# escape="):
            escape = line.split("=", 1)[1].strip()
        if not line or line.startswith("#"):
            continue
        continued = line.endswith(escape)
        pending.append(line[:-len(escape)].rstrip() if continued else line)
        if not continued:
            parts = " ".join(pending).split(maxsplit=1)
            instruction, arguments = parts[0], parts[1] if len(parts) == 2 else ""
            yield instruction.upper(), arguments.strip()
            pending = []
    assert not pending, "fixture: unterminated Dockerfile continuation"


def instruction_destination(instruction, arguments, workdir):
    if instruction in {"COPY", "ADD"}:
        # Flags precede both shell-form and JSON-form operands.
        while arguments.startswith("--"):
            _, _, arguments = arguments.partition(" ")
            arguments = arguments.lstrip()
        operands = json.loads(arguments) if arguments.startswith("[") else shlex.split(arguments)
        if len(operands) < 2:
            return None
        destination = operands[-1]
        if destination.endswith("/"):
            if len(operands) != 2:
                return None
            destination = posixpath.join(destination, posixpath.basename(operands[0]))
    elif instruction == "RUN":
        # An output operand/redirection is evidence of a write; echoing a path is not.
        lexer = shlex.shlex(arguments, posix=True, punctuation_chars=";&|<>")
        lexer.whitespace_split = True
        tokens = list(lexer)
        destinations = [tokens[index + 1] for index, token in enumerate(tokens[:-1])
                        if token in {">", ">>"}]
        for index, token in enumerate(tokens):
            if token not in {"cp", "mv", "install"}:
                continue
            end = next((i for i in range(index + 1, len(tokens)) if tokens[i] in {"&&", ";", "||"}), len(tokens))
            if end > index + 2:
                destinations.append(tokens[end - 1])
        return next((posixpath.normpath(posixpath.join(workdir, path))
                     for path in destinations
                     if posixpath.normpath(posixpath.join(workdir, path)) == "/app/.source-identity.json"), None)
    else:
        return None
    return posixpath.normpath(posixpath.join(workdir, destination))


def assert_runtime_identity_baked(source):
    stages = {}
    stage = None
    for instruction, arguments in docker_instructions(source):
        if instruction == "FROM":
            tokens = shlex.split(arguments)
            tokens = [token for token in tokens if not token.startswith("--")]
            base = tokens[0].lower()
            name = tokens[2].lower() if len(tokens) == 3 and tokens[1].upper() == "AS" else str(len(stages))
            inherited = stages.get(base, {"workdir": "/", "baked": False})
            stage = dict(inherited)
            stages[name] = stage
        elif stage is not None:
            if instruction == "WORKDIR":
                stage["workdir"] = posixpath.normpath(posixpath.join(stage["workdir"], arguments))
            elif instruction_destination(instruction, arguments, stage["workdir"]) == "/app/.source-identity.json":
                stage["baked"] = True
    for name in ("runtime", "runtime-vlm"):
        assert name in stages and stages[name]["baked"], (
            f"CAUSAL_RED: {name} has no baked /app/.source-identity.json destination (ABI-11)")


def test_runtime_image_bakes_identity_document_instead_of_only_env_sha():
    assert_runtime_identity_baked((ROOT / "Dockerfile").read_text())


@pytest.mark.parametrize("copy", [
    "COPY identity.json /app/.source-identity.json",
    "COPY identity.json \\\n    /app/.source-identity.json",
    'COPY ["identity.json", "/app/.source-identity.json"]',
    "RUN printf 'fixture-only' > /app/.source-identity.json",
])
def test_dockerfile_identity_oracle_accepts_logical_destination_inherited_by_both_targets(copy):
    assert_runtime_identity_baked(f"FROM fixture AS runtime-base\n{copy}\nFROM runtime-base AS runtime-vlm\nFROM runtime-base AS runtime\n")


@pytest.mark.parametrize("decoy", [
    "RUN echo .source-identity.json > /dev/null",
    "RUN echo /app/.source-identity.json",
    "COPY identity.json /tmp/.source-identity.json",
    "# COPY identity.json /app/.source-identity.json",
])
def test_dockerfile_identity_oracle_rejects_mentions_and_wrong_destinations(decoy):
    with pytest.raises(AssertionError, match="CAUSAL_RED"):
        assert_runtime_identity_baked(f"FROM fixture AS runtime-base\n{decoy}\nFROM runtime-base AS runtime-vlm\nFROM runtime-base AS runtime\n")


def test_dockerfile_identity_oracle_rejects_baking_only_in_builder_or_one_target():
    for source in (
        "FROM fixture AS builder\nCOPY identity.json /app/.source-identity.json\n"
        "FROM fixture AS runtime-vlm\nFROM fixture AS runtime\n",
        "FROM fixture AS runtime-vlm\nCOPY identity.json /app/.source-identity.json\nFROM fixture AS runtime\n",
    ):
        with pytest.raises(AssertionError, match="CAUSAL_RED"):
            assert_runtime_identity_baked(source)


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
    assert set(result["image_record"]) == IMAGE_FIELDS


@pytest.mark.parametrize("field", sorted(LOADED_FIELDS))
def test_repair_identity_rejects_every_loaded_or_serving_field(field):
    cls = getattr(module("face_role_snapshot"), "RepairIdentityRecordV1", None)
    assert callable(cls), "CAUSAL_RED: missing RepairIdentityRecordV1 (ABI-11)"
    with pytest.raises((ValueError, TypeError)):
        cls(producer_abi_version=1, role="fix-blob-ownership",
            captured_at=datetime(2026, 1, 1, tzinfo=UTC), repair_invocation_id="repair-run",
            source_identity=identity_type()(**identity_args()), image_record=None,
            collection_status="incomplete", reason_code="image_missing", **{field: "fabricated"})


@pytest.mark.parametrize("field", sorted(LOADED_FIELDS | {"unknown_image_extension"}))
def test_repair_image_record_rejects_nested_loaded_or_serving_fields(field):
    cls = getattr(module("face_role_snapshot"), "RepairIdentityRecordV1", None)
    assert callable(cls), "CAUSAL_RED: missing RepairIdentityRecordV1 (ABI-11)"
    image = dict(role="fix-blob-ownership", registry_manifest_digest="sha256:" + "6" * 64,
                 digest_type="manifest", platform="linux/amd64", image_config_digest="sha256:" + "7" * 64,
                 identity_document_sha256="5" * 64)
    image[field] = "fabricated"
    with pytest.raises((ValueError, TypeError)):
        cls(producer_abi_version=1, role="fix-blob-ownership",
            captured_at=datetime(2026, 1, 1, tzinfo=UTC), repair_invocation_id="repair-run",
            source_identity=identity_type()(**identity_args()), image_record=image,
            collection_status="complete", reason_code=None)


def test_synthetic_identity_fixture_has_all_frozen_fields():
    assert set(identity_args()) == FIELDS
    assert len(identity_args()["source_git_sha"]) == 40
    assert len(identity_args()["identity_document_sha256"]) == 64
