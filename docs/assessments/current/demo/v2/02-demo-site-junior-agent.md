# Junior-agent brief: demo.altcontext.com

**Work type:** Public landing/guide copy and bounded presentation changes.  
**Primary route:** `/guide/`, based on the user's supplied rendered DOM.  
**Secondary route:** `/`, content discovery required; its actual markup was not supplied.  
**Primary outcome:** A visitor can explain the example roster and the recorded review boundary without mistaking the walkthrough for celebrity-recognition proof or a trial on their own library.  
**Premortem links:** PM-02, PM-04, PM-05, PM-06, PM-08.  
**Canon:** [HAI-02], [HAI-05], [CLM-03], [PROD-03], [GTM-05], [NDM-07].

## D0 — Reconcile the source revision: blocking prerequisite

The repository reference read during this assessment is `darce/context-alt-text-monorepo` main at `2895d4b92128d772b6eda9268ee4a6a474a2667d`. That reference is **not an instruction to reset to it**.

The user's `evidence/user-supplied-demo.html` differs from that revision in at least these respects:

- The supplied initial applied text is the longer AltText.ai-attributed sample. The read `state.ts` uses “Two people at a film festival.”
- The supplied left-subject gallery shows three reference photographs; the read `state.ts` contains two.
- The supplied public entrance omits the “Watch the recording” action that appears in the read source.

Find the branch or source revision that produced the supplied DOM, or obtain an explicit reconciliation from the owner. Preserve its baseline text, reference assets/counts, removed or gated actions, and existing fixes. Do not “repair” this divergence by downgrading the example to the older seed.

Start with the repository README/index and local agent instructions. Record `git status --short`, `git rev-parse HEAD`, and the relevant content-generation route. Never overwrite dirty files or touch generated bundles directly.

### Verified entry points at the read revision

Paths below are within `apps/prototype-wp-alt-context/` unless qualified otherwise. They are entry points to verify in the actual checkout, not an exhaustive allowlist.

| Path | Role / instruction |
|---|---|
| `js/admin/pages/GuidedPrototypeEntrance.tsx` | Public and admin branches are explicit. Change the public branch only for the new title and introduction. |
| `js/admin/guidedPrototype/publicGuideCopy.ts` | Durable public-only copy; add the new public keys here. |
| `js/admin/guidedPrototype/copy.ts` | Generated shared/admin catalog output. Do not hand-edit. |
| `docs/assessments/current/demo/altcontext_guided_demo_qm_v1/copy.en.json` at repository root | Source of generated `copy.ts`; change only if an intentionally shared phrase needs correction. |
| `scripts/generate_guided_copy.py` at repository root | Existing generator for that catalog. |
| `js/admin/guidedPrototype/RecordedWalkthrough.tsx` | Composes entrance, context, names, draft, outcome; preserves public/admin scope. |
| `js/admin/guidedPrototype/state.ts` | Sample data and state transitions. Do not overwrite the supplied newer fixture or add persistence. |
| `js/admin/pages/guided/GuidedSamplePhoto.tsx` | Evidence image, accessible fallback and current-alt caption. Preserve their distinct roles. |
| `js/admin/pages/guided/GuidedFacesPanel.tsx` | Referenced by the walkthrough; locate actual renderer for names/reference galleries. |
| `js/admin/pages/guided/GuidedDescriptionReview.tsx` | Referenced by the walkthrough; preserve preview and apply guards. |
| `js/admin/pages/guided/GuidedOutcome.tsx` | Referenced completion surface; use for the bounded next-action card. |
| `js/guide/main.tsx` | Public mount. Preserve its boundary from authenticated API/live-generation modules. |

Search for the exact attribution sentence from the supplied DOM. Its owner may not be `GuidedSamplePhoto.tsx`; the read version of that component has only the image and caption. Do not guess where a newer paragraph was introduced.

**Done evidence:** actual source revision identified and discrepancies dispositioned before a content overwrite.

## D1 — Reframe public entry without changing the admin experience

Use `copy/demo-public-copy.json` as the exact proposed wording. It is a specification, not a JSON file to import blindly into the existing catalog.

In `PUBLIC_GUIDED_COPY`, replace `scope.public` and add `entry.title.public` / `entry.intro.public`. Wire the public entrance to those keys. Keep the admin branch on its existing title and disclosure, including the separate live test.

Add the new public introduction beneath the H1. Reuse the existing typography class if suitable; avoid a new page shell. Keep the existing start action, escape navigation, and working secondary case-study action. Preserve the supplied video action's state; do not restore it solely because an older source has it.

The public root remains a `div` within the existing page landmark. Do not introduce nested `<main>` elements. Keep `data-scope="public"`, `data-testid="guided-demo-root"`, heading IDs, and control relationships.

**Done evidence:** public title/scope/intro visible and accessible; admin title and live separation unchanged; no new API imports or requests.

## D2 — Make the example roster visible in the existing review

Before the face cards, add a compact read-only explanation using `roster.explainer.title`, `roster.explainer.body`, and `roster.explainer.purpose`. Add `names.scope.public` near the inclusion choices or panel introduction, not after every radio action.

Do not build a second roster page. The existing cards already show the supplied names and reference photographs. Reuse those data; do not add duplicate thumbnail galleries, fictional people, fake counts, a simulated persistent database, or a “Create roster” button that does not create one.

The shared children currently import generated `copy.ts` directly. Adding a key to `publicGuideCopy.ts` alone does not update them. Pass public explanatory content through a small explicit prop or render it at the public composition boundary. Use the least intrusive existing pattern; do not create a global mutable copy mode or thread a new framework through the app.

Keep “Saved suggestion: {name},” the no-preselection behaviour, both include/omit radio options, reference-photo credits, and the stated shown/total reference coverage. Derive any new counts from actual scenario data; never hard-code the older two-reference fixture.

Do not add a third “not sure” state just for this copy task. “Leave this person unnamed” already supports omission. It is an editorial choice, not a durable negative match or proof that recognition was wrong.

**Done evidence:** the example is clearly a supplied roster, not a live roster editor; all existing name-choice combinations still work.

## D3 — Move comparative evidence into provenance, without deleting it

Move the entire existing paragraph beginning “The starting ‘before’ text was generated by…” into the existing provenance `<details>`. Preserve the vendor link, generation date, no-names/no-keywords condition, statement that the sample is unedited, and its single-sample limitation. Retain the recorded face-run disclosure and all image credits.

Use `context.source.summary.public` for the disclosure summary. Append `context.source.comparison_boundary.public` only when that attribution actually exists. Do not introduce a competitor attribution into a fixture that lacks its recorded evidence.

**Do not modify the actual starting alt text or sample drafts in this task.** The change is where provenance appears, not a rewrite of the evidence. The full unedited sample remains visible as the current applied text and/or within the existing accessible comparison.

This should remove the implied “competitor cannot name these people” storyline while retaining honest authorship. Do not relabel the competitor sample as “without roster” or “generic AI” because the recorded input condition is narrower than that.

**Done evidence:** exact baseline output and attribution preserved; paragraph now under provenance; no unqualified comparative quality claim.

## D4 — Keep drafting and effects accurately scoped

In the public draft surface, show `draft.origin.public` for a selected recorded sample, but preserve the distinct visitor-edited origin when the user edits. Do not erase provenance by labeling an edited draft as original generated output. Add the supplied-page-context explanation where it is not redundant with the context panel.

Keep all operational labels and controls in `unchanged_behavioural_copy`. Do not replace “Apply to demo copy” with “Publish,” “Save to WordPress,” or “Save to roster.” Keep preview invalidation after edits, the pending-name-change confirmation, history retention where it already exists, Undo, Reset, and keyboard/focus handling.

In the supplied DOM, disabled Apply with a stale-preview explanation is an expected guard; it is not evidence that the button should be enabled. Likewise, serialized HTML without a radio's `checked` attribute does not prove its live checked property is false. Use interaction tests before diagnosing a regression.

A manual draft edit may contain text beyond the chosen sample. Do not imply that omission choices enforce a ban on typing a name. No new name-stripping or authorization mechanism belongs in this content revision.

**Done evidence:** all include/omit combinations, edit, preview, apply, undo, keep, reset and failure behaviour still satisfy their existing contract.

## D5 — Add a bounded completion path

After both the applied and kept outcomes, show `outcome.scope.public` and the brief next-batch explanation. Do not equate “Keep current alt text” with failure. Do not show a “verified identity,” “library updated,” or “time saved” success summary.

Enable the optional workflow-discussion link only through `copy/optional-workflow-contact.json` and the main-site M2 approved destination. It may point to the verified main-site contact section with a fixed non-personal placement marker. No photographs, name choices, draft text or roster data are to be passed in the link or analytics.

If the contact dependency is unresolved, publish the explanatory completion text without a dead button. Record this slice's conversion dependency as blocked, not as delivered.

## D6 — Align the signed-out demo root

Locate the actual root landing source and route guards. Use `copy/demo-root-copy.md` for the content, without assuming that the supplied `/guide/` markup is the root page. Link to the public guide only when the site gate makes it available. Keep authorized invite/admin routes and their enforcement unchanged. Do not build a new landing application or duplicate the entire main website.

A disabled guide requires truthful availability text, not an auth bypass. If the root cannot be changed safely from the available source, report D6 separately as blocked and complete the guide tasks.

## D7 — Tests, review and release evidence

Use scenarios D-01 through D-10 and X-01 through X-04 in `acceptance/websites.acceptance.feature`. Extend the nearest existing tests after reading the actual checkout. Existing targets to inspect include `RecordedWalkthrough.test.tsx`, `js/guide/__tests__/public-boundary.test.tsx`, and the public guide failure tests. Do not blindly update snapshots to suppress behaviour failures.

Run the repository's documented test commands. When shared catalog input changes, regenerate once and prove a second generation produces no diff. When only public keys change, keep the generated catalog untouched.

Capture signed-out guide and admin regression evidence separately. Check mobile layout, enlarged text, keyboard-only completion, focus return from reference comparison, image-load fallback, script failure, source details, and optional-CTA disabled state. Inspect outgoing requests: no public recognition, generation, roster mutation or WordPress media write. Existing disclosed analytics are distinct from prohibited processing requests.

Do not test writeback or live inference with unauthorized customer data. No new package, migration, GPU setting, service, job contract, or API endpoint is part of this task.

**Report format:** D0–D7 disposition; actual source SHA; exact changed files; commands and results; screenshots; network evidence; remaining blockers; rollback instructions. Include the regenerated-file check if applicable. Do not claim that copy changes validate accuracy, demand, or deployment readiness for the broader product.
