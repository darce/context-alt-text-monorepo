"""export_map must not synthesise envelope fields (rg-015)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.bench.driver import init_run_dir
from scripts.bench.export_map import export_leg, load_leg_exports
from scripts.bench.score_report import score_head_to_head
from scripts.bench.stack_pair import load_stack_pair
from scripts.bench.tests.conftest import (
    FakeClient,
    golden_entry,
    valid_pair_dict,
    write_pair,
    write_stub_preflight,
)

_ENVELOPE = ("limit", "offset", "total", "data_source")


class BareEnvelopeClient(FakeClient):
    """Upstream returns a bare list / object with no pagination envelope."""

    def media_identities(self, media_ids: list[int]) -> object:
        return [{"identity_id": "i1", "media_id": 1, "bbox": {"x": 1, "y": 1, "width": 2, "height": 2}}]

    def clusters(self, labeled_only: bool = False) -> list[dict]:
        return [{"id": "c1", "label": "Alice Q"}]

    def cluster_members(self, cluster_id: str) -> dict:
        return {"cluster_id": cluster_id, "members": [{"media_id": 1}]}


def test_export_does_not_invent_envelope_fields(tmp_path: Path) -> None:
    run_dir, stack_id = _bare_leg_run(tmp_path)
    export_leg(BareEnvelopeClient(), run_dir, stack_id)
    loaded = load_leg_exports(run_dir, stack_id)
    for name, payload in (
        ("media_identities", loaded.media_identities),
        ("clusters", loaded.clusters),
        ("cluster_members", loaded.cluster_members),
    ):
        _assert_no_synthesised_envelope(payload, name)


def test_load_rejects_export_changed_after_digest_was_recorded(tmp_path: Path) -> None:
    from scripts.bench.stack_pair import BenchError

    run_dir, stack_id = _score_ready_run(tmp_path)
    exports_dir = run_dir / "legs" / stack_id / "exports"
    identities_path = exports_dir / "media_identities.json"
    digest_path = exports_dir / "export_sha256.json"
    original_digests = digest_path.read_bytes()

    identities_path.write_text("[]", encoding="utf-8")
    assert digest_path.read_bytes() == original_digests

    with pytest.raises(BenchError) as exc:
        score_head_to_head(run_dir)
    assert exc.value.code == "export_digest_mismatch"
    assert "media_identities.json" in str(exc.value)


def test_load_rejects_export_missing_from_digest_sidecar(tmp_path: Path) -> None:
    from scripts.bench.stack_pair import BenchError

    run_dir, stack_id = _bare_leg_run(tmp_path)
    export_leg(BareEnvelopeClient(), run_dir, stack_id)
    digest_path = run_dir / "legs" / stack_id / "exports" / "export_sha256.json"
    digests = json.loads(digest_path.read_text(encoding="utf-8"))
    del digests["media_identities.json"]
    digest_path.write_text(json.dumps(digests), encoding="utf-8")

    with pytest.raises(BenchError) as exc:
        load_leg_exports(run_dir, stack_id)
    assert exc.value.code == "export_digest_missing"
    assert "media_identities.json" in str(exc.value)


def _bare_leg_run(tmp_path: Path) -> tuple[Path, str]:
    run_dir = tmp_path / "run"
    stack_id = "acx-dev-insightface"
    leg = run_dir / "legs" / stack_id
    leg.mkdir(parents=True)
    (leg / "cluster_job.json").write_text(json.dumps({"status": "completed"}), encoding="utf-8")
    (leg / "items.jsonl").write_text(
        json.dumps(
            {
                "manifest_media_id": 1,
                "stack_media_id": 1,
                "phase": "analyze",
                "outcome": "ok",
                "image_width": 10,
                "image_height": 10,
                "terminal_ingest_outcome": "success",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return run_dir, stack_id


def _score_ready_run(tmp_path: Path) -> tuple[Path, str]:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "manifest_version": 3,
                "annotation_mode": "exhaustive",
                "roster": ["Alice Q"],
                "entries": [
                    golden_entry(
                        mid,
                        present_identities=["Alice Q"],
                        face_boxes=[
                            {"x": 0.5, "y": 0.5, "w": 0.2, "h": 0.2, "name": "Alice Q", "source": "iptc"}
                        ],
                    )
                    for mid in (1, 2)
                ],
            }
        ),
        encoding="utf-8",
    )
    pair_path = write_pair(
        tmp_path / "pair.yaml",
        valid_pair_dict(accepted_set_floor=0.5),
    )
    pair = load_stack_pair(pair_path)
    run_dir = tmp_path / "score-run"
    init_run_dir(run_dir, pair, manifest_path)

    for endpoint in pair.stacks:
        leg_dir = run_dir / "legs" / endpoint.stack_id
        leg_dir.mkdir(parents=True, exist_ok=True)
        (leg_dir / "cluster_job.json").write_text(json.dumps({"status": "completed"}), encoding="utf-8")
        item_lines = []
        for mid in (1, 2):
            record = {
                "manifest_media_id": mid,
                "manifest_path": f"fixtures/m{mid}.jpg",
                "content_sha256": f"{mid:064x}",
                "stack_media_id": mid,
                "image_width": 10,
                "image_height": 10,
                "phase": "analyze",
                "outcome": "ok",
                "attempt": 1,
                "terminal_ingest_outcome": "success",
            }
            item_lines.extend((json.dumps(record), json.dumps({**record, "phase": "ingest"})))
        (leg_dir / "items.jsonl").write_text("\n".join(item_lines) + "\n", encoding="utf-8")
        write_stub_preflight(run_dir, endpoint.stack_id)
        export_leg(BareEnvelopeClient(), run_dir, endpoint.stack_id)

    return run_dir, pair.stacks[0].stack_id


def _assert_no_synthesised_envelope(payload: object, name: str) -> None:
    if isinstance(payload, list):
        return
    if isinstance(payload, dict):
        # A persist-side cluster_id map is allowed; the values must not grow envelope keys
        # that the upstream object lacked. The top-level persist wrapper must not invent
        # limit/offset/total/data_source from len().
        invented = [k for k in _ENVELOPE if k in payload]
        assert invented == [], f"{name} synthesised {invented}"
        for value in payload.values():
            if isinstance(value, dict):
                invented_inner = [k for k in _ENVELOPE if k in value]
                assert invented_inner == [], f"{name} value synthesised {invented_inner}"


def test_object_envelope_is_rejected() -> None:
    from scripts.bench.export_map import _unwrap_rows
    from scripts.bench.stack_pair import BenchError

    with pytest.raises(BenchError) as exc:
        _unwrap_rows({"data": []}, what="media_identities")
    assert exc.value.code == "export_envelope_invalid"
    with pytest.raises(BenchError) as exc:
        _unwrap_rows({"clusters": [{"id": 1}]}, what="clusters")
    assert exc.value.code == "export_envelope_invalid"


def test_ambiguous_or_unknown_envelope_is_error() -> None:
    from scripts.bench.export_map import _unwrap_rows
    from scripts.bench.stack_pair import BenchError

    with pytest.raises(BenchError) as exc:
        _unwrap_rows({"items": [{"id": 1}]}, what="media_identities")
    assert exc.value.code == "export_envelope_invalid"
    with pytest.raises(BenchError) as exc:
        _unwrap_rows({"data": [], "clusters": []}, what="clusters")
    assert exc.value.code == "export_envelope_invalid"
    rows = _unwrap_rows([{"id": 1}], what="media_identities")
    assert rows == [{"id": 1}]


def test_dict_export_missing_media_identities_is_rejected() -> None:
    from scripts.bench.export_map import _identities_list
    from scripts.bench.stack_pair import BenchError

    with pytest.raises(BenchError) as exc:
        _identities_list({"clusters": []})
    assert exc.value.code == "export_envelope_invalid"


def test_dict_export_missing_clusters_is_rejected() -> None:
    from scripts.bench.export_map import _clusters_list
    from scripts.bench.stack_pair import BenchError

    with pytest.raises(BenchError) as exc:
        _clusters_list({"media_identities": []})
    assert exc.value.code == "export_envelope_invalid"


def test_object_export_is_rejected_not_getattr() -> None:
    from scripts.bench.export_map import _clusters_list, _identities_list
    from scripts.bench.stack_pair import BenchError

    class _Obj:
        media_identities = []
        clusters = []

    with pytest.raises(BenchError) as exc:
        _identities_list(_Obj())
    assert exc.value.code == "export_envelope_invalid"
    with pytest.raises(BenchError) as exc:
        _clusters_list(_Obj())
    assert exc.value.code == "export_envelope_invalid"


def test_non_dict_row_is_rejected() -> None:
    from scripts.bench.export_map import _unwrap_rows
    from scripts.bench.stack_pair import BenchError

    with pytest.raises(BenchError) as exc:
        _unwrap_rows([{"id": 1}, "nope"], what="media_identities")
    assert exc.value.code == "export_envelope_invalid"
