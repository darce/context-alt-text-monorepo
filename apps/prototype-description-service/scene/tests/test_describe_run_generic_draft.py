"""Bulk describe hands the worker an unnamed draft even on cache hits."""

from __future__ import annotations

from types import SimpleNamespace

from scene.interface_adapters.http.routers.describe_run import _worker_generic_draft


def test_cache_hit_passes_unnamed_generic_draft_not_realized_names() -> None:
    response = SimpleNamespace(
        alt_text_draft="Ada stands by a red flower.",
        generic_draft="A woman stands by a red flower.",
    )

    assert _worker_generic_draft(response) == "A woman stands by a red flower."


def test_fresh_response_without_generic_draft_uses_alt_text_draft() -> None:
    response = SimpleNamespace(alt_text_draft="A woman stands by a red flower.", generic_draft=None)

    assert _worker_generic_draft(response) == "A woman stands by a red flower."
