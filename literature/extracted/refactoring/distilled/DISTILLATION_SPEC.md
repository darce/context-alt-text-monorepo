# Distillation format spec (v2 — 2026-07-09)

Every file in this directory is a **decision-rule source for junior LLM coding agents** and the upstream feed for the workbay `engineering-heuristics.md` lexicon. It is referenced, not read end-to-end: the lexicon cites `src: <slug> ch-<n>`, and an agent needing depth jumps to that chapter section. Optimize for that access pattern.

## Required structure

```markdown
# <Book Title> — distilled

> **Source**: <Author>, *<Title>*, <edition/year> · extracted from `../<source>.txt` · distilled <date> (spec v2)
> **Contributes**: <one paragraph — what this book adds to an engineering-heuristics lexicon that no other source in this directory does>

## Chapter map
<one line per chapter: `ch-N — <title>: <what it answers>` — this is the jump table>

## ch-1 — <Chapter title> {#ch-1}
<dense distillation — see content rules>

## ch-2 — … {#ch-2}
…

## Decision rules (summary)
| Trigger (observable in code/diff/plan) | Rule | Rationale | Src |
<the book's top 15–40 rules, one line each, `src: ch-N`>

## Anti-patterns
<named anti-patterns the book warns against, each with its detection cue>

## Applicability & exemptions
<when the book's advice does NOT apply — scope limits, false-positive conditions, contexts the author excludes. This section prevents junior reviewers from over-firing.>

## Candidate lexicon rows
<8–12 rows in exact lexicon grammar (see below) — the shortlist this book nominates for engineering-heuristics.md>
```

## Content rules

1. **Falsifiable condition→action.** Every rule reads "when/if <observable trigger>, do <action>, because <consequence>". "Write good tests" is not a rule; "a test that asserts on N unrelated fields will fail for reasons unrelated to its name — assert the one behavior the test names" is.
2. **Triggers must be observable** in a diff, plan, error message, or runtime signal — something an agent can pattern-match without judgment it doesn't have.
3. **Keep the author's names.** Named concepts (deep modules, seams, characterization test, bulkhead, coordinated omission) are retrieval keys — bold them at first definition.
4. **Micro-examples, not transcriptions.** Where the book's example is canonical, compress it to ≤10 lines (before→after or scenario→outcome). Never reproduce pages of worked code.
5. **Tables for catalogs.** Enumerable content (smell→refactoring, latency numbers, stability patterns, the 9 rules) becomes a table.
6. **Keep the disagreements.** Where the book contradicts another source in this directory, say so in one line (`↔ contra release-it ch-4: …`) — the lexicon needs the tension, not a false synthesis.
7. **Chapter anchors are API.** `{#ch-n}` anchors and the slug filename are cited by the lexicon; never renumber or rename once published.
8. **Length**: proportional to rule density, not page count — typically 400–900 lines; DDIA-class references up to ~1,800. The Decision-rules table is the hot path; chapters are the cold path.

## Candidate lexicon row grammar

```
| <trigger phrase> | **<Rule name>** — <one-line rationale> | <activating question> | <blocker|should|judgment> | <plan|write|review> | src: <slug> ch-<n> |
```

Tier: `blocker` = correctness/data-loss/security if violated; `should` = strong default, exemptions exist; `judgment` = weigh-in-context. Phase: where the rule fires (plan/write/review — pick the primary).
