"""Bulk describe hands the worker an unnamed draft even on cache hits."""

from __future__ import annotations

from types import SimpleNamespace

from scene.application.describe_run_worker import DescribeItemOutcome
from scene.application.identity_merge import NamingStatus
from scene.interface_adapters.http.routers.describe_run import (
    _worker_draft_is_final,
    _worker_generic_draft,
)

FINISHED_DRAFT = "A woman stands by a red flower. Pictured from left: Ada."
GENERIC_DRAFT = "A woman stands by a red flower."


def test_cache_hit_passes_unnamed_generic_draft_not_realized_names() -> None:
    response = SimpleNamespace(
        alt_text_draft="Ada stands by a red flower.",
        generic_draft=GENERIC_DRAFT,
    )

    assert _worker_generic_draft(response) == GENERIC_DRAFT


def test_fresh_response_without_generic_draft_uses_alt_text_draft() -> None:
    response = SimpleNamespace(alt_text_draft=GENERIC_DRAFT, generic_draft=None)

    assert _worker_generic_draft(response) == GENERIC_DRAFT
    assert _worker_draft_is_final(response) is False


def test_cached_applied_draft_marks_outcome_final() -> None:
    response = SimpleNamespace(
        alt_text_draft=FINISHED_DRAFT,
        generic_draft=None,
        naming_provenance=SimpleNamespace(status=NamingStatus.APPLIED),
    )
    outcome = DescribeItemOutcome(
        alt_text_draft=_worker_generic_draft(response),
        draft_is_final=_worker_draft_is_final(response),
    )

    assert outcome.draft_is_final is True
    assert outcome.alt_text_draft == FINISHED_DRAFT == response.alt_text_draft


def test_generic_draft_present_marks_outcome_not_final() -> None:
    response = SimpleNamespace(
        alt_text_draft=FINISHED_DRAFT,
        generic_draft=GENERIC_DRAFT,
        naming_provenance=SimpleNamespace(status=NamingStatus.APPLIED),
    )
    outcome = DescribeItemOutcome(
        alt_text_draft=_worker_generic_draft(response),
        draft_is_final=_worker_draft_is_final(response),
    )

    assert outcome.draft_is_final is False
    assert outcome.alt_text_draft == GENERIC_DRAFT
