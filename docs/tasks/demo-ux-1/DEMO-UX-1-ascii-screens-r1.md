# DEMO-UX-1 — Guided-login demo: ASCII screen inventory, round 1

**Audience decision (operator, 2026-08-22):** the demo is *not* public. It is a
guided-login wp-admin walkthrough shown to **hiring managers** evaluating Daniel.
No general-public funnel.

**Canon validation of that decision:** see §0. Verdict: **sound, with two
obligations it creates.**

Canon: heuristics-canon v0.21.6 `a5f47c6` — `lexicons/accessibility.md`,
`lexicons/interaction-ux.md`.

---

## 0. Does canon support "guided login, no public page"?

| Canon row | Bearing | Verdict |
| --- | --- | --- |
| INT-12 *first success before extract* | "deliver core micro-task success before account walls" | **Satisfied, not violated.** INT-12's harm is the *extract* — registration, profile, ads. A pre-provisioned credential handed to a named viewer extracts nothing. The wall is removed, not erected. |
| NAV-12 *match transferred conventions* | hiring managers bring a mental model | **Strongly favours this choice.** wp-admin is the convention for "a WordPress plugin". A bespoke public page is the novel chrome NAV-12 warns about. |
| HAI-09 *trustworthy ≠ trusted* | a demo is a trust claim | **Favours this choice.** A live workbench operating on real media is component evidence. A static Before/After page is the adjective-without-mechanism failure. |
| NAV-08 *clear entry points* | first-run "now what?" | **Creates obligation #1.** A hiring manager lands in wp-admin — a dense 6-item chrome they did not choose. §2 finding D-1. |
| NAV-07 *escape hatch* | limited-nav screens | **Creates obligation #2.** The viewer can wander into Data Retention/Settings and has no signposted way back to the demo path. |
| COG-03 *design to the goal filter* | viewer's goal ≠ operator's goal | The viewer's goal is "does this person build working software", not "clear my media queue". Copy written for an operator is off-goal for them. |

**Conclusion:** workbench-only is the right call and canon backs it. It shifts the
entire risk from *"does the demo exist"* to *"can a stranger complete the loop
unaided"* — which is exactly the GTM Phase 0 gate. Nothing in canon asks for a
public page for this audience.

---

## 1. The demo path (what we are actually asking a stranger to do)

```
  wp-admin login  →  Alt Context ▸ Overview  →  Review Queue (Scan)
        →  faces appear  →  name a person  →  alt text lands on media
```

Five hops. Canon NAV-09 wants the ordered, named steps visible with
current-and-remaining. **Today there is no step map anywhere in this flow.**

---

## 2. Screen renders

### S1 — Landing: `wp-admin` → Alt Context ▸ Overview

Rendered from `DashboardPage.tsx` (headings L138/L199/L241/L296-301),
`OrientationCard.tsx`, `GuidanceCard.tsx`.

```
┌────────────────────┬─────────────────────────────────────────────────────────┐
│ ⌂ Dashboard        │  Alt Context                                            │
│ ✎ Posts            │  Alt Context Overview                             <h1>  │
│ ▣ Media            │  Monitor your library coverage and manage identity      │
│ ▤ Pages            │  recognition jobs.                                      │
│ ✉ Comments         │                                                         │
│ ◈ Alt Context   ◄──┤  ┌── Identity Recognition ───────────────────── <h2> ─┐ │
│    Overview        │  │  ┌────────┐┌────────┐┌───────────┐┌──────────────┐ │ │
│    Review Queue    │  │  │ People ││Assigned││  Pending  ││  Media with  │ │ │
│    People          │  │  │        ││        ││  Review   ││    faces     │ │ │
│    Description Runs│  │  │   12   ││   9    ││     3     ││      41      │ │ │
│    Data Retention  │  │  └────────┘└────────┘└───────────┘└──────────────┘ │ │
│    Settings        │  │  3 faces are waiting for names.                    │ │
│ ⚙ Appearance       │  │  → Go to Review Queue                              │ │
│ ⚙ Plugins          │  └────────────────────────────────────────────────────┘ │
│ ⚙ Users            │  ┌── Library Coverage ───────────────────────── <h2> ─┐ │
│ ⚙ Tools            │  │  Total Media 41 · Missing Alt Text 18 · Coverage 56%│ │
│ ⚙ Settings         │  │  [████████████░░░░░░░░░]  → Fix missing descriptions │ │
│                    │  └────────────────────────────────────────────────────┘ │
│                    │  ┌── Data Retention ─────────────────────────── <h2> ─┐ │
│                    │  │  Current Mode: Retain all · Last Export: Never ...  │ │
│                    │  └────────────────────────────────────────────────────┘ │
└────────────────────┴─────────────────────────────────────────────────────────┘
     ▲ 6 ACX items                          ▲ OrientationCard NOT RENDERED
       + ~10 WP items                         (gated on people_count === 0)
```

**D-1 · NAV-08 + RLSE-04 — the onboarding is invisible to exactly the demo audience.**
`OrientationCard.tsx:13-15` returns `null` when `peopleCount !== 0`.
`DashboardPage.tsx:312` passes `identityStats.people_count`.
A demo tenant is *pre-seeded* so the walkthrough has something to show — so
`people_count > 0` — so the only three-step "what is this product" explainer
never renders for the one viewer who has never seen the product.
The card is written for an empty install; the demo is never an empty install.
Severity **HIGH**. This is the single biggest "now what?" risk in the demo.

**D-2 · NAV-05 — six ACX menu items, MECE fails.**
`class-menu.php:46-96`: Overview · Review Queue · People · Description Runs ·
Data Retention · Settings. "Name a person" has two homes (Review Queue *and* People).
"See what happened" has two homes (Description Runs *and* Data Retention audit timeline).
A first-time viewer cannot name the one place to go. Severity **MEDIUM**.

**D-3 · COG-03 — the page's own summary line is off-goal.**
"Monitor your library coverage and manage identity recognition jobs" is an
operator's job description. The viewer's goal is "see it produce alt text".
Nothing on the landing screen says what the product *does*. Severity **MEDIUM**.

---

### S2 — The first-run card, when it *does* render (empty install only)

Rendered from `OrientationCard.tsx:19-83`.

```
┌── Getting Started with Identity Recognition ───────────────────── <h2> ──┐
│                                                                          │
│   ⟨Scan⟩              →        ⟨Users⟩            →      ⟨CheckCircle⟩   │
│   1. Scan Media                2. Cluster Faces          3. Assign Labels│
│   Analyze your library         Automatically group       Name your       │
│   to detect faces and          similar faces into        clusters to     │
│   extract mathematical         "Clusters" to review      automatically   │
│   identities (embeddings).     many identities at once.  populate alt    │
│                                                          text across ... │
│                                                                          │
│                        [ Start your first scan ]                         │
└──────────────────────────────────────────────────────────────────────────┘
        ▲ jargon           ▲ RETIRED IA          ▲ RETIRED IA
```

**D-4 · NAV-13 + NAV-14 — the explainer teaches retired vocabulary.**
`roster-people.uxmap.json` goals state *"people-first surface; clusters tab
retired"*. The onboarding card still names step 2 **"Cluster Faces"** and step 3
**"Name your clusters"**. The UI a viewer then reaches is people-first. The
explainer describes an IA that no longer ships. Severity **HIGH** — a wrong map
is worse than no map.

**D-5 · NAV-13 — "extract mathematical identities (embeddings)".**
NAV-14 asks: would a target user file this where we did? A hiring manager parses
"embeddings" as implementation trivia, not as a benefit. Severity **MEDIUM**.

---

### S3 — Review Queue, 2-pane

From `WorkbenchTwoPaneLayout.tsx:148-192,354-355`.

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Review Queue                                                            │
│  [ Scan ] [ Confirm ] [ Review ]              ⟨sync ●⟩  [Advanced ▾]      │
├───────────────────────────────┬──────────────────────────────────────────┤
│  Control                 <h2> │  Library                            <h2> │
│                               │                                          │
│  ┌─ Analysis queue ─────────┐ │  ┌────────────────────────────────────┐  │
│  │                          │ │  │ ▣  IMG_0412.jpg                    │  │
│  │  Your analysis queue     │ │  │    No alt text yet                 │  │
│  │  is empty                │ │  │    [Suggest] [Edit]                │  │
│  │                          │ │  ├────────────────────────────────────┤  │
│  │  ← no next action        │ │  │ ▣  IMG_0413.jpg                    │  │
│  └──────────────────────────┘ │  │    "Two people seated at a table…" │  │
│                               │  └────────────────────────────────────┘  │
│  ┌─ Face groups ────────────┐ │                                          │
│  │  No identities detected  │ │                                          │
│  │  yet.                    │ │                                          │
│  │  ← no next action        │ │                                          │
│  └──────────────────────────┘ │                                          │
├───────────────────────────────┴──────────────────────────────────────────┤
│  ⟨resize handle⟩  role="separator"  aria-label="Resize control and        │
│                   library panels"                                        │
└──────────────────────────────────────────────────────────────────────────┘
```

**D-6 · NAV-08 — empty states are dead ends.**
Enumerated user-facing empty strings (27 unique): *"Your analysis queue is
empty"*, *"No identities detected yet."*, *"No previous jobs yet."*, *"No open
conflicts."*, *"No members found."*, *"No faces in this group."* — none carries a
next action. Canon NAV-08 wants a plain-language front door in exactly this
state. Severity **MEDIUM**, but it is the state a fresh demo tenant sits in.

**Counter-example worth preserving:** *"Face assignments unavailable — this is
not an empty backlog."* correctly distinguishes zero-from-broken. That is the
pattern the other 26 should copy. Do not regress it.

**D-7 · NAV-09 — no step map.** Scan/Confirm/Review are tabs, not a progress
indicator. Nothing says which step the viewer is on or how many remain.
Severity **MEDIUM**.

---

### S4 — Vocabulary audit (the cross-cutting finding)

**D-8 · NAV-13 — no controlled vocabulary; 35 user-facing strings leak internals.**
Enumerated from `js/admin` + `js/components` (`__()` call sites, tests excluded):

```
cluster / clustering  ......  22 strings   "Cluster the latest job results"
                                           "%d clusters created"
                                           "Assign outlier to cluster"
                                           "Clusters that have been matched to a person."
                                           "New clusters waiting for your review and labeling."
                                           "%d person has no assigned clusters."
tenant  ...............  8 strings         "Adopt API key tenant" / "Persisted tenant"
                                           "Tenant ID" / "Purge tenant data"
embedding  ............  3 strings         "Raw embedding vectors are excluded from exports."
provenance  ...........  2 strings         "…provenance incomplete"
```

NAV-13 requires a published say / don't-say list **before label freeze**. None
exists in the repo. Proposed starting list:

| Don't say | Say | Why |
| --- | --- | --- |
| cluster (noun) | **face group** | already the term in `WorkbenchTwoPaneLayout` / uxmap |
| cluster (verb) | **group faces** | |
| embedding | **face signature** (or omit) | benefit, not mechanism |
| tenant | **this site** | viewer has no multi-tenant model |
| provenance | **where this came from** | |
| outlier | **unmatched face** | |
| dead letter | **failed change** | already used correctly in one place |

Severity **HIGH** for the demo specifically — every one of these is a word the
viewer must silently translate, and COG-01 says the untranslated residue is what
drops the goal.

---

## 3. Findings summary

| ID | Canon | Sev | One-line |
| --- | --- | --- | --- |
| D-1 | NAV-08, RLSE-04 | HIGH | OrientationCard hidden on any non-empty tenant — invisible to the demo audience |
| D-4 | NAV-13, NAV-14 | HIGH | Onboarding teaches retired "clusters" IA |
| D-8 | NAV-13 | HIGH | 35 strings leak cluster/tenant/embedding/provenance; no say/don't-say list |
| D-2 | NAV-05 | MED | 6 ACX menu items; naming and history each have two homes |
| D-3 | COG-03 | MED | Landing copy is an operator job description, not what the product does |
| D-5 | NAV-13 | MED | "extract mathematical identities (embeddings)" |
| D-6 | NAV-08 | MED | 26 of 27 empty states are dead ends |
| D-7 | NAV-09 | MED | No step map across Scan → Confirm → Review |

**Not yet assessed** (round 2): error/degraded states (`DegradedModeBanner`,
`ConflictInbox`, `DeadLetterPanel`, `SyncStatusIndicator`), keyboard walk
(A11Y-11), contrast (A11Y-01), the HAI family against the naming loop
(HAI-01 evidence-before-label, HAI-15 commit-before-reveal, HAI-18 name-the-
deferred-effect), and the alt-text output surface itself (A11Y-02 — this product
must be exemplary at the thing it sells).

## 4. Open questions for the operator

1. Is the demo tenant pre-seeded with media+people, or does the viewer scan a
   fresh library live? D-1's fix differs: pre-seeded → orientation must render
   at any count; live-scan → the empty states in S3 become the primary surface.
2. Is a guided script / README handed over with the credential, or must the UI
   be self-explanatory? Canon NAV-08 assumes no script.
