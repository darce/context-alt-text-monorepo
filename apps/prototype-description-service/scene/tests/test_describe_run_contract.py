"""Scene describe-run shared-contract parity."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scene.application.describe_run_repository import DescribeRunRepository
from scene.interface_adapters.http.routers.describe_run import _progress_payload
from scene.interface_adapters.http.schemas.responses import DescribeRunResponse
from scene.tests.test_describe_run_repository import _sessionmaker

TENANT_ID = "00000000-0000-0000-0000-0000000000dd"
REPO_ROOT = Path(__file__).resolve().parents[4]
SCHEMA_ROOT = REPO_ROOT / "packages" / "shared-contracts" / "schemas"


def _schema(name: str) -> dict:
    return json.loads((SCHEMA_ROOT / name).read_text(encoding="utf-8"))


def test_describe_run_response_matches_shared_schema():
    payload = {
        "tenant_id": TENANT_ID,
        "run_id": "11111111-1111-1111-1111-111111111111",
        "status": "pending",
        "phase": "queued",
        "completed": 0,
        "failed": 0,
        "skipped": 0,
        "total": 3,
        "cancel_requested": False,
        "gpu_state": None,
    }
    DescribeRunResponse.model_validate(payload)
    jsonschema.validate(payload, _schema("scene-describe-run.schema.json"))


def test_describe_progress_payload_matches_shared_schema():
    import asyncio
    import uuid

    async def body():
        engine, sf = await _sessionmaker()
        tenant = uuid.UUID(TENANT_ID)
        async with sf() as session:
            repo = DescribeRunRepository(session)
            run_id = await repo.create_run(tenant_id=tenant, media_ids=[1])
            run = await repo.get_run(tenant_id=tenant, run_id=run_id)
        assert run is not None
        jsonschema.validate(_progress_payload(run), _schema("scene-describe-progress.schema.json"))
        await engine.dispose()

    asyncio.run(body())
