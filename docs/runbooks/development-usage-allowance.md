# Development usage allowance

WordPress forwards `POST /acx/v1/recognition/describe/runs` to
`POST /scene/describe/run`. Backend usage admission raises
`AllowanceExceededError` for a missing, expired, or insufficient entitlement.
`_allowance_exhausted` in
`recognition/interface_adapters/http/deps/usage_admission.py` returns HTTP 402
with `{"detail":{"error":"allowance_exhausted"}}`; WordPress preserves it.
These are Alt Context usage credits shared by recognition and descriptions.
Committed and still-chargeable reservations count against the allowance.
A batch must fit the remaining allowance.

On 2026-10-18, r (`http://localhost:10023`) targeted
`https://auraface.dev.altcontext.com`, tenant
`faefa3dc-e52c-49c4-831b-c053c39d6113`. Its October 18–25 UTC beta period had
allowance 64 and committed usage 56. Ten images reproduced 402; one image was
accepted. An audited development grant raised the total to 1,000, preserving
the 56 used and the expiry, leaving 944 available at verification time.

## Manual development grant

Run in the selected development backend with its configured database. This
command targets only the existing r fixture's dev-auraface stack. It raises
the total period allowance to at least 1,000, preserving usage and expiry.
Repeated runs do not add another 1,000. The application service writes an
audit event in the same transaction; no payment provider is called.

```sh
ssh acx-backend 'docker exec -i acx-dev-auraface-api-1 python -' <<'PY'
import asyncio
import os
from uuid import UUID

from sqlalchemy import select
from db.models import TenantEntitlement
from db.session import async_session_factory
from db.tenant_context import set_tenant_context
from recognition.application.services.tenant_entitlement_service import TenantEntitlementService

TENANT = UUID("faefa3dc-e52c-49c4-831b-c053c39d6113")

async def main():
    if os.environ.get("ACX_ENV") != "dev-auraface":
        raise RuntimeError("Development target required")
    async with async_session_factory() as session:
        await set_tenant_context(session, TENANT)
        # Read columns to avoid retaining a stale ORM entity across the upsert.
        row = (await session.execute(select(
            TenantEntitlement.plan_code, TenantEntitlement.source,
            TenantEntitlement.status, TenantEntitlement.allowance_jobs,
            TenantEntitlement.period_start, TenantEntitlement.period_end,
        ).where(TenantEntitlement.tenant_id == TENANT).with_for_update())).one()
        if row.plan_code != "beta" or row.source == "billing" or str(row.status) != "beta_active":
            raise RuntimeError("Active non-billing beta grant required")
        service = TenantEntitlementService(session=session)
        current = await service.snapshot(TENANT)
        if str(current.status) != "beta_active":
            raise RuntimeError("Current beta period required")
        if row.allowance_jobs < 1000:
            await service.grant_beta(
                TENANT, allowance_jobs=1000,
                allowance_version="dev-manual-v1",
                period_start=row.period_start, period_end=row.period_end,
                source="development-manual",
            )
            await session.commit()
    # Verify persisted state after commit using a fresh session.
    async with async_session_factory() as session:
        await set_tenant_context(session, TENANT)
        state = await TenantEntitlementService(session=session).snapshot(TENANT)
        print({"allowance": state.allowance_jobs, "used": state.used_jobs,
               "remaining_before_reservations": state.allowance_jobs - state.used_jobs,
               "expires": str(state.period_end)})

asyncio.run(asyncio.wait_for(main(), 15))
PY
```

A missing or expired development entitlement needs a deliberate new beta grant
with a fixed, timezone-aware period. Do not use a rolling restart time as the
period start: it can hide earlier usage. `grant_beta` takes a total allowance,
not an increment. Changing `RECOGNITION_PLAN_ALLOWANCES` alone does not rewrite
an existing beta entitlement; it configures plan grants/transitions.

## Description runtime is a separate prerequisite

An accepted run does not prove generation succeeded. Inspect its item results.
Initially the r fixture's dev-auraface API and worker omitted
`ACX_DESCRIPTION_ADAPTER`, selecting `florence_small`; the deployed image
lacked that profile's `torch` and `transformers` dependencies. Raising credits
did not repair this model configuration. The maintained GPU-backed profile is
`gpu_qwen30b`; enabling it requires the target's API and worker configuration,
the endpoint's current authentication mode, snapshots and demand-driven lifecycle wiring.
Follow [the separate description smoke procedure](tenant-onboarding-smoke-test.md)
and [GPU environment deployment](gpu-demo-env-flip.md). A successful face scan
or HTTP 202 is insufficient evidence of working descriptions.

On October 19, both dev-auraface services were configured with `gpu_qwen30b`,
the shared private endpoint, winner routing, and concurrency one. Both mount
`/run/acx` read-only for lifecycle snapshots. The GPU owner's finite test window
confirmed WordPress run `90a469e1-cbc9-4c16-80d2-382863f7ba73` completed with
one final GPU draft and zero errors; attachment alt text was preserved. This
proves execution, not caption quality. Further description runs must respect
the bake-off owner's exclusive GPU windows. The canonical lifecycle publisher
subsequently registered `dev-auraface` in release
`4c8ca686e754c8d209db3d88a6bf582e3d7beec5`. All four producer snapshots were
fresh and trustworthy; controller code, effective units, runtime settings and
PostgreSQL containers were unchanged. This wires AuraFace's queued work into
automatic startup. A separate inference test starting from a stopped GPU has
not been run.

## Automatic development seeding

Recommended integration: an explicitly enabled provisioning step, scoped to an
allowlisted development environment and tenant, calls the same audited
`TenantEntitlementService.grant_beta` once for a fixed period and bounded total.
Repeating provisioning keeps that period and ceiling, and skips a sufficient
grant. Renewal is explicit. Keep real usage accounting and admission enabled.
Do not refill from the browser or on every 402, erase reservations, change
production defaults, or directly update the entitlement table.
This repair does not install automatic refill.

Canon v0.26.2 supports keeping per-caller limits through **Rate-limit and cap
per caller** ([SEC-08], *The Developer's Playbook for LLM Security*, ch. 8;
`heuristics-canon-v0.26.2/lexicons/security.md#sec-08`). The bounded development
grant is an application of that rule to this codebase; the canon does not
prescribe a credit API. The pinned release digests were verified.
