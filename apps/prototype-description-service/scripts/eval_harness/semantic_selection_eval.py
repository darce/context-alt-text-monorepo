"""Offline semantic-selection evaluator over precomputed vectors.

Ranks approved context candidates for each frozen query by exact cosine over
precomputed image/query and text vectors, reports top1 and MRR over every
frozen query, and checks the frozen baseline and full-pack selections. It is
an additive, standalone evaluator: it runs no encoder, downloads no model,
makes no network call, and is not part of the FIR recognition pipeline or any
production routing.

CLI::

    python -m scripts.eval_harness.semantic_selection_eval INPUT --output PATH

``INPUT`` is a ``semantic-selection-eval/v2`` JSON document; the committed
``semantic_selection_example.json`` is the reference fixture. The report is
written to ``PATH`` as ``semantic-selection-eval-report/v2`` JSON. Exit status is
0 on success, 1 when the input is rejected or the report cannot be written (no
report is written), and 2 for CLI usage errors. Nothing is printed to stdout.

Contract:

- The query side and the candidate side each declare an encoder contract:
  ``model_id``, an immutable 40-char hex ``revision``, ``preprocessing``,
  ``dimension``, ``normalization``, ``namespace``, and ``space_id``. Every
  field must match across the two sides. Equal vector length alone never
  proves compatibility. A shared preprocessing recipe may explicitly pair
  different image and text paths; the modality preprocessing bytes need not
  be identical (EMB-01).
- Only the ``approved_context`` namespace is accepted. Face or identity
  embeddings cannot be mixed in or ranked here.
- Vectors must be finite JSON numbers, non-zero, and of the declared
  dimension. Dimensional truncation is not supported and is rejected. A
  declared ``l2`` normalization is verified to unit norm within 1e-6.
- Candidate ``status``: ``approved`` candidates are the only ranking pool.
  ``denied`` candidates are never ranked or selected. ``protected`` naming or
  policy records are never ranked or authorized by the ranker. In v2 each
  requires ``protected_scope``: ``{"kind": "global"}`` or
  ``{"kind": "queries", "query_ids": ["q-1", ...]}``. Query IDs refer to
  frozen query/image records, not text parsed from ``source_id``. All
  applicable protected records must appear in both packs, and out-of-scope
  records are rejected. Only protected records may declare this scope.
  Migrate v1 by explicitly annotating scope and changing the schema version;
  v1's implicit all-query scope is no longer accepted (CARD-18/ATTRIB-05).
- Gold ids must name approved candidates. A query with no gold ids stays in
  every denominator as ``no_relevant`` with reciprocal rank 0; it is never
  dropped. A query whose approved pool is empty is reported as
  ``no_approved_candidates`` in the same way.
- Scores are exact cosines (float64, clamped to [-1, 1]). Score ties break by
  ascending candidate id, so the ranking does not depend on input order.
- Frozen pack selections are compared as ordered sequences. Membership-only
  (set) equality is reported as added and removed ids but is never a verdict,
  because it hides phrase and role swaps.

Interpretation: a score is retrieval relevance between a query vector and a
candidate vector in one shared embedding space. It is not visual truth,
identity, consent, or authority, and it never grants a protected record.

Canon v0.26.2 (supplied offline packet):

- EMB-01: https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/ml-systems.md#emb-01
- CARD-18/ATTRIB-05: https://github.com/darce/heuristics-canon/blob/v0.26.2/reasoning/attribute-claims-to-their-bearer.md

Limitations:

- The committed fixture's vectors are hand-authored, not produced by any
  encoder. It documents the contract and the arithmetic, not model quality.
- The report carries no latency, throughput, or model-winner claim.
- Exact cosine is pure Python, O(queries x candidates x dimension). It suits
  small frozen fixtures and audit, not serving.
- Frozen pack selections are inputs that this module checks. It does not
  produce them.
- Dimensional truncation is rejected, not re-normalized.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

SCHEMA_VERSION = "semantic-selection-eval/v2"
REPORT_SCHEMA_VERSION = "semantic-selection-eval-report/v2"
APPROVED_CONTEXT_NAMESPACE = "approved_context"
PACK_NAMES = ("baseline", "full_pack")
NORM_TOLERANCE = 1e-6
EXIT_OK = 0
EXIT_ERROR = 1
_SHA1_RE = re.compile(r"[0-9a-f]{40}")
_CONTRACT_FIELDS = ("model_id", "revision", "preprocessing", "dimension", "normalization", "namespace", "space_id")


class SemanticSelectionError(ValueError):
    """Input rejected. The message names the offending field, id, or contract."""


def _parse_vector(value: Any, owner: str) -> tuple[float, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{owner}: vector must be a non-empty JSON array of numbers")
    numbers: list[float] = []
    for index, item in enumerate(value):
        if isinstance(item, bool) or not isinstance(item, int | float):
            raise ValueError(f"{owner}: vector[{index}] must be a JSON number, got {type(item).__name__}")
        try:
            number = float(item)
        except OverflowError as exc:
            raise ValueError(f"{owner}: vector[{index}] is outside float64 range") from exc
        if not math.isfinite(number):
            raise ValueError(f"{owner}: vector[{index}] is not finite")
        numbers.append(number)
    if math.hypot(*numbers) == 0.0:
        raise ValueError(f"{owner}: zero vector has no direction and cannot be ranked")
    return tuple(numbers)


class EncoderContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model_id: str = Field(min_length=1)
    revision: str = Field(description="Immutable 40-char lowercase hex commit SHA.")
    preprocessing: str = Field(min_length=1)
    dimension: int = Field(ge=1)
    normalization: Literal["l2", "none"]
    namespace: str
    space_id: str = Field(min_length=1)

    @field_validator("revision")
    @classmethod
    def _immutable_revision(cls, value: str) -> str:
        if not _SHA1_RE.fullmatch(value):
            raise ValueError(f"revision must be a 40-char lowercase hex commit SHA, got {value!r}")
        return value

    @field_validator("namespace")
    @classmethod
    def _approved_namespace_only(cls, value: str) -> str:
        if value != APPROVED_CONTEXT_NAMESPACE:
            raise ValueError(
                f"namespace {value!r} is not accepted: only {APPROVED_CONTEXT_NAMESPACE!r} vectors are ranked here; "
                "face or identity embeddings cannot be mixed or ranked by this evaluator"
            )
        return value


class GlobalProtectionScope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["global"]


class QueryProtectionScope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["queries"]
    query_ids: tuple[str, ...] = Field(min_length=1)


class CandidateRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    status: Literal["approved", "denied", "protected"]
    text: str = Field(min_length=1)
    vector: tuple[float, ...]
    protected_scope: GlobalProtectionScope | QueryProtectionScope | None = Field(default=None, discriminator="kind")

    @model_validator(mode="before")
    @classmethod
    def _parse_vector_field(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = {**data, "vector": _parse_vector(data.get("vector"), f"candidate {data.get('id')!r}")}
        return data


class QueryRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    modality: Literal["image", "text"]
    gold_ids: tuple[str, ...]
    vector: tuple[float, ...]

    @model_validator(mode="before")
    @classmethod
    def _parse_vector_field(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = {**data, "vector": _parse_vector(data.get("vector"), f"query {data.get('id')!r}")}
        return data


class PackSelections(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    baseline: dict[str, tuple[str, ...]]
    full_pack: dict[str, tuple[str, ...]]


class SemanticSelectionDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["semantic-selection-eval/v2"]
    description: str = Field(min_length=1)
    query_encoder: EncoderContract
    candidate_encoder: EncoderContract
    candidates: tuple[CandidateRecord, ...]
    queries: tuple[QueryRecord, ...] = Field(min_length=1)
    selections: PackSelections


def _first_duplicate(values: Sequence[str]) -> str | None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            return value
        seen.add(value)
    return None


def _check_vector(vector: tuple[float, ...], contract: EncoderContract, owner: str) -> None:
    if len(vector) != contract.dimension:
        raise SemanticSelectionError(
            f"{owner}: vector length {len(vector)} != dimension {contract.dimension}; "
            "dimensional truncation is not supported, re-embed under the declared contract"
        )
    if contract.normalization == "l2":
        norm = math.hypot(*vector)
        if abs(norm - 1.0) > NORM_TOLERANCE:
            raise SemanticSelectionError(f"{owner}: normalization is 'l2' but vector norm is {norm:.9g}")


def _protected_ids_by_query(doc: SemanticSelectionDocument) -> dict[str, list[str]]:
    return {
        query.id: [
            candidate.id
            for candidate in doc.candidates
            if candidate.status == "protected"
            and (
                isinstance(candidate.protected_scope, GlobalProtectionScope)
                or isinstance(candidate.protected_scope, QueryProtectionScope)
                and query.id in candidate.protected_scope.query_ids
            )
        ]
        for query in doc.queries
    }


def _check_document(doc: SemanticSelectionDocument) -> None:
    query_side, candidate_side = doc.query_encoder, doc.candidate_encoder
    differing = [name for name in _CONTRACT_FIELDS if getattr(query_side, name) != getattr(candidate_side, name)]
    if differing:
        raise SemanticSelectionError(f"encoder contract mismatch between query and candidate sides: {differing} differ")
    if not doc.candidates:
        raise SemanticSelectionError("empty candidate set: at least one candidate is required")

    candidate_ids = [candidate.id for candidate in doc.candidates]
    if duplicate := _first_duplicate(candidate_ids):
        raise SemanticSelectionError(f"duplicate candidate id {duplicate!r}")
    query_ids = [query.id for query in doc.queries]
    if duplicate := _first_duplicate(query_ids):
        raise SemanticSelectionError(f"duplicate query id {duplicate!r}")

    status_by_id = {candidate.id: candidate.status for candidate in doc.candidates}
    for candidate in doc.candidates:
        _check_vector(candidate.vector, query_side, f"candidate {candidate.id!r}")
        scope = candidate.protected_scope
        if candidate.status == "protected" and scope is None:
            raise SemanticSelectionError(f"protected record {candidate.id!r}: explicit protected_scope is required")
        if candidate.status != "protected" and scope is not None:
            raise SemanticSelectionError(
                f"candidate {candidate.id!r}: only protected records may declare protected_scope"
            )
        if isinstance(scope, QueryProtectionScope):
            if duplicate := _first_duplicate(scope.query_ids):
                raise SemanticSelectionError(
                    f"protected record {candidate.id!r}: duplicate scope query id {duplicate!r}"
                )
            unknown = sorted(set(scope.query_ids) - set(query_ids))
            if unknown:
                raise SemanticSelectionError(f"protected record {candidate.id!r}: unknown scope query ids {unknown}")
    protected_by_query = _protected_ids_by_query(doc)
    for query in doc.queries:
        _check_vector(query.vector, query_side, f"query {query.id!r}")
        if duplicate := _first_duplicate(query.gold_ids):
            raise SemanticSelectionError(f"query {query.id!r}: duplicate gold id {duplicate!r}")
        for gold in query.gold_ids:
            if gold not in status_by_id:
                raise SemanticSelectionError(f"query {query.id!r}: unknown gold id {gold!r}")
            if status_by_id[gold] != "approved":
                raise SemanticSelectionError(
                    f"query {query.id!r}: gold id {gold!r} is not an approved candidate (status {status_by_id[gold]!r})"
                )

    for pack_name in PACK_NAMES:
        pack = getattr(doc.selections, pack_name)
        missing = [query_id for query_id in query_ids if query_id not in pack]
        unexpected = sorted(set(pack) - set(query_ids))
        if missing or unexpected:
            raise SemanticSelectionError(
                f"selections.{pack_name} must have exactly one entry per frozen query; "
                f"missing {missing}, unexpected {unexpected}"
            )
        for query_id in query_ids:
            selected = pack[query_id]
            if duplicate := _first_duplicate(selected):
                raise SemanticSelectionError(f"{pack_name} query {query_id!r}: duplicate selected id {duplicate!r}")
            for candidate_id in selected:
                if candidate_id not in status_by_id:
                    raise SemanticSelectionError(
                        f"{pack_name} query {query_id!r}: unknown selected id {candidate_id!r}"
                    )
                if status_by_id[candidate_id] == "denied":
                    raise SemanticSelectionError(
                        f"{pack_name} query {query_id!r}: denied candidate {candidate_id!r} cannot be selected"
                    )
                if status_by_id[candidate_id] == "protected" and candidate_id not in protected_by_query[query_id]:
                    raise SemanticSelectionError(
                        f"{pack_name} query {query_id!r}: protected record {candidate_id!r} is out of scope"
                    )
            for protected_id in protected_by_query[query_id]:
                if protected_id not in selected:
                    raise SemanticSelectionError(
                        f"{pack_name} query {query_id!r}: protected record {protected_id!r} is suppressed; "
                        "every applicable frozen pack must include it"
                    )


def _unit(vector: tuple[float, ...]) -> tuple[float, ...]:
    # EMB-01: cosine direction must survive finite scaling. Computing the norm
    # before scaling can overflow or lose direction at subnormal magnitudes.
    scale = max(abs(component) for component in vector)
    scaled = tuple(component / scale for component in vector)
    norm = math.hypot(*scaled)
    return tuple(component / norm for component in scaled)


def _cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    value = math.fsum(a * b for a, b in zip(left, right, strict=True))
    return min(1.0, max(-1.0, value))


def _evaluate(doc: SemanticSelectionDocument, input_sha256: str) -> dict[str, Any]:
    pool = [(candidate.id, _unit(candidate.vector)) for candidate in doc.candidates if candidate.status == "approved"]
    source_by_id = {candidate.id: candidate.source_id for candidate in doc.candidates}
    rows: list[dict[str, Any]] = []
    for query in doc.queries:
        query_unit = _unit(query.vector)
        ranking = sorted(
            ((candidate_id, _cosine(query_unit, vector)) for candidate_id, vector in pool),
            key=lambda item: (-item[1], item[0]),
        )
        gold = set(query.gold_ids)
        first_gold_rank = next((rank for rank, (cid, _) in enumerate(ranking, 1) if cid in gold), None)
        if not pool:
            status = "no_approved_candidates"
        elif not gold:
            status = "no_relevant"
        else:
            status = "ranked"
        rows.append(
            {
                "query_id": query.id,
                "modality": query.modality,
                "status": status,
                "gold_ids": list(query.gold_ids),
                "ranking": [
                    {"rank": rank, "candidate_id": cid, "source_id": source_by_id[cid], "score": score}
                    for rank, (cid, score) in enumerate(ranking, 1)
                ],
                "top1_hit": bool(ranking) and ranking[0][0] in gold,
                "first_gold_rank": first_gold_rank,
                "reciprocal_rank": 1.0 / first_gold_rank if first_gold_rank else 0.0,
            }
        )

    query_count = len(doc.queries)
    top1_hits = sum(1 for row in rows if row["top1_hit"])
    reciprocal_sum = math.fsum(row["reciprocal_rank"] for row in rows)
    metrics = {
        "query_count": query_count,
        "top1": {"hits": top1_hits, "denominator": query_count, "value": top1_hits / query_count},
        "mrr": {"sum": reciprocal_sum, "denominator": query_count, "value": reciprocal_sum / query_count},
        "no_relevant_query_ids": [row["query_id"] for row in rows if not row["gold_ids"]],
        "no_approved_candidate_query_ids": [
            row["query_id"] for row in rows if row["status"] == "no_approved_candidates"
        ],
    }

    packs: dict[str, dict[str, Any]] = {}
    for pack_name in PACK_NAMES:
        pack = getattr(doc.selections, pack_name)
        packs[pack_name] = {}
        for query in doc.queries:
            gold = set(query.gold_ids)
            selected = list(pack[query.id])
            packs[pack_name][query.id] = {
                "selected_ids": selected,
                "gold_selected_ids": [cid for cid in selected if cid in gold],
            }

    comparison: dict[str, dict[str, Any]] = {}
    for query in doc.queries:
        left = list(doc.selections.baseline[query.id])
        right = list(doc.selections.full_pack[query.id])
        divergence = next((i for i, (a, b) in enumerate(zip(left, right, strict=False)) if a != b), None)
        if divergence is None and len(left) != len(right):
            divergence = min(len(left), len(right))
        comparison[query.id] = {
            "ordered_equal": left == right,
            "first_divergence_index": divergence,
            "added": [cid for cid in right if cid not in left],
            "removed": [cid for cid in left if cid not in right],
        }

    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "input_schema_version": SCHEMA_VERSION,
        "input_sha256": input_sha256,
        "encoder_provenance": {
            "contracts_match": True,
            "query_encoder": doc.query_encoder.model_dump(),
            "candidate_encoder": doc.candidate_encoder.model_dump(),
        },
        "interpretation": {
            "score_meaning": "retrieval relevance only",
            "not_established": ["visual truth", "identity", "consent", "authority"],
        },
        "protected_records": {
            "ids": [candidate.id for candidate in doc.candidates if candidate.status == "protected"],
            "ranked": False,
            "required_in_every_applicable_frozen_pack": True,
            "applicable_ids_by_query": _protected_ids_by_query(doc),
        },
        "metrics": metrics,
        "queries": rows,
        "packs": packs,
        "pack_comparison": comparison,
    }


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SemanticSelectionError(f"duplicate JSON object key {key!r}")
        result[key] = value
    return result


def _summarize(exc: ValidationError) -> str:
    return "; ".join(f"{'.'.join(str(part) for part in err['loc'])}: {err['msg']}" for err in exc.errors())


def evaluate_document(payload: Any, *, input_sha256: str) -> dict[str, Any]:
    """Validate a parsed input document and return the report dict."""
    try:
        doc = SemanticSelectionDocument.model_validate(payload)
    except ValidationError as exc:
        raise SemanticSelectionError(f"invalid semantic-selection input: {_summarize(exc)}") from exc
    _check_document(doc)
    return _evaluate(doc, input_sha256)


def evaluate_bytes(raw: bytes) -> dict[str, Any]:
    """Parse UTF-8 JSON (rejecting duplicate keys) and return the report dict."""
    digest = hashlib.sha256(raw).hexdigest()
    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except UnicodeDecodeError as exc:
        raise SemanticSelectionError(f"input is not UTF-8: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SemanticSelectionError(f"input is not valid JSON: {exc}") from exc
    return evaluate_document(payload, input_sha256=digest)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.eval_harness.semantic_selection_eval",
        description="Offline semantic-selection evaluator over precomputed vectors.",
    )
    parser.add_argument("input", type=Path, help="semantic-selection-eval/v2 JSON document")
    parser.add_argument("--output", type=Path, required=True, help="path for the report JSON")
    args = parser.parse_args(argv)
    try:
        report = evaluate_bytes(args.input.read_bytes())
    except (OSError, SemanticSelectionError) as exc:
        print(f"rejected: {exc}", file=sys.stderr)
        return EXIT_ERROR
    try:
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    except OSError as exc:
        print(f"cannot write report: {exc}", file=sys.stderr)
        return EXIT_ERROR
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
