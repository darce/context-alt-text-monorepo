# ACE Pruning Playbook

> Extracted from `instructions.md` to keep the cold-start document under 500 lines.
> This playbook governs the periodic pruning workflow, evidence-counter maintenance, and process-health evaluation.

---

## Document Maintenance (ACE Playbook Evolution)

`instructions.md` follows Autonomous Coding Engine principles for minimal, self-correcting agent instructions. Each rule is a strategy bullet tracked with evidence counters (`helpful` / `harmful`) to drive retention and pruning.

**Inclusion criteria** -- a rule belongs here only if:

1. It cannot be deduced from code, configs, linters, or static analysis
2. Violating it has caused a real failure in this project (not hypothetical)
3. It applies universally across all domains (domain-specific rules go in sub-documents)

### Reflection triggers

A reflection cycle runs when:

1. A branch review finding references a rule (daemon detects and logs automatically; run `make ace-reflect TASK=<task-ref>` from the orchestrator root to apply pending counter updates)
2. A branch review finding contradicts a rule (daemon detects and logs automatically; run `make ace-reflect TASK=<task-ref>` from the orchestrator root to apply pending counter updates)
3. A new failure mode is discovered that no existing rule covers (add new bullet)
4. A library version upgrade invalidates a rule (remove; ctx7 serves current docs)

### Curation rules

- Rules with `helpful=0 harmful>=2` are pruning candidates; delete on next review.
- Rules that restate a linter/config check get deleted immediately (tool is source of truth).
- New rules require a real failure reference (issue, commit, or branch review finding ID).
- Delta updates only; never rewrite a section from scratch (prevents context collapse).
- Never duplicate content between this file and linked sub-documents; use links.

### Periodic Pruning Workflow

Run a pruning pass:

1. after each epic phase completion
2. after any task with 5+ review findings that reference rules or skills
3. after 30 calendar days without a pruning pass

Workflow:

1. Run `get_metrics_summary` for the active process-hardening task to inspect process-health and handoff-memory signals.
2. Run `make ace-reflect TASK=<task-ref>` from the orchestrator root so pending `helpful` / `harmful` counters are applied before evaluating candidates.
3. Review rule pruning candidates: any rule with `helpful=0 harmful>=2` is an automatic candidate for deletion or demotion.
4. For each candidate, inspect recent handoff decisions and findings for the rule ID before changing the guidance. Delete confirmed dead rules; demote marginal rules to a watch note when evidence is mixed.
5. Review skills for overlap and coverage. Skills referenced in 0 decisions or findings over the evaluation window are candidates for retirement, consolidation, or scope reduction.
6. Record the pruning outcome in MCP with a structured decision summarizing what was deleted, what was kept, and what remains under watch.

Evidence thresholds:

- `helpful=0 harmful>=2`: automatic pruning candidate
- `helpful>=3 harmful=0`: confirmed keeper
- everything else: review on case merit against recent findings and decisions

Skill evaluation criteria:

- trigger frequency: does the skill appear in decisions/findings often enough to justify the maintenance cost?
- coverage: is the skill covering a unique workflow, or overlapping another skill?
- freshness: does the skill reference current tooling, commands, and runtime surfaces?
- convergence: do sessions using the skill reach completion more cleanly or quickly?

Use the curation rules above as the per-rule decision policy, and use this workflow as the cadence and evidence loop.

---

## Handoff Memory Health

Evaluate selective-memory health during the periodic pruning workflow.

Ask:

- Is hot-state load cost growing?
  - measure with `handoff_memory.hot_state_size_bytes` from `get_metrics_summary`
- Are sessions resolving from hot state plus targeted search, or replaying more than they need?
  - compare targeted `search_handoff` use against repeated broad `get_handoff_state` reloads in recent worker activity/logs when available
- Are stale artifacts being archived instead of accumulating forever?
  - inspect artifact counts and age distribution before deciding whether to archive or purge
- Is context rediscovery happening?
  - look for repeated `ctx7 library id:` entries or repeated handoff searches for the same dependency across decisions in the same task

Healthy pattern:

- hot state stays compact
- older context is recovered via search, not replay
- artifacts are archived or purged when they stop serving active work
- repeated upstream doc lookups are reused from prior decisions instead of rediscovered

Unhealthy pattern:

- hot-state size grows without bound
- agents repeatedly reload full state instead of using targeted retrieval
- stale artifacts accumulate with no archival discipline
- the same dependency is re-looked-up across nearby slices because earlier decisions did not cache the resolved `ctx7` pointer

If handoff-memory health regresses, treat that as a process issue: simplify guidance, archive stale state, or tighten retrieval discipline instead of normalizing around larger prompt loads.

---

## ctx7 Adoption Evaluation

Review `ctx7` usage during the periodic pruning workflow.

Ask:

- are resolved library ids being reused across sessions?
  - search recent decisions for `ctx7 library id:` and repeated package names
- are runtime-reported `ctx7` turns visible in metrics?
  - inspect `get_metrics_summary` for the `tool_attribution` section and confirm `used_ctx7` / `ctx7_query_count` appear only when the caller/runtime explicitly reported them
- are bulk upstream doc copies still appearing in repo docs or plans?
  - review instruction-file and task-plan changes for pasted vendor docs instead of targeted references
- is targeted retrieval preferred over broad browsing?
  - check whether recent decisions captured a narrow `ctx7 query:` and impact note instead of generic "looked it up" prose

Keep `ctx7` usage targeted:

- reuse prior library ids and questions when still relevant
- record the impact, not the upstream prose
- prefer repo-owned docs for local process and architecture decisions

Token-cost boundary:

- Use runtime-reported turn attribution for prompt-growth analysis when it exists: `tool_attribution.used_ctx7`, `tool_attribution.ctx7_query_count_total`, and the prompt-token totals attached to those attributed turns.
- Treat `ctx7` token-cost reduction as out of scope unless a tool explicitly records before/after savings; the current repo can measure adoption, reuse, and attributed prompt growth, but not counterfactual token savings.

---

## Data Pattern and Latency Review

Review data-pattern and latency health during the periodic pruning workflow.

Ask:

- are fabricated-field incidents recurring?
  - scan recent findings for `ANTIPATTERN` categories involving made-up fields, inferred payload properties, or contract drift hidden behind fallback values
- are dual-write exceptions being left undocumented?
  - compare recent boundary-touching changes against contract co-change evidence and recorded boundary decisions
- are queue or worker saturation signals rising?
  - inspect context pressure, worker daemon logs, and retry/backpressure notes for repeated saturation patterns
- are tail-latency regressions being distinguished from average-latency improvements?
  - compare `phase_timing` trends and recorded verification notes for mean-only claims without max/tail evidence

Healthy pattern:

- boundary changes record contract evidence and do not fabricate fallback fields
- dual-write or reconciliation exceptions are explicit and time-bounded
- saturation and queue health are reviewed as reliability signals, not only speed signals
- latency claims distinguish average improvements from degraded tails or saturation behavior

Unhealthy pattern:

- fabricated fields reappear because contract drift is absorbed into adapters or UI placeholders
- boundary exceptions are treated as implementation detail rather than reviewed process risk
- workers repeatedly show pressure or retry behavior with no follow-up note
- average latency is reported as "faster" while tail behavior regresses or remains unknown
