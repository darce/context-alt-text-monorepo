"""VLM-6 S2a-1: bakeoff_candidates.yaml fail-fast validator."""

from __future__ import annotations

import os
import sys
import tomllib
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import yaml

from scripts.eval_harness.bakeoff_candidates import (
    GENERATION_PAIR_SHARED_RECIPE_FIELDS,
    SCHEMA,
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

# Test-owned roster pins. YAML is the loader source of truth; these literals
# give TEST-15 kill power if the committed qwen pair drifts.
_QWEN38_ROW_ID = "qwen38-27b"
_QWEN36_ROW_ID = "qwen36-27b"
_QWEN_PAIR_QUANT = "UD-Q4_K_XL"
_QWEN_PAIR_PINS: dict[str, tuple[str, float]] = {
    _QWEN38_ROW_ID: ("Qwen3.8-27B", 17.9),
    _QWEN36_ROW_ID: ("Qwen3.6-27B", 17.6),
}
_PINNED_CANDIDATE_COUNT = 14
_PINNED_INCUMBENT_COUNT = 2

# Test-owned sealed sets. Parametrizing over these — not the production
# constants — is what gives TEST-15 kill power: dropping a name from
# GENERATION_PAIR_SHARED_RECIPE_FIELDS / GENERATION_PAIR_SHARED_ENTRY_FIELDS
# leaves the corresponding drift case in the suite. The equality tests
# below then also fail, so a tuple shrink cannot silently delete its own mutant.
_SEALED_RECIPE_FIELDS = (
    "stack",
    "ctx_size",
    "image_max_tokens",
    "parallel",
    "extra_flags",
    "mmproj",
    "min_runtime_build",
    "min_runtime_build_is_lower_bound",
)
_RECIPE_DRIFT_VALUES: dict[str, Any] = {
    "stack": "vllm",
    "ctx_size": 4096,
    "image_max_tokens": 1,
    "parallel": 8,
    "extra_flags": ["--no-think", "--mutated"],
    "mmproj": "mmproj-mutated.gguf",
    "min_runtime_build": "b9999",
    "min_runtime_build_is_lower_bound": False,
}
_SEALED_ENTRY_FIELDS = (
    "prompt_template",
    "reasoning_tuned",
)
_ENTRY_DRIFT_VALUES: dict[str, Any] = {
    "prompt_template": "v2",
    "reasoning_tuned": False,
}


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
    assert len(registry.entries) == registry.sealed.candidates + registry.sealed.incumbent_anchors
    assert len(registry.entries) == _PINNED_CANDIDATE_COUNT + _PINNED_INCUMBENT_COUNT


def test_sealed_counts_are_exact(registry) -> None:
    n_cand = sum(1 for e in registry.entries if e.role is CandidateRole.CANDIDATE)
    n_inc = sum(1 for e in registry.entries if e.role is CandidateRole.INCUMBENT)
    assert n_cand == registry.sealed.candidates == _PINNED_CANDIDATE_COUNT == 14
    assert n_inc == registry.sealed.incumbent_anchors == _PINNED_INCUMBENT_COUNT == 2


def test_committed_generation_pairs_are_yaml_declared(registry) -> None:
    assert len(registry.sealed.generation_pairs) == 1
    pair = registry.sealed.generation_pairs[0]
    assert pair.ids == [_QWEN38_ROW_ID, _QWEN36_ROW_ID]
    assert pair.quant == _QWEN_PAIR_QUANT


def test_qwen_generation_pair_rows_present(registry) -> None:
    by_id = {e.id: e for e in registry.entries}
    for row_id, (model_id, artifact_gb) in _QWEN_PAIR_PINS.items():
        row = by_id[row_id]
        assert row.model_id == model_id
        assert row.competing is True
        assert row.quant == _QWEN_PAIR_QUANT
        assert row.artifact_gb == artifact_gb
        assert row.artifact == f"{model_id}-UD-Q4_K_XL.gguf"
        assert row.recipe.stack is ServingStack.LLAMA_CPP
        assert row.recipe.gguf == row.artifact
        assert row.recipe.mmproj == "mmproj-F16.gguf"
    assert by_id[_QWEN38_ROW_ID].revision == "1cff334a4a228324d4ee1f76d55d372588f0d556"
    assert by_id[_QWEN36_ROW_ID].revision == "82d411acf4a06cfb8d9b073a5211bf410bfc29bf"
    assert by_id[_QWEN38_ROW_ID].repo == "unsloth/Qwen3.8-27B-GGUF"
    assert by_id[_QWEN36_ROW_ID].repo == "unsloth/Qwen3.6-27B-GGUF"


def test_generation_pair_shared_recipe_fields_are_exactly_the_sealed_set() -> None:
    assert GENERATION_PAIR_SHARED_RECIPE_FIELDS == _SEALED_RECIPE_FIELDS
    assert set(_RECIPE_DRIFT_VALUES) == set(_SEALED_RECIPE_FIELDS)


def test_generation_pair_shared_entry_fields_are_exactly_the_sealed_set() -> None:
    from scripts.eval_harness import bakeoff_candidates as bakeoff_mod

    actual = getattr(bakeoff_mod, "GENERATION_PAIR_SHARED_ENTRY_FIELDS", ())
    assert actual == _SEALED_ENTRY_FIELDS
    assert set(_ENTRY_DRIFT_VALUES) == set(_SEALED_ENTRY_FIELDS)


def _qwen_row(payload: dict[str, Any], row_id: str) -> dict[str, Any]:
    return next(entry for entry in payload["entries"] if entry["id"] == row_id)


def _apply_recipe_drift(payload: dict[str, Any], field: str, value: Any) -> None:
    """Mutate qwen36 so only ``field`` differs, without tripping schema first."""
    qwen36 = _qwen_row(payload, _QWEN36_ROW_ID)
    if field == "stack":
        # Build pins are stack-specific. Neutralize both legs so the pair
        # invariant — not ``_min_runtime_build_matches_stack`` — is the killer.
        for row in (_qwen_row(payload, _QWEN36_ROW_ID), _qwen_row(payload, _QWEN38_ROW_ID)):
            row["recipe"]["min_runtime_build"] = None
            row["recipe"].pop("min_runtime_build_is_lower_bound", None)
    qwen36["recipe"][field] = value


@pytest.mark.parametrize("field", _SEALED_RECIPE_FIELDS)
def test_qwen_pair_recipe_drift_fails(
    field: str, tmp_path: Path, raw_registry: dict[str, Any]
) -> None:
    payload = deepcopy(raw_registry)
    _apply_recipe_drift(payload, field, _RECIPE_DRIFT_VALUES[field])
    with pytest.raises(RegistryError, match=f"recipe drift on {field!r}"):
        load_bakeoff_candidates(_write_registry(tmp_path, payload))


@pytest.mark.parametrize("field", _SEALED_ENTRY_FIELDS)
def test_qwen_pair_entry_drift_fails(
    field: str, tmp_path: Path, raw_registry: dict[str, Any]
) -> None:
    payload = deepcopy(raw_registry)
    _qwen_row(payload, _QWEN36_ROW_ID)[field] = _ENTRY_DRIFT_VALUES[field]
    with pytest.raises(RegistryError, match=f"entry drift on {field!r}"):
        load_bakeoff_candidates(_write_registry(tmp_path, payload))


def test_qwen_pair_omitted_min_runtime_build_fails(
    tmp_path: Path, raw_registry: dict[str, Any]
) -> None:
    payload = deepcopy(raw_registry)
    row = _qwen_row(payload, _QWEN36_ROW_ID)
    del row["recipe"]["min_runtime_build"]
    row["recipe"].pop("min_runtime_build_is_lower_bound", None)
    with pytest.raises(RegistryError, match="recipe drift on 'min_runtime_build'"):
        load_bakeoff_candidates(_write_registry(tmp_path, payload))


def test_dev_extra_declares_huggingface_hub() -> None:
    pyproject_path = Path(__file__).resolve().parents[2] / "pyproject.toml"
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    names = {
        req.split(">=", 1)[0].split("==", 1)[0].split("<", 1)[0].split("[", 1)[0].strip()
        for req in data["project"]["optional-dependencies"]["dev"]
    }
    assert "huggingface_hub" in names


def test_losing_the_previous_generation_row_fails(
    tmp_path: Path, raw_registry: dict[str, Any]
) -> None:
    # Rename rather than delete so the sealed counts still pass: the pair
    # invariant, not the count check, must be what catches this.
    payload = deepcopy(raw_registry)
    row = next(e for e in payload["entries"] if e["id"] == _QWEN36_ROW_ID)
    row["id"] = "qwen36-27b-renamed"
    with pytest.raises(RegistryError, match=f"missing generation-pair row {_QWEN36_ROW_ID}"):
        load_bakeoff_candidates(_write_registry(tmp_path, payload))


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
    assert capsys.readouterr().out.strip() == "ok: 14 candidates + 2 incumbent anchors"


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
    row = next(e for e in payload["entries"] if e["id"] == _QWEN38_ROW_ID)
    row["recipe"]["mmproj"] = None
    with pytest.raises(RegistryError, match="gguf and mmproj"):
        load_bakeoff_candidates(_write_registry(tmp_path, payload))


def test_wrong_candidate_count_fails(tmp_path: Path, raw_registry: dict[str, Any]) -> None:
    payload = deepcopy(raw_registry)
    payload["entries"] = [e for e in payload["entries"] if e["id"] != "ovis2-8b"]
    with pytest.raises(RegistryError, match="expected 14 candidates, found 13"):
        load_bakeoff_candidates(_write_registry(tmp_path, payload))


def test_declared_candidate_count_mismatch_fails(
    tmp_path: Path, raw_registry: dict[str, Any]
) -> None:
    # YAML declaration is the source of truth (rg-009): 13 declared, 14 rows.
    payload = deepcopy(raw_registry)
    payload["sealed"]["candidates"] = 13
    with pytest.raises(RegistryError, match="expected 13 candidates, found 14"):
        load_bakeoff_candidates(_write_registry(tmp_path, payload))


def test_generation_pair_quant_mismatch_fails(
    tmp_path: Path, raw_registry: dict[str, Any]
) -> None:
    # Pair.quant comes from YAML, not a Python constant (TEST-15).
    payload = deepcopy(raw_registry)
    payload["sealed"]["generation_pairs"] = [
        {"ids": ["qwen38-27b", "qwen36-27b"], "quant": "Q5_K_M"}
    ]
    with pytest.raises(RegistryError, match="qwen38-27b quant must be Q5_K_M"):
        load_bakeoff_candidates(_write_registry(tmp_path, payload))


def test_generation_pair_missing_id_fails(
    tmp_path: Path, raw_registry: dict[str, Any]
) -> None:
    payload = deepcopy(raw_registry)
    payload["sealed"]["generation_pairs"] = [
        {"ids": ["qwen38-27b", "does-not-exist"], "quant": "UD-Q4_K_XL"}
    ]
    with pytest.raises(RegistryError, match="missing generation-pair row does-not-exist"):
        load_bakeoff_candidates(_write_registry(tmp_path, payload))


def test_missing_generation_pairs_fails(
    tmp_path: Path, raw_registry: dict[str, Any]
) -> None:
    # rg-008: sibling sealed keys are required; omitting generation_pairs
    # must not silently disable every pair invariant.
    payload = deepcopy(raw_registry)
    del payload["sealed"]["generation_pairs"]
    with pytest.raises(RegistryError, match="generation_pairs"):
        load_bakeoff_candidates(_write_registry(tmp_path, payload))


def test_empty_generation_pairs_fails(
    tmp_path: Path, raw_registry: dict[str, Any]
) -> None:
    payload = deepcopy(raw_registry)
    payload["sealed"]["generation_pairs"] = []
    with pytest.raises(RegistryError, match="generation_pairs"):
        load_bakeoff_candidates(_write_registry(tmp_path, payload))


def test_declared_incumbent_anchor_count_mismatch_fails(
    tmp_path: Path, raw_registry: dict[str, Any]
) -> None:
    payload = deepcopy(raw_registry)
    payload["sealed"]["incumbent_anchors"] = 1
    with pytest.raises(RegistryError, match="expected 1 incumbent anchors, found 2"):
        load_bakeoff_candidates(_write_registry(tmp_path, payload))


def test_generation_pair_non_competing_row_fails(
    tmp_path: Path, raw_registry: dict[str, Any]
) -> None:
    payload = deepcopy(raw_registry)
    _qwen_row(payload, _QWEN36_ROW_ID)["competing"] = False
    with pytest.raises(
        RegistryError, match=f"{_QWEN36_ROW_ID} must compete for the generation delta"
    ):
        load_bakeoff_candidates(_write_registry(tmp_path, payload))


def test_generation_pair_recipe_drift_on_shared_field_fails(
    tmp_path: Path, raw_registry: dict[str, Any]
) -> None:
    # Non-Qwen pair so the generic YAML walker — not the old Qwen-only
    # constant — is the killer (TEST-15).
    payload = deepcopy(raw_registry)
    payload["sealed"]["generation_pairs"] = [
        {"ids": ["ovis25-9b", "ovis2-8b"], "quant": "bf16"}
    ]
    ovis2 = next(entry for entry in payload["entries"] if entry["id"] == "ovis2-8b")
    ovis2["recipe"]["ctx_size"] = 4096
    with pytest.raises(RegistryError, match="recipe drift on 'ctx_size'"):
        load_bakeoff_candidates(_write_registry(tmp_path, payload))


def test_duplicate_id_fails(tmp_path: Path, raw_registry: dict[str, Any]) -> None:
    payload = deepcopy(raw_registry)
    payload["entries"][1]["id"] = payload["entries"][0]["id"]
    with pytest.raises(RegistryError, match="duplicate candidate id"):
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
    qwen38 = next(e for e in registry.entries if e.id == _QWEN38_ROW_ID)
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
    row = next(e for e in payload["entries"] if e["id"] == _QWEN38_ROW_ID)
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
