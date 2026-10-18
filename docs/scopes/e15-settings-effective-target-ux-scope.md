# E15 Settings Effective-Target UX Scope

> **Date**: 2026-06-09  
> **Trigger**: Operator confusion on LocalWP Settings — stored remote URL vs effective `local` routing to `http://localhost:8000`; E15-3a/E15-22 remote E2E proof requires explicit service-mode clarity.

## Problem

LocalWP WordPress runs at `http://localhost:10010` (admin + Workbench UI). Recognition traffic is routed by **`acx_recognition_source`**, not by the URL field alone.

Observed state (LocalWP `wp-json/acx/v1/settings`, abridged to routing-relevant fields — the live response also returns `api_key_set`, `api_key_last4`, `key_source`):

```json
{
  "url": "https://dev.api.altcontext.com",
  "url_source": "option",
  "recognition_source": "local",
  "recognition_source_source": "option"
}
```

- **Effective runtime**: proxy sends recognition requests to `http://localhost:8000` because source is `local`.
- **Stored URL**: `https://dev.api.altcontext.com` remains in options for when source switches to `service`.
- **Global admin notice**: warns about local mode on every ACX page.
- **Settings form**: shows URL + key as "Saved in database" without stating they are inactive under `local` mode.

Operators infer "remote is active" because the URL field displays a hosted endpoint. E2E proof for E15-3a/E15-22 remote loop requires **`recognition_source=service`** and a reachable service URL — not `:8000`.

## Endpoint Clarification (canonical)

| Surface | URL | Notes |
| --- | --- | --- |
| LocalWP WordPress | `http://localhost:10010` | Browser UI only |
| Local description-service (optional) | `http://localhost:8000` | Used only when `recognition_source=local` |
| OCI **production** (E15-3a public gate) | `https://api.altcontext.com` | `/health`, `/health/detailed`, `/ready` — not bare `/` |
| OCI **dev** | `https://dev.api.altcontext.com` | `/health` returns 200; bare `/` returns 404 (expected) |

`https://dev.api.altcontext.com/` returning "not found" is not proof the API is down — probe `/health` or `/health/detailed`.

## UX Gaps

1. **No effective *URL* readout** — GET `/settings` already returns `recognition_source` as the *resolved* mode (same precedence as the proxy), so effective mode is available; what is missing is the effective **URL** (`http://localhost:8000` under `local`, else the resolved service URL). Settings shows the stored `url` field, not where requests actually go.
2. **Per-field "Saved in database"** reads as "in use" rather than "stored for future service mode".
3. **URL field editable in local mode** — invites saving a remote URL that is ignored until source flips to `service`.
4. **Global warning duplicates Settings** without reconciling stored URL vs active mode.
5. **Workbench banner** (`recognitionSource=local`) reads from the page-load `AltContextAdmin` bootstrap (`WorkbenchContext` → `getConfig()`), not a live settings query — so it disagrees with Settings on unsaved form state **and stays stale after a successful Save until a full page reload**.
6. **E2E / run-log docs** do not state that remote proof requires `service` + successful `/settings/test` against the effective URL.

## Proposed Solution

> **Decomposition**: A–E below span backend (PHP response shape), two TS surfaces (SettingsPage, WorkbenchPage), admin PHP notice routing, operator docs, and Playwright — too large for one slice. On promotion to a task plan, split into ≥3 independently shippable slices: (1) backend effective-URL field; (2) Settings UI panel + copy + field gating; (3) admin/Workbench notices; (4) E2E + docs gate.

### A. Settings "Effective routing" panel

Add a summary block above the form:

- **Active mode**: Local | Service — derive from the **existing** `recognition_source` GET field (already resolved with proxy precedence); no new backend field needed here.
- **Requests sent to**: `http://localhost:8000` or resolved service URL — this is the one genuinely new computed field the GET response must add (e.g. `effective_recognition_url`).
- **Stored service URL** (when local): show as secondary/muted: "Saved for Service mode: `https://…`"

### B. Copy and field behavior by mode

- **Local selected**: URL/key fields muted or labeled "Applies when Recognition Source is Service". The Test Connection probe is **already disabled in local mode** (`SettingsPage.tsx` — `disabled={… || recognitionSource === RecognitionSource.LOCAL}`); the remaining work is explanatory copy stating *why* it is disabled (not the disable itself).
- **Service selected**: URL/key active; test probe uses resolved URL; hide global "local mode" notice on Settings route.

### C. Save semantics

- Saving Service + URL in one request: the POST `/settings` endpoint accepts `url` and `recognition_source` in the same body (atomic at the request level). The backend updates each option independently — it does **not** auto-couple URL→source — so the UI must send both keys together and require an explicit Save after a mode change.
- Optional guard: when switching to Service, if URL empty use last stored URL.

### D. Workbench / global notices

- Replace generic localhost warning with mode-specific copy linking to effective target.
- Source the banner mode from a **live settings query** (or invalidate/refetch the bootstrap config on Save) instead of the page-load `AltContextAdmin` value, so it does not stay stale after a mode change until reload.
- When `service`, show connectivity status from last probe or sync health — not localhost warning.

### E. Operator docs + E2E gate

- E15-3a checklist: LocalWP `:10010` for UI; **remote proof** requires `recognition_source=service` and `https://api.altcontext.com` (or documented dev URL for dev-only rehearsal).
- Playwright remote proof path: assert settings API `recognition_source=service` before scan, or document setup step.

## Out of Scope

- Changing OCI routing or adding a root `/` handler on dev.
- Merging recognition source with transport mode (`acx_recognition_transport`).
- Auto-flipping local → service when URL is saved (explicit operator choice remains).

## Verification

- PHPUnit: settings GET adds the effective recognition **URL** field (e.g. `effective_recognition_url`) resolving to `http://localhost:8000` under `local` and the resolved service URL otherwise; existing `recognition_source` resolution is unchanged.
- Vitest: Settings renders effective panel; local mode mutes URL; service mode shows probe target.
- Manual: switch LocalWP to `service` + `https://api.altcontext.com`, probe connected, Workbench scan hits remote (OCI logs).

## Related Work

- E15-12 recognition-source selector (shipped) — this scope closes the **effective vs stored** display gap left open.
- E15-3a / E15-22 proof bundles — depend on correct service-mode documentation and UI truthfulness.