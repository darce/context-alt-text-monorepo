# Operator Manual-Acceptance Playbook

> **Purpose.** Some acceptance steps cannot be performed by a coding agent or by the Playwright/CLI harness — they require human perception, human judgment, a second real person, or an assistive-technology stack the harness does not drive. This playbook is the standing procedure for those steps: what they are, why the CLI can't do them, and exactly how the operator runs and records each one.
>
> **When to use.** Any time a task plan's Verification Strategy lists a step the automated gate can't discharge (screen-reader AT, visual re-baseline acceptance, unaided usability sessions, human-baseline timing, real-device/real-network checks). The task stays blocked on a handoff blocker until the operator records these as `test_result`/evidence.

---

## Why Playwright/CLI can't do these

Playwright drives a browser: it clicks, types, screenshots, reads the DOM/console, runs axe, and measures automated timings. It **cannot**:

- **Run a screen reader and hear it.** VoiceOver/NVDA utterances are produced by the OS accessibility stack and perceived by a human. axe checks static a11y properties (roles, names, contrast) but never proves what a screen reader *announces* during a live interaction.
- **Judge subjective visual quality or accept a baseline.** Playwright *generates* a visual diff; a human decides whether the change is intended and correct (sense-groups, focal point, type steps).
- **Observe a first-time human user.** An unaided usability session needs a real, naive person and an observer — the signal is where a human hesitates, misreads, or gives up.
- **Establish a human-timed baseline.** The harness measures automated task time; the "how long does a real person take" number needs a stopwatch and a human doing the task.
- **Exercise real hardware / real network conditions** (true airplane-mode on a device, a physical assistive device, a real slow link).

The rule of thumb: **if the acceptance criterion is "a human perceives/judges X," it belongs here, not in CI.**

---

## Taxonomy of operator-only actions

| # | Action class | CLI can do | Human must do | Records as |
|---|---|---|---|---|
| A | **Screen-reader AT protocol** (VoiceOver/NVDA) | axe static scan only | Run the SR, perform the flow, confirm each named utterance/behavior | AT-pass evidence (per-utterance checklist) |
| B | **Visual re-baseline acceptance** | Generate the diff image | Review each diff, confirm intended, accept/reject the new baseline | Visual-accept evidence + committed baseline |
| C | **Unaided first-time-user session** | Seed the environment | Recruit a naive user, observe, record completion + friction | Usability-session notes + completion result |
| D | **Human-timed outcome metric** | Run the automated walkthrough (timing tracked run-over-run, never vs the human baseline) | Time a real person doing the same task with a stopwatch/recording | Metric evidence (human time vs baseline) |
| E | **Real-device / real-network** | — | Perform on the actual device/link | Device evidence |

Classes B and D are **semi-automated**: the operator runs a CLI command to produce the artifact, then applies human judgment. A and C are fully manual.

---

## Per-action runbooks

### Prerequisites (all classes that touch the app)
1. A running LocalWP target with the plugin built and seeded (see `docs/runbooks/deploy-demo-cicd.md` for the demo env; local dev uses the LocalWP site under `${LOCAL_WP_ROOT}`).
2. From `apps/prototype-wp-alt-context/`, install the Playwright browser once: `npm run e2e:install`, and establish the auth state: `npm run e2e:auth`.
3. E2E specs are **skip-guarded**: they `test.skip()` when the seeded state they need is absent. A skipped run is **not** a pass — seed the state (scan media → produce pending suggestions) before running acceptance specs, or record "could not run: no seeded suggestions."

### A. Screen-reader AT protocol (macOS VoiceOver; NVDA+Firefox fallback)
1. Enable VoiceOver: ⌘+F5 (or Touch ID triple-press). Have the target flow open in Safari/Chrome against the seeded LocalWP site.
2. Walk the flow and **confirm each named utterance/behavior** from the task plan's AT protocol. Do not paraphrase — the plan pins the exact expected announcements; a silent transition is a failing result.
3. If VoiceOver is unavailable, the named fallback is **NVDA + Firefox on the Windows demo VM** — the pass is not skippable, only substitutable.
4. Record the result as a `test_result` (or handoff evidence) with a per-item pass/fail line for each utterance, plus the SR + browser + OS versions.

### B. Visual re-baseline acceptance
1. Run the visual project: from `apps/prototype-wp-alt-context/`, `npm run visual:localwp` (Playwright project `visual`, e.g. `tests/e2e/visual/workbench-visual.spec.ts`).
2. For an **intended** UI change the run reports diffs. Open each diff image and confirm the change is the intended one and reads correctly (per the plan's design-direction: sense-groups, focal point, type-step assignment).
3. Accept by updating the baseline (`--update-snapshots` via the project's runner) and committing the new baseline images **on the feature branch**, with a one-line note of what changed and why the diff is intended.
4. Record a `test_result` noting "visual re-baseline reviewed + accepted" with the commit SHA of the new baselines. A raw green/red from the runner is **not** acceptance — the human confirmation is.

### C. Unaided first-time-user session
1. Recruit a person who has **not** seen the flow. Give them only the top-level goal (e.g. "name the first person the system found"), no coaching.
2. Observe silently. Record: did they complete? where did they hesitate/misread/backtrack? any dead ends? total time.
3. Record completion (yes/no) + the friction notes as evidence. This is the honest signal the automated walkthrough cannot produce.

### D. Human-timed outcome metric (walkthrough)
1. Run the automated rehearsal: from `apps/prototype-wp-alt-context/`, `npm run e2e:evidence` (or scope to the walkthrough spec `tests/e2e/evidence/first-visitor-walkthrough.spec.ts`). Its timings are tracked **run-over-run only** and never compared to the human baseline (they gate nothing).
2. Separately, **time a real person** doing the same task with a stopwatch/screen-recording, and compare to the recorded pre-change manual baseline (the plan states the target, e.g. ≤50% of baseline time-to-first-outcome).
3. Record both numbers (automated rehearsal timing + human time vs baseline) as evidence.

### E. Real-device / real-network
1. Perform the check on the actual device/link (e.g. true airplane-mode on a laptop, not a mocked offline flag).
2. Record device/OS/network conditions + the observed behavior.

---

## Closing the loop
After running the applicable classes:
1. Record each as a handoff `test_result` (or evidence) tied to the current HEAD SHA.
2. Resolve the operator blocker on the task ref and tick the corresponding plan checklist rows.
3. Only then does the automated pre-merge gate (`handoff_close_check(enforce=True)`) plus these recorded operator results constitute a complete acceptance.

---

## E21-5 (unified review queue) — current acceptance instances

Slices 1a–8 are code-complete and dual-review-clean (zero open findings). The operator gate before merge is blocker **#36**. Per the phase re-prioritization (2026-07-18): **get the UX flow correct first; defer the screen-reader pass.**

**First priority — UX-flow acceptance (do these before merge):**
- **[Class D] Walkthrough metric** — `npm run e2e:evidence` (scope: `first-visitor-walkthrough.spec.ts`) + a human-timed run vs the pre-Slice-1 baseline (target: time-to-first-named-person ≤ 50%).
- **[Class C] Unaided first-time-user session** — one naive user completes the scan → review → name-a-person flow; record completion + friction.
- **[Class B] Visual re-baseline** — `npm run visual:localwp`; review + accept the review-region diff (intended change from the queue rebuild); commit new baselines on `feature/e21-5`.

**Deferred to next phase (tech debt) — see the tech-debt register:**
- **[Class A] VoiceOver AT protocol** — the 6 named utterances/behaviors from the E21-5 Verification Strategy. Deferred; not required for this merge. Tracked as tech debt (`docs/tech-debt/e21-5-voiceover-at-protocol.md`).

When the three UX-flow items are recorded and blocker #36's AT sub-item is split out to the deferred register, the task proceeds to the pre-merge gate and merge.
