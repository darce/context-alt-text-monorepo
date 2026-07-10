# Business & marketing distillation spec (v1 — 2026-07-09)

Every file in this directory is a **decision-rule source for business, marketing, and product choices** — the upstream feed for the business-marketing heuristics lexicon (the commercial sibling of the engineering lexicon). It is referenced, not read end-to-end: the lexicon cites `src: <slug> ch-<n>`, and a reader needing depth jumps to that chapter section. Optimize for that access pattern.

## Required structure

Same skeleton as the engineering spec (`../refactoring/distilled/DISTILLATION_SPEC.md`):
header (Source / Contributes), Chapter map, `## ch-N — <title> {#ch-n}` sections, then:

- `## Decision rules (summary)` — table: `Trigger (observable business/product situation) | Rule | Rationale | Src`
- `## Anti-patterns` — named traps with detection cues
- `## Applicability & exemptions` — when the book's advice does NOT apply (company stage, market type, era-bound tactics)
- `## Candidate lexicon rows` — 8–12 rows in the grammar below

## Content rules

1. **Falsifiable condition→action.** "Focus on customers" is not a rule; "when a feature request comes from a customer who wouldn't pay more for it, log it and don't build it, because effort follows revenue-weighted demand" is.
2. **Triggers must be observable** in a roadmap, metric, conversation, or market signal — something an operator or agent can pattern-match without hindsight.
3. **Keep the author's names** for concepts (inversion, mimetic desire, muse business, calibrated question, lead measure) — bold at first definition; they are retrieval keys.
4. **Numbers survive, anecdotes compress.** Where the book gives thresholds, ratios, or scripts, keep them verbatim; war stories become ≤6-line scenario→lesson blocks.
5. **Era-correction is mandatory.** Tactics bound to a dead landscape (1988 chart mechanics, 2007 outsourcing arbitrage, pre-AI content playbooks) get distilled for their *transferable mechanism*, with the era-bound surface explicitly quarantined in Applicability. Say what the modern equivalent is when it's obvious; don't invent one when it isn't.
6. **Keep the disagreements** between sources in this directory (`↔ contra <slug> ch-n: …`).
7. **Chapter anchors are API** — never renumber after publication.
8. **Length**: 350–700 lines typically; rule density over page coverage.

## Candidate lexicon row grammar

```
| <trigger phrase> | **<Rule name>** — <one-line rationale> | <activating question> | <blocker|should|judgment> | <strategy|product|gtm|ops> | src: <slug> ch-<n> |
```

Tier: `blocker` = existential/irreversible if violated; `should` = strong default; `judgment` = weigh in context. Phase: where the rule fires — `strategy` (what to build/be), `product` (how to build/ship), `gtm` (how to sell/market), `ops` (how to run it).
