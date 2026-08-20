"""ReferenceFact v4 annotation lineage: per-label provenance + pre-adjudication."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from scripts.eval_harness.manifest import (
    ConfirmationSource,
    FactKind,
    FactPolarity,
    HUMAN_CONFIRMATION_SOURCES,
    PreAdjudicationLabel,
    ReferenceFact,
    load_legacy_manifest,
)


def _golden150_path() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "benchmarks" / "manifests" / "golden150-draft-20260723.json"
        if candidate.is_file():
            return candidate
    raise RuntimeError("cannot locate golden150-draft-20260723.json")


def _v3_payload() -> dict:
    return {
        "text": "a red bicycle",
        "kind": "object",
        "polarity": "true",
        "phrases": ["red bicycle", "red bike"],
        "confirmed_by": "agent",
    }


def _full_payload() -> dict:
    return {
        "text": "two people at a table",
        "kind": "count",
        "polarity": "true",
        "phrases": ["two people", "2 people"],
        "confirmed_by": "operator",
        "annotator_id": "ann-07",
        "annotation_batch": "batch-2026-08-20",
        "annotated_at": "2026-08-20T12:00:00Z",
        "source_pool": "golden-646-pool",
        "pre_adjudication": [
            {
                "annotator_id": "ann-01",
                "polarity": "true",
                "text": "two people at a table",
                "noted_at": "2026-08-19T10:00:00Z",
            },
            {
                "annotator_id": "ann-02",
                "polarity": "false",
                "text": "three people at a table",
                "noted_at": "2026-08-19T10:05:00Z",
            },
        ],
        "adjudicated_by": "sme-03",
        "adjudication_rule": "disagreement-escalate-to-sme",
    }


def test_fully_populated_reference_fact_roundtrips():
    fact = ReferenceFact.model_validate(_full_payload())
    dumped = fact.model_dump(mode="json")
    again = ReferenceFact.model_validate(dumped)
    assert again.model_dump(mode="json") == dumped
    assert again.annotator_id == "ann-07"
    assert again.annotation_batch == "batch-2026-08-20"
    assert again.annotated_at == "2026-08-20T12:00:00Z"
    assert again.source_pool == "golden-646-pool"
    assert again.adjudicated_by == "sme-03"
    assert again.adjudication_rule == "disagreement-escalate-to-sme"
    assert len(again.pre_adjudication) == 2


def test_v3_shape_parses_with_empty_lineage():
    fact = ReferenceFact.model_validate(_v3_payload())
    assert fact.text == "a red bicycle"
    assert fact.kind is FactKind.OBJECT
    assert fact.polarity is FactPolarity.TRUE
    assert fact.phrases == ["red bicycle", "red bike"]
    assert fact.confirmed_by is ConfirmationSource.AGENT
    assert fact.annotator_id is None
    assert fact.annotation_batch is None
    assert fact.annotated_at is None
    assert fact.source_pool is None
    assert fact.pre_adjudication == []
    assert fact.adjudicated_by is None
    assert fact.adjudication_rule is None


def test_disagreement_survives_adjudication():
    originals = [
        PreAdjudicationLabel(
            annotator_id="ann-01",
            polarity=FactPolarity.TRUE,
            text="wearing a red hat",
            noted_at="2026-08-19T09:00:00Z",
        ),
        PreAdjudicationLabel(
            annotator_id="ann-02",
            polarity=FactPolarity.FALSE,
            text="wearing a red hat",
            noted_at="2026-08-19T09:01:00Z",
        ),
    ]
    fact = ReferenceFact(
        text="wearing a red hat",
        kind=FactKind.ATTRIBUTE,
        polarity=FactPolarity.TRUE,
        phrases=["red hat"],
        confirmed_by="operator",
        annotator_id="sme-03",
        pre_adjudication=list(originals),
        adjudicated_by="sme-03",
        adjudication_rule="disagreement-escalate-to-sme",
    )
    assert len(fact.pre_adjudication) == 2
    assert fact.pre_adjudication[0].annotator_id == "ann-01"
    assert fact.pre_adjudication[0].polarity is FactPolarity.TRUE
    assert fact.pre_adjudication[1].annotator_id == "ann-02"
    assert fact.pre_adjudication[1].polarity is FactPolarity.FALSE
    assert fact.polarity is FactPolarity.TRUE
    assert fact.polarity != fact.pre_adjudication[1].polarity
    again = ReferenceFact.model_validate(fact.model_dump(mode="json"))
    surviving = [lbl.model_dump(mode="json") for lbl in again.pre_adjudication]
    expected = [lbl.model_dump(mode="json") for lbl in originals]
    assert surviving == expected
    overwritten = [lbl for lbl in again.pre_adjudication if lbl.polarity is not FactPolarity.TRUE]
    assert overwritten, "pre-adjudication disagreement must survive; overwrite would empty this"


def test_human_confirmed_fact_without_annotator_id_raises():
    with pytest.raises(ValidationError, match="annotator_id"):
        ReferenceFact(
            text="a red bicycle",
            kind=FactKind.OBJECT,
            polarity=FactPolarity.TRUE,
            phrases=["red bicycle"],
            confirmed_by="operator",
        )


def test_human_confirmation_sources_are_an_explicit_allowlist():
    named_human = frozenset({ConfirmationSource.OPERATOR})
    named_machine = frozenset({ConfirmationSource.AGENT})
    assert HUMAN_CONFIRMATION_SOURCES == named_human
    assert ConfirmationSource.AGENT not in HUMAN_CONFIRMATION_SOURCES
    leftover = set(ConfirmationSource) - named_human - named_machine
    assert leftover == set(), (
        f"ConfirmationSource members {sorted(m.value for m in leftover)} must be "
        "named as human gold or machine; do not inherit human via complement-of-AGENT"
    )


def test_unknown_confirmation_source_raises_not_promoted_to_human():
    # annotator_id is present so a != AGENT string-promotion would accept this.
    with pytest.raises(ValidationError, match="operatr") as exc_info:
        ReferenceFact(
            text="a red bicycle",
            kind=FactKind.OBJECT,
            polarity=FactPolarity.TRUE,
            phrases=["red bicycle"],
            confirmed_by="operatr",
            annotator_id="ann-01",
        )
    assert "annotator_id" not in str(exc_info.value)


def test_golden150_draft_parses_with_backfilled_fact_annotators():
    path = _golden150_path()
    manifest = load_legacy_manifest(str(path))
    entry = next(row for row in manifest.entries if row.media_id == 648)
    assert len(entry.reference_facts) == 2
    assert all(fact.confirmed_by is ConfirmationSource.OPERATOR for fact in entry.reference_facts)
    assert all(fact.annotator_id == "pre-program-operator" for fact in entry.reference_facts)
