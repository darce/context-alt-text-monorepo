"""VLM-6 S2 candidate registry — fail-fast loader (rg-008).

``bakeoff_candidates.yaml`` is the single source of truth for sealed
candidate/incumbent counts and generation pairs. Every field is strictly
typed under ``extra='forbid'`` and checked at load time: revision pins,
serving recipes, prompt templates, and tiers cannot be omitted or left
as TODO.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from collections.abc import Callable, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

SCHEMA = "acx-bakeoff-candidates/v1"
KNOWN_PROMPT_TEMPLATES = frozenset({"v1", "v2", "v3"})
# Recipe fields that must match across a generation pair for the comparison
# to be like-for-like. ``gguf`` differs by construction (different artifact).
# ``min_runtime_build`` / ``min_runtime_build_is_lower_bound`` decide which
# llama.cpp build is legal; a missing floor on one leg is not a generation
# delta, it is a preflight-policy delta. Structural, not roster data.
GENERATION_PAIR_SHARED_RECIPE_FIELDS = (
    "stack",
    "ctx_size",
    "image_max_tokens",
    "parallel",
    "extra_flags",
    "mmproj",
    "min_runtime_build",
    "min_runtime_build_is_lower_bound",
)
# Entry-level workload fields (not on ServingRecipe) that also decide the
# system prompt and whether /no_think is appended. Sealed separately so a
# recipe-only walk cannot claim the pair is like-for-like.
GENERATION_PAIR_SHARED_ENTRY_FIELDS = ("prompt_template", "reasoning_tuned")
_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
_TODO_RE = re.compile(r"TODO|<TODO", re.IGNORECASE)
_LLAMA_CPP_BUILD_RE = re.compile(r"^b\d+$")
_VLLM_BUILD_RE = re.compile(r"^\d+\.\d+(\.\d+)?$")
DEFAULT_REGISTRY = Path(__file__).with_name("bakeoff_candidates.yaml")


class RegistryError(Exception):
    """Committed or supplied candidate registry failed fail-fast validation."""


class RevisionVerifyError(Exception):
    """Opt-in ``--verify-revisions`` cannot run (missing Hugging Face client)."""


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


class GenerationPair(BaseModel):
    """YAML-declared like-for-like generation comparison (ids + shared quant)."""

    model_config = ConfigDict(extra="forbid")

    ids: list[str] = Field(min_length=2)
    quant: str

    @field_validator("ids")
    @classmethod
    def _ids_unique_nonempty(cls, value: list[str]) -> list[str]:
        cleaned = [_nonempty_no_todo(item) for item in value]
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("generation pair ids must be unique")
        return cleaned

    @field_validator("quant")
    @classmethod
    def _quant_nonempty(cls, value: str) -> str:
        return _nonempty_no_todo(value)


class SealedCounts(BaseModel):
    """Declared sealed sizes and generation pairs; counts must match entry roles."""

    model_config = ConfigDict(extra="forbid")

    candidates: int
    incumbent_anchors: int
    generation_pairs: list[GenerationPair] = Field(min_length=1)


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
    mmproj_gb: float | None = None
    min_runtime_build: str | None = None
    min_runtime_build_is_lower_bound: bool = False

    @field_validator("min_runtime_build")
    @classmethod
    def _min_runtime_build_no_todo(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = _nonempty_no_todo(value)
        if "tbd" in text.lower():
            raise ValueError(f"TODO placeholder is not a pin: {value!r}")
        if not (_LLAMA_CPP_BUILD_RE.fullmatch(text) or _VLLM_BUILD_RE.fullmatch(text)):
            raise ValueError(
                f"min_runtime_build {value!r} must match ^b\\d+$ (llama_cpp) "
                f"or ^\\d+\\.\\d+(\\.\\d+)?$ (vllm); free prose is not a pin"
            )
        return text

    @model_validator(mode="after")
    def _llama_cpp_needs_artifacts(self) -> ServingRecipe:
        if self.stack is ServingStack.LLAMA_CPP and (not self.gguf or not self.mmproj):
            raise ValueError("llama_cpp recipe requires gguf and mmproj")
        if self.min_runtime_build is None and self.min_runtime_build_is_lower_bound:
            raise ValueError("min_runtime_build_is_lower_bound requires min_runtime_build")
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
        return _nonempty_no_todo(value)

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

    @model_validator(mode="after")
    def _min_runtime_build_matches_stack(self) -> CandidateEntry:
        pin = self.recipe.min_runtime_build
        if pin is None:
            return self
        stack = self.recipe.stack
        if stack is ServingStack.LLAMA_CPP:
            if not _LLAMA_CPP_BUILD_RE.fullmatch(pin):
                raise ValueError(
                    f"{self.id}: min_runtime_build {pin!r} must match ^b\\d+$ for llama_cpp"
                )
        elif stack is ServingStack.VLLM:
            if not _VLLM_BUILD_RE.fullmatch(pin):
                raise ValueError(
                    f"{self.id}: min_runtime_build {pin!r} must match "
                    f"^\\d+\\.\\d+(\\.\\d+)?$ for vllm"
                )
        else:
            raise ValueError(
                f"{self.id}: min_runtime_build {pin!r} is not valid for stack {stack.value}"
            )
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


def _nonempty_no_todo(value: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError("field must be non-empty")
    if _TODO_RE.search(text):
        raise ValueError(f"TODO placeholder is not a pin: {value!r}")
    return text


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
    _assert_generation_pairs(registry)


def _assert_counts(
    registry: BakeoffCandidateRegistry,
    candidates: list[CandidateEntry],
    incumbents: list[CandidateEntry],
) -> None:
    declared_c = registry.sealed.candidates
    declared_i = registry.sealed.incumbent_anchors
    if len(candidates) != declared_c:
        raise RegistryError(f"expected {declared_c} candidates, found {len(candidates)}")
    if len(incumbents) != declared_i:
        raise RegistryError(
            f"expected {declared_i} incumbent anchors, found {len(incumbents)}"
        )


def _assert_generation_pairs(registry: BakeoffCandidateRegistry) -> None:
    by_id = {e.id: e for e in registry.entries}
    for pair in registry.sealed.generation_pairs:
        rows = []
        for row_id in pair.ids:
            row = by_id.get(row_id)
            if row is None:
                raise RegistryError(f"sealed roster missing generation-pair row {row_id}")
            if row.quant != pair.quant:
                raise RegistryError(f"{row_id} quant must be {pair.quant}, got {row.quant}")
            if not row.competing:
                raise RegistryError(
                    f"{row_id} must compete for the generation delta to be scored"
                )
            rows.append(row)

        reference, *others = rows
        for field in GENERATION_PAIR_SHARED_RECIPE_FIELDS:
            expected = getattr(reference.recipe, field)
            for row in others:
                actual = getattr(row.recipe, field)
                if actual != expected:
                    raise RegistryError(
                        f"generation pair recipe drift on {field!r}: "
                        f"{reference.id}={expected!r} vs {row.id}={actual!r}. "
                        "The pair must share a recipe or the speed/token delta is unattributable."
                    )
        for field in GENERATION_PAIR_SHARED_ENTRY_FIELDS:
            expected = getattr(reference, field)
            for row in others:
                actual = getattr(row, field)
                if actual != expected:
                    raise RegistryError(
                        f"generation pair entry drift on {field!r}: "
                        f"{reference.id}={expected!r} vs {row.id}={actual!r}. "
                        "The pair must share prompt and reasoning settings or the "
                        "delta is unattributable."
                    )


def _hf_list_repo_files(repo: str, revision: str) -> list[str]:
    try:
        from huggingface_hub import HfApi
    except ImportError as exc:
        raise RevisionVerifyError(
            "huggingface_hub is required for --verify-revisions; "
            "install it or omit the flag. Default load path stays offline."
        ) from exc
    return list(HfApi().list_repo_files(repo_id=repo, revision=revision))


def _declared_artifacts(entry: CandidateEntry) -> list[str]:
    names: list[str] = []
    if entry.recipe.gguf:
        names.append(entry.recipe.gguf)
    if entry.recipe.mmproj:
        names.append(entry.recipe.mmproj)
    return names


def _artifacts_are_siblings(files: Sequence[str], required: Sequence[str]) -> bool:
    if not required:
        return True
    by_dir: dict[str, set[str]] = defaultdict(set)
    for path in files:
        parent, _, name = path.rpartition("/")
        by_dir[parent].add(name)
    needed = set(required)
    return any(needed <= names for names in by_dir.values())


def _verify_one_revision(
    entry: CandidateEntry,
    files: Sequence[str],
) -> tuple[bool, str]:
    required = _declared_artifacts(entry)
    pin = f"{entry.repo}@{entry.revision}"
    if required and not _artifacts_are_siblings(files, required):
        missing = ", ".join(required)
        return False, f"{pin} missing sibling artifacts: {missing}"
    return True, f"{pin} ok"


def verify_revisions(
    registry: BakeoffCandidateRegistry,
    *,
    list_files: Callable[[str, str], Sequence[str]] | None = None,
) -> list[tuple[str, bool, str]]:
    """Confirm each ``repo@revision`` resolves and declared artifacts exist.

    The default ``list_files`` calls the Hugging Face Hub. Tests inject a
    lister so this function makes no network calls unless asked.

    Args:
        registry: Validated roster.
        list_files: Optional ``(repo, revision) -> file paths`` callback.

    Returns:
        One ``(id, ok, detail)`` tuple per registry entry, in roster order.

    Raises:
        RevisionVerifyError: The Hugging Face client is missing and no
            ``list_files`` callback was supplied.
    """
    lister = list_files if list_files is not None else _hf_list_repo_files
    results: list[tuple[str, bool, str]] = []
    for entry in registry.entries:
        try:
            files = lister(entry.repo, entry.revision)
        except RevisionVerifyError:
            raise
        except Exception as exc:
            results.append((entry.id, False, f"{entry.repo}@{entry.revision} unresolved: {exc}"))
            continue
        ok, detail = _verify_one_revision(entry, files)
        results.append((entry.id, ok, detail))
    return results


def _print_revision_verification(
    registry: BakeoffCandidateRegistry,
    *,
    list_files: Callable[[str, str], Sequence[str]] | None = None,
) -> int:
    try:
        results = verify_revisions(registry, list_files=list_files)
    except RevisionVerifyError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    failed = 0
    for entry_id, ok, detail in results:
        status = "ok" if ok else "FAIL"
        print(f"{status} {entry_id} {detail}")
        if not ok:
            failed += 1
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    """Validate a registry file and print sealed counts. Returns process status."""
    parser = argparse.ArgumentParser(description="Validate VLM-6 bakeoff_candidates.yaml")
    parser.add_argument("path", nargs="?", type=Path, default=default_registry_path())
    parser.add_argument(
        "--verify-revisions",
        action="store_true",
        help=(
            "opt-in: resolve each repo@revision on Hugging Face and confirm "
            "declared gguf/mmproj filenames are siblings at that pin"
        ),
    )
    args = parser.parse_args(argv)
    try:
        registry = load_bakeoff_candidates(args.path)
    except RegistryError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    if args.verify_revisions:
        return _print_revision_verification(registry)
    n_cand = sum(1 for e in registry.entries if e.role is CandidateRole.CANDIDATE)
    n_inc = sum(1 for e in registry.entries if e.role is CandidateRole.INCUMBENT)
    print(f"ok: {n_cand} candidates + {n_inc} incumbent anchors")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
