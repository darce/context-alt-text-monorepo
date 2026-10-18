# GPUOPS-1 lane brief: the public GPU/describe API surface

Lane: `gpuops-1-pubapi` · Owned paths: `apps/prototype-description-service/scene/interface_adapters/http/**` and `apps/prototype-description-service/recognition/interface_adapters/http/routers/tenant.py`, plus their tests under `apps/prototype-description-service/scene/tests/` and `apps/prototype-description-service/recognition/tests/`.
Self-verify: `python3 -m pytest apps/prototype-description-service/scene/tests apps/prototype-description-service/recognition/tests -q`

Five open findings on the service's outward-facing HTTP boundary. Read their
full text and evidence from the handoff DB first. The ids you own are GR-08,
GR-09, GR-12, R2-02 and R2-04 — nothing else:

    python3 -c "from workbay_handoff_mcp import *; configure_runtime(RuntimeConfig.for_repo(__import__('pathlib').Path('.'))); import json; print(json.dumps(list_review_findings(task_ref='GPUOPS-1', status='open', detail='full', limit=60), default=str))"

## Actor identity is caller-supplied (GR-08, high)

The public GPU route accepts `requested_by` from the request body and writes it
straight into the audit path. Any authenticated caller can therefore forge the
actor on a GPU start or stop. The PHP layer overwrites the field, but that
protects only callers who go through PHP; the service is directly reachable.
Remove `requested_by` from the public request model entirely and derive the
identity from the verified authentication principal. A field the client can set
is not an audit trail.

## Corrupt data is coerced into meaningful states (GR-09, high)

Unknown enum values from the backend are silently mapped onto actionable
neighbours: intent becomes `auto`, status becomes `none`, reason becomes
`unknown`. A payload carrying `future-intent`, `future-status` and
`future-reason` serialises as three perfectly plausible, wrong values. Validate
the whole snapshot against the shared contract and return an explicit
unknown/unavailable state or a 503 for values you cannot interpret. Coercing an
unrecognised value into a state the UI will act on is the specific shape
[rg-015] forbids.

## Freshness threshold disagrees with the reader (R2-02, medium)

The router hardcodes a 120-second snapshot freshness threshold while
`read_gpu_state` honours the configured `ACX_GPU_STATE_STALE_SECONDS`, default
180. A 150-second-old snapshot is thus reported UNKNOWN by the route and
accepted by the canonical reader — two components disagreeing about the same
fact. The route also reads the state file twice per response, so fields from
two different atomic generations can be stitched into one payload. Centralise
freshness evaluation on the configured threshold and read exactly one validated
snapshot per response. Test ages between 120 and 180 seconds, and with an
override configured.

## Public model drops C7 naming provenance (GR-12, medium)

The internal payload carries the C7 naming fields but the public
`NamingProvenance` model omits `status`, `realizer` and `names_applied`, so
serialisation silently discards the provenance needed to reconstruct naming
behaviour. Add the typed fields and their enums to the public/shared response
model, drop the ad-hoc extra-allow escape hatch on the payload, and assert on
**actual FastAPI wire serialisation** rather than on the internal dict — the
current tests pass precisely because they never look at the wire.

Follow [sr-007]: the status and realizer vocabularies already exist as
`as const` objects on the TypeScript side (`NAMING_PROVENANCE_STATUS`,
`NAMING_REALIZER` in `js/admin/api/describeApi.ts`). Mirror those exact values
with a Python `StrEnum`; do not invent a third spelling.

## Malformed tenant claim returns 500 (R2-04, medium)

`tenant_whoami` parses `auth.tenant_claim` with a bare `uuid.UUID`, so a
malformed but authenticated claim raises `ValueError` and surfaces as a generic
500, where the naming endpoint returns a deliberate 403 for the same condition.
Reuse `_tenant_uuid_for_naming` or catch the expected invalid-claim exceptions
and return 403. Add a malformed-claim test.

## Boundaries

Only the HTTP interface-adapter layer named above and its tests. Do not edit
`infra/oci/**`, `apps/prototype-wp-alt-context/**`, `scripts/**`, or
`docs/workbay/contracts/**` — contract and rule files are tracked but sit under
gitignored directories, and the sandbox returns them as new-file creates, which
rejects the whole patch. If a JSON schema under `docs/workbay/contracts/` needs
to change to express the C7 fields, stop and say so in the result instead of
editing it.

`scene/application/gpu_intent.py` belongs to another lane in this same wave. Do
not touch it.

No AI or model attribution trailers in the commit message.
