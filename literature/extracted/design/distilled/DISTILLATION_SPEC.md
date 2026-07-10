# Design distillation spec (v1 — 2026-07-09)

Every file here is a **decision-rule source for design choices** — aesthetic direction AND practical mechanics — feeding the design-heuristics lexicon (`docs/strategy/design-aesthetics-heuristics.md`), the third strategy document beside engineering and business/marketing.

## Scope boundary (critical)

The engineering lexicon already owns **UI implementation mechanics** (predefined scales, spacing-signals-grouping, weight-over-size hierarchy, shade scales, elevation systems, WCAG floors — its `UI-*` rules from Refactoring UI). **Do not restate those.** This lane owns what sits above and beside them: identity and brand aesthetics, typographic systems and voice, colour *systems and meaning* (not shade generation), layout composition and asymmetry, image direction, cultural positioning, and naming. Where a rule borders the engineering lexicon, add `↔ eng UI-xx` and give only the non-overlapping part.

## Required structure

Same skeleton as `../refactoring/distilled/DISTILLATION_SPEC.md`: Source/Contributes header, Chapter map, `{#ch-n}` anchored chapters, Decision rules (summary), Anti-patterns, Applicability & exemptions, Candidate lexicon rows.

## Content rules

1. **Falsifiable condition→action**, triggers observable in a mockup, brief, brand asset, or channel context. "Make it beautiful" is not a rule; "when an identity must survive at 16px favicon and on a poster, design the mark at both extremes first and let the middle sizes follow" is.
2. **Aesthetic judgment compresses to named principles**, not vibes — keep the author's names (asymmetry, active white space, big-type identity, colour temperature, house style) bolded at first definition.
3. **Cultural context survives**: why a choice signals what it signals, and to whom — era-correct tactics but keep the signal mechanics.
4. **Numbers and systems verbatim** (type scale ratios, measure ranges, line-height rules, colour harmonies); anecdotes → ≤6-line scenario→lesson.
5. **For non-design sources** (brand/adult-economy business books in this batch): distill toward *bootstrap brand-building under constraint* — attention economics, taboo/stigma navigation, licensing and rights, platform dependency, self-promotion mechanics. Route those rows to phase `brand`.
6. Keep cross-source disagreements (`↔ contra <slug> ch-n`).
7. Chapter anchors are API. Length 350–650 lines.

## Candidate lexicon row grammar

```
| <trigger> | **<Rule name>** — <rationale> | <activating question> | <blocker|should|judgment> | <identity|type|colour|layout|image|brand> | src: <slug> ch-<n> |
```
