"""Scene describe-run shared-contract parity."""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

from jsonschema import Draft7Validator, FormatChecker

from scene.application.describe_run_repository import DescribeRunRepository
from scene.interface_adapters.http.routers.describe_run import _run_response
from scene.tests.test_describe_run_repository import _sessionmaker

TENANT_ID = "00000000-0000-0000-0000-0000000000dd"
REPO_ROOT = Path(__file__).resolve().parents[4]
SCHEMA_ROOT = REPO_ROOT / "packages" / "shared-contracts" / "schemas"


def _schema(name: str) -> dict:
    return json.loads((SCHEMA_ROOT / name).read_text(encoding="utf-8"))


def _validate(instance: dict, name: str) -> None:
    Draft7Validator(_schema(name), format_checker=FormatChecker()).validate(instance)


def test_run_response_matches_shared_schema_via_actual_builder():
    async def body():
        engine, sf = await _sessionmaker()
        tenant = uuid.UUID(TENANT_ID)
        async with sf() as session:
            repo = DescribeRunRepository(session)
            run_id = await repo.create_run(tenant_id=tenant, media_ids=[1, 2, 3])
            run = await repo.get_run(tenant_id=tenant, run_id=run_id)
        assert run is not None
        payload = _run_response(run).model_dump(mode="json")
        assert "eta_seconds" in payload
        assert payload["eta_seconds"] is None  # fresh run: no honest estimate yet
        _validate(payload, "scene-describe-run.schema.json")
        await engine.dispose()

    asyncio.run(body())
