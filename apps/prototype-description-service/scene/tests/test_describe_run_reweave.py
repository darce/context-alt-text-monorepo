"""Saved run proposals use current curation without inference or generation writes."""

from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from io import BytesIO
from types import SimpleNamespace

import pytest
from PIL import Image

from db.models.scene import DescribeRunItem
from db.models.tenant import Tenant
from scene.application import naming_preview_service
from scene.application.describe_run_repository import DescribeRunRepository
from scene.application.describe_run_worker import DescribeItemOutcome, _apply_naming_preview
from scene.application.description_repository import ImageDescriptionRepository
from scene.application.hashing import compute_context_hash
from scene.application.identity_merge import join
from scene.application.identity_merge.merge import ConfirmedFace, NormalizedBox
from scene.tests.test_describe_run_worker import TENANT_ID, _client

GENERIC = "A woman waves."
FACE_ID = uuid.UUID("00000000-0000-0000-0000-000000000011")
CLUSTER_ID = uuid.UUID("00000000-0000-0000-0000-000000000012")
ROSTER_ID = uuid.UUID("00000000-0000-0000-0000-000000000013")
BOX = NormalizedBox(0.1, 0.1, 0.1, 0.1)
BASE = {
    "version": 1,
    "caption": GENERIC,
    "image_hash": "a" * 64,
    "width": 100,
    "height": 100,
    "phrase_boxes": [{"phrase": "A woman", "span": [0, 7], "box": [0, 0, 0.8, 0.9]}],
}


def _seed(sf, *, stored: str, agreement: bool = True, basis: dict | None = BASE):
    async def seed():
        async with sf() as session:
            tenant = await session.get(Tenant, TENANT_ID)
            tenant.naming_agreement_enabled = agreement
            repo = DescribeRunRepository(session)
            run_id = await repo.create_run(tenant_id=TENANT_ID, media_ids=[71], recognition_enabled=True)
            provenance = {"image_hash": "a" * 64}
            if basis is not None:
                provenance["naming_base"] = basis
            await repo.record_item_result(
                tenant_id=TENANT_ID,
                run_id=run_id,
                media_id=71,
                alt_text_draft=stored,
                caption=GENERIC,
                provenance=provenance,
            )
            item = (await repo.list_run_items(tenant_id=TENANT_ID, run_id=run_id))[0]
            item.status = "completed"
            await session.commit()
            return run_id

    return asyncio.run(seed())


def _install_faces(monkeypatch, *, label: str | None, unknown: bool = False):
    faces = [ConfirmedFace(FACE_ID, CLUSTER_ID, ROSTER_ID, label, 0.99, BOX)] if label is not None else []

    async def confirmed(*args, **kwargs):
        assert kwargs["tenant_id"] == TENANT_ID
        assert kwargs["media_id"] == 71
        return faces

    async def suppressed(*args, **kwargs):
        return frozenset()

    async def detected(*args, **kwargs):
        result = [SimpleNamespace(identity_id=FACE_ID, box=BOX)]
        if unknown:
            result.append(SimpleNamespace(identity_id=uuid.uuid4(), box=NormalizedBox(0.5, 0.1, 0.1, 0.1)))
        return result

    monkeypatch.setattr(naming_preview_service, "load_confirmed_faces", confirmed)
    monkeypatch.setattr(naming_preview_service, "load_suppressed_roster_ids", suppressed)
    monkeypatch.setattr(join, "load_detected_faces", detected, raising=False)


@pytest.mark.parametrize(
    ("stored", "label", "agreement", "expected"),
    [
        (GENERIC, "Ada", True, "Ada waves."),
        ("Former name waves.", "Ada", True, "Ada waves."),
        ("Former name waves.", None, True, GENERIC),
        ("Former name waves.", "Ada", False, GENERIC),
    ],
)
def test_saved_proposal_reweaves_current_identity_without_changing_generation(
    monkeypatch, stored, label, agreement, expected
):
    _install_faces(monkeypatch, label=label)
    with _client() as (client, sf):
        run_id = _seed(sf, stored=stored, agreement=agreement)
        response = client.get(f"/scene/describe/run/{run_id}/items")
        assert response.status_code == 200, response.text
        item = response.json()["items"][0]
        assert item["alt_text_draft"] == expected
        assert item["provenance"]["naming_refresh"]["status"] == "current"

        async def unchanged():
            async with sf() as session:
                row = (await DescribeRunRepository(session).list_run_items(tenant_id=TENANT_ID, run_id=run_id))[0]
                assert isinstance(row, DescribeRunItem)
                assert row.alt_text_draft == stored
                assert row.provenance["naming_base"] == BASE
                assert row.result_generation == 1

        asyncio.run(unchanged())


def test_unknown_second_face_prevents_ambiguous_grounded_name(monkeypatch):
    _install_faces(monkeypatch, label="Ada", unknown=True)
    with _client() as (client, sf):
        run_id = _seed(sf, stored="Former name waves.")
        response = client.get(f"/scene/describe/run/{run_id}/items")
        assert response.status_code == 200, response.text
        assert response.json()["items"][0]["alt_text_draft"] == GENERIC


def test_worker_preserves_original_replay_inputs_before_naming_or_lookup_failure():
    image = BytesIO()
    Image.new("RGB", (100, 100)).save(image, format="PNG")
    image_bytes = image.getvalue()
    outcome = DescribeItemOutcome(alt_text_draft=GENERIC, caption=GENERIC)
    updated = asyncio.run(
        _apply_naming_preview(
            enabled=True,
            session=None,
            tenant=None,
            tenant_id=TENANT_ID,
            media_id=71,
            image_bytes=image_bytes,
            outcome=outcome,
            naming_inputs=None,
            item_started=time.monotonic(),
            item_envelope=10,
        )
    )
    base = updated.provenance.get("naming_base")
    assert base is not None
    assert base["caption"] == GENERIC
    assert base["width"] == base["height"] == 100
    assert base["image_hash"] == hashlib.sha256(image_bytes).hexdigest()
    assert base["phrase_boxes"] == []


def test_legacy_proposal_uses_exact_original_cache_and_verified_image(monkeypatch):
    _install_faces(monkeypatch, label="Ada")
    provenance = {
        "image_hash": "a" * 64,
        "adapter": "gpu_remote",
        "model_id": "original-model",
        "model_version": "original-version",
        "prompt_or_task_version": "original-prompt",
        "context_hash": compute_context_hash(None),
    }
    calls = []

    async def cached(self, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(visual_facts={"caption": GENERIC}, phrase_boxes=BASE["phrase_boxes"])

    monkeypatch.setattr(ImageDescriptionRepository, "get_by_cache_key", cached)
    with _client() as (client, sf):
        run_id = _seed(sf, stored=GENERIC, basis=None)

        async def metadata():
            async with sf() as session:
                row = (await DescribeRunRepository(session).list_run_items(tenant_id=TENANT_ID, run_id=run_id))[0]
                row.provenance = provenance
                await session.commit()

        asyncio.run(metadata())
        response = client.post(
            f"/scene/describe/run/{run_id}/items/preview",
            json={
                "images": [
                    {
                        "media_id": 71,
                        "image_hash": "a" * 64,
                        "width": 100,
                        "height": 100,
                    }
                ]
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["items"][0]["alt_text_draft"] == "Ada waves."
        assert calls == [{"tenant_id": TENANT_ID, **provenance}]

        wrong = client.post(
            f"/scene/describe/run/{run_id}/items/preview",
            json={
                "images": [
                    {
                        "media_id": 71,
                        "image_hash": "b" * 64,
                        "width": 100,
                        "height": 100,
                    }
                ]
            },
        )
        assert wrong.status_code == 200
        assert wrong.json()["items"][0]["provenance"]["naming_refresh"]["status"] == "unavailable"
        assert len(calls) == 1


def test_preview_rejects_evidence_outside_tenant_run(monkeypatch):
    _install_faces(monkeypatch, label="Ada")
    with _client() as (client, sf):
        run_id = _seed(sf, stored=GENERIC)
        response = client.post(
            f"/scene/describe/run/{run_id}/items/preview",
            json={
                "images": [
                    {
                        "media_id": 99,
                        "image_hash": "a" * 64,
                        "width": 100,
                        "height": 100,
                    }
                ]
            },
        )
        assert response.status_code == 400
