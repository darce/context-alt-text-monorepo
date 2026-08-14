"""VLM-6 S2 candidate registry — fail-fast loader (rg-008).

``bakeoff_candidates.yaml`` is the single source of truth for the sealed
13-candidate + 2-incumbent bake-off roster. Every field is strictly typed
under ``extra='forbid'`` and checked at load time: revision pins, serving
recipes, prompt templates, and tiers cannot be omitted or left as TODO.
"""

from __future__ import annotations

import argparse
import re
import sys
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

SCHEMA = "acx-bakeoff-candidates/v1"
SEALED_CANDIDATE_COUNT = 13
SEALED_INCUMBENT_COUNT = 2
KNOWN_PROMPT_TEMPLATES = frozenset({"v1", "v2", "v3"})
QWEN38_ROW_ID = "qwen38-27b"
RETIRED_QWEN36_ROW_ID = "qwen36-27b"
QWEN38_QUANT = "UD-Q4_K_XL"
QWEN38_ARTIFACT_GB = 17.9
_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
_TODO_RE = re.compile(r"TODO|<TODO", re.IGNORECASE)
DEFAULT_REGISTRY = Path(__file__).with_name("bakeoff_candidates.yaml")


class RegistryError(Exception):
    """Committed or supplied candidate registry failed fail-fast validation."""


class CandidateRole(StrEnum):
    """Roster role. Incumbents are measured, not competing."""

    CANDIDATE = "candidate"
    INCUMBENT = "incumbent"


class ServingStack(StrEnum):
    """Serving stack the bake-host must smoke before S3."""

    LLAMA_CPP = "llama_cpp"
    VLLM = "vllm"
    HF_TRANSFORMERS = "hf_transformers"


class BakeoffTier(StrEnum):
    """Latency-gated product tier (gate, not ranking axis)."""

    GPU_ASYNC = "gpu_async"
    CPU_INLINE = "cpu_inline"


class HardwareTarget(BaseModel):
    """Burst-host envelope the roster is sized against."""

    model_config = ConfigDict(extra="forbid")

    shape: str
    vram_gb: int
    usable_vram_budget_gb: int


class SealedCounts(BaseModel):
    """Declared sealed sizes; must match loader constants and entry counts."""

    model_config = ConfigDict(extra="forbid")

    candidates: int
    incumbent_anchors: int


class ServingRecipe(BaseModel):
    """How to stand the candidate up. llama.cpp rows require gguf + mmproj."""

    model_config = ConfigDict(extra="forbid")

    stack: ServingStack
    ctx_size: int
    image_max_tokens: int
    parallel: int = 1
    extra_flags: list[str] = Field(default_factory=list)
    gguf: str | None = None
    mmproj: str | None = None

    @model_validator(mode="after")
    def _llama_cpp_needs_artifacts(self) -> ServingRecipe:
        if self.stack is ServingStack.LLAMA_CPP and (not self.gguf or not self.mmproj):
            raise ValueError("llama_cpp recipe requires gguf and mmproj")
        return self


class CandidateEntry(BaseModel):
    """One sealed roster row: pin + recipe + tier + license."""

    model_config = ConfigDict(extra="forbid")

    id: str
    role: CandidateRole
    competing: bool
    model_id: str
    repo: str
    revision: str
    quant: str
    artifact: str
    artifact_gb: float
    license: str
    prompt_template: str
    tiers: list[BakeoffTier]
    recipe: ServingRecipe
    reasoning_tuned: bool = False
    notes: str | None = None

    @field_validator("id", "model_id", "repo", "quant", "artifact", "license")
    @classmethod
    def _nonempty_no_todo(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("field must be non-empty")
        if _TODO_RE.search(text):
            raise ValueError(f"TODO placeholder is not a pin: {value!r}")
        return text

    @field_validator("revision")
    @classmethod
    def _revision_is_sha(cls, value: str) -> str:
        pin = value.strip().lower()
        if not _SHA1_RE.fullmatch(pin):
            raise ValueError(f"revision must be a 40-char lowercase hex SHA, got {value!r}")
        return pin

    @field_validator("prompt_template")
    @classmethod
    def _known_prompt(cls, value: str) -> str:
        if value not in KNOWN_PROMPT_TEMPLATES:
            raise ValueError(f"unknown prompt_template {value!r}; expected one of {sorted(KNOWN_PROMPT_TEMPLATES)}")
        return value

    @field_validator("tiers")
    @classmethod
    def _at_least_one_tier(cls, value: list[BakeoffTier]) -> list[BakeoffTier]:
        if not value:
            raise ValueError("at least one tier is required")
        return value

    @model_validator(mode="after")
    def _incumbents_are_not_competing(self) -> CandidateEntry:
        if self.role is CandidateRole.INCUMBENT and self.competing:
            raise ValueError(f"incumbent {self.id} cannot be competing")
        return self


class BakeoffCandidateRegistry(BaseModel):
    """Root document for the sealed VLM-6 bake-off roster."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_id: str = Field(alias="schema")
    task_ref: str
    hardware_target: HardwareTarget
    sealed: SealedCounts
    entries: list[CandidateEntry]

    @field_validator("schema_id")
    @classmethod
    def _known_schema(cls, value: str) -> str:
        if value != SCHEMA:
            raise ValueError(f"unsupported schema {value!r}; expected {SCHEMA}")
        return value


def default_registry_path() -> Path:
    """Return the committed registry path next to this module."""
    return DEFAULT_REGISTRY


def load_bakeoff_candidates(path: str | Path | None = None) -> BakeoffCandidateRegistry:
    """Load and fail-fast validate the candidate registry.

    Args:
        path: Registry YAML. Defaults to the committed ``bakeoff_candidates.yaml``.

    Returns:
        Validated registry.

    Raises:
        RegistryError: Missing file, malformed YAML, schema violation, or
            sealed-count / uniqueness / swap-row invariant failure.
    """
    registry_path = Path(path) if path is not None else default_registry_path()
    raw = _read_yaml(registry_path)
    try:
        registry = BakeoffCandidateRegistry.model_validate(raw)
    except ValidationError as exc:
        raise RegistryError(f"bakeoff candidate registry schema violation: {exc}") from exc
    _assert_sealed_invariants(registry)
    return registry


def _read_yaml(registry_path: Path) -> Any:
    if not registry_path.is_file():
        raise RegistryError(f"candidate registry not found: {registry_path}")
    try:
        raw = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise RegistryError(f"candidate registry unreadable or malformed YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise RegistryError("candidate registry root must be a mapping")
    return raw


def _assert_sealed_invariants(registry: BakeoffCandidateRegistry) -> None:
    candidates = [e for e in registry.entries if e.role is CandidateRole.CANDIDATE]
    incumbents = [e for e in registry.entries if e.role is CandidateRole.INCUMBENT]
    _assert_counts(registry, candidates, incumbents)
    ids = [e.id for e in registry.entries]
    if len(ids) != len(set(ids)):
        raise RegistryError(f"duplicate candidate id in registry: {ids}")
    _assert_qwen38_swap(registry)


def _assert_counts(
    registry: BakeoffCandidateRegistry,
    candidates: list[CandidateEntry],
    incumbents: list[CandidateEntry],
) -> None:
    declared_c = registry.sealed.candidates
    declared_i = registry.sealed.incumbent_anchors
    if declared_c != SEALED_CANDIDATE_COUNT or declared_i != SEALED_INCUMBENT_COUNT:
        raise RegistryError(
            f"sealed declaration {declared_c}+{declared_i} != "
            f"{SEALED_CANDIDATE_COUNT}+{SEALED_INCUMBENT_COUNT}"
        )
    if len(candidates) != SEALED_CANDIDATE_COUNT:
        raise RegistryError(
            f"expected {SEALED_CANDIDATE_COUNT} candidates, found {len(candidates)}"
        )
    if len(incumbents) != SEALED_INCUMBENT_COUNT:
        raise RegistryError(
            f"expected {SEALED_INCUMBENT_COUNT} incumbent anchors, found {len(incumbents)}"
        )


def _assert_qwen38_swap(registry: BakeoffCandidateRegistry) -> None:
    ids = {e.id for e in registry.entries}
    if RETIRED_QWEN36_ROW_ID in ids:
        raise RegistryError(
            f"{RETIRED_QWEN36_ROW_ID} is retired; roster row is {QWEN38_ROW_ID}"
        )
    row = next((e for e in registry.entries if e.id == QWEN38_ROW_ID), None)
    if row is None:
        raise RegistryError(f"sealed roster missing swapped row {QWEN38_ROW_ID}")
    if row.quant != QWEN38_QUANT:
        raise RegistryError(f"{QWEN38_ROW_ID} quant must be {QWEN38_QUANT}, got {row.quant}")
    if row.artifact_gb != QWEN38_ARTIFACT_GB:
        raise RegistryError(
            f"{QWEN38_ROW_ID} artifact_gb must be {QWEN38_ARTIFACT_GB}, got {row.artifact_gb}"
        )


def main(argv: list[str] | None = None) -> int:
    """Validate a registry file and print sealed counts. Returns process status."""
    parser = argparse.ArgumentParser(description="Validate VLM-6 bakeoff_candidates.yaml")
    parser.add_argument("path", nargs="?", type=Path, default=default_registry_path())
    args = parser.parse_args(argv)
    try:
        registry = load_bakeoff_candidates(args.path)
    except RegistryError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    n_cand = sum(1 for e in registry.entries if e.role is CandidateRole.CANDIDATE)
    n_inc = sum(1 for e in registry.entries if e.role is CandidateRole.INCUMBENT)
    print(f"ok: {n_cand} candidates + {n_inc} incumbent anchors")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
