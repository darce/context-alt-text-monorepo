# dux-w2v-b verdicts

## DUX-W2D14-RV-11 — z-retention-posture states

VERDICT: sustained

Mechanism: DashboardPage.tsx:96-98 and :256/:304-306. `retentionPolicy` is null unless `retentionStatus.available`; `showRetentionPanel = !isRetentionLoading && (isRetentionError || Boolean(retentionPolicy))`; the zone mounts only when that is true, else `<></>`.

- dashboard.uxmap.json:107-110 `z-retention-posture.states` is exactly `["default","error"]` — no `loading`, no `empty`.
- dashboard.md:51 mirrors `default, error`.
- Loading: `isRetentionLoading` true → panel false → zone-absent. Confirmed by comment at :305.
- `available:false`: policy null, and if not error → panel false → zone-absent.
- Rendered compositions: error (`isRetentionError`) vs default (policy present). Inner `:259 isRetentionError || !retentionPolicy` cannot show a third empty panel because `!retentionPolicy` is only reachable when `isRetentionError` already made `showRetentionPanel` true.

Dropping `loading`/`empty` matches the shipped UI; it is not a convenient deletion. Absence is named in open_questions rather than invented as fake zone states.

## DUX-W2D14-RV-12 — both identity retry controls

VERDICT: sustained

Mechanism: DashboardPage.tsx:153-165 has two exclusive identity-error branches with different button copy, and dashboard.uxmap.json top-level `actions` now names both:

- `:156-158` `__('Retry','alt-context')` on `isIdentityError` → `act-retry-identity-stats` (json:298-306, verb `"Retry"`).
- `:163-165` `__('Retry identity stats','alt-context')` on `!identityStats` → `act-retry-identity-stats-unavailable` (json:308-316, verb `"Retry identity stats"`).
- dashboard.md:192 and :330-331 document the same pair.

Duplicate-id check: `act-retry-identity-stats` appears once. The second control is a different id (`act-retry-identity-stats-unavailable`), not a duplicated row. `rg '"id":' dashboard.uxmap.json` shows unique action ids. The previously observed duplicate is gone.

## DUX-W2D14-RV-14 — GuidanceCard caught-up branch

VERDICT: not_sustained

Plainly: a documentation dodge, and the relocated text is false about the product.

The fourth branch is real and reachable. GuidanceCard.tsx:13-72 falls through when pending==0, unassigned==0, people_count>0 to :74-81, which renders EmptyState `EMPTY` heading "All caught up. New faces will appear here for review." plus body and CTA `Open Review Queue` → `#/workbench?tab=scan`. Test GuidanceCard.test.tsx:107-124 asserts that link.

What the remediation did:

- json `z-identity-recognition.states` (dashboard.uxmap.json:76-81) is `["default","loading","error","first_time"]` — no `caught_up`, no `empty`.
- open_questions json:411 says the branch has no canonical MapState, so it was "Left undrawn in states, sketched in the md."
- dashboard.md:90-92 keeps a "Caught up" sketch but claims "caught-up message with no CTA". The sketch at :109 draws only the heading. That is not the shipped UI.

Schema constraint is real: MAP_STATES in uxmap-render-parity.test.ts:44-53 (mirror of models.py) has no `caught_up`, extra="forbid". Adding a new state name is not an available fix. Relocating into prose/open_questions is available.

The dodge: canonical `empty` already exists in MAP_STATES, and the component uses `EmptyStateVariant.EMPTY`. They did not put `empty` on the zone. They removed the invalid member so the guard stays green, then parked a wrong "no CTA" sketch in markdown. The json map still does not describe a reachable composition. DRIFT-03: guard-clean map, product misdescribed.

An honest relocation would name the predicates, the EmptyState, and the Open Review Queue CTA, and/or list canonical `empty`. This one does neither.

## DUX-W2D14-RV-15 — z-recent-activity non-exclusivity

VERDICT: not_sustained

An open_question does not discharge a map that still asserts false exclusivity. This remains an open defect.

- dashboard.uxmap.json:96-101 `z-recent-activity.states` is still `["default","empty","degraded","error"]` — four peer values, the schema's exclusive-state shape.
- DashboardRecentActivitySection.tsx:149-151 renders the `historySource === 'browser_local_fallback'` banner from its own `if`, then :152-198 independently selects error (`unavailable` && length===0) / empty (length===0) / default (list). `degraded` overlays `empty` and `default`. `error` is exclusive with `degraded` only because `historySource` is single-valued.
- Shipped empty copy is `__('No recent scans yet')` (:163), not the finding's / sketch's "No recent recognition jobs found." dashboard.md:241-243 still draws the finding's paraphrase. The sketch was aligned to the finding text, not the product.
- json:412 open_question and dashboard.md:377 correctly describe the overlay. That is commentary. The machine-readable `states` list is unchanged, so a consumer of the map still sees exclusive peers. Guard only checks schema + label parity, not exclusivity. DRIFT-03 stands: map passes the guard while misdescribing the UI.

No mechanism makes the original failure impossible. Relocating the admission to `open_questions` is the available schema workaround; leaving the false peer list in place means the defect is documented, not removed.

## Independent zone check

### z-library-coverage — match

dashboard.uxmap.json:87-91 states `["default","loading"]`. DashboardPage.tsx:217-219 is `isStatsLoading ? loading copy : stats grid`. `useMediaStats` exposes `isError` (useMediaStats.ts:68,83) but DashboardPage.tsx:57 discards it, so error is not a reachable component branch (zeros render as default). CTA/progress remain mounted during loading (md:163 already notes this). No new drift vs the states list.

### z-sync-health — new drift

DUX-W2V-B-NEW-1: `z-sync-health.states` is `["default","loading","error","offline","degraded"]` (dashboard.uxmap.json:64-70). DashboardSyncHealthSection.tsx:56-66 exclusive-replaces only loading vs error (`isError || !syncStatus`) vs the default scaffold. `offline` is `getDashboardSyncHealthSummary` case `'offline'` (degradedModeBannerLogic.ts:45-46) swapping the summary sentence while the stats grid and Open Review Queue stay mounted (:96-146). `degraded` is additive (mirror banner :68-95, warning/non-healthy summaries, conflict/failed CTAs). Peer states again assert exclusivity the component does not have. Same class as RV-15; this zone was not in the original findings.

FINDINGS_BEGIN
FINDING: DUX-W2D14-RV-11
VERDICT: sustained
EVIDENCE: dashboard.uxmap.json:107-110 and dashboard.md:51 list z-retention-posture states exactly ['default','error']. DashboardPage.tsx:96-98 `showRetentionPanel = !isRetentionLoading && (isRetentionError || Boolean(retentionPolicy))` with policy null unless available; :256 mounts the zone only when true, :304-306 else `<></>`. Loading and available:false are zone-absent, so dropping those states matches the shipped UI.
FINDING: DUX-W2D14-RV-12
VERDICT: sustained
EVIDENCE: DashboardPage.tsx:156-158 renders __('Retry') on isIdentityError; :163-165 renders __('Retry identity stats') on !identityStats. Both are in the top-level actions array as act-retry-identity-stats (json:298-306, verb Retry) and act-retry-identity-stats-unavailable (json:308-316, verb Retry identity stats). No duplicate ids.
FINDING: DUX-W2D14-RV-14
VERDICT: not_sustained
EVIDENCE: Documentation dodge. GuidanceCard.tsx:74-81 (pending==0 && unassigned==0 && people>0) ships EmptyState EMPTY with heading 'All caught up...' AND CTA 'Open Review Queue' (asserted by GuidanceCard.test.tsx:107-124). json:76-81 omits the branch from states; json:411 parks it in open_questions; dashboard.md:92/109 claim 'no CTA' and draw none. Canonical MAP_STATES already includes 'empty' (uxmap-render-parity.test.ts:44-53); they did not use it. Guard-clean map still misdescribes the product.
FINDING: DUX-W2D14-RV-15
VERDICT: not_sustained
EVIDENCE: Open defect. json:96-101 still lists ['default','empty','degraded','error'] as peer exclusive states. DashboardRecentActivitySection.tsx:149-151 banner is an independent if from :152-198 empty/default/error, so degraded+empty compose. json:412 open_question admits this but does not change the states list. md:243 even draws 'No recent recognition jobs found.' vs shipped __('No recent scans yet') at :163. No mechanism makes the false exclusivity impossible.
FINDING: DUX-W2V-B-NEW-1
VERDICT: open
EVIDENCE: z-sync-health states json:64-70 include 'offline' and 'degraded' as peers of default/loading/error. DashboardSyncHealthSection.tsx:56-66 exclusive-replaces only loading vs error vs default scaffold; offline is a summary-string swap (degradedModeBannerLogic.ts:45-46) and degraded is additive banners/CTAs on that scaffold. Same false-exclusivity class as RV-15. z-library-coverage json:87-91 ['default','loading'] matches DashboardPage.tsx:217-219.
FINDINGS_END
