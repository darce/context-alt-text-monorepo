# Upstream implementation request (consolidated) — refactoring-lens enforcement, a sturdier overlay install/materialize/cleanup mechanism, semantic-reinjection delivery, and lifecycle/CLI/pin gaps

> **For:** `agentic-protocol-monorepo` (canonical `workbay-system` / `workbay-bootstrap`; with `mcp-workbay-handoff` / `mcp-workbay-orchestrator` where noted).
> **From:** `context-alt-text-monorepo` (consumer), `MAINT-workbay-migration-cleanup-20260628`.
> **Status:** **Consolidated. Supersedes and retires** the prior `2026-06-28` refactoring-lens+overlay request **and** the consumer's `workstate`→`workbay` migration upstream-asks doc. All open, implementable upstream asks from both are preserved here; consumer-side records are listed (and intentionally excluded) at the end.
> **Why:** completing the `workstate`→`workbay` migration in this consumer surfaced four classes of upstream-owned gaps: (1) the distilled engineering-literature review lens is enforced only by **local, untracked** state that any re-sync silently drops; (2) the install/materialize/cleanup mechanism left this consumer **half-materialized** with no single command that converges or cleans it; (3) semantic-compaction reinjection is **shipped but not delivered** (no model, no hook wiring, no activation); and (4) a backlog of **lifecycle / handoff-CLI / lane / MCP-pin / close-check** gaps a consumer cannot fix from its own checkout (Plugin Boundary Rule). Fix each where it is owned — upstream — so every consumer inherits a sturdy, enforceable surface and only repo-specific rules remain local.

The design below is written **applying the distilled concepts themselves** (idempotency, fail-fast, single-source-of-truth, expand→migrate→contract, characterization tests). Anchors like `#data--consistency`, `#resilience--failure-modes`, and `#refactoring--design` deep-link the attached `engineering-heuristics.md` (the lens lives there).

---

## Consumer current state (what you're fixing)

Distilled from the migration hand-completion (no installer run) — the half-materialized starting point:

- **Mode/symlink split:** package-mode ledger (`.workbay-bootstrap.json`, `source_kind=package`, **no `remote_sha`**) but **clone-mode symlinks** — `scripts/hooks`, `.github/hooks`, `Makefile.d/*`, `scripts/workstate/*` still resolve into `.workstate/remote/…workstate-system…`; **`.workbay/remote` does not exist**. The ≈200 MB `.workstate/` clone is load-bearing and unremovable until the installer repoints symlinks.
- **Untracked review lens:** `docs/workbay/rules/engineering-heuristics.md` is gitignored, local-only, absent from the payload, and the **sole backing** for the review lens — it vanishes on any re-materialization.
- **Hoisted, hand-patched tooling:** `overlay_resolver.py`, `check_harness_sync.py`, the workflow generators, etc. are general harness tooling hoisted into the consumer and kept workstate-free by hand.
- **Greenfield + fail-fast posture:** no production data; the repo resolves only the canonical overlay home through a single `scripts/_overlay_clone.py` seam and fails fast when absent (no stale-clone fallback).
- **Reverting hand-fixes:** sed-patched hooks (`workstate_handoff_mcp`→`workbay_handoff_mcp`), a manually-added Stop hook, ledger/sentinel renames, and `overrides.lock.json` digest edits all revert on the next materialization.

---

## Goal

Move the **general** engineering-discipline surface (smell catalog, resilience/latency/data lens, produce-first gates), the **overlay install/cleanup mechanism**, the **semantic-reinjection delivery**, and the **lifecycle/CLI/pin** surfaces into **sturdy, enforceable, upstream-shipped** workbay skills + hooks + bootstrap behavior, so that:

- a **junior agent** implementing a plan is *guided to produce well-factored code on the first draft* (less downstream refactoring), and review *enforces* it;
- the lens, the overlay, and the compaction system **survive** clone / CI / overlay re-materialization;
- **consumers keep only repo-specific rules** (e.g. this repo's `refactor-wp-alt-context` / `refactor-description-service` deltas), not a private copy of the general lexicon or a hand-patched copy of overlay internals.

---

## Part A — Refactoring lens: ship it, wire it, enforce it

Audit of the shipped skills (this consumer, 2026-06-28) found the lens **applied only partially and enforced only by local overlay edits**. Each item below is general → belongs in the payload.

### A1. Adopt the engineering-heuristics lexicon into the payload

`engineering-heuristics.md` (attached) is a general `Trigger | Rule | Answers` lexicon for the eight distilled books. It currently lives **untracked + gitignored** at the consumer's `docs/workbay/rules/engineering-heuristics.md`, is **absent from the upstream payload**, and is the sole backing for the review lens. On any re-materialization it vanishes and review silently reverts to the design-thin canonical guide (canonical `branch-review-guide` carries only partial Fowler smells, no resilience/latency/idempotency lens).

- **Ship** `engineering-heuristics.md` in `workbay-system/payload/docs/workbay/rules/`.
- **Wire** the canonical `branch-review-guide.md` and `planning-review-guide.md` to deep-link its anchors (the consumer-local guide extensions — coupling-type triage, ports&adapters, steady-state, schema-evolution, p99/fan-out, CQS, YAGNI gate — should become the upstream default).
- **Interim guard (also useful upstream):** a `make check-*` assertion that the guides still reference `engineering-heuristics.md`, so the wiring can't silently rot.
- *Concept:* **single source of truth** (Farley) — one lexicon, referenced not copied. The lexicon currently exposes section-level anchors only; add per-rule `{#slug}` anchors when adopting.

### A2. Materialize and cross-reference the `refactor` skill

The upstream `refactor` skill (`payload/skills/refactor/body.md`, full Fowler/Beck smell catalog + characterization-tests-before-move) **is not materialized** in **any** effective harness tree (claude/codex/cursor/grok) here — it is absent from `.workbay/generated/plugins/workbay-system/effective/claude/skills/` — and **no** implementation/review skill links to it. A junior reaches it only by explicitly typing "refactor".

- **(a)** Confirm *why* `refactor` is filtered out of every harness tree here, and ensure it materializes into every harness's effective skill tree.
- **(b)** Add `See Also → refactor` + a **red-flag re-entry** to `incremental-implementation` and `branch-review`: *"diff is growing a second responsibility → stop, run `refactor`."*
- *Concept:* discoverability of the rubric from the flow a junior actually runs.

### A3. Produce-first shaping gate in `incremental-implementation`

Generation skills (`tdd`, `incremental-implementation`, `scope`) nudge *cadence* + NFR intake but never make smell-**avoidance** a produce-first gate, so god-class / long-function / data-clump / primitive-obsession shaping is left to catch-at-review — exactly the downstream-refactoring cost we want to remove.

- Add a 3–4 line "produce-first shape" cue to the `incremental-implementation` effective patch: cohesion / SoC **"and"-test** (a description containing "and" is two responsibilities), ≤~400-line / ≤3-nesting budgets, **Extract on the second responsibility**, **strategy-map over enum switch**, **outcome enum over deceptive boolean** — each deep-linking `engineering-heuristics.md#refactoring--design`.
- *Concept:* **Two Hats** + shape-as-you-build (Fowler/Beck Ch2-3).

### A4. Design pass in `plan-analyze`

`plan-analyze` triage has 7 passes (duplication / ambiguity / underspec / constitution / coverage / terminology / impl-grounding) and **no** complexity / coupling / cohesion / failure-mode pass, so a plan that bakes in a god-class or unbounded-result design passes triage untouched.

- Add an 8th pass — **design-quality & failure-mode grounding** — spot-checking the plan against the lexicon (coupling-type triage, ports&adapters, steady-state reclaimer, consistency model, unbounded-result, complexity budget), mirroring the wiring already in `planning-review-guide.md`, and recording findings with `review_mode="planning"`.
- *Concept:* catch bad architecture at the **cheapest** stage (before code).

### A5. `review-parallel` reviewer prompt must cite the lens

`review-parallel` is pure coordination and guarantees no rubric of its own; reviewers apply the design rubric only if the reviewer prompt routes them to it. The default `reviewer_prompt_template` should explicitly cite the `branch-review-guide` design sections + `engineering-heuristics` anchors.

---

## Part B — A sturdier install / materialize / cleanup mechanism

### B0. Evidence (what this consumer was left in)

| # | Observed state | Root cause |
|---|---|---|
| 1 | Package-mode ledger (`.workbay-bootstrap.json`, `source_kind=package`, **no `remote_sha`**) but **clone-mode symlinks** — symlinks **within** `scripts/hooks`, `.github/hooks`, `Makefile.d/*`, `scripts/workstate/*` resolve into `.workstate/remote/…workstate-system…`; **`.workbay/remote` does not exist** | mode switch / rename did not **repoint** symlinks |
| 2 | `.workstate/` (≈200 MB old clone) cannot be removed — the live hooks resolve through it; no command to repoint+reclaim | no **cleanup/gc** path |
| 3 | Effective plugin tree **stale** — predates the override-dir rename; `refactor` + the two repo skills not materialized | install did not re-run `plugins-build` after state change |
| 4 | The review lens (`engineering-heuristics.md` + guide extensions) is **untracked, local-only** — lost on re-materialization | **no sanctioned consumer-enrichment overlay for rules/guides** (only skills have one) |
| 5 | `.gitignore`/`Makefile` carried stale **`WORKSTATE_BOOTSTRAP`** sentinels (hand-fixed in `7a222195`) while the installer greps **`WORKBAY_BOOTSTRAP`** — an un-migrated install would orphan/duplicate the block | rename didn't migrate the **managed-block contract** |
| 6 | Vendored validators **mode-blind** — `overlay_resolver` is keyed on `remote_sha` + hardcodes `.workstate/remote`; `check_harness_sync` also hardcodes `.workstate/remote`; both fail/degrade under package-mode | validators not part of the versioned, mode-aware surface |
| 7 | 11 generic skills + 14 generic templates left **tracked duplicates** in the consumer | install leaves an ambiguous tracked-vs-overlay boundary |
| 8 | Editing a `mode:patch` base file desynced the `overrides.lock.json` digest with **no regen command** surfaced | digest maintenance is manual |

### B1. Idempotent, convergent materialization

`workbay-bootstrap install` must be a **pure function of the ledger** — re-running from *any* partial state converges to the fully-materialized state: (re)point every symlink to the current remote/package home, (re)write every managed block, rebuild the effective plugin tree, never duplicate a managed block or leave a dangling symlink.

- *Concept:* **idempotency** (`#resilience--failure-modes`, Kleppmann Ch11) — install is the canonical "apply twice = apply once".

### B2. Atomic mode-switch / rename = expand → migrate → contract

A mode change (clone→package) or rename (`workstate`→`workbay`) must not leave two truths on disk. Treat it as a schema migration:

- **Expand:** materialize the new home (`.workbay/remote` or package path) and the new managed-block sentinels **alongside** the old.
- **Migrate:** repoint **all** symlinks (`scripts/hooks`, `.github/hooks`, `Makefile.d`, `scripts/<tool>`), rewrite vendored path constants, regenerate the effective tree.
- **Contract:** remove the old clone/sentinels/symlinks **only after** verifying nothing live resolves through them.
- *Concept:* **expand→migrate→contract** (`#data--consistency`) — keep N and N+1 working across the cutover; never strand the consumer mid-migration (as happened here).

### B3. A consumer-enrichment overlay for rules & guides (the durable fix for B0#4)

Extend the existing **skills** override model (`mode: add` / `mode: patch`) to **rules and guides**, so a consumer can add `engineering-heuristics`-style lexicon or extend a guide **without local edits that re-materialization clobbers**. General content ships in the payload; consumer-specific deltas live in a tracked `*-overrides/<plugin>/rules/…` surface and compose deterministically.

- *Concept:* **single source of truth + ports&adapters** (`#refactoring--design`) — the consumer extends through a sanctioned seam, not by mutating upstream-owned materialized files.

### B4. Mode-aware, fail-fast validators

`check_harness_sync` / `overlay_resolver` and the materialization itself must understand **both** clone-mode and package-mode ledgers (no `remote_sha` in package mode is valid, not an error), and must **fail loudly with an actionable message** when the overlay is half-materialized (symlink target missing, sentinel drift, stale effective tree) instead of silently degrading.

- *Concept:* **fail fast** (Nygard §5.5) + **validate at load** — a half-materialized overlay is a detectable, named failure, not a silent fallback.

### B5. Reversible cleanup / `gc`

Provide `workbay-bootstrap clean` (or `gc`) that **safely** reclaims orphaned overlay state — old clones (`.workstate/remote`), dangling symlinks, superseded generated trees, vestigial tracked duplicate skills/templates — **only after** confirming no live symlink/validator resolves through them, printing what it will remove first.

- *Concept:* **steady-state reclaimer** (`#resilience--failure-modes`) — anything install accretes needs a same-rate reclaim path; cleanup must be confirm-then-act, never a blind `rm -rf` of a load-bearing clone.

### B6. Unambiguous tracked-vs-overlay boundary

Install should not leave generic upstream artifacts as **tracked consumer duplicates** (the 11 skills / 14 templates here), and repo-specific files should not be **force-tracked under a gitignored overlay dir** (the `docs/workbay/contracts|rules` co-location here is fragile: a new consumer file is silently ignored). Define and validate one boundary: overlay-delivered = gitignored; consumer-owned = a tracked, non-ignored path (e.g. `local/…`).

- *Concept:* **leaky abstraction** (`#refactoring--design`) — don't blend two ownership domains in one regenerated directory.

### B7. Digest maintenance is a command, not a manual step

When a `mode:patch` base legitimately changes (e.g. a rename sweep), surface `workbay-bootstrap overrides-relock` to recompute `overrides.lock.json` digests, rather than requiring the consumer to hand-edit the lock (as was needed here).

### B8. Hoist (or repoint) the shared workflow-generator scripts *(folded from migration §F)*

The migration install (commit `1fcac802`) deleted `scripts/generate_agent_workflows.py`, `scripts/check_workflow_facade.py`, and `scripts/validate_claude_settings_pin.py` from the consumer root but did not symlink them back, leaving canonical `Makefile.d/workflows.mk` (which resolves the generator relative to the consumer root) broken. Fixed locally by symlinking the three scripts into `scripts/` → `.workbay/remote/packages/workbay-system/scripts/`.

- **Ask:** `workbay-bootstrap` should materialize these shared scripts and track them in `.workbay-bootstrap.json` `surfaces` exactly like the `Makefile.d/*.mk` and `scripts/hooks` symlinks it already manages, so future installs need no consumer-side repair. (This is the **interim materialization** ask; Part D2's de-hoist is the end-state where the package owns them as modules/CLIs — keep both, B8 is the convergent-install behavior that must hold regardless.)
- *Maps to:* B0#3 (stale tree after state change) + B1 (idempotent materialization includes these surfaces).

### B9. Shared Git hooks must resolve guards relative to the hook directory *(folded from migration §G)*

`scripts/hooks` is an ignored symlink to the canonical `workbay-system` surface. Its `git/post-checkout` hook resolves guard helpers through `GUARD_DIR`, but `git/pre-push`, `git/post-merge`, `git/post-rewrite`, `git/post-commit`, and `git/pre-commit` still resolve helpers via `$REPO_ROOT/scripts/hooks/...`. That misses in nested-source or hoisted-consumer layouts where the git root is not the shared hook source.

- **Ask:** update canonical `workbay-system/scripts/hooks/git/*` to use the same `HOOK_DIR` / `GUARD_DIR` pattern as `post-checkout`.

### B10. Stop-hook adapter must not require absolute consumer paths *(folded from migration §H)*

`workbay-bootstrap==0.7.3 doctor --target .` reports `hook_adapter_drift: .claude/settings.json` when the repo keeps the managed Claude Stop hook portable as `python3 "$CLAUDE_PROJECT_DIR/scripts/hooks/compact-session.py"`. Running repair would rewrite the checked-in adapter to an absolute consumer-root command (`/Users/.../scripts/hooks/compact-session.py`), conflicting with the no-user-local-path policy and making committed settings non-portable.

- **Ask:** change the canonical compact-session adapter declaration to an environment-/workspace-relative command, and teach `doctor`/`repair` to accept that portable form. (Pairs with Part C's hook wiring.)

### B11. Linked git worktrees must inherit the overlay *(folded from migration §J)*

`workbay-bootstrap install` materializes the gitignored overlay (`.workbay/`, `.claude-plugin/`, `Makefile.d`, `scripts/workstate`, `scripts/hooks`, …) once in the primary worktree. **Linked git worktrees** (`git worktree add`, and Claude Code's auto-worktrees under `.claude/worktrees/<name>/`) share `.git` but **not** gitignored files, so they start with the overlay absent. Only tracked files survive — e.g. `.claude/settings.json` keeps `enabledPlugins: workbay-system@…=true`, so the plugin is *enabled but unresolvable* → zero skills load and `make` targets fail (missing `Makefile.d`). Today each worktree is repaired by hand.

- **Ask (capability):** a worktree-aware materialization path — `workbay-bootstrap adopt-worktree --target <wt>` (or making `install`/`repair` detect a linked worktree) that **symlinks the shared + generated surfaces to the primary worktree's already-materialized overlay** rather than re-cloning per worktree (`.task-state/` stays per-worktree). The surface list already lives in the ledger, so only the package can do this without a consumer hardcoding overlay-internal paths.
- **Ask (trigger):** git has no native post-worktree-add hook and Claude Code auto-worktrees are harness-created, so the robust catch-all is a **session-start self-heal**: `make context` / `.claude/settings.json` `SessionStart` runs `workbay-bootstrap doctor` + auto-repair, made worktree-aware so it fixes every entry path (`git worktree add`, `make task-start`, auto-worktree) identically. For the `make task-start` path, shared `lifecycle.mk` can call the adopt step directly.
- **Consumer-template note:** if upstream chooses symlink materialization, the `.gitignore` template must use **slashless** patterns (`/.workstate`, `/.claude-plugin`) — a dir-only pattern (`.workbay/`) does **not** match a symlink (git treats it as a file), so the symlink shows up untracked.
- *Maps to:* B1 (convergent install) + B4 (fail-loud when overlay absent).

---

## Part C — Semantic compaction reinjection: deliver it, don't just ship it

The handoff package **fully implements** semantic compaction reinjection. Design intent (confirmed in `mcp-workbay-handoff`):

- The Stop hook fires after every **50 000 new tokens** since the last compaction (`DEFAULT_MIN_NEW_TOKENS = 50_000` in `workbay_handoff_mcp.compaction`).
- At compaction, the new-turn anchor text is **embedded** into `session_compactions.anchor_vector` via `embed_compaction_anchor_on_write()`.
- At the next SessionStart, `reinject-context.py` + `build_semantic_reinjection_packet()` **reinject semantically-ranked concepts** by local-ONNX cosine-similarity + MMR dedup, with `ReinjectionConfig` controlling top-K (default 8), min score (0.35), MMR weight (0.7), snippet budget (1 500 chars). Off by default; byte-identical when off / model absent / `embeddings` extra missing; **never hits the network**.

**None of it is active in this consumer** — the architecture is shipped but not *delivered*. The same materialization mechanism (Part B) should close the gaps below.

### C1. Provision the embedding model artifact idempotently *(folds migration §M Gap 1)*

`EmbeddingProvider.from_env()` reads four env vars that point to provisioned file paths:

```
WORKBAY_HANDOFF_EMBEDDING_MODEL=<path-to-onnx-model>
WORKBAY_HANDOFF_EMBEDDING_TOKENIZER=<path-to-tokenizer>
WORKBAY_HANDOFF_EMBEDDING_MODEL_SHA256=<hex-digest>
WORKBAY_HANDOFF_EMBEDDING_TOKENIZER_SHA256=<hex-digest>
```

`workbay-bootstrap install` never writes these, so the provider always returns `None` and reinjection silently degrades.

- **Ask 1 — provision (default-active):** install should download **the package's pinned model** — `Alibaba-NLP/gte-base-en-v1.5`, int8 ONNX, 768-d, ~147 MB (the download **MUST** match the package's `model_id` and embedding dimension) — **verify SHA256** against the pinned digest, and write the four `WORKBAY_HANDOFF_EMBEDDING_*` env vars into a harness-owned surface (`.workbay/embedding.env` sourced by the hook launcher, or injected into `.claude/settings.json` `env:`).
- **Ask 2 — opt-out:** provide `workbay-bootstrap install --no-embeddings` or `WORKBAY_HANDOFF_EMBEDDINGS_DISABLED=1`. Feature defaults to **active** (download + wire on first install) but remains fully optional.
- **Ask 3 — repair:** `workbay-bootstrap repair` detects absent/mismatched artifacts and re-downloads, using the same idempotent repair logic as other managed surfaces.
- **Ask 4 — preserve degrade:** the model-absent path (provider=None → non-semantic reinjection, no error) is correct and must be preserved.
- *Concept:* **verify-then-trust + idempotent repair** — pinned digest, converges on re-run; **fail fast** on digest mismatch instead of degrading silently.

### C2. Wire the SessionStart reinject hook *and* the Stop hook (the read/write pair) *(folds migration §L items 2 & 5, §M Gap 2)*

`reinject-context.py` (SessionStart) is on disk but **no `SessionStart` entry** is written, and the `compact-session.py` (Stop) hook was likewise left unwired after the rename — the consumer had to add the Stop entry by hand. These two hooks are the read/write pair of the compaction system and neither is useful without the other.

- **Ask:** `workbay-bootstrap install` / `repair` should wire **both** in the managed `.claude/settings.json` surface — `compact-session.py` under `Stop`, `reinject-context.py` under `SessionStart` — alongside the existing `PreToolUse`/`PostToolUse` entries, and **idempotently re-add** either if absent on `repair`. This is the same hook-wiring the improved materializer (B2) already owns; the adapter command must use the portable form from B10.

### C3. A supported activation path + observable delivery state *(folds migration §M Gap 3)*

Semantic mode is gated on `WORKBAY_REINJECT_SEMANTIC=1` (formerly `WORKSTATE_REINJECT_SEMANTIC=1`), which no install step sets, and no install-time prompt asks about it.

- **Ask 1 — activation:** once a provider resolves (C1), set semantic mode **on by default**; otherwise emit a one-time post-install advisory naming the env var to enable it.
- **Ask 2 — observability:** `workbay-bootstrap doctor` must **report the delivery state** — hook wired? `embeddings` extra installed? model present + digest-valid? `anchor_vector` backfilled? semantic enabled? — so the operator sees *why* reinjection is or isn't active.
- *Concept:* **fail-loud observability** (Nygard) — the silent degrade path is correct behavior, but the operator must be able to *see* it, not guess.

### C4. Migrate the hooks' names + ship the contract patterns so the wiring survives re-sync *(folds migration §L items 1, 3, 4)*

Both hooks still carry pre-rename identifiers that the consumer sed-patched locally — and those patches revert on the next materialization:

- `reinject-context.py` imports `workstate_handoff_mcp` (12 occurrences) and reads `WORKSTATE_REINJECT_*` env-var names; `compact-session.py` imported `workstate_handoff_mcp` (18 occurrences).
- **Ask 1:** complete the `workstate_handoff_mcp`→`workbay_handoff_mcp` rename and the `WORKSTATE_REINJECT_*`→`WORKBAY_REINJECT_*` rename **in the payload** for both hooks, and audit the tunables table in `harness-protocol.yaml` for the env-var rename, so the hooks are correct as-shipped (ties into Part B's "consumer must not hand-patch overlay-owned files"). The install/repair cycle should **verify the package is importable** before declaring success.
- **Ask 2 — `permitted_main_surfaces` gap:** `.claude/settings.json` and `.claude/settings.hooks.json` were not listed as `permitted_main_surfaces` in `docs/workbay/contracts/harness-protocol.yaml`, so the main-branch guard (BR-21) blocked operator-config edits under a valid `MAINT-*` task whenever unrelated code files were dirty. The canonical `harness-protocol.yaml` template should ship these two patterns **pre-populated** so a fresh install doesn't hit this block on first operator-config edit.

### C5. Clarify the 50k trigger: session-end gate vs. mid-session interval *(folds migration §M "Clarification needed")*

The current Stop hook fires **once** at session end, then checks if 50k+ new tokens accumulated — a threshold gate, not a periodic mid-session trigger. If the intent is to compact at 50k-token intervals **within** a session (compact+reinject every time context grows by 50k), that requires a `UserPromptSubmit` / `PreToolUse` hook counting running token usage and triggering `compact_session()` mid-turn.

- **Ask:** clarify whether the 50k gate is intended as session-end-only (current behaviour) or a continuous within-session interval trigger, and implement the mid-session path if the latter is intended.

---

## Part D — Greenfield posture: no legacy fallback, fail fast, de-hoist the overlay tooling

This is a **greenfield** consumer (no production data, no legacy installs to migrate). Two consequences for the overlay surface:

### D1. No legacy clone fallback — fail fast

The repo resolves **only** the canonical `.workbay/remote` overlay home and **fails fast** (loud, actionable: "run `workbay-bootstrap install`") when absent — never silently degrading onto a stale `.workstate/remote` clone. The consumer centralizes this in one seam (`scripts/_overlay_clone.py`, single source of truth — no overlay path hardcoded across scripts).

- **Ask:** the bootstrap should drop the legacy `.workstate-overlay.json` overlay *mode* entirely for greenfield consumers (dead code once a canonical ledger exists) and ship the hoisted tooling **workstate-free**.

### D2. De-hoist the general overlay tooling (repo↔workbay boundary)

`overlay_resolver.py`, `check_harness_sync.py`, `generate_agent_workflows.py`, `apply_cursor_skills_only_surface.py`, `check_skills.py`, `lint_hoisted_paths.py` are **general agent-harness tooling hoisted into the consumer** (E17-10) — not repo-specific, yet the consumer carries, patches, and must keep them workstate-free (the source of residual `.workstate-overlay.json` / payload-name references and brittle path coupling).

- **Ask:** workbay should own these as **package-provided** modules/CLIs (or expose the overlay home from the install ledger) so consumers neither hoist nor hand-patch them. The consumer then keeps only repo-specific config + the thin `_overlay_clone` seam — and that seam disappears once the package exposes the home. (B8's materialization is the interim; this de-hoist is the end-state.)
- *Concept:* **Ports & Adapters + single source of truth** (Farley) — the repo depends on a workbay *port*, not on hoisted copies of workbay internals; **remove dead code** (the legacy mode) for the greenfield case.

### D3. Cross-harness portability

Overlay resolution is harness-agnostic (the clone is shared across Claude/Codex/Cursor/Grok); the `_overlay_clone` seam resolves identically for every harness, and the produced effective trees are per-harness. Any de-hoisted package surface must preserve this (one resolution, N harness trees).

---

## Part E — Lifecycle / handoff-CLI / lane / MCP-pin / close-check gaps

These asks span `Makefile.d` lifecycle fragments, the `mcp-workbay-handoff` / `mcp-workbay-orchestrator` CLIs, and the close-check gate. They do not fit A–D but are upstream-owned and a consumer cannot fix them from its own checkout (Plugin Boundary Rule).

### E1. `maint-start` / `maint-archive-stale` have no canonical lifecycle equivalent *(migration §A)*

Canonical `Makefile.d/lifecycle.mk` + `scripts/workstate/lifecycle` CLI has `task-start` (MODE=here creates a branch in the current repo) but **no path to register a `MAINT-*` row against the repo root with no feature branch / no linked worktree**, and **no stale-MAINT garbage-collector**. This repo's `make maint-start` (`scripts/maint-start.sh` + `scripts/_maint_start_inline.py`) and `make maint-archive-stale` (`scripts/maint_archive_stale.py`) were kept and repointed to `workbay_handoff_mcp` because the CLAUDE.md startup protocol requires them.

- **Ask:** canonical lifecycle should absorb a `maint-start` / `maint-archive-stale` surface (or `task-start --no-branch` + `tasks-gc`).

### E2. Handoff CLI dropped the lane-data verbs (now MCP-tool-only) *(migration §B)*

`mcp-workbay-handoff` 0.12.0 dropped CLI subcommands the lane workflow depends on: `lane-upsert`, `lane-message`, `lane-message-list`, `lane-message-update`, `lane-report`, `lane-report-list`. They now exist only as orchestrator **MCP tools** (`manage_worktree_lane`, `lane_communication`, `worker_reports`). `make` / bash cannot invoke MCP tools, so these consumer targets execute dropped verbs and **fail at runtime**: `make lane-dispatch` (`mk/lane-lifecycle.mk`), `make lane-inbox`, `make lane-intake` (`mk/lane-maintenance.mk`), and `scripts/worktree-lane` upsert/report/message ops. The orchestrator CLI's `dispatch` subcommand is a partial replacement for `lane-upsert` only.

- **Ask:** either expose the lane-data verbs on the `mcp-workbay-orchestrator` CLI, or reimplement the lane workflow against the MCP tools upstream in `workbay-system`.

### E3. Handoff CLI redesigned verbs (consumer recipes left at old flag-shapes) *(migration §C)*

These verbs were redesigned, not dropped — direct equivalents with different invocation shapes: `test` → `event` (`event_kind=test_result`), `blocker` → `event` (`event_kind=blocker`), `artifact-search` → `artifacts`, `handoff-close-check` → `integrity-check --kind close`. The consumer lane recipes (`mk/lane-worker.mk` `lane-check`; `mk/lane-maintenance.mk` `lane-intake`) were left calling old shapes pending an upstream decision on whether the lane workflow is reworked in `workbay-system` rather than this consumer.

- **Ask:** decide where the lane workflow lives and migrate these recipes to the redesigned verb shapes upstream (or document the canonical shapes for consumers to adopt).

### E4. Canonical `lifecycle.mk` `tasks-gc` calls a non-existent subcommand *(migration §D)*

`Makefile.d/lifecycle.mk` defines `tasks-gc: @mcp-workbay-handoff tasks-gc`, but `tasks-gc` is not a `mcp-workbay-handoff` subcommand (the gc path is `archive --operation gc` / a `tasks` operation).

- **Ask:** fix the canonical fragment to call the real subcommand (coordinate with E1's `tasks-gc` proposal so the name is real and consistent).

### E5. Canonical `check-agent-workflows` drops the codex router-block check *(migration §E)*

Canonical `Makefile.d/workflows.mk` `check-agent-workflows` runs the generator `--check` + facade + settings-pin checks but **not** `--check-codex-router-blocks`. This consumer keeps a repo-local `check-codex-command-router` target and added it to `check-all` to preserve coverage.

- **Ask:** canonical `check-agent-workflows` should include the codex router-block validation (the generator already supports the flag).

### E6. MCP pin source-of-truth: overlay-manifest drift + generation cutover *(migration §I; coordinate with E17-15)*

The MCP runtime version (`mcp-workbay-handoff`, `mcp-workbay-orchestrator`) is hand-fanned across ~14 consumer references (`.mcp.json`, `.vscode/mcp.json`, `.codex/config.toml`, `Makefile`, CI, docs/doc-tests) — a single-source-of-truth violation that already produced live drift twice. Two halves split by ownership:

- **Consumer-side (done here, for context):** `scripts/check_mcp_pins.py` + `make check-mcp-pins` (wired into `check-all`); canonical = the Makefile `MCP_*_PACKAGE` pins; every editable current-pin reference must match (frozen ADR/spec/task records exempt).
- **Ask 1 (upstream):** the overlay `config/agent-workflows/mcp_servers.yaml` (symlink into `.workbay/remote/`, `source: shared` from `workbay-system`) is in lockstep only by hand — keep its manifest pins in lockstep with the consumer live-config pins, ideally **derive/check one from the other in the shared generator**.
- **Ask 2 (downstream, E17-15 in `agentic-protocol-monorepo`):** per ADR-010 / E17-15 the live harness configs remain the pin source of truth and emitted plugin manifests *preserve* them. The plugin generator (`scripts/generate_agent_workflows.py`) + live-config↔plugin-manifest parity belong to E17-15's downstream implementation. Do **not** build a second live-config generation path in the consumer — it would duplicate and invert E17-15's decided model.

### E7. Close-check gate validates recorded evidence but never RUNS verification commands *(migration §K)*

`handoff_close_check` / `integrity-check --kind close` (`workbay_handoff_mcp/decisions.py`) enforces that `test_result` evidence exists and is tied to the current HEAD SHA, but it **never executes** lint/typecheck/test — it trusts recorded evidence. A broken tree can therefore merge if evidence was recorded green while the working tree is red (observed: E15-26's `DashboardPage.test.tsx` with 25 crashing tests merged to main and was only caught when a later integration ran `make check`). "Run the checks" is repo-specific, so the capability must be config-driven, not hardcoded upstream.

- **Ask:** add a generic capability for the close-check to **RUN one or more consumer-configured verification commands (fail-closed on non-zero exit)** before it passes — e.g. a runtime-config `close_check.required_commands: ["make check-all"]` — so the gate verifies the working tree rather than only trusting recorded evidence.
- **Consumer mitigation (context):** a local `make pre-merge` (= `make check-all`) run by habit before the close-check. This does **not** close the bypass — it is not enforced by the gate.

---

## Acceptance criteria

1. `engineering-heuristics.md` ships in the payload; canonical `branch-review-guide` / `planning-review-guide` deep-link it; a fresh consumer's review lens is the full 8-book rubric with **no local untracked files** required.
2. `refactor` materializes in every harness tree and is cross-referenced from `incremental-implementation` + `branch-review`.
3. `incremental-implementation` carries a produce-first shaping gate; `plan-analyze` carries a design/failure-mode pass; `review-parallel`'s default reviewer prompt cites the lens.
4. `workbay-bootstrap install` is idempotent and convergent from any partial state (characterization test: corrupt each B0 symptom, install, assert converged) — including the hoisted generator scripts (B8) and linked-worktree overlay (B11).
5. A mode-switch/rename leaves **zero** orphaned clone/symlink/sentinel; `clean`/`gc` reclaims safely with a dry-run.
6. Validators pass under **both** ledger modes and fail loudly on a half-materialized overlay.
7. A consumer can add a rules/guide enrichment that **survives re-materialization**.
8. Semantic reinjection is **one bootstrap step from active**: model provisioned (digest-verified), SessionStart reinject + Stop compact hooks wired, toggle documented, `doctor` reports delivery state; the silent degrade path is preserved **and** observable; both hooks ship with `workbay`-correct package + env-var names; `permitted_main_surfaces` ships pre-populated; the 50k-trigger semantics are documented.
9. The consumer resolves the overlay through a **single seam** with **no scattered hardcoded paths** and **no `.workstate` literal in repo-specific code**; resolution is canonical-only + fail-fast (no legacy clone fallback); the general overlay tooling is **package-provided (de-hoisted)** and ships workstate-free; resolution stays cross-harness (one resolution, N harness trees).
10. **Lifecycle:** a canonical `maint-start` / `maint-archive-stale` (or `task-start --no-branch` + `tasks-gc`) surface exists, and `lifecycle.mk` `tasks-gc` calls a real subcommand.
11. **Lane / CLI:** the lane-data verbs are invokable from `make`/bash (CLI re-exposed or workflow reworked upstream), and the redesigned verb shapes (`event`/`artifacts`/`integrity-check`) are the documented canonical path.
12. **Workflows:** canonical `check-agent-workflows` includes the codex router-block check.
13. **MCP pins:** the overlay `mcp_servers.yaml` pins and the live-config pins are kept in lockstep by a shared generator/check (one derived from the other); no second live-config generation path in the consumer.
14. **Close-check:** the gate can run consumer-configured verification commands and **fails closed** on non-zero exit before passing.
15. **Portable hooks/surfaces:** the Stop-hook adapter is environment-/workspace-relative (B10) and accepted by doctor/repair; shared git hooks resolve guards via `HOOK_DIR`/`GUARD_DIR` (B9).

## Test posture (apply the concepts to the mechanism)

- **Characterization tests** (Fowler Ch4) capturing on-disk state before/after install, mode-switch, rename, and cleanup — the migration must be verifiably behavior-preserving.
- **Idempotency test** — install∘install == install on every B0 partial state.
- **Fail-fast tests** — each half-materialized state yields a named, actionable error, not a silent pass (this consumer's `check-skills` reported `OK (0 skills)` on a broken overlay — a false green).
- **Hook-delivery tests** — fresh install wires both compaction hooks with workbay-correct names; `doctor` reports each delivery dimension; close-check fails closed when a configured verification command exits non-zero.

## Appendix

- `engineering-heuristics.md` — the general lexicon to adopt upstream (attached, this bundle). The lens anchors referenced throughout (`#resilience--failure-modes`, `#data--consistency`, `#refactoring--design`) deep-link into it.
- Consumer-side audit + half-materialized symptoms: folded into **Part B (B0 evidence table)** and the **Consumer current state** section above (these were previously in the now-retired consumer migration upstream-asks doc).

## Excluded (consumer record — intentionally omitted, not upstream-implementable)

The following items from the source docs describe **consumer-side state**, not upstream work, and are deliberately not carried as asks (distilled into "Consumer current state" only):

- **"Resolved during this migration"** — the orchestrator `importlib.util` `AttributeError` fixed by upgrading 0.4.7 → 0.5.0 (already resolved; no action).
- **"Hand-completion status — `MAINT-workbay-migration-cleanup-20260628`"** and its **"Installer-gated remainder"** list — the by-hand renames, ledger/sentinel swaps, vestigial-duplicate removals, keep-until-cutover `.workstate`-path references, `guard-main-branch.sh` overlay-symlink note, `branch-review` SKILL digest-lock note, `codex-subagent-bridge` `uv.lock` dependency bump, and tracked-template offload — all consumer execution state. The *upstream-owned* root causes behind them are captured in Parts B/C/D/E above; the consumer bookkeeping itself is not an upstream ask.
