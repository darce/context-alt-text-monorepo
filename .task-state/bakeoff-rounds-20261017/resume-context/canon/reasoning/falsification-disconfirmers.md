# Falsification and disconfirmers

Slug: `falsification-disconfirmers`
ID: `CARD-08`
Mechanism claim: Name the observation that would make you wrong, then look for
it before confidence hardens into a plan, diagnosis, or forecast.

## Scope

Covers: disconfirmers and non-X before a forward plan; kill criteria on loved
designs; resolution criteria and movers written in advance; pre-mortems and
alternate diagnoses of early-warning sets; threat models that list how policy
dies; reproduce-before-fix and absence-of-cause tests; hostile literal reading
of claims.

Excludes: the *timing* of inspectable evidence packages before a durable
commit (see [evidence-before-commitment](evidence-before-commitment.md)); sampling-frame integrity of meters
(see [measurement-integrity](measurement-integrity.md)); proxy-vs-outcome target choice (see
[proxy-outcome-integrity](proxy-outcome-integrity.md)); step size after a gate opens (see
[step-size-by-feedback](step-size-by-feedback.md)).

## Observable triggers

- A plan shows only the path to win; non-X and kill criteria are absent.
- A forecast or estimate has no resolution criterion or listed movers.
- A fix or redesign ships without a reproduce step or a stated way the cause
  could be shown false.
- Early-warning cues are each explained away in isolation; no alternate
  diagnosis of the set is forced.
- Threat modeling starts after controls are already purchased.
- Claim copy has not been read as a regulator, platform reviewer, or future
  plaintiff would read it.

## Causal mechanism

Confidence prefers supporting stories. Without a pre-named observation that
would count against the thesis, every green signal looks like confirmation and
every red cue gets a local benign story. Disciplines that survive put the
disconfirmer first: invert the plan, write resolution criteria, reproduce the
failure, force an alternate diagnosis, list how the policy dies. The clock that
blocks a durable commit until evidence exists is a sibling decision, not this
one.

## Required action

1. Define non-X and disconfirmers before the forward plan; name the result that
   would kill the darling ([STRAT-02](../lexicons/business-marketing.md#strat-02),
   [PROD-04](../lexicons/business-marketing.md#prod-04), Principle 2).
2. Write resolution criteria and movers in advance; pre-mortem the plan as
   already failed; force an alternate diagnosis of early-warning sets
   ([FORE-02](../lexicons/epistemics.md#fore-02),
   [FORE-09](../lexicons/epistemics.md#fore-09),
   [NDM-02](../lexicons/epistemics.md#ndm-02),
   [NDM-05](../lexicons/epistemics.md#ndm-05)).
3. Reproduce the failure before proposing a fix; establish a cause when its
   absence kills the failure. For a new test, predict the exact initial failure
   message; if it passes before code exists or fails differently, fix the test
   ([DBG-01](../lexicons/engineering.md#dbg-01),
   [DBG-11](../lexicons/engineering.md#dbg-11),
   [TEST-06](../lexicons/engineering.md#test-06)).
4. List how the policy dies before buying controls
   ([SECD-07](../lexicons/security.md#secd-07)).
5. Read claims as the hostile literal reader would
   ([CLM-05](../lexicons/business-marketing.md#clm-05)).

## Predicted failure

Plans commit to a thesis that never named how it dies. Forecasts cannot be
scored. Fixes chase the last anomaly. Controls buy theater. Green suites certify
nothing because they never exercised failure. Claims fail the first hostile
reading in production.

## Worked example

The design doc for the cart service promises a Redis read-through layer will cut checkout p99 by half, and the only scheduled work is a confirmatory load test. Write the kill line before ship: if two weeks of shadow traffic leave p99 within five percent of baseline, revert and close the bet. Without that line, every noisy win is celebrated and the hypothesis never dies.

## Exemptions and boundaries

- Reversible experiments may run small exposure to *hunt* disconfirmers; sizing
  that exposure is [step-size-by-feedback](step-size-by-feedback.md) (Principle 19).
- Whether a durable commit may proceed once disconfirmers and packages exist is
  owned by [evidence-before-commitment](evidence-before-commitment.md) (Principle 13); plain pointer only.
- Whether the meter itself can be shaped by the measured party is owned by
  [measurement-integrity](measurement-integrity.md) (Principle 15); TEST-06 may load both cards when a
  new test’s initial failure is also a check of a shaped instrument.
- Contract-before-build authorship of gatekeeper specs is owned by
  [contract-before-components](contract-before-components.md); CLM-05 may load both when the hostile reader is
  also the gatekeeper contract.

## Tensions

| Partition | Side A (keep fully) | Side B (keep fully) | Cut |
|---|---|---|---|
| sequence | [STRAT-02](../lexicons/business-marketing.md#strat-02) disconfirmers before the plan | [PROD-04](../lexicons/business-marketing.md#prod-04) kill the loved design when the result arrives | write kill criteria first; execute them when the result lands |
| surface | [DBG-01](../lexicons/engineering.md#dbg-01) reproduce before fix | [FORE-02](../lexicons/epistemics.md#fore-02) resolution criteria before forecast | both name what would count against the claim before action hardens |

## Disconfirmers

- Named kill criteria fired and the thesis updated without narrative rescue.
- A held-out alternate diagnosis of early cues would have blocked the chosen
  path.
- Skipping the disconfirmer list under controlled conditions did not increase
  reverse cost (mechanism not load-bearing for this class).

## Verification

- Pre-mortem or disconfirmer list dated before the freeze.
- Forecast records list resolution criteria and movers.
- Defect write-ups show reproduce steps and a cause-absence check.
- Claim review notes a hostile-reader pass.

## Rule IDs

- [STRAT-02](../lexicons/business-marketing.md#strat-02): disconfirmers before the forward plan
- [PROD-04](../lexicons/business-marketing.md#prod-04): kill or pivot when the result falsifies the darling
- [FORE-02](../lexicons/epistemics.md#fore-02): resolution criteria written in advance
- [FORE-09](../lexicons/epistemics.md#fore-09): movers named before the estimate locks
- [NDM-02](../lexicons/epistemics.md#ndm-02): pre-mortem assumes the plan already failed
- [NDM-05](../lexicons/epistemics.md#ndm-05): alternate diagnosis of the early-warning set
- [DBG-01](../lexicons/engineering.md#dbg-01): reproduce the failure before the fix
- [DBG-11](../lexicons/engineering.md#dbg-11): cause established when its absence kills the failure
- [TEST-06](../lexicons/engineering.md#test-06): predict and observe a new test’s exact initial failure
- [SECD-07](../lexicons/security.md#secd-07): threat-model how the policy dies before buying controls
- [CLM-05](../lexicons/business-marketing.md#clm-05): hostile reader can check the claim

## Principles

- 2. Specify what would prove you wrong

Also load Principle 13 when the next step is a durable commit that needs an
inspectable evidence package, not only a named disconfirmer (see
[evidence-before-commitment](evidence-before-commitment.md)).

## Evidence / source slugs

- [`poor-charlies-almanack`](../SOURCES.md#src-poor-charlies-almanack): supports [STRAT-02](../lexicons/business-marketing.md#strat-02)
- [`lean-ux`](../SOURCES.md#src-lean-ux): supports [PROD-04](../lexicons/business-marketing.md#prod-04)
- [`superforecasting`](../SOURCES.md#src-superforecasting): supports [FORE-02](../lexicons/epistemics.md#fore-02), [FORE-09](../lexicons/epistemics.md#fore-09)
- [`sources-of-power`](../SOURCES.md#src-sources-of-power): supports [NDM-02](../lexicons/epistemics.md#ndm-02), [NDM-05](../lexicons/epistemics.md#ndm-05)
- [`debugging-9-rules`](../SOURCES.md#src-debugging-9-rules): supports [DBG-01](../lexicons/engineering.md#dbg-01)
- [`why-programs-fail`](../SOURCES.md#src-why-programs-fail): supports [DBG-11](../lexicons/engineering.md#dbg-11)
- [`modern-software-engineering`](../SOURCES.md#src-modern-software-engineering): supports [TEST-06](../lexicons/engineering.md#test-06)
- [`anderson-security-engineering`](../SOURCES.md#src-anderson-security-engineering): supports [SECD-07](../lexicons/security.md#secd-07)
- [`bootstrap`](../SOURCES.md#src-bootstrap): supports [CLM-05](../lexicons/business-marketing.md#clm-05)

## Non-claims

This card does not reconstruct any source's structure, quote its text, or claim
to hold every evaluation or debugging method. Open the rule rows for triggers
and tiers. [SOURCES.md](../SOURCES.md) is a bibliography registry, not a
substitute for the original works.
