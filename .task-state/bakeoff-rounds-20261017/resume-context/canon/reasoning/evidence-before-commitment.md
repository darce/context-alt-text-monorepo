# Evidence before commitment

Slug: `evidence-before-commitment`
ID: `CARD-06`
Mechanism claim: Durable state (deploy, merge, buy, label, "done") requires
inspectable evidence *before* the commit, not after the harm.

## Scope

Covers: model and feature ship gates; architecture and fidelity commitments;
purchase and inventory bets; agent completion claims; characterization before
legacy edit; outside-view priors before narrative lock-in.

Excludes: naming disconfirmers and kill criteria as a posture (see
[falsification-disconfirmers](falsification-disconfirmers.md)); pure apparatus integrity when no commit is
pending (see [measurement-integrity](measurement-integrity.md)); wrong-proxy targets (see
[proxy-outcome-integrity](proxy-outcome-integrity.md)); step-size after the gate is open (see
[step-size-by-feedback](step-size-by-feedback.md)); dual-control mechanics alone (see
[dual-control-two-keys](dual-control-two-keys.md)); reversible choice and landlord exit (see
[reversible-commitments](reversible-commitments.md), [second-exit-hostile-landlord](second-exit-hostile-landlord.md)).

## Observable triggers

- A plan freezes architecture, inventory, model promotion, or high-fidelity
  build without a stated evidence package.
- Completion is claimed without file:line, named test, or decisive output.
- Suitability for deployment is assumed from aggregate accuracy or demo polish.
- "Users said they would buy" stands in for costly action.
- An estimate locks to an inside story with no outside-view base rate.
- Legacy code will be changed without a characterization pin of current
  behavior.

## Causal mechanism

Commitment converts a guess into durable state. After that moment, reverse cost
jumps: data is written, money is spent, identity is labeled, trust is spent.
Model suitability may be discovered only after deployment, through harm to
users. Surviving release, discovery, and forecasting disciplines put the
walkable package on a clock: inspectable evidence first, then the irreversible
bit. Naming what would falsify the thesis is a prior discipline; this card owns
whether the commit may fire once the package is due.

## Required action

1. Name the commitment and the evidence that must exist first (Principle 13).
2. For models and risk surfaces: disaggregated analysis, baselines, and
   threshold behavior before promote ([PROV-02](../lexicons/ml-systems.md#prov-02),
   [FAIR-02](../lexicons/ml-systems.md#fair-02), [EVAL-01](../lexicons/ml-systems.md#eval-01)).
3. Show outcome or comparison before costly UI or product commit
   ([INT-07](../lexicons/interaction-ux.md#int-07), [COG-04](../lexicons/interaction-ux.md#cog-04)).
4. Take the outside view before the story locks
   ([FORE-05](../lexicons/epistemics.md#fore-05)); accept training labels against
   embedded gold ([HITL-05](../lexicons/ml-systems.md#hitl-05)).
5. Pin current behavior before changing legacy contracts
   ([TEST-03](../lexicons/engineering.md#test-03)); name evidence for every done-claim
   ([AGT-04](../lexicons/engineering.md#agt-04)).
6. Prefer costly demand signals over stated intent
   ([GTM-01](../lexicons/business-marketing.md#gtm-01), [GTM-02](../lexicons/business-marketing.md#gtm-02)); scale fidelity to evidence
   ([PROD-05](../lexicons/business-marketing.md#prod-05)); respect that most tested ideas fail
   ([EXP-01](../lexicons/epistemics.md#exp-01)).

## Predicted failure

Models ship and fail only on slices never tabulated. Refactors redefine behavior
silently. Inventory and headcount follow survey optimism. Agents mark done while
nothing green proves it. Confidence tracks a coherent story, not evidence amount.

## Worked example

A merge is marked ready because CI is green on the author's laptop cache, with no recorded run on the shared gate. The trigger is durable "done" without checkable evidence. Require the PR checklist to link the shared CI run (or re-run) before merge rights unlock. Without that, local-only green becomes production red on a clean runner.

## Exemptions and boundaries

- Reversible experiments may commit *small* exposure to *gain* evidence; that
  is Principle 19 step size ([step-size-by-feedback](step-size-by-feedback.md)), not a waiver of evidence
  for the larger freeze.
- Emergency break-glass commits still need post-hoc evidence packages and dual
  control where high impact applies ([dual-control-two-keys](dual-control-two-keys.md)).
- Expert recognition under high validity and fast feedback
  ([NDM-01](../lexicons/epistemics.md#ndm-01)) can support operational micro-decisions; it does
  not replace scored evidence for durable public claims.
- Writing disconfirmers, kill criteria, and resolution criteria as a *posture*
  is owned by [falsification-disconfirmers](falsification-disconfirmers.md) (Principle 2); this card owns the
  commit clock once those criteria and packages are in play.

## Tensions

| Partition | Side A (keep fully) | Side B (keep fully) | Cut |
|---|---|---|---|
| sequence | [PROD-05](../lexicons/business-marketing.md#prod-05) fidelity scales with evidence | [GTM-08](../lexicons/business-marketing.md#gtm-08) loud first exposure when discovery needs one | low-fidelity exposure can lead; high-fidelity freeze still waits on evidence |
| object | [FORE-05](../lexicons/epistemics.md#fore-05) outside view for empirical estimates | [STRAT-07](../lexicons/business-marketing.md#strat-07) mission values not Brier-scored | evidence gates forecasts and bets; values are not "proven wrong" by a quarter |
| surface | [TEST-03](../lexicons/engineering.md#test-03) characterization before edit | [HITL-05](../lexicons/ml-systems.md#hitl-05) gold-checked labels before accept | both put observation before durable write; one pins code contract, one pins training truth |

## Disconfirmers

- Evidence package existed and a held-out check still would have blocked the
  commit (package incomplete).
- Skipping the gate under controlled conditions did not increase reverse cost
  or harm (mechanism not load-bearing for this class).
- Outside-view priors updated when resolution arrived without narrative rescue
  ([FORE-03](../lexicons/epistemics.md#fore-03)).

## Verification

- Commit record lists evidence artifacts with pointers (report, test name,
  receipt, base-rate table).
- Model or feature promote checklist includes disaggregated or slice metrics
  where harm is uneven.
- "Done" entries cite evidence; grepping the claim without a pointer fails review.

## Rule IDs

- [PROV-02](../lexicons/ml-systems.md#prov-02): model card / disaggregated reporting before deploy claims
- [FAIR-02](../lexicons/ml-systems.md#fair-02) / [FAIR-03](../lexicons/ml-systems.md#fair-03): intersectional and threshold outcomes
- [EVAL-01](../lexicons/ml-systems.md#eval-01): baselines that make metrics meaningful
- [INT-07](../lexicons/interaction-ux.md#int-07) / [COG-04](../lexicons/interaction-ux.md#cog-04): outcome before costly choice
- [HITL-05](../lexicons/ml-systems.md#hitl-05): accept labels against embedded gold
- [FORE-05](../lexicons/epistemics.md#fore-05): outside view before narrative lock-in
- [TEST-03](../lexicons/engineering.md#test-03): characterization before legacy edit
- [AGT-04](../lexicons/engineering.md#agt-04): done names evidence
- [GTM-01](../lexicons/business-marketing.md#gtm-01) / [GTM-02](../lexicons/business-marketing.md#gtm-02): costly demand before capability
- [PROD-05](../lexicons/business-marketing.md#prod-05): Truth Curve / fidelity scales with evidence
- [EXP-01](../lexicons/epistemics.md#exp-01): most ideas fail controlled tests
- [BIAS-01](../lexicons/epistemics.md#bias-01): confidence is not evidence amount
- [AIPX-01](../lexicons/business-marketing.md#aipx-01): deterministic baseline before ML commitment
- [NAV-39](../lexicons/interaction-ux.md#nav-39): compare the hierarchy with alternatives on retrieval tasks before accepting its depth

## Principles

- 13. Evidence precedes commitment

Also load Principle 2 when the gap is missing kill criteria rather than a late
package (see [falsification-disconfirmers](falsification-disconfirmers.md)). Also load Principle 9 when the
commitment is a claim that must walk back to what produced it (open the
principle row, starting at GRPH-14). Walkable lineage is not this card's owned
mechanism; do not re-own correction or source-of-truth repair here (see
[correction-at-source](correction-at-source.md)).

## Evidence / source slugs

- [`model-cards`](../SOURCES.md#src-model-cards): supports [PROV-02](../lexicons/ml-systems.md#prov-02)
- [`gender-shades`](../SOURCES.md#src-gender-shades): supports [FAIR-02](../lexicons/ml-systems.md#fair-02)
- [`nist-frvt-demographics`](../SOURCES.md#src-nist-frvt-demographics): supports [FAIR-03](../lexicons/ml-systems.md#fair-03)
- [`designing-ml-systems`](../SOURCES.md#src-designing-ml-systems): supports [EVAL-01](../lexicons/ml-systems.md#eval-01)
- [`designing-interfaces`](../SOURCES.md#src-designing-interfaces): supports [INT-07](../lexicons/interaction-ux.md#int-07)
- [`designing-with-the-mind-in-mind`](../SOURCES.md#src-designing-with-the-mind-in-mind): supports [COG-04](../lexicons/interaction-ux.md#cog-04)
- [`human-in-the-loop-ml`](../SOURCES.md#src-human-in-the-loop-ml): supports [HITL-05](../lexicons/ml-systems.md#hitl-05)
- [`superforecasting`](../SOURCES.md#src-superforecasting): supports [FORE-05](../lexicons/epistemics.md#fore-05)
- [`working-effectively-with-legacy-code`](../SOURCES.md#src-working-effectively-with-legacy-code): supports [TEST-03](../lexicons/engineering.md#test-03)
- [`bootstrap`](../SOURCES.md#src-bootstrap): supports [AGT-04](../lexicons/engineering.md#agt-04)
- [`four-hour-workweek`](../SOURCES.md#src-four-hour-workweek): supports [GTM-01](../lexicons/business-marketing.md#gtm-01), [GTM-02](../lexicons/business-marketing.md#gtm-02)
- [`lean-ux`](../SOURCES.md#src-lean-ux): supports [PROD-05](../lexicons/business-marketing.md#prod-05)
- [`trustworthy-controlled-experiments`](../SOURCES.md#src-trustworthy-controlled-experiments): supports [EXP-01](../lexicons/epistemics.md#exp-01)
- [`kahneman-thinking-fast-slow`](../SOURCES.md#src-kahneman-thinking-fast-slow): supports [BIAS-01](../lexicons/epistemics.md#bias-01)
- [`building-ml-powered-applications`](../SOURCES.md#src-building-ml-powered-applications): supports [AIPX-01](../lexicons/business-marketing.md#aipx-01)
- [`tufte-seeing-with-fresh-eyes`](../SOURCES.md#src-tufte-seeing-with-fresh-eyes): supports [NAV-39](../lexicons/interaction-ux.md#nav-39)

## Non-claims

This card does not reconstruct any source's structure, quote its text, or claim
to hold every evaluation or product-discovery method. Open the rule rows for
triggers and tiers. [SOURCES.md](../SOURCES.md) is a bibliography registry, not
a substitute for the original works.
