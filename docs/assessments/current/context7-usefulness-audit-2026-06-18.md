# context7 Usefulness Audit & Reintroduction Criteria

- **Date:** 2026-06-18
- **Task:** `MAINT-context7-usefulness-audit-20260618`
- **Trigger:** context7 MCP server removed (`MAINT-context7-removal-20260618`, merge `44b84835`) after it spawned zombie `npx` processes that regularly drove CPU to ~99%.
- **Status:** Complete.

## Verdict

**Removal was justified. Historical usefulness is not proven by the record.** Across the entire handoff ledger (1,006 decisions, 76 archived task snapshots, all blockers/findings/actions/errors), context7 was cited as the basis of an outcome **zero** times — the only trace it leaves is its own removal decision. In task plans it appears 237 times across 64 files, but ~almost entirely as the templated planning ritual "Confirmed `ctx7` not required" or "External docs via `ctx7` **only if** <condition>" — and the condition essentially never fired. Workbay resolves design questions from local-codebase references and pinned-version stability, not from context7-fetched docs.

**Do not reinstate now.** It was a nonzero-cost (zombie processes, CPU) dependency with near-zero realized utility. Reintroduce only if the trigger criteria below are met, and prefer the lightweight on-demand alternative first.

## What context7 was

`@upstash/context7-mcp`, an `npx`-spawned stdio MCP server (`resolve-library-id` + `query-docs`/`get-library-docs`) providing on-demand, version-current documentation for third-party libraries. Wired as an on-demand server in `.mcp.json`/`.vscode`/`.codex` and the workbay bootstrap, surfaced via the MCP loading protocol only when a task's "External docs" entry criteria fired.

## Audit method (reproducible — see Appendix)

1. **Handoff DB** — searched every text surface for `context7`/`ctx7` via the `workbay_handoff_mcp` Python API (FTS + raw `LIKE` cross-check; never raw `sqlite3` on internal tables).
2. **Repository docs** — `grep` over `docs/`, categorized each mention by intent (declined / conditional / actual-use).
3. **Git history** — reviewed commits referencing context7.

## Findings

### 1. Handoff DB: zero realized usage

| Surface | Scanned | context7/ctx7 hits |
| --- | --- | --- |
| `decisions` (live, all task_refs) | 1,006 | **1** — the removal decision |
| `task_archives` snapshots | 76 | **1** — same removal task |
| `review_findings`, `blockers`, `next_actions`, `agent_errors`, `worker_reports`, `lane_messages` | all | **0** |

The decision ledger is the authoritative record of *what actually drove an outcome*. Not one slice rationale, verification, blocker resolution, or review finding across the project's history cites context7 as its source. The sole hit is `claude_context7_removal_mcp_and_docs` (today).

### 2. Docs: intent ≠ execution

237 mentions across 64 doc files, dominated by scaffolding rather than use:

- **29** lines: explicitly "not required" / "no `ctx7` needed".
- **42** lines: "only if / only for / only when <condition>" — conditional gates whose trigger condition was not met in practice.
- **Remainder:** template headers, "Entry Criteria" sections, and per-task checklist items (`[ ] Confirmed ctx7 not required`).

The pattern is a planning *ritual*: nearly every task plan carried a ctx7 checklist line, and nearly every one resolved to "not needed — stable surfaces / derivable from repo code."

### 3. Genuine-use accounting (the honest exceptions)

Three cases rise above pure scaffolding; none establish recurring value:

- **`docs/archive/tasks/8.0/ace-ctx7-documentation-evolution-task-plan.md` (2026-03-22):** the task that *installed and verified context7 itself* (confirmed it could fetch docs for fastapi/radix/vitest/phpunit, noted `wp-mock` had no coverage). This is meta — proving the tool works — not using it to make a product decision.
- **E15-2 observability baseline:** "verify latest via `ctx7` **or PyPI**" for `python-json-logger`/`prometheus-client` pins. Hedged; PyPI alone is sufficient and authoritative for version/availability.
- **E19-1 headless description foundation:** plan marks ctx7 "needed **only** for Florence-2 / `transformers` `trust_remote_code` load semantics during S9." Forward-looking, narrow, one-time, and **not yet executed** (no DB trace). This is the single most plausible future trigger — see criteria below.

## Usefulness evaluation

| Dimension | Assessment |
| --- | --- |
| Realized value | Effectively zero — no decision ever depended on it. |
| Why so low | Dependencies are version-pinned and stable; behavior questions are answered from local code, contracts, and tests. The codebase is the source of truth, not external library docs. |
| Cost | Persistent `npx`/node zombie processes → ~99% CPU regularly. Real, recurring operational cost. |
| Cost/benefit | Strongly negative. A persistent always-available server idling as a zombie to serve a lookup that fired ~never. |

## Recommendation

1. **Keep context7 removed.** The evidence does not support reinstatement.
2. **No further doc churn needed.** The ctx7 checklist ritual was already excised by `MAINT-context7-removal-20260618`; leave the historical task-plan mentions in place (archived artifacts).
3. **For the rare genuine need, use on-demand lookup, not a resident server:** `WebFetch`/`WebSearch` against the library's official docs/model card, or a short-lived one-shot `npx` invocation that exits. This serves the E19-1 Florence-2/`transformers` case without a long-lived process.

### Reintroduction criteria (all must hold)

Reconsider a resident context7 (or equivalent docs-MCP) only if **all** of the following become true:

1. A pattern of **≥3 distinct tasks within one epic** are blocked on *version-current* third-party API behavior that is **not** derivable from local code, pinned-version docs, or a single web fetch.
2. The upstream surfaces churn fast enough that pinned local knowledge goes stale between tasks (e.g., a pre-1.0 dependency under active development in the hot path).
3. A process-lifecycle fix is in hand: the server must terminate cleanly on session end (no zombies / CPU pin) — verify with a soak test before re-wiring.

If reintroduced, gate it as on-demand (not always-loaded) and instrument actual `resolve-library-id`/`query-docs` call counts, so this audit can be repeated against real telemetry rather than planning-checklist intent.

## Appendix — reproduce this audit

```bash
# Handoff DB (Python API; read-only; package owns the schema map)
python3 - <<'PY'
from pathlib import Path
import workbay_handoff_mcp as w
from workbay_handoff_mcp import core
w.configure_runtime(w.RuntimeConfig.for_repo(Path(".")))
with core._get_db_connection() as conn:
    for rtype,(fts,_) in core._RECORD_TYPE_FTS_MAP.items():
        rows = conn.execute(
            f"SELECT task_ref, snippet({fts},0,'[',']','...',20) s "
            f"FROM {fts} WHERE {fts} MATCH '\"context7\" OR \"ctx7\"' ORDER BY rank", ()).fetchall()
        print(rtype, len(rows), [dict(r) for r in rows])
    # raw LIKE cross-check (FTS tokenization can miss substrings)
    for term in ('%context7%','%ctx7%'):
        n = conn.execute("SELECT COUNT(*) FROM decisions WHERE IFNULL(decision,'')||IFNULL(rationale,'') LIKE ?", (term,)).fetchone()[0]
        a = conn.execute("SELECT COUNT(*) FROM task_archives WHERE IFNULL(snapshot_json,'') LIKE ?", (term,)).fetchone()[0]
        print(term, "decisions:", n, "archives:", a)
PY

# Docs intent categorization
grep -rIi -e context7 -e ctx7 docs/ | wc -l                              # total mentions
grep -rIi -e ctx7 -e context7 docs/ | grep -Eci 'not (required|needed)'  # declined
grep -rIi -e ctx7 -e context7 docs/ | grep -Eci 'only if|only for'       # conditional gates
```
