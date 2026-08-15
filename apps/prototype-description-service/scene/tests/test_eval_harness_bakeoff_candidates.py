"""VLM-6 S2a-1: bakeoff_candidates.yaml fail-fast validator."""

from __future__ import annotations

import os
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import yaml

from scripts.eval_harness.bakeoff_candidates import (
    QWEN38_ARTIFACT_GB,
    QWEN38_QUANT,
    QWEN38_ROW_ID,
    RETIRED_QWEN36_ROW_ID,
    SCHEMA,
    SEALED_CANDIDATE_COUNT,
    SEALED_INCUMBENT_COUNT,
    BakeoffTier,
    CandidateRole,
    RegistryError,
    RevisionVerifyError,
    ServingStack,
    default_registry_path,
    load_bakeoff_candidates,
    main,
    verify_revisions,
)

REGISTRY_PATH = default_registry_path()


@pytest.fixture(scope="module")
def raw_registry() -> dict[str, Any]:
    return yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def registry():
    return load_bakeoff_candidates(REGISTRY_PATH)


def _write_registry(tmp_path: Path, payload: dict[str, Any]) -> Path:
    path = tmp_path / "bakeoff_candidates.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def test_committed_registry_loads(registry) -> None:
    assert registry.schema_id == SCHEMA
    assert registry.task_ref == "VLM-6"
    assert len(registry.entries) == SEALED_CANDIDATE_COUNT + SEALED_INCUMBENT_COUNT


def test_sealed_counts_are_exact(registry) -> None:
    n_cand = sum(1 for e in registry.entries if e.role is CandidateRole.CANDIDATE)
    n_inc = sum(1 for e in registry.entries if e.role is CandidateRole.INCUMBENT)
    assert n_cand == SEALED_CANDIDATE_COUNT == 13
    assert n_inc == SEALED_INCUMBENT_COUNT == 2
    assert registry.sealed.candidates == 13
    assert registry.sealed.incumbent_anchors == 2


def test_qwen38_replaces_qwen36_row(registry) -> None:
    ids = [e.id for e in registry.entries]
    assert QWEN38_ROW_ID in ids
    assert RETIRED_QWEN36_ROW_ID not in ids
    row = next(e for e in registry.entries if e.id == QWEN38_ROW_ID)
    assert row.model_id == "Qwen3.8-27B"
    assert row.quant == QWEN38_QUANT
    assert row.artifact_gb == QWEN38_ARTIFACT_GB
    assert row.artifact == "Qwen3.8-27B-UD-Q4_K_XL.gguf"
    assert row.recipe.stack is ServingStack.LLAMA_CPP
    assert row.recipe.gguf == row.artifact
    assert row.recipe.mmproj == "mmproj-F16.gguf"
    assert row.revision == "1cff334a4a228324d4ee1f76d55d372588f0d556"


def test_every_entry_has_pin_recipe_tier(registry) -> None:
    for entry in registry.entries:
        assert len(entry.revision) == 40
        assert entry.recipe.stack in ServingStack
        assert entry.recipe.ctx_size > 0
        assert entry.tiers
        assert entry.prompt_template == "v3"
        assert entry.license


def test_incumbent_ids_and_florence_pin(registry) -> None:
    incumbents = {e.id: e for e in registry.entries if e.role is CandidateRole.INCUMBENT}
    assert set(incumbents) == {"florence-2-base-ft", "qwen3-vl-30b-a3b"}
    florence = incumbents["florence-2-base-ft"]
    assert florence.revision == "f6c1a25888ffc1d945ee8a1a77ac833c7303d46e"
    assert florence.competing is False
    assert BakeoffTier.CPU_INLINE in florence.tiers


def test_unique_ids(registry) -> None:
    ids = [e.id for e in registry.entries]
    assert len(ids) == len(set(ids))


def test_cli_prints_sealed_counts(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(REGISTRY_PATH)]) == 0
    assert capsys.readouterr().out.strip() == "ok: 13 candidates + 2 incumbent anchors"


def test_missing_file_fails(tmp_path: Path) -> None:
    with pytest.raises(RegistryError, match="not found"):
        load_bakeoff_candidates(tmp_path / "missing.yaml")


def test_malformed_yaml_fails(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text(":\n  - [", encoding="utf-8")
    with pytest.raises(RegistryError, match="malformed YAML"):
        load_bakeoff_candidates(path)


def test_unknown_field_fails(tmp_path: Path, raw_registry: dict[str, Any]) -> None:
    payload = deepcopy(raw_registry)
    payload["entries"][0]["unexpected"] = True
    with pytest.raises(RegistryError, match="schema violation"):
        load_bakeoff_candidates(_write_registry(tmp_path, payload))


def test_missing_revision_fails(tmp_path: Path, raw_registry: dict[str, Any]) -> None:
    payload = deepcopy(raw_registry)
    del payload["entries"][0]["revision"]
    with pytest.raises(RegistryError, match="schema violation"):
        load_bakeoff_candidates(_write_registry(tmp_path, payload))


def test_unpinned_revision_fails(tmp_path: Path, raw_registry: dict[str, Any]) -> None:
    payload = deepcopy(raw_registry)
    payload["entries"][0]["revision"] = "main"
    with pytest.raises(RegistryError, match="40-char lowercase hex SHA"):
        load_bakeoff_candidates(_write_registry(tmp_path, payload))


def test_todo_artifact_fails(tmp_path: Path, raw_registry: dict[str, Any]) -> None:
    payload = deepcopy(raw_registry)
    payload["entries"][0]["artifact"] = "<TODO MiniCPM GGUF url>"
    with pytest.raises(RegistryError, match="TODO placeholder"):
        load_bakeoff_candidates(_write_registry(tmp_path, payload))


def test_llama_cpp_missing_mmproj_fails(tmp_path: Path, raw_registry: dict[str, Any]) -> None:
    payload = deepcopy(raw_registry)
    row = next(e for e in payload["entries"] if e["id"] == QWEN38_ROW_ID)
    row["recipe"]["mmproj"] = None
    with pytest.raises(RegistryError, match="gguf and mmproj"):
        load_bakeoff_candidates(_write_registry(tmp_path, payload))


def test_wrong_candidate_count_fails(tmp_path: Path, raw_registry: dict[str, Any]) -> None:
    payload = deepcopy(raw_registry)
    payload["entries"] = [e for e in payload["entries"] if e["id"] != "ovis2-8b"]
    with pytest.raises(RegistryError, match="expected 13 candidates, found 12"):
        load_bakeoff_candidates(_write_registry(tmp_path, payload))


def test_duplicate_id_fails(tmp_path: Path, raw_registry: dict[str, Any]) -> None:
    payload = deepcopy(raw_registry)
    payload["entries"][1]["id"] = payload["entries"][0]["id"]
    with pytest.raises(RegistryError, match="duplicate candidate id"):
        load_bakeoff_candidates(_write_registry(tmp_path, payload))


def test_restoring_qwen36_row_fails(tmp_path: Path, raw_registry: dict[str, Any]) -> None:
    payload = deepcopy(raw_registry)
    row = next(e for e in payload["entries"] if e["id"] == QWEN38_ROW_ID)
    row["id"] = RETIRED_QWEN36_ROW_ID
    with pytest.raises(RegistryError, match="retired"):
        load_bakeoff_candidates(_write_registry(tmp_path, payload))


# Rows whose vision floor is unpublished in
# infra/oci/incidents/a10-multimodel-bakeoff.sh:11-14 (rg-015: do not invent).
# phi4-mm is listed because this repo documents no vLLM version anywhere.
_MIN_RUNTIME_BUILD_EXCEPTIONS = frozenset(
    {
        "minicpm-v-45",
        "minicpm-v-46",
        "kimi-vl-a3b",
        "gemma-4-12b",
        "phi4-mm",
    }
)


def test_llama_cpp_min_runtime_build_or_documented_exception(registry) -> None:
    by_id = {entry.id: entry for entry in registry.entries}
    for exception_id in _MIN_RUNTIME_BUILD_EXCEPTIONS:
        assert exception_id in by_id
        assert by_id[exception_id].recipe.min_runtime_build is None
    for entry in registry.entries:
        if entry.recipe.stack is ServingStack.LLAMA_CPP and entry.recipe.min_runtime_build is None:
            assert entry.id in _MIN_RUNTIME_BUILD_EXCEPTIONS
        if entry.recipe.min_runtime_build is None:
            continue
        pin = entry.recipe.min_runtime_build.lower()
        assert "todo" not in pin
        assert "tbd" not in pin
        if entry.recipe.stack is ServingStack.LLAMA_CPP:
            assert pin.startswith("b") and pin[1:].isdigit()
        elif entry.recipe.stack is ServingStack.VLLM:
            assert pin[0].isdigit()


def test_qwen_min_runtime_build_matches_incident_source(registry) -> None:
    qwen_vl = next(e for e in registry.entries if e.id == "qwen3-vl-30b-a3b")
    assert qwen_vl.recipe.min_runtime_build == "b6887"
    assert qwen_vl.recipe.min_runtime_build_is_lower_bound is False
    qwen38 = next(e for e in registry.entries if e.id == QWEN38_ROW_ID)
    assert qwen38.recipe.min_runtime_build == "b6887"
    assert qwen38.recipe.min_runtime_build_is_lower_bound is True


def test_min_runtime_build_todo_rejected(
    tmp_path: Path, raw_registry: dict[str, Any]
) -> None:
    payload = deepcopy(raw_registry)
    row = next(e for e in payload["entries"] if e["id"] == "qwen3-vl-30b-a3b")
    row["recipe"]["min_runtime_build"] = "TODO-b6887"
    with pytest.raises(RegistryError, match="TODO placeholder"):
        load_bakeoff_candidates(_write_registry(tmp_path, payload))


def test_min_runtime_build_tbd_rejected(
    tmp_path: Path, raw_registry: dict[str, Any]
) -> None:
    payload = deepcopy(raw_registry)
    row = next(e for e in payload["entries"] if e["id"] == "qwen3-vl-30b-a3b")
    row["recipe"]["min_runtime_build"] = "tbd"
    with pytest.raises(RegistryError, match="TODO placeholder"):
        load_bakeoff_candidates(_write_registry(tmp_path, payload))


def test_min_runtime_build_prose_rejected(
    tmp_path: Path, raw_registry: dict[str, Any]
) -> None:
    payload = deepcopy(raw_registry)
    row = next(e for e in payload["entries"] if e["id"] == QWEN38_ROW_ID)
    row["recipe"]["min_runtime_build"] = "newer than b6887"
    row["recipe"].pop("min_runtime_build_is_lower_bound", None)
    with pytest.raises(RegistryError, match="newer than b6887"):
        load_bakeoff_candidates(_write_registry(tmp_path, payload))


def test_default_load_does_not_import_huggingface_hub() -> None:
    sys.modules.pop("huggingface_hub", None)
    load_bakeoff_candidates()
    assert "huggingface_hub" not in sys.modules
    assert main([]) == 0
    assert "huggingface_hub" not in sys.modules


def test_cli_help_includes_verify_revisions(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    assert exc_info.value.code == 0
    assert "--verify-revisions" in capsys.readouterr().out


def test_verify_revisions_accepts_sibling_artifacts(registry) -> None:
    def list_files(repo: str, revision: str) -> list[str]:
        entry = next(e for e in registry.entries if e.repo == repo and e.revision == revision)
        names = ["config.json"]
        if entry.recipe.gguf:
            names.append(f"weights/{entry.recipe.gguf}")
        if entry.recipe.mmproj:
            names.append(f"weights/{entry.recipe.mmproj}")
        return names

    results = verify_revisions(registry, list_files=list_files)
    assert [entry_id for entry_id, _ok, _detail in results] == [e.id for e in registry.entries]
    assert all(ok for _entry_id, ok, _detail in results)


def test_verify_revisions_rejects_missing_or_split_artifacts(registry) -> None:
    def list_files(repo: str, revision: str) -> list[str]:
        entry = next(e for e in registry.entries if e.repo == repo and e.revision == revision)
        if entry.recipe.gguf and entry.recipe.mmproj:
            return [entry.recipe.gguf, f"other/{entry.recipe.mmproj}"]
        return []

    results = {entry_id: (ok, detail) for entry_id, ok, detail in verify_revisions(registry, list_files=list_files)}
    llama = next(e for e in registry.entries if e.recipe.stack is ServingStack.LLAMA_CPP)
    ok, detail = results[llama.id]
    assert ok is False
    assert "missing sibling artifacts" in detail
    non_llama = next(e for e in registry.entries if e.recipe.stack is not ServingStack.LLAMA_CPP)
    assert results[non_llama.id][0] is True


def test_verify_revisions_reports_unresolved_revision(registry) -> None:
    def list_files(repo: str, revision: str) -> list[str]:
        raise RuntimeError("revision not found")

    results = verify_revisions(registry, list_files=list_files)
    assert results
    assert all(ok is False for _entry_id, ok, _detail in results)
    assert all("unresolved" in detail for _entry_id, _ok, detail in results)


def test_verify_revisions_requires_huggingface_hub(registry, monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = __import__

    def blocked_import(name: str, *args: Any, **kwargs: Any):
        if name == "huggingface_hub" or name.startswith("huggingface_hub."):
            raise ImportError("blocked for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", blocked_import)
    with pytest.raises(RevisionVerifyError, match="huggingface_hub"):
        verify_revisions(registry)


def test_cli_verify_revisions_exit_status(
    registry, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def list_files(repo: str, revision: str) -> list[str]:
        entry = next(e for e in registry.entries if e.repo == repo and e.revision == revision)
        names: list[str] = []
        if entry.recipe.gguf:
            names.append(entry.recipe.gguf)
        if entry.recipe.mmproj:
            names.append(entry.recipe.mmproj)
        return names

    monkeypatch.setattr(
        "scripts.eval_harness.bakeoff_candidates._hf_list_repo_files",
        list_files,
    )
    assert main(["--verify-revisions"]) == 0
    out = capsys.readouterr().out
    for entry in registry.entries:
        assert entry.id in out
        assert out.count(f"ok {entry.id} ") == 1


@pytest.mark.skipif(
    not os.environ.get("ACX_BAKEOFF_VERIFY_REVISIONS"),
    reason="opt-in network; set ACX_BAKEOFF_VERIFY_REVISIONS=1",
)
def test_live_verify_revisions_hits_huggingface() -> None:
    assert main(["--verify-revisions"]) == 0
