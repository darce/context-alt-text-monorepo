# Measurement integrity

Slug: `measurement-integrity`
ID: `CARD-11`
Mechanism claim: A measurement the measured system can shape (frame, sample, or
denominator) is not evidence of the world.

## Scope

Covers: sampling frames, divisors, and thresholds the system under test can
edit; load and eval apparatus that delete hard cases; independent watchers on
goal, sample, or pass bar; dataset filters that define a benchmark.

Excludes: choosing the *right outcome vs a convenient proxy* (see
[proxy-outcome-integrity](proxy-outcome-integrity.md)); designed unknown / forced precision (see
[designed-unknown](designed-unknown.md)); evidence clocks before a durable commit (see
[evidence-before-commitment](evidence-before-commitment.md)).

## Observable triggers

- The sampling frame, denominator, or pass threshold is editable by the system
  under test (filters, auto-baselines, detector-harvested sets).
- A wait-then-send or completeness-assuming loader pauses when the system
  stalls, so slow cases never enter the histogram.
- Benchmarks or evals report on a rebalanced fantasy mix, not the live regime.
- Goal, sample, or threshold lives inside the optimizer with no outside
  watcher.
- Absolute bars quietly track an eroding recent baseline.

## Causal mechanism

Measurement is an apparatus plus a claim. Under pressure, people and systems
optimize the apparatus: they exclude hard cells, widen the divisor, pause the
load generator, or move the bar. The report stays green because the
observations that would falsify the claim never land. Integrity fails at the
frame and the denominator first; the formula is usually fine.

## Required action

1. Fix the sampling frame and divisor *outside* the system under test; put an
   independent watcher on goal, sample, or threshold
   ([OBS-09](../lexicons/engineering.md#obs-09), Principle 15).
2. Prefer open-loop (or equivalent) arrival so stalls still generate
   observations ([PERF-03](../lexicons/engineering.md#perf-03)).
3. For unconstrained face-recognition evaluations harvested with a
   frontal-biased detector, preserve non-frontal pose coverage
   ([MLDATA-09](../lexicons/ml-systems.md#mldata-09)). Audit detector-harvested
   sets for demographic blind spots
   ([MLDATA-08](../lexicons/ml-systems.md#mldata-08)); use the owning rule for
   other filtered regimes.
4. Predefine denominators; do not accept rates the system mints for itself
   ([UXR-07](../lexicons/interaction-ux.md#uxr-07),
   [TEST-11](../lexicons/engineering.md#test-11),
   [OPS-01](../lexicons/planning.md#ops-01),
   [MLDATA-08](../lexicons/ml-systems.md#mldata-08)).
   In 1:N face identification, do not let detector false alarms dilute FPIR
   ([EVAL-19](../lexicons/ml-systems.md#eval-19)).
5. Evaluate on the real mix, not a rebalanced fantasy
   ([EVAL-03](../lexicons/ml-systems.md#eval-03)).
6. Hold absolute standards against eroding goals
   ([OBS-11](../lexicons/engineering.md#obs-11)).
7. For a new test, predict its exact initial failure message and observe that
   failure before proceeding ([TEST-06](../lexicons/engineering.md#test-06)).
   For a passing suite, deliberately insert the bug it claims to catch on a
   separate branch and confirm the suite detects it
   ([TEST-15](../lexicons/engineering.md#test-15)).

## Predicted failure

Latency looks fine while tails burn. Benchmarks pass because hard cases were
filtered. Denominators expand until the rate is meaningless. Absolute SLOs
drift into recent averages. The next incident postmortem discovers the meter
never could have gone red.

## Worked example

A ranking team optimizes offline NDCG on a eval set that is re-sampled each week from the same logs the model already serves. The trigger is a measurement the system can shape. Freeze a holdout cohort and a fixed sample recipe the trainer cannot rewrite. Without integrity, scores climb while live satisfaction stays flat.

## Exemptions and boundaries

- Exploratory telemetry that is not used to gate, promote, or claim compliance
  may stay rough; the card fires when the number *decides*.
- Regulatory or contractual metrics you did not choose still need an integrity
  audit; "required by audit" is not an exemption from a shaped sample.
- Wrong-proxy / outcome mismatch is owned by [proxy-outcome-integrity](proxy-outcome-integrity.md)
  (Principle 4), not this card.
- Partial knowledge and designed unknown states are owned by
  [designed-unknown](designed-unknown.md) (Principle 11).
- Evidence-before-commit clocks are owned by [evidence-before-commitment](evidence-before-commitment.md)
  (Principle 13). Named disconfirmers as posture are owned by
  [falsification-disconfirmers](falsification-disconfirmers.md) (Principle 2); TEST-06 may load both that card
  and this one when a never-failing suite is also a shaped instrument.

## Tensions

| Partition | Side A (keep fully) | Side B (keep fully) | Cut |
|---|---|---|---|
| surface | [PERF-03](../lexicons/engineering.md#perf-03) / [MLDATA-09](../lexicons/ml-systems.md#mldata-09) (apparatus deletes hard cases) | [OBS-11](../lexicons/engineering.md#obs-11) (absolute bar vs eroding goal) | Frame integrity vs bar integrity; both can fail independently |
| sequence | [TEST-06](../lexicons/engineering.md#test-06) (never trust a test never seen failing) | [EVAL-03](../lexicons/ml-systems.md#eval-03) (real mix over fantasy) | First install a falsifiable instrument; then insist the sample matches the claim |

## Disconfirmers

- Expanding the sample to include previously filtered hard cells does not move
  the score (filter was not load-bearing).
- An independent lab or held-out owner recomputes the metric and matches within
  stated error (watcher is real).
- The measured party cannot change frame, divisor, or threshold without an
  external change-control path (Principle 15 structure holds).
- A deliberate stall still lands observations in the histogram (open-loop
  holds).

## Verification

- For each gate metric: who owns the frame, who can edit it, and what decision
  it is allowed to make.
- Load or eval config: open-loop arrival (or equivalent) so stalls still
  generate observations ([PERF-03](../lexicons/engineering.md#perf-03)).
- Dataset card or filter list: every exclusion checked against the claim's
  covered conditions ([MLDATA-09](../lexicons/ml-systems.md#mldata-09),
  [MLDATA-08](../lexicons/ml-systems.md#mldata-08)).
- Denominator predefined and not emitted by the system under test
  ([UXR-07](../lexicons/interaction-ux.md#uxr-07),
  [TEST-11](../lexicons/engineering.md#test-11),
  [OPS-01](../lexicons/planning.md#ops-01),
  [MLDATA-08](../lexicons/ml-systems.md#mldata-08)).
  Detector false alarms that dilute FPIR in 1:N identification stay with
  [EVAL-19](../lexicons/ml-systems.md#eval-19).

## Rule IDs

- [PERF-03](../lexicons/engineering.md#perf-03): coordinated omission in load apparatus
- [OBS-09](../lexicons/engineering.md#obs-09): independent watcher the optimizer cannot tune
- [OBS-11](../lexicons/engineering.md#obs-11): absolute standards against eroding goals
- [MLDATA-08](../lexicons/ml-systems.md#mldata-08): detector-harvested sets inherit blind spots
- [MLDATA-09](../lexicons/ml-systems.md#mldata-09): filters that remove the regime under test
- [EVAL-03](../lexicons/ml-systems.md#eval-03): evaluate on the real mix, not a rebalanced fantasy
- [EVAL-19](../lexicons/ml-systems.md#eval-19): in 1:N face identification, do not let detector false alarms dilute FPIR
- [UXR-07](../lexicons/interaction-ux.md#uxr-07): predefined denominator
- [TEST-11](../lexicons/engineering.md#test-11): measure the stability outcome, not a gameable coverage target
- [OPS-01](../lexicons/planning.md#ops-01): name the behavior the metric pays for before trusting the number
- [TEST-06](../lexicons/engineering.md#test-06): a test never seen failing may assert nothing
- [TEST-15](../lexicons/engineering.md#test-15): prove the green can go red

## Principles

- 15. A measurement the measured party can shape is not a measurement

## Evidence / source slugs

- [`latency-reduce-delay-in-software-systems`](../SOURCES.md#src-latency-reduce-delay-in-software-systems): supports [PERF-03](../lexicons/engineering.md#perf-03)
- [`thinking-in-systems`](../SOURCES.md#src-thinking-in-systems): supports [OBS-09](../lexicons/engineering.md#obs-09), [OBS-11](../lexicons/engineering.md#obs-11)
- [`janus-benchmark-c`](../SOURCES.md#src-janus-benchmark-c): supports [MLDATA-09](../lexicons/ml-systems.md#mldata-09), [EVAL-19](../lexicons/ml-systems.md#eval-19)
- [`gender-shades`](../SOURCES.md#src-gender-shades): supports [MLDATA-08](../lexicons/ml-systems.md#mldata-08)
- [`designing-ml-systems`](../SOURCES.md#src-designing-ml-systems): supports [EVAL-03](../lexicons/ml-systems.md#eval-03)
- [`measuring-the-ux-albert-tullis`](../SOURCES.md#src-measuring-the-ux-albert-tullis): supports [UXR-07](../lexicons/interaction-ux.md#uxr-07)
- [`modern-software-engineering`](../SOURCES.md#src-modern-software-engineering): supports [TEST-06](../lexicons/engineering.md#test-06), [TEST-11](../lexicons/engineering.md#test-11)
- [`poor-charlies-almanack`](../SOURCES.md#src-poor-charlies-almanack): supports [OPS-01](../lexicons/planning.md#ops-01)
- [`pragmatic-programmer`](../SOURCES.md#src-pragmatic-programmer): supports [TEST-15](../lexicons/engineering.md#test-15)

## Non-claims

This card does not reconstruct any source's structure, quote its text, or claim
to hold every important idea about statistics or evaluation. Open the rule rows
for triggers and tiers. [SOURCES.md](../SOURCES.md) is a bibliography registry,
not a substitute for the original works.
