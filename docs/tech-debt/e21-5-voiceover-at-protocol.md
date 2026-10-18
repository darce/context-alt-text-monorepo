# Tech Debt: E21-5 VoiceOver AT protocol (deferred)

**Status:** deferred to next phase · **Owner:** operator (AT pass) + frontend (any fixes it surfaces) · **Origin:** E21-5 (unified review queue), Slice 8 close, 2026-07-18

## What was deferred
The manual macOS **VoiceOver** assistive-technology acceptance pass for the unified review queue — the 6 named utterances/behaviors pinned in the E21-5 task plan's Verification Strategy (A11Y-23):
1. Accept → "Saving — Undo" announced without moving VO focus off the card.
2. Undo window lapses → advance announced ("Reviewing item N of M…") and focus lands on the next card's primary action.
3. Undo (reached via Tab, activated) → "Action canceled" announced, card unchanged.
4. Simulated commit failure → alert announced assertively, retry reachable, alert persists until addressed.
5. Drain the queue → empty-state announcement.
6. Go offline → sync-strip announces; disabled controls remain focusable and read their reason.
NVDA + Firefox on the Windows demo VM is the named fallback.

## Why it's safe to defer for this merge
- Phase re-prioritization (2026-07-18): **UX-flow correctness is the first priority**; the screen-reader pass follows once the flow is validated. Getting the interaction model right first avoids re-running the AT pass against a flow that may still change.
- The **structural** a11y surface is already implemented and unit-tested this task: inline `role="status"` hold announces, persistent `role="alert"` failures, `aria-disabled` (never HTML `disabled`) offline with `aria-describedby` reasons, focus-on-advance to the next primary, `aria-live` announce regions with a seq nonce so identical consecutive messages re-announce, and the sync-strip offline announce. axe scans pass. What's deferred is the human confirmation that these *sound right* live — not their existence.
- Greenfield: no production users depend on the AT pass right now.

## Trigger to pick up
When the UX flow is accepted (the three UX-flow operator items in `docs/runbooks/operator-manual-acceptance-playbook.md` recorded) **and** the flow is considered stable for the demo phase — before any public/AT-sensitive launch.

## Acceptance criteria
Run the VoiceOver protocol per **Class A** of `docs/runbooks/operator-manual-acceptance-playbook.md`, confirming all 6 utterances/behaviors above; record a per-item pass/fail `test_result` with SR + browser + OS versions. Any silent transition is a failing result and becomes a follow-up fix. If VoiceOver is unavailable, use the NVDA + Firefox fallback.

## Also parked here (adjacent, low)
- **E21-5-BR-84** (deferred finding): the Slice-8 single-accent-primary DOM test uses a faithful *copy* of the `ScanTabContent` reconciliation + a mocked panel rather than mounting real `ScanTabContent`/`ClusterReviewPanel`. The invariant property was independently grep-verified; a real-`ScanTabContent`-mounted footer-accent assertion is a low-value hardening follow-up.
