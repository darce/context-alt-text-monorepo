"""Offline name/phrase-binding evaluator for the IDWEAVE L13 wrong-binding ledger (DESCBAKE-1 B3).

Consumes precomputed proposals only. It never calls a model, a network service, or any
production mutation path. Architecture is unchanged (ADR018): a deterministic CPU rewrite over
the frozen anonymous base plus phrase boxes. A model rewriter stays a deferred challenger, and
this module is benchmark plumbing, not a production choice.

Measurement contract (denominators fixed before any arm is scored; CARD-11, Principle 15):
- Denominators come from the frozen image list and the fixture's gold phrase->person bindings,
  never from what an arm predicted. A missing prediction cannot shrink the denominator.
- Each gold binding receives exactly one outcome, so outcomes partition the gold denominator:
    correct         the predicted person on that phrase equals the gold person
    wrong_person    that phrase was bound to a different person
    wrong_phrase    that phrase is empty, but its gold person was bound to another phrase
    abstained       that phrase is empty and its gold person was named nowhere in the image
    missing_record  no record exists for this arm and image: unknown, never success
                    (CAL-02 unknown is a valid result; Principle 11)
- A wrong_person outcome whose predicted person is the gold person of another phrase in the same
  image carries ``misattributed_to_phrase``, so a cross-person role swap stays visible instead of
  being hidden by set equality over people.
- Prohibited-name additions, unbound-phrase bindings and required-identity omissions are reported
  beside the gold outcomes, never folded into them. A name on a stranger or unnamed person
  (ADR-018 section 13 wrong-name event) is an unbound-phrase binding: it has no gold binding to attach
  to, so it is listed per image and counted as ``unbound_phrase_bindings`` rather than in the gold partition.
- Matching is exact equality on frozen IDs. Phrase text, name order and string similarity are not
  evidence. Embedding similarity is not caption truth or identity (prior attempted path, task brief;
  no embedding or similarity library is imported).

Provenance (PROV-01, GRPH-14): each frozen image declares its own source anonymous-base digest
and generation/reweave IDs. Each prediction must match all three fields for that image.
The report carries these image-keyed sources and the SHA-256 of the input bytes. Lineage is
declared evidence, not a verification of unavailable caption/model bytes.
https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/ml-systems.md#prov-01
https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/graph-theory.md#grph-14

Version 2 replaces the v1 fixture-global ``source`` with required ``frozen_images[].source``;
predictions retain ``source_anonymous_base_digest`` and require ``source_generation_id`` and
``source_reweave_id``. The report replaces global ``source`` with ``image_sources`` keyed by image ID.
V1 is refused: individual caption lineage cannot be recovered from a batch-global value.
Both ``gold_bindings`` and prediction ``bindings`` must be explicit; [] is a measured negative
or abstention, while omission is refused (CAL-02, CARD-03, CARD-11; Principles 15 and 18).
https://github.com/darce/heuristics-canon/blob/v0.26.2/reasoning/designed-unknown.md
https://github.com/darce/heuristics-canon/blob/v0.26.2/reasoning/measurement-integrity.md
Raw error categories may overlap. This diagnostic report supplies no zero-error acceptance gate;
any future gate needs a deduplicated event union and complete gold/prediction coverage.

Per-arm aggregates are reported for every arm with a per-image ledger, never one pooled number
(EVAL-04). A fixture emits no ranking (``ranking`` is null): synthetic fixtures do not declare a winner.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

INPUT_SCHEMA = "name_binding_eval/v2"
REPORT_SCHEMA = "name_binding_eval_report/v2"
GOLD_OUTCOMES = ("correct", "wrong_person", "wrong_phrase", "abstained", "missing_record")
EXIT_OK = 0
EXIT_INVALID_INPUT = 1

_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")


class NameBindingEvalError(ValueError):
    """Fail-closed input contract violation. No report is produced."""


class SourceProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    anonymous_base_digest: str
    generation_id: str = Field(min_length=1)
    reweave_id: str = Field(min_length=1)

    @field_validator("anonymous_base_digest")
    @classmethod
    def _digest_shape(cls, value: str) -> str:
        if not _DIGEST_RE.fullmatch(value):
            raise ValueError("anonymous_base_digest must be 'sha256:' followed by 64 lowercase hex digits")
        return value


class IdentityRoles(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required: list[str] = Field(default_factory=list)
    allowed: list[str] = Field(default_factory=list)
    prohibited: list[str] = Field(default_factory=list)


class Binding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phrase_id: str = Field(min_length=1)
    person_id: str = Field(min_length=1)


class FrozenImage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image_id: str = Field(min_length=1)
    source: SourceProvenance
    phrases: list[str]
    identity_roles: IdentityRoles
    gold_bindings: list[Binding]


class PredictionRecord(BaseModel):
    """One arm's proposal for one frozen image. An empty ``bindings`` list is an explicit all-abstain."""

    model_config = ConfigDict(extra="forbid")

    arm_id: str = Field(min_length=1)
    image_id: str = Field(min_length=1)
    source_anonymous_base_digest: str
    source_generation_id: str = Field(min_length=1)
    source_reweave_id: str = Field(min_length=1)
    bindings: list[Binding]


class NameBindingInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_id: Literal["name_binding_eval/v2"] = Field(alias="schema")
    fixture_id: str = Field(min_length=1)
    arm_ids: list[str]
    frozen_images: list[FrozenImage]
    predictions: list[PredictionRecord] = Field(default_factory=list)


def evaluate_bytes(raw: bytes) -> dict[str, Any]:
    """Validate a ``name_binding_eval/v2`` fixture and score every declared arm."""
    try:
        data = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NameBindingEvalError(f"input is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise NameBindingEvalError("input must be a JSON object")
    try:
        model = NameBindingInput.model_validate(data)
    except ValidationError as exc:
        raise NameBindingEvalError(f"input schema violation: {exc}") from exc
    _check_references(model)
    return _score(model, input_sha256=hashlib.sha256(raw).hexdigest())


def evaluate_file(path: Path | str) -> dict[str, Any]:
    return evaluate_bytes(Path(path).read_bytes())


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.eval_harness.name_binding_eval",
        description="Offline name/phrase-binding ledger over precomputed proposals (no model calls).",
    )
    parser.add_argument("input", type=Path, help="name_binding_eval/v2 fixture (JSON)")
    parser.add_argument("--output", type=Path, required=True, help="report path; written only if the input validates")
    args = parser.parse_args(argv)
    try:
        report = evaluate_file(args.input)
    except (OSError, NameBindingEvalError) as exc:
        print(f"name_binding_eval: refused: {exc}", file=sys.stderr)
        return EXIT_INVALID_INPUT
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    try:
        _write_report(args.output, rendered)
    except OSError as exc:
        print(f"name_binding_eval: cannot write report: {exc}", file=sys.stderr)
        return EXIT_INVALID_INPUT
    return EXIT_OK


def _write_report(output: Path, rendered: str) -> None:
    """Replace only after a complete sibling write; failures leave any prior report intact."""
    temporary: Path | None = None
    try:
        fd, name = tempfile.mkstemp(dir=output.parent, prefix=f".{output.name}.", suffix=".tmp")
        temporary = Path(name)
        os.close(fd)
        temporary.write_text(rendered, encoding="utf-8")
        os.replace(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _reject_duplicates(values: Sequence[str], message: str) -> None:
    if len(set(values)) != len(values):
        raise NameBindingEvalError(message)


def _check_references(model: NameBindingInput) -> None:
    if not model.frozen_images:
        raise NameBindingEvalError("frozen_images must not be empty")
    if not model.arm_ids:
        raise NameBindingEvalError("arm_ids must not be empty")
    _reject_duplicates(model.arm_ids, "duplicate arm_id in arm_ids")
    _reject_duplicates([image.image_id for image in model.frozen_images], "duplicate image_id in frozen_images")
    for image in model.frozen_images:
        _check_image(image)
    images = {image.image_id: image for image in model.frozen_images}
    _check_predictions(model, images)


def _check_image(image: FrozenImage) -> None:
    roles = image.identity_roles
    _reject_duplicates(image.phrases, f"phrases must be unique in image {image.image_id}")
    for name, values in (("required", roles.required), ("allowed", roles.allowed), ("prohibited", roles.prohibited)):
        _reject_duplicates(values, f"duplicate person_id in identity_roles.{name} for image {image.image_id}")
    role_sets = {
        "required": set(roles.required),
        "allowed": set(roles.allowed),
        "prohibited": set(roles.prohibited),
    }
    names = list(role_sets)
    for i, left in enumerate(names):
        for right in names[i + 1 :]:
            if role_sets[left] & role_sets[right]:
                raise NameBindingEvalError(
                    f"identity_roles overlap between {left} and {right} in image {image.image_id}"
                )
    phrases = set(image.phrases)
    gold_by_phrase: dict[str, str] = {}
    for binding in image.gold_bindings:
        if binding.phrase_id not in phrases:
            raise NameBindingEvalError(
                f"gold_bindings reference unknown phrase_id {binding.phrase_id!r} in image {image.image_id}"
            )
        if binding.phrase_id in gold_by_phrase:
            raise NameBindingEvalError(
                f"phrase {binding.phrase_id!r} has more than one gold binding in image {image.image_id}"
            )
        if binding.person_id in role_sets["prohibited"]:
            raise NameBindingEvalError(f"gold binding names a prohibited person in image {image.image_id}")
        if binding.person_id not in role_sets["required"] | role_sets["allowed"]:
            raise NameBindingEvalError(
                f"gold binding person_id {binding.person_id!r} is not declared required or allowed "
                f"in image {image.image_id}"
            )
        gold_by_phrase[binding.phrase_id] = binding.person_id
    gold_people = set(gold_by_phrase.values())
    for person_id in roles.required:
        if person_id not in gold_people:
            raise NameBindingEvalError(f"required person without gold binding {person_id!r} in image {image.image_id}")


def _check_predictions(model: NameBindingInput, images: dict[str, FrozenImage]) -> None:
    arms = set(model.arm_ids)
    seen: set[tuple[str, str]] = set()
    for record in model.predictions:
        if record.image_id not in images:
            raise NameBindingEvalError(f"unknown image_id {record.image_id!r} in predictions")
        if record.arm_id not in arms:
            raise NameBindingEvalError(f"unknown arm_id {record.arm_id!r} in predictions")
        key = (record.arm_id, record.image_id)
        if key in seen:
            raise NameBindingEvalError(f"duplicate prediction record for arm {record.arm_id} image {record.image_id}")
        seen.add(key)
        image = images[record.image_id]
        for field in ("anonymous_base_digest", "generation_id", "reweave_id"):
            if getattr(record, f"source_{field}") != getattr(image.source, field):
                raise NameBindingEvalError(
                    f"source_{field} does not match the frozen image source for arm {record.arm_id} "
                    f"image {record.image_id}"
                )
        roles = image.identity_roles
        declared = set(roles.required) | set(roles.allowed) | set(roles.prohibited)
        phrases = set(image.phrases)
        seen_phrases: set[str] = set()
        for binding in record.bindings:
            if binding.phrase_id not in phrases:
                raise NameBindingEvalError(
                    f"unknown phrase_id {binding.phrase_id!r} for arm {record.arm_id} image {record.image_id}"
                )
            if binding.person_id not in declared:
                raise NameBindingEvalError(
                    f"undeclared person_id {binding.person_id!r} for arm {record.arm_id} image {record.image_id}"
                )
            if binding.phrase_id in seen_phrases:
                raise NameBindingEvalError(
                    f"duplicate phrase_id {binding.phrase_id!r} in record for arm {record.arm_id} "
                    f"image {record.image_id}"
                )
            seen_phrases.add(binding.phrase_id)


def _score(model: NameBindingInput, *, input_sha256: str) -> dict[str, Any]:
    images = model.frozen_images
    predictions = {(record.arm_id, record.image_id): record for record in model.predictions}
    return {
        "schema": REPORT_SCHEMA,
        "input_schema": INPUT_SCHEMA,
        "fixture_id": model.fixture_id,
        "input_sha256": input_sha256,
        "image_sources": {image.image_id: image.source.model_dump() for image in images},
        "frozen_image_count": len(images),
        "gold_binding_count": sum(len(image.gold_bindings) for image in images),
        "required_identity_count": sum(len(image.identity_roles.required) for image in images),
        "arm_ids": list(model.arm_ids),
        "arms": {arm_id: _score_arm(arm_id, images, predictions) for arm_id in model.arm_ids},
        "ranking": None,
        "ranking_reason": "per-arm aggregates over one fixture; no empirical winner is declared",
    }


def _score_arm(
    arm_id: str,
    images: list[FrozenImage],
    predictions: dict[tuple[str, str], PredictionRecord],
) -> dict[str, Any]:
    rows = [_score_image(arm_id, image, predictions.get((arm_id, image.image_id))) for image in images]
    frozen = len(images)
    scored = sum(1 for row in rows if row["record_status"] == "scored")
    gold_count = sum(len(image.gold_bindings) for image in images)
    required_count = sum(len(image.identity_roles.required) for image in images)

    counts = dict.fromkeys(GOLD_OUTCOMES, 0)
    misattributed = 0
    for row in rows:
        for outcome in row["gold_outcomes"]:
            counts[outcome["outcome"]] += 1
            if outcome["outcome"] == "wrong_person" and outcome["misattributed_to_phrase"] is not None:
                misattributed += 1

    prohibited = sum(len(row["prohibited_name_additions"]) for row in rows)
    omissions = sum(len(row["required_identity_omissions"]) for row in rows)
    all_abstain = sum(1 for row in rows if row["all_abstain"])
    status = "complete" if scored == frozen else ("partial" if scored else "no_records")

    return {
        "status": status,
        "frozen_image_count": frozen,
        "scored_image_count": scored,
        "missing_image_count": frozen - scored,
        "coverage": scored / frozen,
        "gold_binding_count": gold_count,
        "gold_outcome_counts": counts,
        "gold_outcome_rates": _rates(counts, gold_count, scored),
        "misattributed_identity_bindings": misattributed,
        "unbound_phrase_bindings": sum(len(row["unbound_phrase_bindings"]) for row in rows),
        "prohibited_name_additions": prohibited,
        "prohibited_name_addition_rate": _ratio(prohibited, frozen, scored),
        "required_identity_count": required_count,
        "required_identity_omissions": omissions,
        "required_identity_omission_rate": _ratio(omissions, required_count, scored),
        "all_abstain_images": all_abstain,
        "all_abstain_image_rate": _ratio(all_abstain, frozen, scored),
        "image_ledger": rows,
    }


def _score_image(
    arm_id: str,
    image: FrozenImage,
    record: PredictionRecord | None,
) -> dict[str, Any]:
    gold_by_phrase = {binding.phrase_id: binding.person_id for binding in image.gold_bindings}
    if record is None:
        return {
            "image_id": image.image_id,
            "arm_id": arm_id,
            "record_status": "missing",
            "all_abstain": None,
            "gold_outcomes": [
                _gold_row(binding.phrase_id, binding.person_id, None, "missing_record", None)
                for binding in image.gold_bindings
            ],
            "unbound_phrase_bindings": [],
            "prohibited_name_additions": [],
            "required_identity_omissions": [],
        }

    predicted_by_phrase = {binding.phrase_id: binding.person_id for binding in record.bindings}
    gold_outcomes = []
    for binding in image.gold_bindings:
        phrase, gold = binding.phrase_id, binding.person_id
        predicted = predicted_by_phrase.get(phrase)
        misattributed_to: str | None = None
        if predicted == gold:
            outcome = "correct"
        elif predicted is not None:
            outcome = "wrong_person"
            misattributed_to = next(
                (other for other, person in gold_by_phrase.items() if other != phrase and person == predicted),
                None,
            )
        else:
            elsewhere = any(
                person == gold and gold_by_phrase.get(other) != gold for other, person in predicted_by_phrase.items()
            )
            outcome = "wrong_phrase" if elsewhere else "abstained"
        gold_outcomes.append(_gold_row(phrase, gold, predicted, outcome, misattributed_to))

    prohibited = set(image.identity_roles.prohibited)
    predicted_people = set(predicted_by_phrase.values())
    return {
        "image_id": image.image_id,
        "arm_id": arm_id,
        "record_status": "scored",
        "all_abstain": not record.bindings,
        "gold_outcomes": gold_outcomes,
        "unbound_phrase_bindings": [
            {"phrase_id": b.phrase_id, "person_id": b.person_id}
            for b in record.bindings
            if b.phrase_id not in gold_by_phrase
        ],
        "prohibited_name_additions": [
            {"phrase_id": b.phrase_id, "person_id": b.person_id} for b in record.bindings if b.person_id in prohibited
        ],
        "required_identity_omissions": [
            person for person in image.identity_roles.required if person not in predicted_people
        ],
    }


def _gold_row(
    phrase_id: str,
    gold_person_id: str,
    predicted_person_id: str | None,
    outcome: str,
    misattributed_to_phrase: str | None,
) -> dict[str, Any]:
    return {
        "phrase_id": phrase_id,
        "gold_person_id": gold_person_id,
        "predicted_person_id": predicted_person_id,
        "outcome": outcome,
        "misattributed_to_phrase": misattributed_to_phrase,
    }


def _rates(counts: dict[str, int], gold_count: int, scored: int) -> dict[str, float] | None:
    if gold_count == 0 or scored == 0:
        return None
    return {outcome: counts[outcome] / gold_count for outcome in GOLD_OUTCOMES}


def _ratio(count: int, denominator: int, scored: int) -> float | None:
    if denominator == 0 or scored == 0:
        return None
    return count / denominator


__all__ = [
    "GOLD_OUTCOMES",
    "INPUT_SCHEMA",
    "REPORT_SCHEMA",
    "NameBindingEvalError",
    "evaluate_bytes",
    "evaluate_file",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
