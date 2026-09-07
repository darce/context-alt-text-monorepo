# GPUOPS-1 lane brief: the admin SPA GPU surface

Lane: `gpuops-1-spa` · Owned paths: `apps/prototype-wp-alt-context/js/admin/**` only.
Self-verify: `npx vitest run apps/prototype-wp-alt-context/js/admin`

**Expect self-verify to fail with a network error.** The sandbox has no
outbound network, so `npx` cannot fetch vitest. That failure is not a signal
about your work. Land the commit anyway; the coordinator runs the real suite on
the host. Do not restructure code to make an unrunnable command pass, and do
not report success you have not observed — say plainly in the result that the
suite could not run.

Five open findings. Read their full text and evidence from the handoff DB. The
ids you own are GR-10, GR-11, H-02, L-11 and R2-03 — nothing else:

    python3 -c "from workbay_handoff_mcp import *; configure_runtime(RuntimeConfig.for_repo(__import__('pathlib').Path('.'))); import json; print(json.dumps(list_review_findings(task_ref='GPUOPS-1', status='open', detail='full', limit=60), default=str))"

## Stale telemetry still enables Start (GR-11, high)

When `snapshot_fresh` is false the state is converted to `unknown`, but
`stateCanStart('unknown')` returns true, so `canStart` stays true and the
button remains live. There is even an existing test asserting that a stale
response enables Start — that test encodes the bug and must be changed. This is
a controlled-stock resource: acting on telemetry you know is stale is how you
start an A10 that is already running. Require a fresh snapshot before Start is
enabled, and leave the control unavailable with an explicit stale reason in the
copy rather than silently disabled.

## The boundary parser validates a subset and casts the rest (GR-10, medium)

`parseGpuStatusResponse` performs shallow checks and then casts to
`GpuStatusResponse`. `intent_status`, `last_transition_reason`,
`snapshot_age_seconds`, the nested load fields and several required `gpu_state`
fields are never validated at runtime, so a malformed payload reaches the
control surface wearing a trusted type. Implement exhaustive runtime validation
against `scene-gpu-status.schema.json` and reject malformed responses at the
boundary. Per [sr-005], this is request/input validation — validate explicitly;
do not reach for an assertion helper. Add tests for missing fields, wrong
types, and invalid enum values.

## The naming toggle cannot be saved (H-02, high)

`SettingsPage` holds `allowPersonNames` in its reducer but never passes it or
its change handler down to `SettingsForm`, and never includes
`allow_person_names` in the save payload. The form falls back to the server
value and its optional callback is simply absent, so the user's change is
discarded on save. Wire the state and callback through, include the field in
the save payload when the client value is authoritative, and add a page-level
test that clicks the toggle, saves, and asserts the payload — a unit test on
the form alone would not have caught this.

## VisualFactsResponse is missing required fields (R2-03, medium)

`VisualFactsResponse` omits the backend-required `tier` and `result_generation`
and the named-caption provenance fields that the response contract now carries.
`describeMedia` passes this incomplete type to `fetchRequiredApi`, so neither
the compiler nor the tests can see contract drift and consumers may drop
provenance without noticing. Align the type with the backend model and the
shared schema, validate at the API boundary, and update fixtures.

Note that `describeApi.ts` already exports `NAMING_PROVENANCE_STATUS`,
`NAMING_REALIZER` and `NamingProvenance` — reuse them rather than declaring a
parallel vocabulary.

## Settings query key bypasses the factory (L-11, low)

`SettingsPage` uses an ad-hoc `['settings']` key for both `useQuery` and
invalidation while the repository provides a `queryKeys` factory. Add a
settings key to the factory and use it in both places.

## Boundaries

Only `apps/prototype-wp-alt-context/js/admin/**`. Do not edit
`apps/prototype-description-service/**`, `infra/oci/**`, `scripts/**`, or
`docs/workbay/contracts/**` — contract and rule files are tracked but sit under
gitignored directories, and the sandbox returns them as new-file creates, which
rejects the whole patch.

When editing SCSS, use the existing `--acx-*` design tokens for colour, type,
radius, shadow and font weight; no raw literals. A stale-state indicator must
pair its colour with an icon, never colour alone.

No AI or model attribution trailers in the commit message.
