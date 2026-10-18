# Skill Pattern Extraction Assessment

> **Sources reviewed**: `obra/superpowers` skills, `github/spec-kit` templates, `addyosmani/agent-skills` lifecycle skills.
> **Prior context**: [superpowers-evaluation.md](superpowers-evaluation.md)
> **Applied in**: E17 skill anatomy additions, patches to `review`, `tdd`, `incremental-implementation`.

---

## Executive Summary

Three patterns across the three sources have the highest ROI for this project's skills. They address real failure modes visible in practice:

| Pattern | Source | Failure it addresses |
|---|---|---|
| **CSO Principle** — descriptions state *when*, not *how* | superpowers | Agents read the description summary and skip the full skill body |
| **Rationalizations Table** — each shortcut has a rebuttal | agent-skills | Bullet-list rationalizations are skipped; tabled rebuttals create a logic gate |
| **Verification-before-completion** — name the command that proves the claim | superpowers | Reviews and slice completions claim success without fresh evidence |

Two secondary patterns worth incorporating into E17's planned skills:

| Pattern | Source | Where it applies |
|---|---|---|
| **Complexity Justification** — track architectural violations explicitly | spec-kit | planning-review, branch-lifecycle, plan-analyze skills |
| **Red Flags as Re-entry Triggers** — flags restart the skill, not just warn | agent-skills | tdd, incremental-implementation, review |

---

## Deep Dives

### 1. `verification-before-completion` (superpowers)

**The mechanism in full:**

```
1. Identify what command proves the claim ("tests pass" → name the exact command)
2. Execute it NOW — no cached or assumed results
3. Read the full output, check exit code
4. Verify the output text confirms the specific claim
5. Only then make the claim, quoting the relevant output line
```

The key constraint is **fresh execution + quoted output** — the agent cannot report success without running the command and pasting proof. The skill lists prohibited language: "should work", "seems right", "probably passes", "Done!" before verification.

**What this project's skills currently do:** The `review` skill says "Convergence Criteria: a verdict decision exists via `record_event`." This is *state-based* not *evidence-based* — it checks that an MCP write happened, not that the claim is actually true.

**Applied to branch review:** Before recording `pass` or `pass_with_findings`:
```bash
git diff --stat main...HEAD           # quote line count — must match "I reviewed N files"
make test-handoff (or stack test)     # quote pass count — cannot claim tests pass without running them
```

**Applied to tdd skill:** Before recording `test_result(passed=true)`:
```bash
<test command>                        # quote the exact passing output line
                                      # e.g. "497 passed in 4.32s" — not "tests pass"
```

This is already *partially* in the tdd skill ("Record the GREEN evidence with `record_event(..., result=...)`) but the requirement to *quote actual output* is implicit. Making it explicit prevents agents from recording a fabricated `result` field.

**Applied to this project's skills pattern:** Every skill's Convergence Criteria should end with a `## Verification Evidence` subsection listing the exact commands and required output shape:

```
## Verification Evidence

| Claim | Command | Required output |
|---|---|---|
| All tests pass | `make test-handoff` | `N passed` with N > 0, exit 0 |
| No open findings | `review_findings(operation="list", status="open")` | `items: []` |
| Verdict recorded | `review_runs(operation="list")` | entry with matching `verdict` field |
```

---

### 2. Rationalizations Table (agent-skills)

**The mechanism in full:**

agent-skills structures rationalizations as a three-column table with *why it fails* and *required action*, not just a list of things to avoid. The table acts as a refutable logic gate: the agent must work through each row before skipping a step.

Current `review` skill:
```
## Common Rationalizations
- "I can mention the issue now and record it later."
- "This looks minor, so I don't need the full checklist."
```

These are dismissible bullets. The agent reads them and moves on.

**Upgraded format:**

```markdown
## Common Rationalizations

| Rationalization | Why it fails | Required action |
|---|---|---|
| "I can mention the issue now and record it later." | Findings reported without a stable `finding_id` cannot be tracked, deferred, or verified by the pre-merge gate. The gate does not audit chat history. | Record the finding before mentioning it. If MCP is unavailable, record a blocker instead. |
| "This looks minor, I don't need the full checklist." | Every pass has found findings on "minor" diffs — e.g. contract field drift, missing test coverage. Severity cannot be assessed by inspection before the checklist runs. | Run the full checklist. Mark LOW-severity findings as such, but still record them. |
| "The user only asked for a quick pass." | "Quick" describes the desired pace, not permission to skip recording discipline. A quick pass with durable findings is better than a fast pass with none. | Full checklist, expedited where straightforward. Still record. |
```

The key difference: each row forces the agent to process the counter-argument, not just recognize the pattern.

**This applies to every execution skill in this project.** The tdd and incremental-implementation skills already have rationalizations bullets — they should be converted to three-column tables.

---

### 3. CSO Principle — trigger-only descriptions (superpowers)

**The mechanism:**

> "Descriptions must focus on *when* to use (triggers), NOT *how*, because full workflow summaries cause agents to follow the summary instead of reading the complete skill."

The constraint is: the `description` frontmatter field and the first sentence of the Overview must describe activation conditions, not workflow steps. If the description summarizes the workflow, agents treat the summary as sufficient and don't read the full body.

**Current state in this project:**

| Skill | Current `description` | Violation |
|---|---|---|
| `review` | "Run a structured branch or planning review, record findings in MCP, and finish with a durable verdict." | Describes what the skill does, not when to activate it |
| `tdd` | "Enforce RED -> GREEN -> REFACTOR with a recorded failing-test gate before any implementation edit." | Same — describes the process |
| `incremental-implementation` | "Break implementation into bounded vertical slices that each start with a recorded failing test and end with a reviewable commit." | Same |

**Corrected form:**

| Skill | Trigger-focused description |
|---|---|
| `review` | "Use when asked to review a branch diff, task plan, PR, epic, or ADR. Activates on: 'review', 'audit', 'flag gaps', 'propose improvements'." |
| `tdd` | "Use at the start of any implementation slice. Activates when `make slice-start` is the next step or when new test coverage is needed before production edits." |
| `incremental-implementation` | "Use when turning a reviewed task plan into implementation slices. Activates when starting feature work from an approved plan." |

The principle: the `description` field is what shows up in skill menus and CLAUDE.md key triggers. It must answer "when do I activate this?" not "what does this do?"

---

### 4. Complexity Justification (spec-kit)

**The mechanism:**

spec-kit's `plan-template.md` requires a **Complexity Justification** table before any task plan is approved:

```markdown
| Decision | Simpler Alternative Considered | Why Simpler Doesn't Work |
|---|---|---|
| Two-phase write in _task_start_inline.py | Single atomic call | switch_task API has no target_worktree_path parameter |
```

This is an audit trail for architectural violations. It forces teams to document *why* a simpler path was not taken, creating a reference for future reviewers.

**How this maps here:** The `planning-review` skill (E17-3 deliverable) and `plan-analyze` skill should check for a complexity justification when a plan includes anything that violates the greenfield policy (backward-compat shims, two-phase writes, migration work). Currently `planning-review-guide.md` has "Reuses existing abstractions where appropriate" as a checkbox — it doesn't require justification documentation.

**Applied pattern for E17 planning-review skill:**

Add as a detection pass: "If the plan contains any implementation that cannot be the simplest possible approach (multi-step operations where one step would suffice, compatibility shims, parallel state management), it must include a Complexity Justification section in the task plan. A plan without justification for non-trivial complexity is a MEDIUM GAP finding."

---

### 5. Red Flags as Re-entry Triggers (agent-skills)

**The mechanism:**

agent-skills specifies that Red Flags are not just warnings — they are **re-entry triggers**. When a red flag is detected, the agent re-enters the skill at the step that was violated, not just adds a note and continues.

Current `tdd` skill:
```
## Red Flags
- A production file is edited before the failing test is recorded.
```

This reads as "notice and feel bad." The agent-skills version reads as: "if you see this, go back to step 2 (write the failing test first), do not continue from where you are."

**Upgraded pattern:**

```markdown
## Red Flags

Each flag is a re-entry trigger, not a warning. When detected, stop and re-enter at the step listed.

| Flag | Re-entry point |
|---|---|
| Production file edited before failing test recorded | Re-enter at Step 2 (write the failing test). Do not record GREEN evidence for code written without a RED gate. |
| First test failure is syntax/import noise unrelated to the behavior | Re-enter at Step 3 (confirm failure is for the intended reason). |
| Test passed on first run without seeing it fail | Invalidate the result — if it never failed, it may not be testing anything. Re-enter at Step 2 with a more targeted assertion. |
```

The "test passed on first run" flag is particularly important — it's from agent-skills and catches a failure mode where a test is written to match the existing code rather than to specify new behavior. This happens regularly in TDD shortcuts.

---

## Skill Anatomy Additions for E17

The five patterns above translate directly to additions for the E17 `SKILL_ANATOMY.template.md` (E17-1 deliverable):

```yaml
# New optional frontmatter fields:
verification_evidence: true   # requires ## Verification Evidence subsection in Convergence Criteria
reentry_triggers: true        # Red Flags are re-entry points, not warnings
```

And two mandatory sections for all execution skills:

```markdown
## Common Rationalizations

| Rationalization | Why it fails | Required action |
|---|---|---|
```

```markdown
## Verification Evidence

| Claim | Command | Required output shape |
|---|---|---|
```

The `description` frontmatter field now has a documented constraint: **trigger conditions only, no workflow steps**.

---

## What NOT to adopt

| Pattern | Source | Why not |
|---|---|---|
| Full session-start hook that injects entire skill into context | superpowers | Conflicts with selective-memory direction; this project uses CLAUDE.md for startup discipline |
| Extreme task granularity (2-5 minute steps with full code blocks) | superpowers/spec-kit | Too prescriptive for a mature codebase; slice decisions already provide the right granularity |
| Constitution as 9 immutable principles with ratification dates | spec-kit | This project's `[sr/rg-NNN]` rules in `constitution.md` already serve this purpose |
| Persona injection (Staff Engineer, Security Auditor) | agent-skills | The branch-review-guide's multi-lens audit workflow covers this without separate personas |
| YAML-registry for agent integrations | spec-kit | This project has no need for pluggable agent backends; `.claude/skills/` is the surface |

---

## Immediate Patches Applied

Three skills patched in the same commit as this assessment:

1. **`review` SKILL.md** — description field → trigger-only; Rationalizations → table with rebuttals; Convergence Criteria → adds Verification Evidence subsection.

2. **`tdd` SKILL.md** — description field → trigger-only; Rationalizations → table with rebuttals; Red Flags → re-entry trigger format; adds "test-passed-on-first-run" red flag.

3. **`incremental-implementation` SKILL.md** — description field → trigger-only; Rationalizations → table with rebuttals; Red Flags → re-entry trigger format.

---

## Backlog for E17 Skill Anatomy Work (E17-1 + E17-2 deliverables)

- `SKILL_ANATOMY.template.md`: add `## Common Rationalizations` table format + `## Verification Evidence` table format as mandatory for execution skills; add CSO constraint to `description` field docs
- `plan-analyze` skill (E17-3): add Complexity Justification detection pass — flag plans with non-trivial complexity but no justification section
- Remaining skills (`document-sync`, `refactor`, `security-audit`, `investigate`): patch CSO principle on descriptions; add rationalizations tables in E17-3 retrofit phase
