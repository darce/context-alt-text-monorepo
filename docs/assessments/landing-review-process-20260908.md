# Consolidated branch landing review — 2026-09-08

The operator's requested process is consistent with the canon's guidance on
feature ownership, bounded feedback, and recoverable decisions. The corpus
does not establish that a particular model, effort setting, or service tier
is optimal; those are explicit operator choices for this wave.

## Review contract

1. Consolidate fragmented branches into one worktree per feature. Preserve
   original commit identities, slice scopes, and unresolved findings.
2. Review each slice with **gpt-5.6-luna, MAX effort, fast service**. Fix high
   and medium findings. Record low and formatting findings for the next wave.
3. After integration and relevant tests, harmonize the feature with
   **gpt-6-astra, MEDIUM effort, regular service**. Only high findings block
   this review. Record medium and low findings for the next wave.
4. Run the final close check against the actual feature HEAD, merge, then
   archive and remove absorbed worktrees/branches with ancestry evidence.

A test failure remains unresolved evidence until diagnosed. A finding deferred
because a branch was parked must be reassessed when that branch resumes.
Formatting and low findings must not expand this wave's implementation scope.

## Canon validation

| Process choice | Supporting source | Application and limit |
|---|---|---|
| Feature boundaries before review | [Engineering REF-13/14, TEAM-05/07](../../../heuristics-canon-research/lexicons/engineering.md#ref-13) | Group by shared behavior and release ownership; retain small review slices within each feature. |
| Separate consolidation from fixes | [Engineering REF-05](../../../heuristics-canon-research/lexicons/engineering.md#ref-05), [Contract before components](../../../heuristics-canon-research/reasoning/contract-before-components.md) | Preserve source ancestry and identify semantic conflict decisions; a successful Git merge is not behavioral validation. |
| Preserve decision history | [DDIA distillation](../../../heuristics-canon-research/distilled/engineering/designing-data-intensive-applications.md), [Durable decision memory](../../../heuristics-canon-research/reasoning/durable-decision-memory.md) | MCP findings and continuations retain provenance, superseded decisions, and recovery steps. Do not silently replace an existing contract (AGT-13). |
| Bound concurrency and feedback | [Latency, pass 2, chapter 2](../../../heuristics-canon-research/distilled/engineering/latency-reduce-delay-in-software-systems-pass-2.md#ch-2), [Step size by feedback](../../../heuristics-canon-research/reasoning/step-size-by-feedback.md) | Use small falsifying tests while fixes develop and resource-capped remote suite runs. Re-measure host conditions after a restart; old RAM observations are not current admission evidence. |
| Test before committing readiness | [Evidence before commitment](../../../heuristics-canon-research/reasoning/evidence-before-commitment.md), [Engineering RLSE-03](../../../heuristics-canon-research/lexicons/engineering.md#rlse-03) | State expected behavior and record reproducible failures, fixes, and exact tested SHAs. The operator's severity thresholds govern classification; generic canon wording does not add new blockers. |
| Durable follow-up rather than hidden skips | [Engineering AGT-06](../../../heuristics-canon-research/lexicons/engineering.md#agt-06), [Release It!, operational feedback](../../../heuristics-canon-research/distilled/engineering/release-it.md#ch-17) | Record every deferral with severity, trigger, location, and next-wave reason. Test skips retain their actual prerequisite/coverage meaning. |

The [principles](../../../heuristics-canon-research/PRINCIPLES.md) and reasoning
cards reinforce these mechanisms. They are heuristics for identifying failure
modes, not empirical proof that two reviews guarantee correctness.

## Evidence and recovery

MCP decision `9963` records the policy validation. Each feature owns its slice
reviews, test receipts, harmonizing review, and deferred findings. Recovery
artifacts under `.task-state/landing-20260908/` preserve the initial references,
consolidation ancestry, review scopes, and full remote gate logs. Continuations
identify completed work and remaining obligations so a crash does not turn
historical green results into claims about a newer HEAD.
