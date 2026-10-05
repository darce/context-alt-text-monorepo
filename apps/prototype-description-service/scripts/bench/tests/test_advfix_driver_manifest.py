"""Paired runs validate the exact manifest snapshot before any ingestion."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts.bench.driver import run_pair
from scripts.bench.stack_pair import BenchError, load_stack_pair
from scripts.bench.tests.conftest import FakeClient, write_hashed_manifest, write_pair


def _fresh_reset_evidence(pair) -> dict[str, dict[str, object]]:
    completed_at = datetime.now(UTC).isoformat()
    return {
        endpoint.stack_id: {
            "reset_attested_by": "bench test operator",
            "reset_reference": "FIR23-STACK runbook reset",
            "reset_completed_at": completed_at,
            "prior_run_identity_rows_empty": True,
        }
        for endpoint in pair.stacks
    }


def test_run_pair_rejects_analyze_id_collision_before_ingest(tmp_path: Path) -> None:
    images = tmp_path / "images"
    manifest = write_hashed_manifest(tmp_path / "manifest.json", images, [1, 1_000_001])
    pair = load_stack_pair(write_pair(tmp_path / "pair.yaml"))
    clients = {endpoint.stack_id: FakeClient() for endpoint in pair.stacks}
    out = tmp_path / "out"

    with pytest.raises(BenchError) as exc:
        run_pair(
            pair,
            manifest_path=manifest,
            images_dir=images,
            out_dir=out,
            clients=clients,
            skip_preflight=True,
            pre_run_reset_by_stack=_fresh_reset_evidence(pair),
        )

    assert exc.value.code == "media_id_exceeds_analyze_ceiling"
    assert all(not client.analyze_calls for client in clients.values())
    assert not (out / "run.json").exists()
