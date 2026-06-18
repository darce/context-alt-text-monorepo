# ACE Rule-Curation Framework — Usefulness Audit

- **Date:** 2026-06-18
- **Task:** `MAINT-ace-framework-usefulness-audit-20260618`
- **Scope:** The ACE (Autonomous Coding Engine) helpful/harmful evidence-counter loop that is meant to curate & prune the `sr-*` / `rg-*` rules. Companion to [context7-usefulness-audit-2026-06-18.md](context7-usefulness-audit-2026-06-18.md).
- **Status:** Complete.

## Verdict

**Split.** Two layers must be judged separately:

- **The rule *set* (`sr-*`/`rg-*`) is load-bearing and useful.** 26 bullets are injected into `CLAUDE.md` and many `rg-*` rules are enforced as real `PreToolUse` hooks (main-branch guard, task-plan-findings guard, SHA validation, branch enforcement). This works.
- **The ACE *curation loop* (helpful/harmful counters → prune/promote) is dormant and structurally broken.** It has produced **zero** curation outcomes in the project's history: no counter ever auto-incremented, no rule ever pruned or promoted by the mechanism, `harmful` is `0` on all 26 rules, and no pruning pass was ever recorded in MCP.

**Answers to the two questions:** Is it still being updated? **No.** Has it shaped skills/instructions/hooks? **The loop has not** — the rules that shaped hooks were authored and promoted manually, not via the helpful/harmful mechanism.

## The machinery (it exists and is wired)

| Component | Location | State |
| --- | --- | --- |
| Detector hook | `scripts/hooks/ace-detect.py` (wired in `.claude/settings.json`) | Active; logs rule refs/contradictions from review findings |
| Reflect log | `.task-state/ace_reflect_log.jsonl` | **7 entries ever; last 2026-06-05** (13 days stale) |
| Reflector | `scripts/ace/ace_reflect.py` (470 lines) | Runs, but parses the wrong file (below) |
| Make targets | `ace-metrics`, `ace-metrics-json`, `ace-reflect`, `ace-curation-report`, `ace-trends` | `ace-metrics` **crashes**; `ace-reflect`/`ace-curation-report` no-op |
| Playbook | `docs/workstate/playbooks/ace-pruning-playbook.md` | Defines triggers + 30-day cadence — not being followed |
| Counters (canonical) | `docs/workstate/constitution.md` (26 bullets) | Hand-seeded; never auto-updated |

## Findings (evidence)

### 1. The tooling is pointed at the wrong file (root cause)
`make ace-reflect` and `make ace-curation-report` both parse `--instruction-files docs/workstate/instructions.md`. But the rule bullets moved to `constitution.md` during the workstate migration:

| File | ACE bullets (`- [sr/rg-NNN] helpful=… harmful=…`) |
| --- | --- |
| `docs/workstate/constitution.md` (canonical) | **26** |
| `CLAUDE.md` (injected copy) | 26 |
| `docs/workstate/instructions.md` (what the tools parse) | **0** |

`make ace-curation-report` confirms it: *"Total bullets: 0 … No pruning candidates."* The application side reads zero data, so counter updates and pruning are structural no-ops regardless of what the detector logs.

### 2. The loop is open — captured contradictions never land
The detector did its job 7 times. One entry is a genuine signal:
```
{"finding_id":"MAINT-FB-DEFERRED-20260604-REV-B-BR-01","rule_id":"rg-008","contradicts":true,"timestamp":"2026-06-04T20:22:11Z"}
```
A review finding **contradicted `rg-008`** — exactly the signal that should bump `rg-008`'s `harmful` counter and flag it for review. It was never applied: `rg-008` still reads `helpful=1 harmful=0`. Detection writes the log; application never runs (and would no-op anyway per #1).

### 3. `harmful` has never once been nonzero
Across all 26 live rules (and project history), no rule has ever carried `harmful>=1`. The playbook's prune criterion is `helpful=0 harmful>=2` — **unreachable in practice**, so nothing can ever become a pruning candidate. The counters are effectively decorative.

### 4. Counters are hand-seeded, not evolved
`git log -S` on counter strings shows changes only in manual doc-authoring commits (e.g. `dc785e15 add constitution…`, `e5a2bf11 docs(rg-018)…`). New rules (like `rg-018`) were added **by hand** with a human-written rationale — real curation, but not the ACE mechanism. No commit shows an automated `ace-reflect` counter bump.

### 5. Zero curation activity in the handoff ledger
Across 1,006 decisions: `ace_reflect`=0, `helpful=`/`harmful=`=0, `strategy bullet`=0, `ace-pruning`=**1** (the context7 removal merely editing an "ACE-pruning Adoption Evaluation" doc section — not a pruning pass). The playbook's step 6 ("record the pruning outcome in MCP") has never executed. The 30-day pruning cadence is overdue with no pass on record.

### 6. Observability is broken
`make ace-metrics` crashes in this workspace (`resolve_active_task_ref` → ambiguous active task, the same multi-`MAINT-*` ambiguity that affects other cwd-resolved tools). The metrics/trends side can't run without an explicit `TASK=`.

## Evaluation

| Layer | Useful? | Why |
| --- | --- | --- |
| Rule set (`sr-*`/`rg-*`) | **Yes** | Injected into agent context; several `rg-*` rules enforced as hooks; genuinely shapes behavior. |
| Helpful/harmful counters | **No** | Hand-seeded, never auto-updated, `harmful` always 0 — they imply measured evidence that does not exist. |
| Detect→reflect→prune loop | **No (broken)** | Detector logs, but `ace-reflect` parses the wrong file; no counter update, prune, or promotion has ever occurred. |
| Metrics/trends | **No (broken)** | `make ace-metrics` crashes. |

**Risk of the status quo:** the decorative counters give a false impression of an evidence-driven, self-correcting system. An agent reading `[rg-008] helpful=1 harmful=0` may trust it as measured signal when it is a static seed — and the one real contradiction the system ever caught was silently dropped.

## Recommendation — decide: repair or retire

**Option A — Repair (small, mechanical):**
1. Repoint the Make targets + `ace_reflect.py` default from `instructions.md` → `docs/workstate/constitution.md` (the canonical bullet home), then re-sync the injected `CLAUDE.md` copy.
2. Run a reflect pass to apply the backlog (the `rg-008` contradiction from 2026-06-04).
3. Fix `make ace-metrics` (pass `TASK=`, or archive stale `MAINT-*` rows so cwd resolution is unambiguous — see the context7 audit's same ambiguity).
4. Run the overdue 30-day pruning pass and record the outcome in MCP per the playbook.

**Option B — Retire (honest):** if no one will run the cadence, drop the `helpful=/harmful=` annotations from the injected surfaces (keep the rules as a plain curated list), and remove the `ace-detect` hook + `ace-*` Make targets. Keeps the load-bearing rules; deletes the machinery that only signals rigor it doesn't deliver.

**Recommended:** Option A *only if* an owner commits to the cadence; otherwise Option B. Do not leave the loop in its current state — wired, surfaced as evidence, doing nothing.

## Appendix — reproduce

```bash
# bullet location (tools parse instructions.md; data lives in constitution.md)
for f in docs/workstate/constitution.md docs/workstate/instructions.md CLAUDE.md; do
  printf '%s: ' "$f"; grep -cE '^\s*-\s+\[(sr|rg)-[0-9]{3}\]\s+helpful=' "$f"; done

make ace-curation-report          # -> "Total bullets: 0 ... No pruning candidates."
grep -rIn 'harmful=[1-9]' docs/   # -> empty: harmful never nonzero
cat .task-state/ace_reflect_log.jsonl   # 7 entries; last 2026-06-05; one contradicts:true (rg-008)

# ledger: zero ACE-curation decisions (Python API; read-only)
python3 - <<'PY'
from pathlib import Path
import workstate_handoff_mcp as w
from workstate_handoff_mcp import core
w.configure_runtime(w.RuntimeConfig.for_repo(Path(".")))
with core._get_db_connection() as conn:
    for t in ('%ace_reflect%','%helpful=%','%harmful=%','%ace-pruning%'):
        n=conn.execute("SELECT COUNT(*) FROM decisions WHERE IFNULL(decision,'')||IFNULL(rationale,'') LIKE ?", (t,)).fetchone()[0]
        print(t, n)
PY
```
