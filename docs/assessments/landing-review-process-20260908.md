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


## Recovered reference disposition

The initial inventory contained 22 local feature/review references. Their exact
SHAs and ancestry checks are retained in `consolidation.json` under the recovery
artifact directory. EVID absorbed eight references, LAND three, EVAL eight,
and DEVGUARD three. GPUOPS and OCIR then received their surviving requirements;
DEMO reconciled the historical user-interface slices. Ancestry-only merges
preserve provenance while explicit fixes carry the accepted behavior.

The remote inventory also contained rewritten and sparse historical references.
MCP decision `9998` and `remote-ref-audit.json` retain the commit-level audit.
These histories must not be blindly merged merely to make every remote tip an
ancestor: that would reintroduce deliberately removed artifacts or obsolete
runtime code.

| Historical references | Disposition |
|---|---|
| `origin/feature/5.0.1-fe-ux` | 774 of 775 commits have exact patch equivalents; the remaining merge and tip have verified equivalent trees. No new implementation remains. |
| `origin/feature/slr-003-suppress-cleanup` | Substantive patch is equivalent to integrated `77b4`; the other commit is merge bookkeeping. |
| `origin/refactor/14-mcp-rewrite` | All four commits have integrated patch equivalents. |
| Three `n16` lane references | Current EVAL preserves method-form/Kish estimators and table/tilde-fence guards; fresh Luna review verified these requirements. |
| Seven `r4int/dux` references | Ancestry-consolidated in DEMO `37f2ed14b`; current HAI, sync and vocabulary gaps were implemented and reviewed. Current contracts refute the conditional authentication/GPU claims. |
| Two `r7int` references | Canonical Golden37 restoration is retained in `cd6c33771`; the competing Golden20 reseal is superseded, with the old 20 examples preserved separately as held-out input. Current `3258b1a13` restores B711 identity, split, selection, and strict held-out guards; Luna evidence is in MCP `2013/2014` and decision `10033`. Neither historical tip needs to be merged wholesale. |
| `vmlic3/lic3` | Sparse unrelated history: 103 of 106 patches equivalent; remaining baseline/import shims and ignore setup do not warrant merging the sparse repository. |
| `vmbundle/vlm-6` | Rewritten VLM history includes deliberately purged private artifact paths. Prior decision `5581` governs exclusion; retain surviving code through current EVAL, never reattach that history. |

## Boundaries that remain explicit

The historical Grok transport findings remain upstream records under authority
`4398`; fresh Codex review inputs and exact destination-SHA receipts replace
them as landing evidence. The audit in decision `10023` distinguishes observed
upstream corrections from independently verified end-to-end behavior. It does
not claim every upstream defect is fixed.

`VLM6-GATE-PRIV-05` concerns a tracked manifest whose blob is identical in main
and the EVAL feature. It remains an unresolved preexisting main/release privacy
risk; the earlier feature-history rewrite did not remediate main. No separate
maintenance task was found, so no such task or remediation is implied. This
landing neither changes that manifest nor claims a privacy-sensitive release
is cleared.

Research readiness remains separate from code landing. Current Golden37 lacks
the required Golden100 size, strata and independent selection evidence; report
gates now emit `not_ready` and block adoption. Offline score proxies remain
`unvalidated_proxy`; production threshold validation and independent empirical
evidence are still required before a bakeoff or adoption claim. No additional
images, annotations or measurements were fabricated to satisfy these gates.
