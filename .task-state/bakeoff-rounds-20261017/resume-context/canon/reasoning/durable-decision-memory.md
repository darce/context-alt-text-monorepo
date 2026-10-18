# Durable decision memory

Slug: `durable-decision-memory`
ID: `CARD-05`
Mechanism claim: Decisions, rationale, and operational intent must live where
the next reader will find them; head-only knowledge dies at handoff.

## Scope

Covers: architecture decision records; agent and session notes at discovery;
correlation IDs and post-mortem reconstructability; brand and ops authority that
must outlive a founder; handoff packets with intent and constraints.

Excludes: full provenance graphs for every data artifact (open PRINCIPLES
Principle 9 starting at GRPH-14 for walk-back of claims); measurement
dashboards (see [measurement-integrity](measurement-integrity.md)); dual-control completion (see
[dual-control-two-keys](dual-control-two-keys.md)).

## Observable triggers

- The same fact is re-derived twice in one session, or the plan lives only in
  chat context.
- An architecture choice has no written context/decision/consequences, or a
  diff silently contradicts a recorded ADR.
- Incidents require archaeology because logs lack correlation and decision
  trail.
- Brand or ops judgment exists only in one person's head.
- Handoffs list tasks without intent, priorities, constraints, or forbidden
  moves.

## Causal mechanism

Working memory and social proximity feel sufficient until succession, context
compaction, or on-call rotation. What was "obvious" to the author is invisible
to the next executor. Externalizing working memory can reduce the cost of resuming
interrupted work. The same discipline appears in programming cognition, ADRs,
observability, brand systems, and naturalist decision handoffs: write the
decision where the next person will look.

## Required action

1. Externalize plan, path verdicts, and model at discovery
   ([AGT-07](../lexicons/engineering.md#agt-07)).
2. Record architecture decisions as context, decision, consequences; amend
   rather than silently override ([ARCH-07](../lexicons/engineering.md#arch-07),
   [AGT-13](../lexicons/engineering.md#agt-13)).
3. Put correlation IDs on the path so post-mortems are greps
   ([OBS-03](../lexicons/engineering.md#obs-03)).
4. Systemize founder taste into rules and review
   ([BRND-12](../lexicons/design-aesthetics.md#brnd-12)); write authority so ops run without the hero
   ([OPS-08](../lexicons/planning.md#ops-08), [OPS-13](../lexicons/planning.md#ops-13)).
5. Ship handoffs with intent, priorities, constraints, and forbidden moves
   ([NDM-07](../lexicons/epistemics.md#ndm-07)).

## Predicted failure

Rework after context loss. Conflicting architecture "truths." Untraceable
incidents. Brand drift when the founder steps away. Executors improvise against
unstated constraints and reverse hard-won decisions.

## Worked example

A retro decides to freeze an API field, but the rationale lives only in chat and the OpenAPI file has no deprecation note. The trigger is operational intent stored outside the artifact consumers read. Record the decision, owner, and date next to the field (or linked ADR). Without durable memory, a later PR "cleans up" the field and breaks clients the chat no longer remembers.

## Exemptions and boundaries

- Throwaway spikes may stay oral if they ship nothing and leave no durable
  dependency; the card fires when another person or future self must continue.
- Not every micro-choice needs an ADR; use ADRs when the choice constrains
  future options or coordinates teams.
- Secrets do not belong in world-readable decision logs; record that a secret
  path exists and who owns it.

## Tensions

| Partition | Side A (keep fully) | Side B (keep fully) | Cut |
|---|---|---|---|
| object | [ARCH-07](../lexicons/engineering.md#arch-07) durable decision record | [REF-12](../lexicons/engineering.md#ref-12) refuse speculative extension points | write decisions that exist; do not invent future hooks as documentation theater |
| sequence | [AGT-07](../lexicons/engineering.md#agt-07) write at discovery | [AGT-12](../lexicons/engineering.md#agt-12) timebox and hand off when stuck | externalize early; when blocked, hand off legibly rather than thrash |
| surface | [NDM-07](../lexicons/epistemics.md#ndm-07) intent on the wire | [OPS-13](../lexicons/planning.md#ops-13) orders include rationale | same completeness demand on live handoff vs written order |

## Disconfirmers

- After a forced author absence, the next executor completes correctly from
  written artifacts alone (memory is durable).
- Silent ADR override still produced coordinated outcomes (process is theater;
  fix culture or the ADR is the wrong tool).
- Correlation-free logs still yield fast root cause under drill (instrumentation
  elsewhere carries the trail).

## Verification

- Decision log or ADR exists for each cross-cutting choice in the change.
- Session or agent notes capture path verdicts before context reset.
- Trace ID present on request path used in the last incident drill.
- Handoff template fields (intent, constraints, forbidden) are filled, not
  optional empty.

## Rule IDs

- [AGT-07](../lexicons/engineering.md#agt-07): externalize at discovery
- [AGT-13](../lexicons/engineering.md#agt-13): no silent ADR override
- [ARCH-07](../lexicons/engineering.md#arch-07): ADR with context, decision, consequences
- [OBS-03](../lexicons/engineering.md#obs-03): correlation ID on the path
- [BRND-12](../lexicons/design-aesthetics.md#brnd-12): brand rules outlive the founder
- [OPS-08](../lexicons/planning.md#ops-08): written authority for absence
- [OPS-13](../lexicons/planning.md#ops-13): orders include who/what/when/where/why
- [NDM-07](../lexicons/epistemics.md#ndm-07): intent and constraints on the handoff
- [AGT-12](../lexicons/engineering.md#agt-12): legible handoff after timebox
- [TEAM-17](../lexicons/planning.md#team-17): no single-head knowledge concentration
- [TEAM-14](../lexicons/planning.md#team-14): published plan with an owned revision trail
- [COG-09](../lexicons/interaction-ux.md#cog-09): write the visit's concerns down at the start and track them through interruptions

## Principles

- 7. Write it where it outlives the person who knows it

Also load Principle 9 when the artifact is a claim that must walk back to
inputs, not only a decision that must outlive its author (open PRINCIPLES
starting at GRPH-14). Walkable lineage is not this card's owned mechanism.

## Evidence / source slugs

- [`programmers-brain`](../SOURCES.md#src-programmers-brain): supports [AGT-07](../lexicons/engineering.md#agt-07)
- [`architecture-hard-parts`](../SOURCES.md#src-architecture-hard-parts): supports [AGT-13](../lexicons/engineering.md#agt-13), [ARCH-07](../lexicons/engineering.md#arch-07)
- [`release-it`](../SOURCES.md#src-release-it): supports [OBS-03](../lexicons/engineering.md#obs-03)
- [`playboy-brand-value`](../SOURCES.md#src-playboy-brand-value): supports [BRND-12](../lexicons/design-aesthetics.md#brnd-12)
- [`four-hour-workweek`](../SOURCES.md#src-four-hour-workweek): supports [OPS-08](../lexicons/planning.md#ops-08)
- [`poor-charlies-almanack`](../SOURCES.md#src-poor-charlies-almanack): supports [OPS-13](../lexicons/planning.md#ops-13)
- [`sources-of-power`](../SOURCES.md#src-sources-of-power): supports [NDM-07](../lexicons/epistemics.md#ndm-07)
- [`bootstrap`](../SOURCES.md#src-bootstrap): supports [AGT-12](../lexicons/engineering.md#agt-12)
- [`antipatterns-laplante-neill`](../SOURCES.md#src-antipatterns-laplante-neill): supports [TEAM-17](../lexicons/planning.md#team-17), [TEAM-14](../lexicons/planning.md#team-14)
- [`tufte-seeing-with-fresh-eyes`](../SOURCES.md#src-tufte-seeing-with-fresh-eyes): supports [COG-09](../lexicons/interaction-ux.md#cog-09)

## Non-claims

This card does not reconstruct any source's structure, quote its text, or claim
to hold every knowledge-management practice. Open the rule rows for triggers and
tiers. [SOURCES.md](../SOURCES.md) is a bibliography registry, not a substitute
for the original works.
