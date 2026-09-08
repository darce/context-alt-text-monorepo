"""WBUX-4 INT-01a: per-item drafts read route.

A completed bulk run's generated drafts must be reachable by the operator.
This exercises the GET /scene/describe/run/{id}/items endpoint end to end.
"""

from __future__ import annotations

import asyncio
import uuid

import scene.interface_adapters.http.routers.describe_run as describe_run_mod
from scene.application.describe_run_repository import DescribeRunRepository
from scene.domain.describe_run import DescribeItemStatus
from scene.domain.description import DescriptionResultTier
from scene.tests.test_describe_run_worker import TENANT_ID, _client, _submit


def _no_worker(monkeypatch):
    async def _noop(**_):
        return None

    monkeypatch.setattr(describe_run_mod, "run_describe_job", _noop)


def test_items_route_returns_persisted_drafts(monkeypatch):
    _no_worker(monkeypatch)
    with _client() as (client, sf):
        run_id = _submit(client, [70, 71]).json()["run_id"]

        async def seed():
            async with sf() as s:
                repo = DescribeRunRepository(s)
                await repo.record_item_result(
                    tenant_id=TENANT_ID,
                    run_id=uuid.UUID(run_id),
                    media_id=70,
                    alt_text_draft="A dog resting on green grass",
                    caption="a dog on grass",
                    provenance={"adapter": "florence", "model_id": "florence-2"},
                )
                # S1-01: drive real terminal item statuses so the serialized
                # `status` field is exercised with a mixed (completed/failed) run.
                await repo.mark_item(
                    tenant_id=TENANT_ID,
                    run_id=uuid.UUID(run_id),
                    media_id=70,
                    status=DescribeItemStatus.COMPLETED,
                )
                await repo.mark_item(
                    tenant_id=TENANT_ID,
                    run_id=uuid.UUID(run_id),
                    media_id=71,
                    status=DescribeItemStatus.FAILED,
                    error_message="adapter boom",
                )
                await s.commit()

        asyncio.run(seed())

        resp = client.get(f"/scene/describe/run/{run_id}/items")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["run_id"] == run_id
        items = {i["media_id"]: i for i in body["items"]}
        assert set(items) == {70, 71}
        assert items[70]["alt_text_draft"] == "A dog resting on green grass"
        assert items[70]["caption"] == "a dog on grass"
        assert items[70]["provenance"] == {"adapter": "florence", "model_id": "florence-2"}
        # S1-01: terminal statuses serialize and mixed outcomes round-trip.
        assert items[70]["status"] == DescribeItemStatus.COMPLETED
        assert items[71]["status"] == DescribeItemStatus.FAILED
        # item 71 never described: draft is null, not fabricated.
        assert items[71]["alt_text_draft"] is None


def test_items_route_orders_by_media_id(monkeypatch):
    """S1-02: the items payload is ordered by media_id ascending regardless of
    submit order, locking the media-id ordering contract for the WP consumer."""
    _no_worker(monkeypatch)
    with _client() as (client, _sf):
        media_ids = [73, 71, 72]  # deliberately out of natural order
        run_id = _submit(client, media_ids).json()["run_id"]

        resp = client.get(f"/scene/describe/run/{run_id}/items")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert [i["media_id"] for i in body["items"]] == sorted(media_ids)


def test_items_route_returns_persisted_gpu_and_provisional_tiers(monkeypatch):
    _no_worker(monkeypatch)
    with _client() as (client, sf):
        run_id = _submit(client, [80, 81]).json()["run_id"]

        async def seed():
            async with sf() as s:
                repo = DescribeRunRepository(s)
                for media_id, tier in (
                    (80, DescriptionResultTier.FINAL_GPU),
                    (81, DescriptionResultTier.PROVISIONAL_CPU),
                ):
                    await repo.record_item_result(
                        tenant_id=TENANT_ID,
                        run_id=uuid.UUID(run_id),
                        media_id=media_id,
                        alt_text_draft=f"draft {media_id}",
                        caption=f"caption {media_id}",
                        provenance={"adapter": "gpu", "model_id": "org/model@revision"},
                        tier=tier,
                    )
                    await repo.mark_item(
                        tenant_id=TENANT_ID,
                        run_id=uuid.UUID(run_id),
                        media_id=media_id,
                        status=DescribeItemStatus.COMPLETED,
                    )
                await s.commit()

        asyncio.run(seed())

        resp = client.get(f"/scene/describe/run/{run_id}/items")
        assert resp.status_code == 200, resp.text
        items = {item["media_id"]: item for item in resp.json()["items"]}
        assert items[80]["tier"] == "final_gpu"
        assert items[81]["tier"] == "provisional_cpu"
        assert items[80]["result_generation"] == 1
        assert items[81]["result_generation"] == 1


def test_items_route_404_for_unknown_run(monkeypatch):
    _no_worker(monkeypatch)
    with _client() as (client, _sf):
        missing = uuid.uuid4()
        resp = client.get(f"/scene/describe/run/{missing}/items")
        assert resp.status_code == 404
