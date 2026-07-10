# Upstream request — reconcile materialized surfaces, config/hook registrations, and the ignore fence

**Target repo:** `agentic-protocol-monorepo` / `darce/workbay` (`workbay-bootstrap` installer + `workbay-system` payload).
**Consumer:** `context-alt-text-monorepo` (package-mode install, no `.workbay/remote` clone).
**Affected release:** `workbay-v0.1.41` — `workbay-bootstrap==0.3.10`, `workbay-system==0.3.8`.

## Summary

Three sources of truth drift because nothing reconciles them:

1. what the installer **materializes** (`SHARED_SURFACES`, `GENERATED_SURFACES`, `LIFECYCLE_HOISTS`, curated `.claude/*` subtrees),
2. what it **registers in configs** (hook commands in `.claude/settings.json` / `.claude/settings.hooks.json`),
3. what it **adds to the ignore fence** (`_consumer_gitignore_entries()`).

Two live defects fall out of this, each caught only by accident (a leaked file in `git status`; a `SessionStart` hook error). Neither is flagged by `doctor`, which reports "no drift detected" while both are present.

---

## Defect 1 — hoisted lifecycle runner leaks into `git status`

After `workbay update` to `workbay-system==0.3.8`, the consumer repo shows `scripts/workbay_lifecycle/` (37 untracked files) — a bootstrap-materialized SHARED surface that should be ignored and regenerated, not committed.

Root cause, two independent gaps (either alone is sufficient):

- **(A) The fence-entry generator can't see the lifecycle runner.** `install.py::_consumer_gitignore_entries()` derives the ignore set only from `SURFACE_PROVENANCE` (kinds `shared` / `generated` / `generator_input` / `harness_materialized`). The lifecycle runner is materialized through the *separate* `LIFECYCLE_HOISTS` tuple (`install.py:296`), which no fence code reads (it is referenced only by the copy passes at `install.py:1553–2503`). Pre-rename the runner lived at `scripts/workbay/lifecycle`, *under* the `scripts/workbay` shared surface, so the umbrella `/scripts/workbay` ignore covered it by accident. `workbay-system==0.3.8` hoisted it to the top-level sibling `scripts/workbay_lifecycle` with no umbrella — exposing the latent omission. **A full `workbay install` would not auto-ignore it either.**
- **(B) `update` never reconciles the fence.** `_ensure_consumer_gitignore_block()` is called only from `install_plan.py:633` (install) and `adopt.py:345` (adopt). `subcommands.py::update()` (`:3072`) makes **zero** gitignore calls — it refreshes/materializes surfaces but skips fence reconciliation, so any surface added or renamed between versions leaks after an `update` regardless of (A).

The reconciler itself is correct and self-documents this class: *"a surface added to the managed lists after the block was first written … keeps a stale block and the new surface leaks into `git status` forever."* It simply is not fed the hoist paths, and is not run on update.

## Defect 2 — registered `SessionStart` hook points at an un-materialized script

`.claude/settings.json` and `.claude/settings.hooks.json` both register:

```
SessionStart → bash "$CLAUDE_PROJECT_DIR/.claude/hooks/ensure-agent-surfaces.sh"
```

but `.claude/hooks/` does not exist in the consumer. Result on every session start:

```
SessionStart:startup hook error
Failed with non-blocking status code: bash: …/.claude/hooks/ensure-agent-surfaces.sh: No such file or directory
```

Root cause: the `workbay-system` payload ships **both** the registration (`payload/.claude/settings.hooks.json`) **and** the script (`payload/.claude/hooks/ensure-agent-surfaces.sh`), but the installer's per-agent materialization (`install.py:216`) copies `.claude/skills` and `.claude/commands` and **not** `.claude/hooks/`. So the registered command is delivered while the file it invokes is not — the mirror image of Defect 1 (there: a materialized surface with no fence entry; here: a registered reference with no materialized surface).

The un-delivered script is itself the fresh-clone self-heal hook (`make plugins-build` + `make generate-agent-workflows` for gitignored generated surfaces) — so the mechanism meant to repair missing surfaces is the one surface that goes missing.

Secondary: even if `.claude/hooks/` were materialized, it is **not in the canonical ignore fence** (`_consumer_gitignore_entries()` has `/.github/hooks`, `/scripts/hooks`, but no `.claude/hooks`), so it would then leak — a second instance of Defect 1(A).

---

## Consumer workaround (please obsolete)

- Defect 1: hand-added `/scripts/workbay_lifecycle` to the consumer `.gitignore` (`context-alt-text-monorepo@f6e22d42`). Re-verify after each upgrade until the fence generator is fixed.
- Defect 2: currently unremediated (hook fails non-blocking). Local options are all unsatisfactory — vendoring/committing package payload, or deleting a workbay-managed registration that `update` re-adds.

## Ask

**Fence (Defect 1):**
1. Fold `LIFECYCLE_HOISTS` destinations into the fence source — e.g. `_consumer_gitignore_entries()` appends `[f"/{dest}" for _src, dest in LIFECYCLE_HOISTS]` (deduped), or register the hoist dests in `SURFACE_PROVENANCE` as `shared`.
2. Call `_ensure_consumer_gitignore_block(target)` from `subcommands.update()` too, so a cross-version rename self-heals on `update` instead of only on `install`/`adopt`.

**Materialization (Defect 2):**
3. Include `.claude/hooks/` in the installer's per-agent surface materialization so every payload-registered hook command resolves to a delivered file. Add `/.claude/hooks` to `_consumer_gitignore_entries()` (it is regenerable payload, same rule as `/scripts/hooks`).

**Prevention (root cause):**
4. Add a `doctor` integrity check that fails on either drift class:
   - every hook `command` path in `.claude/settings*.json` resolves to an existing file, and
   - every materialized overlay surface is tracked **or** ignored (no leaks).
   Both current defects passed `doctor` — a completeness assertion against materialized-reality (not just content-drift of known surfaces) would have caught them at install time.

## Acceptance

On a fresh consumer, immediately after `workbay install` (and again after `workbay update` across the rename):

```
git status --porcelain           # no untracked scripts/workbay_lifecycle/**, no untracked .claude/hooks/**
test -f .claude/hooks/ensure-agent-surfaces.sh   # exit 0 (delivered)
# open a Claude Code session → no SessionStart hook error
workbay doctor --target .        # fails if any registered hook path is missing OR any materialized surface leaks
```

---

## Additional asks (orchestrator observability — separate from the overlay-reconciliation defects above)

### Ask 5 — grok offload per-turn token metrics tallied, presented, and logged

**Confirmed gap** (traced in `agentic-protocol-monorepo`, `workbay-v0.1.41`):

- grok-cli emits no recognized usage — `orchestration/backend_registry.py:102-107` declares `supports_token_telemetry=False` (`total_tokens=0`); `normalize_cli_usage` (`orchestration/adapters/_result_text.py:217-228`) accepts only claude snake_case keys and returns `None` for grok's `promptTokens`/`completionTokens` (`adapters/grok_cli.py:323-324`).
- No **main-agent / orchestrator** token capture exists anywhere — accounting is subagent/worker-only (`worker_daemon.py:593-610`).
- Turn/pass end surfaces only a single cumulative **subagent** total (`offload_pass.py:664-674`), not a main-vs-subagent breakdown. `turn_metrics(summary)` / `get_metrics_summary` are on-demand queries, not a turn-end presentation.
- Persistence into the handoff `turn_metrics` table (`workbay_handoff_mcp/shared_schema.py:451-473`) is gated on `total_tokens>0` (`worker_daemon.py:742`), so grok 0-token turns **and** any main-agent usage are never logged.

**Ask:** at the end of each orchestration turn, present the user token usage broken down by **main agent** and each **subagent**, and log per-turn usage to the handoff DB for future tabulation. Requires: (a) main-agent token capture; (b) a grok usage parser (`promptTokens`/`completionTokens`) or explicit estimated/zero accounting so grok turns are not silently dropped; (c) a turn-end summary renderer; (d) relaxing the `total_tokens>0` persistence gate so zero/absent turns still tabulate.

### Ask 6 — codemap MCP wired into automated flows (NOT coupled to embeddings)

Two parts, one corrected:

- **Valid:** the codemap / codebase-graph MCP (`get_architecture`, `trace_path`, `detect_changes`, `index_repository`) is **purely advisory/manual** today — referenced only in skill-body cue text and `CLAUDE.local.md`, launched opt-in (`config/agent-workflows/mcp_servers.yaml:60-69`), and **never auto-invoked** by any hook or the orchestrator (0 grep hits across hooks/orchestrator/handoff). Codemap is cheap to run. **Ask:** wire `detect_changes` / `index_repository` into the automated review/plan flows so agents use it as much as possible, and keep the index fresh (`auto_index` / an index_status precheck) rather than relying on manual refresh.
- **Corrected — dropped:** the original framing "update codemap **before** semantic embeddings are computed" rests on a false premise. The semantic-reinjection embeddings embed **handoff concepts** (decision rationales, findings, blockers, objectives, compaction residuals — `workbay_handoff_mcp/embeddings/store.py:31-40`), **not source code**. Codemap indexes code structure. They are disjoint pipelines over disjoint data; refreshing codemap first would **not** make embeddings "reflect current code" (they never index code). So there is no ordering dependency to add — the two systems should stay decoupled.
