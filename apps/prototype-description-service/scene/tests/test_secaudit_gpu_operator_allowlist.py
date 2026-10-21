"""Local reference-monitor checks for the shared GPU operator allowlist."""

from pathlib import Path

import pytest

from recognition.interface_adapters.http.deps.auth import AuthContext
from scene.tests.test_gpu_router import _client

TENANT = "abcdefab-1234-5678-90ab-abcdefabcdef"
OTHER = "22222222-2222-2222-2222-222222222222"


@pytest.mark.asyncio
@pytest.mark.parametrize("configured", [None, "", "   ", OTHER, f"{TENANT},not-a-uuid", f"{TENANT},"])
async def test_unlisted_or_invalid_config_denies_without_writing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture,
    configured: str | None,
) -> None:
    auth = AuthContext(token="test", tenant_claim=TENANT, enabled=True)
    async with _client(monkeypatch, tmp_path, auth=auth) as (client, _, _, intent):
        if configured is None:
            monkeypatch.delenv("ACX_GPU_OPERATOR_TENANT_IDS", raising=False)
        else:
            monkeypatch.setenv("ACX_GPU_OPERATOR_TENANT_IDS", configured)
        response = await client.post("/scene/gpu/intent", json={"action": "stop", "ttl_seconds": 7200})
        assert response.status_code == 403
        assert response.json()["detail"] == "gpu_control_forbidden"
        assert not intent.exists()
    if configured and ("not-a-uuid" in configured or configured.endswith(",")):
        errors = [record for record in caplog.records if record.levelname == "ERROR"]
        assert len(errors) == 1
        assert errors[0].getMessage() == "Invalid ACX_GPU_OPERATOR_TENANT_IDS configuration"
        assert configured not in errors[0].getMessage()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("claim", "admin", "enabled", "tier", "expected"),
    [
        (TENANT.upper(), False, True, None, 202),
        (None, True, True, None, 202),
        (TENANT, False, False, None, 202),
        (TENANT, False, True, "demo", 403),
        (OTHER, True, True, None, 403),
    ],
)
async def test_operator_gate_preserves_prior_checks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, claim: str | None,
    admin: bool, enabled: bool, tier: str | None, expected: int,
) -> None:
    auth = AuthContext(
        token="test", tenant_claim=claim, enabled=enabled,
        is_admin=admin, rate_limit_tier=tier,
    )
    async with _client(monkeypatch, tmp_path, auth=auth) as (client, _, _, intent):
        monkeypatch.setenv("ACX_GPU_OPERATOR_TENANT_IDS", f"  {OTHER}, {TENANT.upper()}  ")
        if claim == OTHER:
            monkeypatch.setenv("ACX_GPU_OPERATOR_TENANT_IDS", TENANT)
        response = await client.post("/scene/gpu/intent", json={"action": "start"})
        assert response.status_code == expected
        assert intent.exists() is (expected == 202)
        if expected == 403:
            assert response.json()["detail"] == "gpu_control_forbidden"


@pytest.mark.asyncio
async def test_allowlist_is_reloaded_for_each_request(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    auth = AuthContext(token="test", tenant_claim=TENANT, enabled=True)
    async with _client(monkeypatch, tmp_path, auth=auth) as (client, _, _, intent):
        monkeypatch.setenv("ACX_GPU_OPERATOR_TENANT_IDS", TENANT)
        accepted = await client.post("/scene/gpu/intent", json={"action": "start"})
        assert accepted.status_code == 202
        original = intent.read_bytes()
        monkeypatch.delenv("ACX_GPU_OPERATOR_TENANT_IDS")
        denied = await client.post("/scene/gpu/intent", json={"action": "stop"})
        assert denied.status_code == 403
        assert intent.read_bytes() == original
        assert (await client.get("/scene/gpu/status")).status_code == 200
