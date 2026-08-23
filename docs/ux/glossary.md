# Alt Context controlled vocabulary

> Authored by the orchestrator, consumed by every lane. Do not invent
> synonyms; if a term is missing here, ask before coining one [NAV-13].

Wave 2 renamed the admin menu. These are the **only** user-facing names for
those concepts. Every page title, CTA, aria-label, help string, and empty-state
sentence must use the preferred term.

| Concept | Say | Don't say |
| --- | --- | --- |
| Landing page for the plugin | **Overview** | Dashboard, Dashboard Overview |
| Where you confirm face groups and write alt text | **Review Queue** | Workbench, the Workbench |
| The list of named people | **People** | Roster, Roster Management |
| Log of past description runs | **Description Runs** | Description Review History, Review History |
| Data-lifecycle settings | **Data Retention** | Retention, Retention & Audit Controls |
| A set of faces the system believes is one person | **face group** | cluster, identity cluster, embedding |
| Step 1 — find faces in the media library | **Scan** | Scan Media |
| Step 2 — confirm which face groups are one person | **Confirm** | Cluster Faces, Clustering (user-facing prose) |
| Step 3 — name people and write alt text | **Review** | Assign Labels |

## Rules

1. A menu label and the `<h1>` of the page it opens must be the **same words**
   [NAV-05]. "Review Queue" in the sidebar may not open "Alt Context Workbench".
2. Cross-references name the destination as the sidebar names it: "Open Review
   Queue", not "Open Workbench".
3. Prefer plain language over pipeline jargon in anything an operator reads.
   "face group" beats "cluster"; never surface "embedding" to an operator.
4. **Out of scope for this wave:** internal job-pipeline phase strings
   (`syncVocabulary.ts`, `phasePresentation.ts`, `DeadLetterPanel.tsx`,
   progress/status text) — a separate, larger change, left alone so this wave
   stays reviewable. This exemption is scoped to **non-navigational** strings
   only: progress labels, badges, and status prose. It does not cover a string
   that is itself the visible label of a link or button that navigates
   somewhere — those are cross-references and Rule 2 governs them regardless
   of which file they live in [BR-33]. A file appearing in this list is not a
   blanket pass for every string in that file.
