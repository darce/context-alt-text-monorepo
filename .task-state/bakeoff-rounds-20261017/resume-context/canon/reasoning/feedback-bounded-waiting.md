# Feedback and bounded waiting

Slug: `feedback-bounded-waiting`
ID: `CARD-09`
Mechanism claim: Bound every blocking wait, queue, pool, and automation loop
so a stall fails closed instead of hanging the system.

## Scope

Covers: client and RPC timeouts; pool, queue, and result-set capacity;
agent and automation loop limits; delayed queue-and-retry with a fast answer
when immediate remote retries encounter a persistent fault.

Excludes: pure measurement-frame integrity (see [measurement-integrity](measurement-integrity.md)); pure
privilege sizing (see [least-privilege-blast-radius](least-privilege-blast-radius.md)); reversible choice and
landlord exit (see [reversible-commitments](reversible-commitments.md), [second-exit-hostile-landlord](second-exit-hostile-landlord.md));
correction reaching source of truth (see [correction-at-source](correction-at-source.md)); durable
decision memory (see [durable-decision-memory](durable-decision-memory.md)); fail-loudly channel design
(see [fail-loudly-succeed-quietly](fail-loudly-succeed-quietly.md)); plan and rollout step size (see
[step-size-by-feedback](step-size-by-feedback.md)). Expert recognition validity is a boundary tension
only, not this card's owned decision.

## Observable triggers

- Connect, read, pool checkout, RPC, or `wait()` with no timeout.
- Queues, pending-work buffers, or result sets without capacity bounds.
- A model- or agent-driven loop runs "until done" with no max steps, tokens,
  spend, or repeated-state stop.
- A remote call retries immediately while the dependency’s fault persists.

## Causal mechanism

Control requires a deadline on every wait. Unbounded sockets, pools, and loops
convert a local stall into system-wide hang or budget death. The bound is not
cosmetic: without it, failure cannot surface as a controlled timeout or terminal
result, and the rest of the system cannot shed load or answer.

## Required action

1. Timeout every blocking call; bound pools, queues, and result sets; fail
   fast when slow failure would cascade
   ([RES-02](../lexicons/engineering.md#res-02),
   [RES-03](../lexicons/engineering.md#res-03),
   [RES-05](../lexicons/engineering.md#res-05),
   [RES-14](../lexicons/engineering.md#res-14)).
2. Declare agent loops as state machines with explicit limits and a terminal
   failure result ([FM-08](../lexicons/ml-systems.md#fm-08)).
3. When a remote call retries immediately against a persistent fault, queue
   the retry with a delay and return a fast answer to the caller
   ([RES-06](../lexicons/engineering.md#res-06)).

## Predicted failure

Thread pools exhaust on eternal waits. Agents loop until budget death or false
completion. Callers hang while a stuck dependency never returns.

## Worked example

Nightly import workers call BLPOP on a Redis list and never pass a timeout. When the upstream CSV job stalls, every consumer blocks on the empty list and the pool reports healthy idle. Set a deadline, dead-letter the wait, and page on the timeout metric. One stalled producer then cannot pin the whole consumer fleet overnight.

## Exemptions and boundaries

- In-process memory calls may omit network timeouts; they do not omit
  application-level deadlines for user-visible operations.
- One-shot offline batch jobs still need wall-clock and cost bounds if they
  can starve shared systems.
- Bounded waiting is necessary but not sufficient for measurement integrity:
  a timed-out load test can still coordinate omission if arrivals pause.
- Corrections that must reach training, graph, or system of record are owned
  by [correction-at-source](correction-at-source.md) (Principle 12); plain pointer only.
- Handoff and durable intent memory are owned by [durable-decision-memory](durable-decision-memory.md)
  (Principle 7); plain pointer only.
- Success/failure channel design (silence is not success; ERROR means action;
  stdout vs stderr) is owned by [fail-loudly-succeed-quietly](fail-loudly-succeed-quietly.md) (Principle 16);
  plain pointer only.
- Plan and rollout step size, canaries, and feedback-lag windowing are owned
  by [step-size-by-feedback](step-size-by-feedback.md) (Principle 19); plain pointer only.
- Human recognition under time pressure is valid only where cues are valid and
  feedback was fast for long practice ([NDM-01](../lexicons/epistemics.md#ndm-01));
  outside that gate, scored judgment applies. This card does not own that
  validity decision; treat it as a boundary when expertise claims substitute
  for a bounded wait.

## Tensions

| Partition | Side A (keep fully) | Side B (keep fully) | Cut |
|---|---|---|---|
| object | [RES-02](../lexicons/engineering.md#res-02) timeout every wait | [RES-06](../lexicons/engineering.md#res-06) queue-and-retry, answer fast | timeout the wait; when immediate retries encounter a persistent fault, queue the retry with delay and answer fast |
| surface | [NDM-01](../lexicons/epistemics.md#ndm-01) recognition under validity+feedback (boundary) | [FORE-01](../lexicons/epistemics.md#fore-01) / [FORE-05](../lexicons/epistemics.md#fore-05) scored, outside-view probabilities | not owned here: use recognition only when the NDM gate holds; otherwise score |

## Disconfirmers

- Fault injection: a stuck dependency surfaces as timeout and shed load, not
  global hang.
- Loop policy hits max steps and emits a terminal failure under rehearsal.
- Queue-and-retry path returns a controlled answer while the dependency is
  still recovering.

## Verification

- Config grep (or equivalent) for client timeouts on every egress.
- Loop policy lists max steps, tokens, spend, repeated-state count, terminal
  failure.
- Pending-work and result-set bounds are named in config or schema.

## Rule IDs

- [RES-02](../lexicons/engineering.md#res-02): timeout every blocking call
- [RES-03](../lexicons/engineering.md#res-03): slow failure worse than fast failure
- [RES-05](../lexicons/engineering.md#res-05): unbounded result sets
- [RES-14](../lexicons/engineering.md#res-14): handshaking and pending-work bounds
- [RES-06](../lexicons/engineering.md#res-06): queue-and-retry, answer fast
- [FM-08](../lexicons/ml-systems.md#fm-08): agent loops must be bounded

## Principles

No exclusive principle claim. Bound waits so feedback can arrive; channel
design is Principle 16 ([fail-loudly-succeed-quietly](fail-loudly-succeed-quietly.md)) and step size is
Principle 19 ([step-size-by-feedback](step-size-by-feedback.md)).

## Evidence / source slugs

- [`release-it`](../SOURCES.md#src-release-it): supports [RES-02](../lexicons/engineering.md#res-02), [RES-03](../lexicons/engineering.md#res-03), [RES-05](../lexicons/engineering.md#res-05), [RES-14](../lexicons/engineering.md#res-14), [RES-06](../lexicons/engineering.md#res-06)
- [`ai-engineering`](../SOURCES.md#src-ai-engineering): supports [FM-08](../lexicons/ml-systems.md#fm-08)

## Non-claims

This card does not reconstruct any source's structure, quote its text, or claim
to cover every control-theory or SRE pattern. It is a decision aid over existing
rule IDs. [SOURCES.md](../SOURCES.md) is a bibliography registry, not a substitute
for the original works.
