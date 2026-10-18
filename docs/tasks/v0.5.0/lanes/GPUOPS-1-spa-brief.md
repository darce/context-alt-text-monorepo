# GPUOPS-1 lane brief: the admin SPA settings and describe surface

Lane: `gpuops-1-spa` · Owned paths: `apps/prototype-wp-alt-context/js/admin/**` only.

**There is no self-verify command you can run, and that is structural.** The
implement-lane gate admits only `pytest <args>` and `python3 -m pytest <args>`;
`npx`, `node`, bare `vitest`, `npm` and `bash` are all refused, and the sandbox
has no outbound network so `npm ci` could not run anyway. Land the commit
without a green suite. The coordinator runs vitest and tsc on the host. Do not
restructure code to make an unrunnable command pass, do not invent a test
result, and say plainly in your result that the suite could not be run here.

Three open findings. Read their full text and evidence from the handoff DB. The
ids you own are H-02, R2-03 and L-11 — nothing else:

    python3 -c "from workbay_handoff_mcp import *; configure_runtime(RuntimeConfig.for_repo(__import__('pathlib').Path('.'))); import json; print(json.dumps(list_review_findings(task_ref='GPUOPS-1', status='open', detail='full', limit=60), default=str))"

GR-10 and GR-11 were on this surface and are already fixed at `40009d82a` by
another session. Do not reopen them, and do not weaken what that commit added.

## The naming toggle cannot be saved (H-02, high)

`SettingsPage` holds `allowPersonNames` in its reducer but never passes it or
its change handler down to `SettingsForm`, and never includes
`allow_person_names` in the save payload. The form falls back to the server
value and its optional callback is simply absent, so the user's change is
discarded on save. The control looks live and does nothing.

Wire the state and the callback through, include the field in the save payload
when the client value is authoritative, and add a page-level test that clicks
the toggle, saves, and asserts the request body. A unit test on the form alone
would not have caught this, which is why it shipped.

## VisualFactsResponse is missing required fields (R2-03, medium)

`VisualFactsResponse` omits the backend-required `tier` and `result_generation`
and the named-caption provenance fields the response contract now carries.
`describeMedia` passes this incomplete type to `fetchRequiredApi`, so neither
the compiler nor the tests can see contract drift, and consumers may silently
drop provenance.

Align the type with the backend model, validate at the API boundary, and update
fixtures. Two things already exist that you must reuse rather than duplicate:
`describeApi.ts` exports `NAMING_PROVENANCE_STATUS`, `NAMING_REALIZER` and
`NamingProvenance`; and `gpuApi.ts` was rewritten at `40009d82a` with exhaustive
runtime validation of a response envelope. Follow that file's validation shape
so the two boundaries look like the same codebase.

Per [sr-005] this is request/input validation — validate explicitly at the
boundary; do not reach for an assertion helper. Add tests for missing fields,
wrong types and invalid enum values.

## Settings query key bypasses the factory (L-11, low)

`SettingsPage` uses an ad-hoc `['settings']` key for both `useQuery` and
invalidation while the repository provides a `queryKeys` factory. Add a settings
key to the factory and use it in both places.

## Boundaries

Only `apps/prototype-wp-alt-context/js/admin/**`. Do not edit
`apps/prototype-description-service/**`, `infra/oci/**`, `scripts/**`, or
`docs/workbay/contracts/**` — contract and rule files are tracked but sit under
gitignored directories, and the sandbox returns them as new-file creates, which
rejects the whole patch.

When editing SCSS, use the existing `--acx-*` design tokens for colour, type,
radius, shadow and font weight; no raw literals. A status indicator must pair
its colour with an icon, never colour alone.

No AI or model attribution trailers in the commit message.
