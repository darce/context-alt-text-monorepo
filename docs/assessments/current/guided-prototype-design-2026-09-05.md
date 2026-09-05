# AltContext guided prototype: delivery decision and ASCII iteration

Date: 2026-09-05. **Design proposal for iteration; no components or deployment.**
Audience: invited hiring managers, with a controlled screen share as the initial delivery.

## Delivery decision

Use **the existing demo domain, a branded entrance, and a guide inside the actual
WordPress plugin UI**. Preserve WordPress authentication. The guide opens a prepared
review scenario directly, with no detour through the WordPress dashboard.

**The flagship demonstration is the description transformation:** visual facts +
confirmed face identity + relevant page context become a coherent named description.
Identity confirmation is the input; readable, grounded prose is the output. The
tour must make that causal link visible before explaining its implementation.

| Option | Visitor experience | Work / limitation | Decision |
| --- | --- | --- | --- |
| Existing domain + actual plugin + inline guide | Recognizable WordPress workflow; reviewer makes decisions in context | Needs scenario isolation and a prepared entry route | Recommended |
| New subdomain | Another address for the same journey | Does not solve login, seeding, or unavailable generation | No benefit for this audience |
| Unauthenticated results page | Easy to open and read | Demonstrates output, with little evidence of the editor's interaction design | Use case study for this job |
| Separate interactive replica | Can run independently of WordPress | Duplicate UI can drift; must be labelled as a simulation | Fallback only if real-component isolation proves expensive |

There are two delivery stages, with the **same screen design**:

1. **Initial interview:** Daniel signs into the demo and screen-shares the prepared
   plugin screen. This uses existing authentication. A short captioned recording
   and equivalent text walkthrough are the fallback. No new guest-auth system is
   required to demonstrate the journey this way.
2. **Later invited self-service:** an expiring invitation establishes a restricted
   session and opens the same prepared screen. It must not grant administrator
   permissions. This is proposed infrastructure, not an existing capability.
   Public visitors see the branded introduction and case study; they cannot mint
   their own guest sessions.

The homepage can explain a hiring-only prototype without distributing access.
On an authorized invitation/session it offers **Open a saved example**. Otherwise
it says **Available through a guided walkthrough** and makes **Read the case study**
the useful action. A button must not promise access and then expose a login surprise.

Keep darce.xyz and the AltContext case study authoritative. Leave the resume and
cover-letter strategy intact. Add the case-study secondary prototype link only
when the entrance and seeded journey are ready; its destination must explain the
invitation requirement. The altcontext.com marketing-site rework is separate.

## Verified context and limits

- Anonymous GET `/` returned 200 with “Hello world!”. Anonymous `/wp-admin/`
  redirected to `wp-login.php`. **The plugin admin remains authenticated.**
- Headless Chrome via the installed Playwright CLI/runtime reproduced the login
  boundary. The saved browser authentication state is stale: both prepared admin
  route attempts reached login. The admin inventory here is grounded in current
  repository code and existing UX maps, not a fresh authenticated visual inspection.
- The unauthenticated WordPress media endpoint returned 100 attachments in the
  requested page. Its first records identify public figures in their metadata,
  including Keanu Reeves and Emma Watson. A direct image request returned 200.
  This is separate from admin access and from the intended hiring-only audience.
- `infra/oci/demo/seed/README.md` records 100 celebs01 images and an operator-accepted
  editorial/fair-use demonstration basis (E15-29), with attribution and takedown on
  request. This supports the historical decision, not a claim that subjects gave
  consent or that every image has a verified licence. Use existing samples for
  private design review; do not label them “consented sample photographs”.
- Public-figure status does not establish ownership of the photograph. The
  [US Copyright Office](https://www.copyright.gov/engage/photographers/) explains
  that the photographer generally owns the initial copyright; Canadian
  [Copyright Act section 29](https://laws-lois.justice.gc.ca/eng/acts/c-42/Section-29.html)
  lists fair-dealing purposes. These sources do not establish that this particular
  use is legally cleared. No wider rights review is needed to iterate these text maps.
- Read-only inspection downloaded attachment 104 for visual context. Its existing
  metadata names Keanu Reeves and credits Governo do Estado de São Paulo. The
  image is a portrait crop. That means a proposed description must not invent the
  wider meeting scene simply because it appears in the caption metadata.
- Main contains the GPU lifecycle, durable describe-run and UI status paths;
  `docs/assessments/current/demo-landing-plan-2026-09-04.md` tracks pending integration
  and live-proof work. No paid inference or GPU start was performed here. Treat
  current live generation as **unverified and unavailable in this guided build**.
  A future GPU merge does not silently switch this tour to live inference.

## Prior art used

Code discovery used `Users-daniel-Development-context-alt-text-monorepo`; the shorter
duplicate project was found to be older and was not used for the final anchors.
The graph has current coverage metadata for the existing components below.
Semantic prior-work retrieval returned `embeddings_mode=verified`, model
`gte-base-en-v1.5`, with no degradation; E15-28 (demo provisioning), E20-9 (page
context), E20-10 (confirmed identities), and E15-24 (admin exposure) were useful leads.
Historical findings are not assumed to be current defects.

| Existing surface | Reuse / design implication |
| --- | --- |
| `js/admin/App.tsx:App` | Existing Workbench, People, Description History and Settings routes; guide must stay within the current router |
| `js/admin/pages/workbench/WorkbenchTwoPaneLayout.tsx:WorkbenchTwoPaneLayout` | Reuse the two-pane workspace and existing keyboard splitter; narrow layouts currently put Library before Control |
| `js/admin/pages/workbench/identity-clusters/ClusterReviewPanel.tsx` | Existing identity evidence/review surface; do not invent a Confirm tab |
| `js/admin/pages/DescriptionHistoryPage.tsx` | Existing history and correction destination; use it for editorial provenance |
| `js/admin/api/describeApi.ts:correctDescriptionHistoryItem` | Graph traces correction to `useCorrectMediaAlt`; map correction as a record change, not a cosmetic text replacement |
| `js/admin/pages/SettingsPage.tsx` | Retention is under Settings in current router; show a bounded scenario policy view without exposing service settings |

Paths above are relative to `apps/prototype-wp-alt-context/`.
Existing authentication evidence: `tests/e2e/auth-setup/auth.setup.ts` and
`docs/runbooks/deploy-demo-cicd.md`. Existing walkthrough and reset runbooks live in
`infra/oci/demo/`; the reset runbook currently describes **manual** reset by default,
not a proven automatic per-visitor reset.

The August `DEMO-UX-1-ascii-screens-r1.md` already identified the need for a
hiring-manager entry point and return path. Its login-only conclusion and old
navigation diagrams are historical context. This proposal incorporates the latest
request for a branded entrance, offline scenarios, and accessibility at design time.

## Identity woven into descriptions: evidence worth surfacing

Semantic retrieval surfaced E19-4A, VLM-2A and E20-FUSION. Current graph discovery
then located `scene/application/identity_merge/merge.py:merge_identities`, which
returns `generic_draft`, `named_draft`, associations and naming provenance. It
matches eligible confirmed faces to grounded phrases, uses a positional fallback
when phrase boxes are absent, and keeps generic text when grounding is ambiguous.
Naming policy can suppress insertion. This is implemented source, not just a plan.

The inbound call graph reaches `naming_preview_service.py:naming_preview`,
`describe_run_worker.py:_apply_naming_preview`, and the fusion reconciliation path.
The worker bounds naming work by the remaining item deadline and preserves the
generic result on failure. The preview is documented as draft-only. This supports
the design's separation between description creation and application, but does
not prove that today's deployed WordPress build completes the whole journey.

| Evidence inspected | What the status panel may say | Limit to keep alongside it |
| --- | --- | --- |
| `docs/tasks/altq/bakeoff-results/run-altq-646-interleave-v3.json` | Saved two-pass description experiment: Qwen3-VL-30B-A3B-Instruct Q4_K_M; 640 non-error description records / 646 items; six failed items; build `5a67b070fe8e383ffd243a77029d2225b6f8d700`, 2026-07-16 | Saved generation evidence, not 99% accuracy, today's availability, or validated recognition-to-name correctness |
| Same record's `describe_facts` and `ground_weave` pass outputs | Inspect a selected output's intermediate visual facts and final wording | A celebrity name in text is not proof of confirmed recognition: inspected media 47 has an empty `identities` list but names Emma Watson in its draft |
| `docs/tasks/20.0/E20-FUSION-staged-report.json` and matching run record | A saved ten-item fusion harness exercised context and name insertion | Producer is `seeded` / `fusion-eval-stub`; report contains one wrong-name image, a rescoring manifest mismatch and refused facial identification metrics. Not a live model accuracy claim |
| `tests/e2e/evidence/e19-4a-named-preview.spec.ts` | Existing LocalWP evidence harness compares generic/named drafts and naming provenance | Its scenario seeds confirmed identities directly and uses a seeded adapter with positional fallback. Harness source is not a fresh passing run |

Backend paths above are under `apps/prototype-description-service/`; E2E path is
under `apps/prototype-wp-alt-context/`. Do not copy the June assessment's external
93.2% insertion-rate citation into an AltContext performance claim: that number is
from another system's published research, not this repository's experiment.

In the tour, the default is the clearly labelled illustrative comparison below.
A **View saved experiment** disclosure in implementation status can later present
a checked original output with its real build/model/time and limitations. The
benchmark corpus contains personal as well as celebrity images; select only the
intended existing demo samples and verify image bytes/context before importing a
record. Keep the full raw corpus outside the hiring-manager UI.

## Iteration 1 → iteration 2

These are two design passes, not user-test results.

| First-pass idea | Heuristic problem | Current revision |
| --- | --- | --- |
| Tour bubbles floating over controls | Can obscure focus, force visual search, and complicate reflow | One inline guide above the workspace; no spotlight overlay |
| Guide sidebar beside Control and Library | Three competing columns; too little room at zoom | Guide spans both panes; collapses to a one-line step summary |
| Three equally prominent scenario cards at the entrance | Choice before first success | Confirmed identity is prepared; other examples are secondary navigation |
| “Next” advances after every action | Adds clicks and may mark unread work as reviewed | Actions update state; a named continuation remains user-controlled |
| Auto-advance immediately after confirmation | Steals focus before feedback is read | Keep focus on the action; announce the result; enable “Review saved description” |
| “Apply” changes the original sample attachment | Shared visitor state and reset races | Apply to a session's scenario copy; show that scope beside the action |
| Reviewer names the face visually to continue | Sight becomes a requirement | Text evidence route and “Leave unidentified” are equally available |
| One “Saved output” badge on the landing page | Provenance lost when deep-linking into a result | Provenance appears on each candidate and in history |
| Identity confirmation followed by an unexplained final caption | Core identity-to-prose contribution is invisible | Show generic draft → confirmed identity + context → named draft together, with textual explanation |

## ASCII screens, revision 2

`[button]` denotes an action; underlined-style text is represented as a plain link.
Map IDs match `guided-prototype.uxmap.json`. These are proposed states, not
screenshots of shipped behavior. Product navigation shown is a restricted tour
subset; retain WordPress chrome and current plugin labels when implemented.

### S0 · `entrance` · existing domain, no surprise login

```text
+-----------------------------------------------------------------------+
| AltContext                                      Read the case study   |
|                                                                       |
| AltContext — guided WordPress prototype                                |
| Explore how AltContext brings confirmed identities and page context    |
| into an editor-reviewed image-description workflow.                    |
|                                                                       |
| Prototype status                                                      |
| The interface and saved review scenarios are available.                |
| Live description generation is not available in this build and         |
| remains under development.                                            |
|                                                                       |
| Invited session:                                                      |
| [Open a saved example]     Read the case study                          |
| View implementation status                                            |
|                                                                       |
| Without an invitation:                                                |
| Available through a guided walkthrough with Daniel.                    |
| [Read the case study]      View implementation status                  |
+-----------------------------------------------------------------------+
```

Only one access variant is rendered. No sample gallery on this entrance. An expired
invitation has its own explanatory state, not a WordPress error page. Keep the
case-study and status links usable if the tour is unavailable.

### S1 · `identity` · prepared Review Queue

```text
+---------------+-------------------------------------------------------+
| WordPress     | AltContext · Guided prototype              [End tour] |
|               | Changes affect your practice example only.            |
| AltContext    |                                                       |
| Review Queue  | 1 Identity  >  2 Description  >  3 Result               |
| People        | Confirm a name only when the evidence supports it.    |
| Description   | Use the sample record, or leave this person unnamed.  |
|   Runs        | [Jump to review controls]           [Hide guide]      |
|               +---------------------------+---------------------------+
|               | CONTROL                   | LIBRARY                   |
|               | Identity: unconfirmed     | [prepared portrait]       |
|               | Sample record names:      | Text image description    |
|               | Keanu Reeves              | Portrait crop; grey       |
|               | [Inspect source record]   | jacket, plain background. |
|               |                           |                           |
|               | [Confirm sample identity] | Page context              |
|               | [Leave unidentified]      | Illustrative actor profile|
|               |                           | Name is useful only if    |
|               | Review saved description  | the editor confirms it.   |
|               | (available after choice)  |                           |
|               +---------------------------+---------------------------+
|               | Illustrative scenario—not generated by the current   |
|               | service. Source metadata is evidence, not a model     |
|               | identification.                                       |
|               | Other examples: Uncertain identity · Edit or reject   |
+---------------+-------------------------------------------------------+
```

The name comes from the existing sample metadata, not facial identification by the
tour. Confirmation is a new practice editorial decision. Its immediate feedback:
**“Identity confirmed for this example. The description has not been applied.”**
The action remains in place, visibly complete; focus is not moved automatically.
“Review saved description” becomes available. Naming never applies alt text.

Provide a useful, independently authored text equivalent for the portrait from the
start. Do not force a screen-reader user to encounter an unlabeled image in order
to demonstrate an accessibility product. The editable candidate is separate.

### S2 · `uncertain` · same workspace, useful uncertainty

```text
+-----------------------------------------------------------------------+
| 1 Identity > 2 Description > 3 Result                     [End tour]   |
| Uncertain identity · Illustrative scenario                             |
|                                                                       |
| Evidence does not establish a name for this practice example.          |
| A resemblance or filename alone is not confirmation.                   |
| [Inspect source record]                                               |
|                                                                       |
| [Keep person unidentified]                                            |
| No name will be supplied to this example's description.                |
|                                                                       |
| After choice:                                                         |
| Identity left unresolved. You can still review a description.          |
| [Review saved description]                                            |
+-----------------------------------------------------------------------+
```

This is a deliberately constructed unresolved record, even if a viewer recognizes
the celebrity. Do not claim the production recognizer was uncertain or invent a
confidence score. A known name must not leak into the unnamed candidate. Different
identity branches select different illustrative candidates; never relabel an old
generated output as though it had been recomputed with a new identity decision.

### S3 · `description` · review before application

```text
+---------------+-------------------------------------------------------+
| WordPress     | 1 Identity [done] > 2 Description > 3 Result           |
| AltContext    | Review the wording in its page context.                |
| Review Queue  |                                                       |
| People        | Current image alt text: Not set                       |
| Description   | Page: illustrative actor profile                      |
|   Runs        | Identity supplied: confirmed from sample record       |
|               |                                                       |
|               | How identity changes the description                  |
|               | Illustrative scenario—not generated by the current   |
|               | service.                                              |
|               |                                                       |
|               | Visual draft                                          |
|               | A person in a grey jacket against a plain background. |
|               |                                                       |
|               | + Confirmed sample identity: Keanu Reeves              |
|               | + Page context: illustrative actor profile            |
|               |   The name is relevant here; no new scene is inferred.|
|               |                                                       |
|               | Identity-informed candidate                           |
|               | +---------------------------------------------------+ |
|               | | Keanu Reeves in a grey jacket against a plain      | |
|               | | background.                                       | |
|               | +---------------------------------------------------+ |
|               | [Inspect provenance]                                  |
|               | Changed: “A person” became the confirmed name.         |
|               | Visual facts are preserved. Nothing has been applied. |
|               |                                                       |
|               | [Review and apply…]    [Edit description] [Reject]    |
|               | Applies only to this practice example.                |
|               |                                                       |
|               | [Generate new description — unavailable]              |
|               | Live generation is under development in this build.  |
|               | Continue using the saved candidate above.             |
+---------------+-------------------------------------------------------+
```

Generic and named text remain readable together, rather than requiring a hover
or animated morph to reveal the difference. The explicit “Changed” sentence
conveys the same comparison without color or vision. At narrow widths these
sections stack in source order. For the uncertain scenario, the comparison says
“No confirmed name supplied; visual description retained.” The output stays
generic even if the visitor recognizes the public figure.

The textarea has a visible associated label in edit mode. “Save edit” stores the
revised candidate, preserves the original, and returns to this review state; it
does not apply. Empty edits show an inline error and retain focus and input.
Rejected candidates cannot be applied. “Use original candidate” is an explicit
reversible choice recorded in practice history, not a silent undo of rejection.

### S4 · `apply-preview` · inline final review, same page

```text
+-----------------------------------------------------------------------+
| 2 Description · Review application                                     |
|                                                                       |
| Image: prepared portrait        Destination: this practice example     |
| Before: Not set                                                       |
| After:  Keanu Reeves in a grey jacket against a plain background.       |
|                                                                       |
| This does not update the original WordPress media library.             |
| [Apply to this example]                [Back to editing]               |
+-----------------------------------------------------------------------+
```

This is a replace-in-place view, not an extra modal. A disabled, labelled Generate
control never issues a request. Its adjacent explanation is always visible and
programmatically associated; no tooltip-only reason or fake progress animation.

### S5 · `outcome` · the applied result and editorial record

```text
+-----------------------------------------------------------------------+
| 1 Identity [done] > 2 Description [done] > 3 Result                      |
| Applied to your practice example                                       |
| The original WordPress attachment is unchanged.                        |
|                                                                       |
| Image alt text                                                        |
| Keanu Reeves in a grey jacket against a plain background.               |
|                                                                       |
| Editorial history                                                     |
| 1. Confirmed sample identity                                           |
| 2. Opened illustrative candidate                                       |
| 3. Edited wording                    (only when an edit occurred)      |
| 4. Applied to practice example                                         |
| [Inspect provenance]       [Undo application]                          |
|                                                                       |
| [Try uncertain identity]   Try edit or reject                          |
| Review data choices        Read the case study         [End tour]     |
+-----------------------------------------------------------------------+
```

The history order follows actual session actions (identity generally precedes
opening the candidate). The list above illustrates event types, not a fixed fake
timeline. Undo restores the previous applied value and appends an undo event;
it does not erase the revision history or relabel the candidate as generated.

### S6 · `rejected` · a successful editorial decision

```text
+-----------------------------------------------------------------------+
| Edit or reject · Description review                                    |
| Saved illustrative candidate:                                         |
| “Keanu Reeves looks confident before an important meeting.”            |
|                                                                       |
| The portrait does not establish confidence or what happens next.       |
| [Edit description]          [Reject candidate]                         |
|                                                                       |
| After Reject:                                                         |
| Rejected. Current alt text remains unchanged.                          |
| Reason (optional): [Unsupported inference                         ]    |
| [Revise rejected candidate]       [Choose another example]             |
+-----------------------------------------------------------------------+
```

No failure styling for a considered rejection. An edited candidate still needs
the explicit apply step. A saved rejection and its optional reason are practice
history; they are not training data or a promise of model retraining.

### S7 · `data-choices` · bounded privacy interaction

```text
+-----------------------------------------------------------------------+
| Data choices for this practice example                  [Back to tour] |
|                                                                       |
| Names in descriptions                                                 |
| [x] Allow confirmed names in a future description                      |
| Only confirmed names can be included.                                  |
| Turning this off does not rewrite an already applied description.      |
| [Save example preference]                                             |
|                                                                       |
| In this tour                                                          |
| Photos and candidates are prepared examples.                           |
| Your edits stay in your practice session and are cleared at its end.   |
| Images are not sent for generation by this guided build.               |
|                                                                       |
| [Clear my practice changes…]                                           |
| Service settings and credentials are outside this guest experience.   |
+-----------------------------------------------------------------------+
```

The checkbox changes the session's identity-input policy; switching it off selects
the unnamed illustrative candidate for a subsequent review. Existing applied text
remains visible until the editor explicitly replaces it. Before save, show this
effect and the next “Review unnamed candidate” action. Do not claim this changes
production retention or retroactively removes names from published content.

### S8 · `reset-dialog` · the only modal needed

```text
+-----------------------------------------------------------------------+
| Clear your practice changes?                                          |
| This removes your edits, decisions and applied text from this session. |
| The prepared examples and original media are preserved.                |
| [Keep my changes]                 [Clear practice changes]             |
+-----------------------------------------------------------------------+
```

Focus starts on Keep. Escape cancels; focus returns to the invoking control.
After clear, focus moves to the prepared scenario heading and a status announces
the reset. End tour invalidates/clears the session without touching other visitors.
While a remote session-clear request is pending, keep the dialog and its focus
scope visible. On failure, preserve the changes and say “Practice changes could
not be cleared. Try again or keep your changes.” Never show reset success before
the session boundary confirms it. Repeated Apply/Clear clicks must be idempotent.
Avoid automatic idle resets during review; an eventual auth expiry needs a visible
warning, an accessible extension where permitted, and a clear recovery path.

### S9 · `status` · implementation boundary / fallback

```text
+-----------------------------------------------------------------------+
| Implementation status                                                 |
| Prepared scenarios: available in this guided build                     |
| Identity, editing and applying: interactive practice workflow          |
| Live generation: unavailable; under development                       |
| WordPress/GPU integration: separate implementation evidence            |
| [View saved description experiment and its limits]                     |
|                                                                       |
| [Return to saved example]                                              |
| Read the case study · Read the walkthrough transcript                  |
| Watch the captioned walkthrough (show only once recorded)              |
+-----------------------------------------------------------------------+
```

If no authorized session exists, primary action is Read the case study. A session
failure states “Your practice session has ended” with an invitation recovery path.
Do not show stale “available” labels when scenario loading failed. Until the saved
build exists, entrance copy must instead say “Prepared walkthrough in development”.

### Narrow layout · same information at 320 CSS pixels

```text
+--------------------------------+
| WordPress / AltContext          |
| Guided prototype    [End tour]  |
| 1 Identity / 3 steps            |
| [Show steps] [Hide guide]       |
| Confirm only with evidence.    |
| [Jump to review controls]      |
+--------------------------------+
| LIBRARY                        |
| [portrait]                     |
| Text image description         |
| Page context / source record   |
+--------------------------------+
| CONTROL                        |
| Identity: unconfirmed          |
| [Inspect source record]        |
| [Confirm sample identity]      |
| [Leave unidentified]           |
| [Review saved description]     |
+--------------------------------+
```

Respect the existing Library-first narrow layout. The “Jump to review controls”
link makes the primary action reachable without scrolling through an image.
The guide is in normal flow; it never covers focus or reduces the workspace to a
scrolling slit. Controls wrap vertically. Source details use inline disclosures.
Show the full named step list when expanded, with current/completed text.

## Interaction contract before components

| Event | State change | Feedback / focus | Invariant |
| --- | --- | --- | --- |
| Open saved example | Load versioned seed into isolated session | Focus scenario heading | No scan, GPU start or description generation |
| Confirm / leave unidentified | Update practice identity record | Polite status; preserve focus | No applied-text change |
| Open saved candidate | Select candidate matching scenario and identity policy | Focus description heading | Illustrative origin remains visible |
| Save edit | New revision of candidate + history event | “Edit saved. Not applied.” | Original provenance retained |
| Reject | Mark revision rejected | “Rejected. Alt text unchanged.” | No application possible from rejected state |
| Apply | Replace applied value in practice copy; append event | Focus result heading; announce once | Only explicit Apply changes applied value |
| Undo application | Restore previous value + append event | Polite status; preserve focus | Candidate edit and provenance remain |
| Change examples | Retain each example's local practice state | Focus new scenario heading | Never mixes one image's evidence with another |
| Clear / End tour | Reset current session / invalidate session | Announce reset / focus exit heading | Other sessions and original media unaffected |

One state owner per session drives the candidate, applied text and history. A
fixture adapter can implement these transitions while reusing plugin components.
Do not give a frontend overlay access to live mutation APIs and call it a sandbox.
Guest capabilities, API authorization and any fixture write boundary must enforce
the same scope that the interface promises. Existing administrator sessions must
not be silently converted into guest sessions by the entrance.

Every candidate has an explicit origin: `illustrative` or `saved-build`, scenario
version, image reference, page-context snapshot, identity-input state and revision
history. `saved-build` additionally requires a real build identifier and run
evidence. Never fill “build X” with an invented value. This first design uses
illustrative candidates throughout.

## Heuristic review and falsifiers

The local `~/Development/heuristics-canon-research` corpus was read directly:
accessibility, interaction-UX and engineering lexicons; Principles 1, 4, 5, 9 and 10;
CARD-09 (feedback and bounded waiting), CARD-12 (perceived/enforced boundaries);
distilled DDIA, *Latency* and *Release It!*. Rules are applied to observable triggers,
not counted as votes. Public canon was checked for the current source surface.

| Trigger / source | Decision | What would disprove the design |
| --- | --- | --- |
| A11Y-02/03/04/12; native controls and text alternatives | Labelled buttons/fields, useful image text, no visual-only identity task | Keyboard/AT user cannot complete the unresolved-identity route |
| A11Y-08; WCAG reflow | Inline guide; existing narrow pane order; jump link | 320px or 400% desktop zoom requires two-dimensional scrolling |
| NAV-09/12; recognizable workflow | Named progress and actual plugin components | Reviewer cannot say where they are or how to return |
| HAI-01/02/09; Principles 9/10 | Source evidence plus immutable origin; corrections reach session state | A deep-linked candidate loses its label, or rejected text returns after navigation |
| DDIA ch-11 / DATA-14 | One authoritative session state, derived history/result views | Editing one view leaves another showing a conflicting current value |
| Latency ch-1/2 / PERF-01 | Local saved path; measure feedback distributions later | Opening/acting waits on GPU, or median hides stalled interactions |
| Release It! ch-5 / RES-03 / CARD-09 | No live-generation dependency in the tour | A slow/down service prevents reading, editing, or exiting |
| CARD-12 / Principle 10 | Restricted session enforced below UI | Guest can call an original-media or settings mutation directly |
| Principle 4 / A11Y-23 | Distinguish map critique, automated checks, and human evidence | An axe pass is reported as full screen-reader or WCAG conformance |

Primary accessibility sources: W3C guidance on
[focus not obscured](https://www.w3.org/WAI/WCAG22/Understanding/focus-not-obscured-minimum.html),
[status messages](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html), and
[reflow](https://www.w3.org/WAI/WCAG22/Understanding/reflow.html). These support the
flow-first guide, programmatic feedback and narrow layout; they do not certify this
unbuilt interface. HAI-01's corpus source is marked bootstrap, so its evidence-first
rule is a design hypothesis here, not an externally established standard.

Before building, iterate this map against the three journeys with a keyboard-order
walkthrough on paper. After components exist, run Playwright behavior/axe/viewport
checks and manual VoiceOver/NVDA review. The existing
`docs/runbooks/operator-manual-acceptance-playbook.md` distinguishes automated
rehearsal from human AT and unaided-use evidence. None of those implementation
checks is claimed complete by these ASCII designs.

The accessibility acceptance contract starts with full keyboard operation, visible
unobscured focus, labelled controls, useful image alternatives, and a text-only
path through identity evidence. Check text/UI contrast at the actual color stage;
plan at least 44px control heights and clear spacing. Test 200% text size and 320px
reflow, including user text spacing. Named route changes move focus to the new
heading; same-screen saves use one polite status announcement. Do not announce
the same result through both focus and a live region. No time-limited tour steps,
hover-only content, drag-only action, or required animation is part of this design.

Map validation and generated renders are documented in
`guided-prototype-review-2026-09-05.md`. The map is the structural source of truth;
this document is the proposed copy, spatial sketch and interaction rationale.

## Recording script, once the journey exists

Target a short guided recording, approximately 90–120 seconds, with captions and
a text transcript. This is a pacing target, not measured visitor completion time.

1. State prototype status and open the prepared WordPress scenario.
2. Inspect the identity evidence and confirm the sample record.
3. Show the saved candidate's illustrative origin, page context and current alt text.
   Compare visual-only and identity-informed wording; explain exactly where the
   confirmed name enters the prose and why the page needs it.
4. Edit, review the before/after preview, and apply to the practice copy.
5. Show the editorial history; demonstrate leaving an identity unresolved.
6. Briefly reject unsupported wording and show the bounded data choices.
7. End with the case study and implementation boundary.

Describe the meaningful on-screen changes aloud. The video must work without
hearing via captions and without seeing via its descriptive transcript. Keep the
recording in the same invited-audience scope as the demonstration.
