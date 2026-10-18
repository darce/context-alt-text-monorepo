# Agentic Coding Heuristics — distilled from frontier-model experience

> **Source**: Claude Fable 5, operating experience across agentic coding sessions (this repo's workbay pipeline, multi-harness offload lanes, and the 2026-07-09 process audit's 6,338-finding / 554-error evidence base) · distilled 2026-07-09 (spec v2)
> **Contributes**: The failure modes specific to LLM coding agents — especially junior ones at cold start — that no book covers, because books assume a human who retains context between sessions, feels friction, and knows what they don't know. A junior agent's characteristic failures are not knowledge gaps (the other files in this directory fix those); they are *process* failures: acting on plausible memory instead of the actual repo, claiming completion without observation, burning context on re-derivation, and treating guardrails as obstacles instead of information. Every rule here was observed as a real failure pattern in this workspace's handoff data or in direct operation.

## Chapter map

- ch-1 — Cold start: orient before acting
- ch-2 — Ground truth: the repo beats your memory
- ch-3 — Verification: done means observed, not written
- ch-4 — Scope: the task you were given, all of it, only it
- ch-5 — Context economy: tokens are working memory
- ch-6 — Guards and errors: the system is talking to you
- ch-7 — Escalation: knowing when you're the wrong tool

## ch-1 — Cold start: orient before acting {#ch-1}

A junior agent's first five tool calls determine the session's quality. The observed failure: diving into the named file and editing within two turns, then discovering (or never discovering) the task had prior state — an existing plan, a half-done slice, open findings, a sibling worktree doing the same thing.

- **Orientation is a fixed procedure, not a vibe.** Before the first write: (1) what task am I in (`make context` / handoff state), (2) what does the plan/checklist say is already done, (3) what do the last few decisions/findings on this task say, (4) is the working tree clean and on the expected branch. Four reads, under a minute, prevents the two most expensive failures: redoing finished work and colliding with parallel work.
- **Read the plan's checklist as a contract, not a suggestion.** If the plan names files and functions, those are your anchors; if you find they don't exist, that is a *finding to record*, not a license to improvise a different design.
- **State your understanding before starting.** One sentence — "slice 2: widen both gates and add the rebuild migration; slice 1's reader already landed" — written into the decision log. If the understanding is wrong, it's now visible and correctable; silent misunderstanding compounds for the whole session.
- **Inherit vocabulary.** Use the names the repo uses (its terms for lanes, slices, surfaces), not synonyms. A junior agent that renames concepts in its own prose desynchronizes from every grep and every future reader (↔ programmers-brain on consistent lexicons).

## ch-2 — Ground truth: the repo beats your memory {#ch-2}

The signature junior-agent defect is **plausible invention**: API signatures, config keys, file paths, and flag names produced from training-data memory instead of from the repo. They are right often enough to build trust and wrong often enough to burn sessions.

- **Never cite an anchor you haven't resolved this session.** Before writing `foo.py:142` or `resolve_gate()` into code, a plan, or a finding: grep/read it. The cost is one tool call; the cost of an invented anchor is a downstream agent implementing against fiction. (The repo's plan-review process rejects ungrounded anchors for exactly this reason.)
- **Version-check before API use.** The library in this venv is not the library in your memory. One `grep` in the lockfile or an import-and-inspect beats recalling an API that changed two majors ago.
- **When memory and repo disagree, the repo wins — silently updating your model, loudly updating the artifact.** If the disagreement suggests the repo has a bug, record it as a question/finding; do not "fix" the repo toward your memory.
- **Copy the neighborhood's idiom.** Before writing new code in a file, read the surrounding 50 lines. Error handling style, naming, import placement, test structure — locality of idiom is what makes a codebase greppable, and a junior agent's "better" pattern in one function is a net cost (↔ refactoring-fowler-beck on consistency over local optimality).
- **The error message is data; read all of it.** Junior agents pattern-match the first line of a traceback to a known failure and act. The actual cause is usually in the middle frames or the caused-by chain. Quote the decisive line in your notes before acting on it.

## ch-3 — Verification: done means observed, not written {#ch-3}

The audit's single strongest human-side friction signal — 170 prompts containing "still" ("still not working", "build still fails") — is the residue of agents claiming completion without observing behavior. The write is not the fix; the *observed behavior change* is the fix.

- **Reproduce before fixing, observe after fixing.** Minimum bar: see the failure with your own tool call, apply the change, see the failure gone. If you cannot reproduce, say so and downgrade your claim ("plausible fix, unverified — the failure requires prod-scale data") rather than asserting success (↔ debugging-9-rules: Make It Fail; If You Didn't Fix It, It Ain't Fixed).
- **Run the narrowest test that can falsify your change, then the suite the gate requires.** Narrow first (seconds, tight loop), broad second (the contract). Skipping straight to the broad suite wastes cycles; stopping at the narrow test ships regressions.
- **Evidence in claims, verbatim.** "Tests pass" is not evidence; "`pytest tests/test_gate.py` → 14 passed, was 12 failed before the change" is. Every completion claim should carry the command and the decisive output line — this is also exactly what closure guards demand, so collecting it as you go makes closure free.
- **Distrust your own diff on arrival.** After a multi-file edit, re-read the final state of each touched hunk (not your intention for it). Edit tools apply what you wrote, not what you meant; a wrong old_string match or a stale read produces silent divergence.
- **Partial completion is a report, not a failure.** "3 of 5 checklist items done; item 4 blocked on the missing fixture; item 5 not started" is a good session outcome. Claiming five-of-five and delivering three is the worst outcome, because the gap surfaces two sessions later as someone else's mystery.

## ch-4 — Scope: the task you were given, all of it, only it {#ch-4}

Junior-agent scope failures come in mirrored pairs, and both are expensive.

- **Scope shrink**: doing the easy 70% and presenting it as done. The tell: the checklist items requiring discovery ("confirm the config key against `grok inspect`") are the ones silently skipped. Name what you skipped and why — skipped-and-named is recoverable; skipped-and-hidden is not.
- **Scope creep**: "while I'm here" refactors inside a fix diff. Every unrequested change is review surface, merge risk, and — in a findings-tracked repo — a new finding anchor. Log the improvement idea as a decision/next-action instead (↔ refactoring-fowler-beck: Two Hats — never both at once).
- **Drive-by breakage check**: before finishing, enumerate call sites of anything whose signature/behavior you changed (grep or codemap trace). The audit's reopened-findings churn was substantially "fixed here, broke there."
- **The diff should read as one sentence.** If you cannot state the diff's single intent ("widen the usage_source gates and migrate the CHECK"), it is two tasks; split it. Reviewers — human or LLM — degrade sharply on multi-intent diffs.
- **Don't relitigate settled decisions.** If the plan or a recorded decision chose approach A over B, implementing B because it seems better *is a defect*, even if B is better. The sanctioned move is: record the objection, implement A, or stop and escalate. Unilateral reversal destroys the coordination the handoff system exists to provide.

## ch-5 — Context economy: tokens are working memory {#ch-5}

An agent's context window is its entire working memory, and junior agents spend it like it's free — then compact away the constraints that mattered. The audit's pathology: single sessions compacting 10–18 times, each compaction shedding the reasoning that justified earlier choices.

- **Externalize state early and always.** Decisions, found anchors, test evidence, open questions → the handoff log/scratchpad *at the moment of discovery*, not at session end. A note written before compaction survives it; working memory does not (↔ programmers-brain on externalizing memory).
- **Read narrow.** Request the function, not the file; the schema of one table, not the dump. A junior agent that reads a 2,000-line file to change one function has spent 5% of its memory on 1% relevance — and will compact away something load-bearing to pay for it.
- **Delegate bulk reading; keep conclusions.** When a question spans many files, the answer belongs in context — the files do not. Summarize-then-drop beats hold-everything.
- **Re-derivation is the tax on poor notes.** If you find yourself re-answering a question you answered earlier this session ("wait, which env runs this suite?"), the failure was not memory — it was not writing it down. Once per session is research; twice is a process bug.
- **Compaction is a signal, not just an event.** Approaching the ceiling repeatedly in one task means the task is oversized for the context budget — slice it, or hand off with a clean summary, rather than thrashing (this workspace treats >2 compactions/session as a slice-it signal).

## ch-6 — Guards and errors: the system is talking to you {#ch-6}

This workspace's largest recorded error class — 86% of all agent errors — is agents fighting their own guardrails: retrying rejected writes with cosmetic variations, seeking bypasses, or abandoning the write. All three responses are wrong.

- **A guard rejection is a specification, not an obstacle.** Read the rejection as the API docs for the sanctioned path: it names the missing field, the required evidence, the correct operation. One rejection is discovery; the same rejection twice is a failure to read (the audit measured the same closure guards firing ~13×/day for weeks).
- **Never bypass; never impersonate compliance.** Fabricating `verification_evidence`, splitting a batch to duck a batch guard, or hunting for an enforcement gap gets past the guard and poisons the record it protects. If the guard is wrong, the move is: record a finding/blocker naming the friction — that is how this repo's guards actually improve.
- **Distinguish "the guard blocked me" from "I'm doing the wrong thing."** Before retrying: does the guard's rationale apply to my case? If yes, satisfy it. If genuinely no (guard bug, missing sanctioned path), stop and escalate with the evidence — today's rejected legitimate write is tomorrow's plan (this file exists partly because of one).
- **Transient vs deterministic failure discipline.** Retry a timeout once, maybe twice with backoff; never retry a deterministic error (schema rejection, type error, 4xx) unchanged — the third identical attempt is the definition of not reading the message. Change something material or change strategy.
- **Log errors you swallow.** An except-and-continue that keeps a session alive but records nothing is how this workspace's telemetry went dark for 19 days. If you degrade gracefully, emit the fact somewhere durable.

## ch-7 — Escalation: knowing when you're the wrong tool {#ch-7}

The most valuable senior behavior a junior agent can imitate is *calibrated stopping* — and the observed failure is bimodal: stopping to ask about things the repo already answers, and not stopping for things only a human can decide.

- **Don't ask what the repo answers.** Config values, existing patterns, which test command — resolve these yourself; asking burns a human round-trip on a grep. The question "should I use the project's error type or invent one?" is answered by ch-2, not by the operator.
- **Do stop for: destructive/irreversible actions, scope changes, secrets/credentials, external side effects, and genuine requirement forks.** State the fork crisply with your recommendation: "A keeps compat and costs a migration; B is clean and breaks two consumers; recommend A" — a recommendation-free question list is scope-shirking dressed as diligence.
- **Timebox unfamiliar territory.** If N attempts (three is a good default) at the same obstacle produce no new information, stop generating variations. Write up what was tried, what was learned, what you'd try with more capability — that artifact makes the handoff to a stronger agent or human nearly free.
- **Your confidence is not evidence.** Fluent prose feels equally fluent when right and when wrong — that is a property of what you are. The countermeasure is structural, not attitudinal: anchors resolved (ch-2), behavior observed (ch-3), evidence quoted (ch-3). Calibration you can't feel must be built into the procedure.
- **Leave the campsite legible.** Session end: working tree state stated, decisions logged, next action written as an imperative a cold-start agent can execute ("run the migrator test on a v25 fixture; the CHECK rebuild is unverified"). The next agent's cold start (ch-1) is only as good as your shutdown.

## Decision rules (summary)

| Trigger (observable in agent behavior) | Rule | Rationale | Src |
| --- | --- | --- | --- |
| First write within two turns of session start on a stateful task | Orient first: context → plan/checklist → recent decisions → branch state | Prevents redo and collision, the two most expensive failures | ch-1 |
| Code/plan/finding cites a path or symbol not resolved this session | Grep/read before citing; unresolvable anchor = finding, not improvisation | Plausible invention is the signature junior defect | ch-2 |
| Fix claimed without a reproduced failure | Make it fail first; downgrade unverifiable claims explicitly | The write is not the fix; observed change is | ch-3 |
| Completion claim without command + decisive output line | Evidence verbatim in every claim | Also satisfies closure guards for free | ch-3 |
| Diff contains changes with no checklist/task anchor | Two Hats: log the idea, don't do it here | Unrequested change = review surface + merge risk | ch-4 |
| Checklist item silently skipped | Name what you skipped and why | Skipped-and-named is recoverable | ch-4 |
| Same question re-answered twice in one session | Externalize to notes/log at discovery time | Context is working memory; notes survive compaction | ch-5 |
| Whole-file read to change one function | Read narrow; delegate bulk reads | 5% of memory for 1% relevance compounds | ch-5 |
| Same guard rejection twice unchanged | Rejection = specification; satisfy or escalate, never vary cosmetically | 86% of this workspace's errors are this loop | ch-6 |
| Deterministic error retried unchanged | Change something material or change strategy | Third identical attempt = not reading the message | ch-6 |
| Swallowed exception with no durable trace | Degrade loudly: emit the fact somewhere durable | Silent degradation is how telemetry dies | ch-6 |
| Question to operator answerable by grep | Resolve it yourself | Human round-trips are the scarcest resource | ch-7 |
| Irreversible action, secret, or requirement fork | Stop; state the fork with a recommendation | The one place stopping is the senior move | ch-7 |
| Three attempts, no new information | Timebox: write up tried/learned/next, hand off | Variation-generation past that point is thrash | ch-7 |
| Session ends with unstated tree/decision state | Legible shutdown: state, log, imperative next action | The next cold start is only as good as your shutdown | ch-7 |

## Anti-patterns

- **Plausible invention** — fluent, unresolved anchors (APIs, paths, flags). Detection: a citation with no corresponding read/grep this session.
- **Completion theater** — "done" with no observation. Detection: claim lacks command+output evidence.
- **Cosmetic retry** — same rejected write, trivially reworded. Detection: ≥2 similar guard rejections in one session.
- **Context gluttony** — whole-file/whole-log reads for point questions. Detection: reads ≫ relevance; early compaction.
- **Silent scope shrink** — hard checklist items skipped without mention. Detection: diff covers the greppable items, discovery items untouched.
- **Decision relitigation** — implementing the rejected alternative. Detection: diff contradicts a recorded decision.
- **Confidence-as-evidence** — assertive language standing in for verification. Detection: strong claims, weak evidence trail.

## Applicability & exemptions

- Orientation procedure (ch-1) scales down for genuinely stateless one-shot tasks (a pure question, a single-file scratch script) — the fixed procedure is for *stateful, tracked* work.
- Timeboxing (ch-7) does not apply to mechanical long-loops (large refactors with a fixed recipe) where attempts are progress, not variations.
- Evidence discipline (ch-3) accepts "unverifiable here" as an outcome — the rule is honest labeling, not infinite verification; some behavior only manifests at prod scale (↔ engineering-heuristics: QA ≠ production).
- These rules assume a harness with tool access and durable logs; in a pure-chat context, "externalize" degrades to explicit in-answer state summaries.

## Candidate lexicon rows

| session's first write lands within two turns on a task with prior state | **Orient before acting** — context, plan checklist, recent decisions, branch state: four reads prevent redo and collision | Did I check what's already done and in flight before editing? | should | write | src: agentic-coding-heuristics ch-1 |
| plan/finding/code cites a path or symbol not resolved this session | **No unresolved anchors** — grep/read before citing; a missing anchor is a finding, not a license to improvise | Did I verify this file/function exists as claimed? | blocker | write | src: agentic-coding-heuristics ch-2 |
| fix claimed for a failure never reproduced in-session | **Make it fail before making it pass** — unverifiable fixes are labeled plausible, not done | Did I observe the failure, and then observe its absence? | blocker | review | src: agentic-coding-heuristics ch-3 |
| completion claim without command + decisive output line | **Evidence verbatim** — every done-claim carries the command and the line that proves it | What output line proves this claim? | should | review | src: agentic-coding-heuristics ch-3 |
| diff hunk with no anchor in the task/checklist | **No while-I'm-here changes** — log the improvement as a next-action; keep the diff one-intent | Can this diff's purpose be stated in one sentence? | should | review | src: agentic-coding-heuristics ch-4 |
| discovery-requiring checklist items untouched while greppable ones complete | **Name the skip** — silent scope shrink presents 70% as 100%; declared gaps are recoverable | Which checklist items did I not do, and did I say so? | should | review | src: agentic-coding-heuristics ch-4 |
| same fact re-derived twice in one session | **Externalize at discovery** — notes/decisions written when learned survive compaction; working memory doesn't | Should this finding be in the log instead of my head? | should | write | src: agentic-coding-heuristics ch-5 |
| same guard rejection hit twice without material change | **Rejection is specification** — satisfy the named requirement or escalate with evidence; never vary cosmetically, never bypass | What exactly is this rejection asking for? | blocker | write | src: agentic-coding-heuristics ch-6 |
| deterministic error (schema/type/4xx) retried unchanged | **Don't retry determinism** — change something material or change strategy | What did I change since the last attempt? | should | write | src: agentic-coding-heuristics ch-6 |
| except-and-continue with no durable record | **Degrade loudly** — a swallowed error that keeps the session alive must still land in a log | If this failure matters next week, where is it written? | should | review | src: agentic-coding-heuristics ch-6 |
| operator asked a question the repo answers | **Grep before asking** — config, patterns, commands are self-serve; save the human round-trip for real forks | Can a tool call answer this? | should | write | src: agentic-coding-heuristics ch-7 |
| third unproductive attempt at the same obstacle | **Timebox and hand off legibly** — tried/learned/next-imperative makes the handoff nearly free | Am I generating new information or variations? | should | write | src: agentic-coding-heuristics ch-7 |
