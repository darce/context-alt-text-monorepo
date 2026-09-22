# APP-1 browser keys/usage postlanding review

Scope: initial review of the integrated `ea146c3f971a13d0a6fa3962c36cfbe019e3e536..c951de548924ef34df731c09c0271168b2b00ef5` delta only. The feature modules remain intentionally unmounted; this report does not treat mounting or the shared transport as defects.

Verdict: findings remain; the delta is not clean for orchestration without the follow-ups below.

## Findings

### APP1-KEYS-RV01 — high — one-time secret can be replaced before the user closes it

- Location: `apps/app-portal/src/screens/KeysScreen.tsx:319-327,418-425`; `apps/app-portal/src/components/OneTimeSecretDialog.tsx:48-65`
- Scenario: After a create succeeds and the refresh finishes, `creating` becomes false while `secret` is still set. The underlying Create API key control is therefore enabled while the `aria-modal` secret dialog is open. The dialog has no focus trap or inert background. A keyboard user can leave the dialog and start a second create; when it succeeds, `setSecret` replaces the first raw secret, so an un-copied one-time secret is lost with no recovery path.
- Minimal fix: Make the secret dialog an exclusive modal (trap focus, handle Escape/close, and make the background inert or disable all underlying actions while it is present). Do not allow a second create/rotate until the current secret dialog is closed.

### APP1-KEYS-RV02 — medium — initial revoke preview does not move focus into the modal

- Location: `apps/app-portal/src/screens/KeysScreen.tsx:187-191,395-417`
- Scenario: Clicking Revoke mounts the `phase: 'preview'` dialog, but the focus effect only runs for `phase: 'last_usable'`. Focus remains on the row's Revoke button behind an `aria-modal="true"` dialog, and normal Tab/Shift-Tab navigation can leave the dialog. A keyboard user can miss the irreversible confirmation or activate controls behind it; only the later last-usable warning gets Cancel-first focus.
- Minimal fix: On every revoke-dialog mount/phase change, focus Keep key (or another explicit cancel-first control), trap focus within the dialog, support Escape, and restore focus to the initiating row button after either close path.

### APP1-KEYS-RV03 — high — revoke accepts a 200 response that says no revocation occurred

- Location: `apps/app-portal/src/api/portalKeys.ts:237-247`; success handling in `apps/app-portal/src/screens/KeysScreen.tsx:249-251`
- Scenario: `parseRevoke` treats any boolean `revoked` as a valid success envelope. If a 200 response contains valid UUIDs but `revoked: false` (a malformed/proxy response or contract drift), `client.revoke` resolves; the screen closes the destructive confirmation and refreshes as though the action succeeded. The UI has no failure state for an operation that did not revoke the key.
- Minimal fix: Require `revoked === true` and the returned `id` to equal the requested UUID before resolving; otherwise return `invalid_portal_key_response` and retain the row/confirmation for recovery.

### APP1-KEYS-RV04 — medium — tenant key-limit errors leave Create enabled

- Location: `apps/app-portal/src/screens/KeysScreen.tsx:56-81,203-214,319-327`
- Scenario: The route contract says `409 tenant key limit reached` keeps Create unavailable until the usable key changes. The catch path only updates status; `finally` clears `creating`, `busy` then becomes false, and the Create button is disabled only by `busy`. The user can repeatedly submit the same create action while the existing usable key is unchanged.
- Minimal fix: Add a create-blocked state for the exact tenant-limit error, disable Create while it is set, and clear it only after a successful list confirms the usable-key state changed (or after an explicit successful refresh).

### APP1-KEYS-RV05 — medium — malformed key timestamps fail open as usable

- Location: `apps/app-portal/src/api/portalKeys.ts:63-74,169-199`; `apps/app-portal/src/screens/KeysScreen.tsx:95-105`
- Scenario: The backend contract fields are datetimes, but the client accepts any non-empty string. A 200 metadata row with `expires_at: "not-a-date"` passes parsing; `isUsable` excludes it because `Date.parse` is not finite, while `rowStatus` falls through to `usable`. The row publishes `status: usable` even though expiry was not established, and the status disagrees with the rotation-selection logic.
- Minimal fix: Validate all key datetime fields as finite ISO/datetime values in the API parser and reject the envelope (or render an explicit unknown/degraded state) instead of labeling invalid expiry usable.

### APP1-KEYS-RV06 — medium — usage parser publishes invalid counts and timestamps

- Location: `apps/app-portal/src/api/portalUsage.ts:37-59,116-155`; rendering in `apps/app-portal/src/screens/UsageScreen.tsx:107-117`
- Scenario: `parseNullableInt` accepts negative integers and the string parsers accept arbitrary non-empty timestamps. A malformed 200 such as `{used:-1, remaining:-5, period_start:"not-a-date", ...}` is accepted and displayed as authoritative usage/period evidence; the screen does not turn a negative remaining value into an error or unknown state. This bypasses the fail-closed shape validation expected for the backend's non-negative count and datetime contract.
- Minimal fix: Require non-negative count fields and validate `period_start`, `period_end`, nested period bounds, and non-null `as_of` as datetimes; reject invalid 200 envelopes so the screen uses its bounded error/recovery state.

The provided scoped VM self-verification reported 21/21 tests passing; it was not rerun in this lane per the review brief's instruction to use the supplied verification and not run the app or whole suites. No provider, live request, or feature-code change was made.
