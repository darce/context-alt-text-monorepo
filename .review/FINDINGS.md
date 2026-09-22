# APP-1 browser-claim-billing initial postlanding review

Range: `c951de548924ef34df731c09c0271168b2b00ef5..b378a4c78ab8dee475dd1b1f10dd48f61fd01e13`

Verdict: **3 medium findings; follow-up is required before calling this UI slice clean.**

This is the initial postlanding review of the supplied inline delta only. The
feature remains intentionally unmounted and uses injected transport; those
boundaries are not findings. The supplied scoped VM verification is accepted
as provided and was not rerun here.

## Findings

### APP1-CLAIMUI-RV01 — medium — terminal claim failures retain the raw invitation token

Path: `apps/app-portal/src/screens/ClaimScreen.tsx:164-187`

When a claim request returns a terminal response such as `not_admitted`,
`invitation_consumed`, or `invalid_claim_request`, `submitClaim` clears
`token` only in the success branch at line 176. The catch branch leaves the raw
single-use invitation in both React state and the input while rendering the
error/retry UI. A user can leave a failed claim mounted with the secret still
available, contrary to the contract's request-scoped one-time-secret lifetime
and privacy default.

Minimal fix: clear the token for terminal claim outcomes before presenting
recovery (and require re-entry for those retries); preserve it only where a
bounded transport-ambiguity retry is explicitly required, while retaining the
422 field-focus behavior.

### APP1-CLAIMUI-RV02 — medium — attempt handoff occurs after external navigation starts

Path: `apps/app-portal/src/screens/BillingScreen.tsx:234-240`

For a normal pending/provider-requested checkout, the component calls
`hostedNavigation.open`, whose production implementation is
`window.location.assign`, and only then calls `onNavigateToReturn(attempt_id)`.
On a real external navigation the document can unload before the parent's
attempt snapshot/state handoff commits. The `/billing/return` landing state can
therefore lose the only `attempt_id` needed to explain or recover an ambiguous
checkout, even though the mutation itself was accepted.

Minimal fix: durably hand off the attempt before initiating external
navigation (or put the attempt reference in the server-selected return
context); do not rely on a state update scheduled after `location.assign`.

### APP1-CLAIMUI-RV03 — medium — manage recovery remains active inside checkout confirmation

Path: `apps/app-portal/src/screens/BillingScreen.tsx:297-337,383-397`

If manage returns `billing_portal_unavailable`, the component sets
`retryKind` to `manage`. If the user then chooses `Continue to checkout`,
`onContinue` enters hosted-checkout preview but does not clear `retry` or
`retryKind`. The rendered `Try billing again` action remains beside
`Confirm hosted checkout`; activating it still calls `startManage` and can open
the hosted billing portal instead of the checkout the user just selected.

Minimal fix: clear `retry` and `retryKind` whenever a new checkout preview is
entered (and whenever the active recovery intent changes), or bind the recovery
button to the currently displayed intent.

GROK_REVIEW_FINDINGS_JSON
[
  {
    "finding_id": "APP1-CLAIMUI-RV01",
    "severity": "medium",
    "category": "privacy-secret-lifetime",
    "file_path": "apps/app-portal/src/screens/ClaimScreen.tsx",
    "line_start": 164,
    "line_end": 187,
    "description": "Terminal claim errors leave the raw single-use invitation token in React state and the input because token clearing occurs only on success.",
    "fix": "Clear the token for terminal claim outcomes before rendering recovery; require re-entry for those retries and preserve it only for explicitly bounded transport-ambiguity recovery."
  },
  {
    "finding_id": "APP1-CLAIMUI-RV02",
    "severity": "medium",
    "category": "billing-recovery",
    "file_path": "apps/app-portal/src/screens/BillingScreen.tsx",
    "line_start": 234,
    "line_end": 240,
    "description": "The component starts window.location.assign through hostedNavigation.open before handing the checkout attempt_id to the parent, so a real external unload can lose the return/recovery snapshot.",
    "fix": "Persist or hand off attempt_id before external navigation, or include it in the server-selected return context."
  },
  {
    "finding_id": "APP1-CLAIMUI-RV03",
    "severity": "medium",
    "category": "recovery-ux",
    "file_path": "apps/app-portal/src/screens/BillingScreen.tsx",
    "line_start": 297,
    "line_end": 397,
    "description": "After a manage outage, entering checkout preview leaves retryKind=manage and a Try billing again button that still invokes startManage next to Confirm hosted checkout.",
    "fix": "Clear retry/retryKind when entering checkout preview or bind the recovery action to the active intent."
  }
]
