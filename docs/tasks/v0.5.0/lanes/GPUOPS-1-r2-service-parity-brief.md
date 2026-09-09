# GPUOPS-1-R2. Service intent parity and enforced status staleness

Fix wave lane. Base: `feature/gpuops-1`. Owned files only:
`apps/prototype-description-service/scene/application/gpu_intent.py`,
`apps/prototype-description-service/scene/interface_adapters/http/routers/gpu.py`,
`scene/tests/test_gpu_intent.py`, `scene/tests/test_gpu_router.py`.

Read `docs/workbay/contracts/gpu-lifecycle.md` and
`packages/shared-contracts/schemas/scene-gpu-status.schema.json` for the frozen contract.
**Do not edit anything under `docs/workbay/`** — the sandbox cannot round-trip those paths.

## Defects to close

**M-03 — `OverflowError` escapes as a 500.** `read_gpu_intent()` documents that malformed
files return `None`, but `requested_at + timedelta(seconds=ttl_seconds)` raises
`OverflowError` for extreme-but-parseable values, and nothing catches it, so
`GET /scene/gpu/status` 500s instead of falling back to `auto`. Reject out-of-range
timestamp arithmetic (or catch `OverflowError`) inside the malformed-payload path. Cover
both the reader boundary and the route.

**M-06 — reader parity gap.** The service reader coerces timezone-naive timestamps to UTC
while the lifecycle reader rejects the same payload as malformed. The status API therefore
advertises an active intent the controller ignores. Reject naive timestamps in the service
reader and add a parity test that feeds the *same* payload to both readers and asserts they
agree.

**M-07 — unparsed date strings copied through the boundary.** `_gpu_state_response()`
copies lifecycle date fields into `str | None` response fields without parsing, so a
corrupt-but-fresh state payload returns 200 with `intent_expires_at="not-a-date"`, in
violation of the shared schema's `date-time` requirement. Parse and validate additive
timestamps at the boundary; null an invalid value (or mark the snapshot unknown) rather
than passing it through. This is rg-015: a boundary adapter must not invent or launder
contract metadata.

**CANON-05 — the status endpoint reports staleness but does not enforce it.**
`gpu-state.json` is written by the reaper itself, so a dead reaper freezes the sensor at
its last value and the SPA steers on a corpse with Start still armed. Make the status
endpoint *enforce* a staleness bound: past the bound the reported `gpu_state.state` must
degrade to an explicit unknown/stale representation rather than serving the frozen value
with `snapshot_fresh: false` alongside otherwise-authoritative fields. Keep the response
schema-valid; if the schema has no unknown state you may only null the derived fields and
must not invent a new enum value — say so in the commit body if you hit that wall.

## Definition of done

- TDD: one test per defect above, plus the cross-reader parity test.
- `cd apps/prototype-description-service && python -m pytest scene/tests/test_gpu_intent.py scene/tests/test_gpu_router.py scene/tests/test_gpu_state.py -q -p no:cacheprovider` green.
- Commit on `feature/gpuops-1-r2-service-parity` with subject
  `scene: gpu intent reader parity and enforced status staleness bound`.
- **Commit early and often** — first commit inside the first quarter of the turn. Never end
  on `needs_guidance` with uncommitted work.
- No AI attribution trailers.
