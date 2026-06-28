# Upstream request — refactoring-lens enforcement + a sturdier overlay install/materialize/cleanup mechanism

> **For:** `agentic-protocol-monorepo` (canonical `workbay-system` / `workbay-bootstrap`).
> **From:** `context-alt-text-monorepo` (consumer), `MAINT-workbay-migration-cleanup-20260628`.
> **Why:** two findings from completing the `workstate`→`workbay` migration here. (1) The distilled
> engineering literature is enforced only by **local, untracked, consumer-side** state that any
> re-sync silently drops; (2) the install/materialize/cleanup mechanism left this consumer in a
> **half-materialized** state that no single command can converge or clean. Both should be fixed
> where they are owned — upstream — so every consumer inherits a sturdy, enforceable surface and
> only repo-specific rules remain local.

The design below is written **applying the distilled concepts themselves** (idempotency,
fail-fast, single-source-of-truth, expand→migrate→contract, characterization tests). Anchors like
`#data--consistency` deep-link the attached `engineering-heuristics.md`.

---

## Goal

Move the **general** engineering-discipline surface (smell catalog, resilience/latency/data lens,
produce-first gates) into **sturdy, enforceable, upstream-shipped** workbay skills + hooks, so that:

- a **junior agent** implementing a plan is *guided to produce well-factored code on the first
  draft* (less downstream refactoring), and review *enforces* it;
- the lens **survives** clone / CI / overlay re-materialization;
- **consumers keep only repo-specific rules** (e.g. this repo's `refactor-wp-alt-context` /
  `refactor-description-service` deltas), not a private copy of the general lexicon.

---

## Part A — Refactoring lens: ship it, wire it, enforce it

Audit of the shipped skills (this consumer, 2026-06-28) found the lens **applied only partially and
enforced only by local overlay edits**. Each item below is general → belongs in the payload.

### A1. Adopt the engineering-heuristics lexicon into the payload

`engineering-heuristics.md` (attached) is a general `Trigger | Rule | Answers` lexicon for the eight
distilled books. It currently lives **untracked + gitignored** at the consumer's
`docs/workbay/rules/engineering-heuristics.md`, is **absent from the upstream payload**, and is the
sole backing for the review lens. On any re-materialization it vanishes and review silently reverts
to the design-thin canonical guide.

- **Ship** `engineering-heuristics.md` in `workbay-system/payload/docs/workbay/rules/`.
- **Wire** the canonical `branch-review-guide.md` and `planning-review-guide.md` to deep-link its
  anchors (the consumer-local guide extensions — coupling-type triage, ports&adapters,
  steady-state, schema-evolution, p99/fan-out, CQS, YAGNI gate — should become the upstream
  default; canonical guides today carry only partial Fowler smells).
- *Concept:* **single source of truth** (Farley) — one lexicon, referenced not copied. (The lexicon
  currently exposes section-level anchors only; add per-rule `{#slug}` anchors when adopting.)

### A2. Materialize and cross-reference the `refactor` skill

The upstream `refactor` skill (`payload/skills/refactor/body.md`, full Fowler smell catalog +
characterization-tests-before-move) **is not materialized** in **any** effective harness tree
(claude/codex/cursor/grok), and **no** implementation/review skill links to it. A junior reaches it
only by explicitly typing "refactor".

- Ensure `refactor` materializes into every harness's effective skill tree (confirm why it is
  filtered out of every harness tree here).
- Add `See Also → refactor` + a **red-flag re-entry** to `incremental-implementation` and
  `branch-review`: *"diff is growing a second responsibility → stop, run `refactor`."*
- *Concept:* discoverability of the rubric from the flow a junior actually runs.

### A3. Produce-first shaping gate in `incremental-implementation`

Generation skills (`tdd`, `incremental-implementation`, `scope`) nudge *cadence* + NFR intake but
never make smell-**avoidance** a produce-first gate, so god-class / long-function / data-clump
shaping is left to catch-at-review — exactly the downstream-refactoring cost we want to remove.

- Add a 3–4 line "produce-first shape" cue: cohesion / SoC **"and"-test** (a description containing
  "and" is two responsibilities), ≤~400-line / ≤3-nesting budgets, **Extract on the second
  responsibility**, **strategy-map over enum switch**, **outcome enum over deceptive boolean** — each
  deep-linking `engineering-heuristics.md#refactoring--design`.
- *Concept:* **Two Hats** + shape-as-you-build (Fowler/Beck Ch2-3).

### A4. Design pass in `plan-analyze`

`plan-analyze` triage has 7 passes (duplication / ambiguity / underspec / constitution / coverage /
terminology / impl-grounding) and **no** complexity / coupling / cohesion / failure-mode pass, so a
plan that bakes in a god-class or unbounded-result design passes triage untouched.

- Add an 8th pass — **design-quality & failure-mode grounding** — spot-checking the plan against the
  lexicon (coupling-type triage, ports&adapters, steady-state reclaimer, consistency model,
  unbounded-result, complexity budget) and recording findings with `review_mode="planning"`.
- *Concept:* catch bad architecture at the **cheapest** stage (before code).

### A5. `review-parallel` reviewer prompt must cite the lens

`review-parallel` is pure coordination; reviewers apply the design rubric only if the reviewer
prompt routes them to it. The default `reviewer_prompt_template` should explicitly cite the
`branch-review-guide` design sections + `engineering-heuristics` anchors.

---

## Part B — A sturdier install / materialize / cleanup mechanism

### B0. Evidence (what this consumer was left in)

| # | Observed state | Root cause |
|---|---|---|
| 1 | Package-mode ledger (`.workbay-bootstrap.json`, `source_kind=package`, **no `remote_sha`**) but **clone-mode symlinks** — symlinks **within** `scripts/hooks`, `.github/hooks`, `Makefile.d/*`, `scripts/workstate/*` resolve into `.workstate/remote/…workstate-system…`; **`.workbay/remote` does not exist** | mode switch / rename did not **repoint** symlinks |
| 2 | `.workstate/` (≈200 MB old clone) cannot be removed — the live hooks resolve through it; no command to repoint+reclaim | no **cleanup/gc** path |
| 3 | Effective plugin tree **stale** — predates the override-dir rename; `refactor` + the two repo skills not materialized | install did not re-run `plugins-build` after state change |
| 4 | The review lens (`engineering-heuristics.md` + guide extensions) is **untracked, local-only** — lost on re-materialization | **no sanctioned consumer-enrichment overlay for rules/guides** (only skills have one) |
| 5 | `.gitignore`/`Makefile` carried stale **`WORKSTATE_BOOTSTRAP`** sentinels (hand-fixed here in `7a222195`) while the installer greps **`WORKBAY_BOOTSTRAP`** — an un-migrated install would orphan/duplicate the block | rename didn't migrate the **managed-block contract** |
| 6 | Vendored validators **mode-blind** — `overlay_resolver` is keyed on `remote_sha` + hardcodes `.workstate/remote`; `check_harness_sync` also hardcodes `.workstate/remote`; both fail/degrade under package-mode | validators not part of the versioned, mode-aware surface |
| 7 | 11 generic skills + 14 generic templates left **tracked duplicates** in the consumer | install leaves an ambiguous tracked-vs-overlay boundary |
| 8 | Editing a `mode:patch` base file desynced the `overrides.lock.json` digest with **no regen command** surfaced | digest maintenance is manual |

### B1. Idempotent, convergent materialization

`workbay-bootstrap install` must be a **pure function of the ledger** — re-running from *any*
partial state converges to the fully-materialized state: (re)point every symlink to the current
remote/package home, (re)write every managed block, rebuild the effective plugin tree, never
duplicate a managed block or leave a dangling symlink.

- *Concept:* **idempotency** (`#resilience--failure-modes`, Kleppmann Ch11) — install is the canonical
  "apply twice = apply once".

### B2. Atomic mode-switch / rename = expand → migrate → contract

A mode change (clone→package) or rename (`workstate`→`workbay`) must not leave two truths on disk.
Treat it as a schema migration:

- **Expand:** materialize the new home (`.workbay/remote` or package path) and the new managed-block
  sentinels **alongside** the old.
- **Migrate:** repoint **all** symlinks (`scripts/hooks`, `.github/hooks`, `Makefile.d`,
  `scripts/<tool>`), rewrite vendored path constants, regenerate the effective tree.
- **Contract:** remove the old clone/sentinels/symlinks **only after** verifying nothing live
  resolves through them.
- *Concept:* **expand→migrate→contract** (`#data--consistency`) — keep N and N+1 working across
  the cutover; never strand the consumer mid-migration (as happened here).

### B3. A consumer-enrichment overlay for rules & guides (the durable fix for B0#4)

Extend the existing **skills** override model (`mode: add` / `mode: patch`) to **rules and guides**,
so a consumer can add `engineering-heuristics`-style lexicon or extend a guide **without local edits
that re-materialization clobbers**. General content ships in the payload; consumer-specific deltas
live in a tracked `*-overrides/<plugin>/rules/…` surface and compose deterministically.

- *Concept:* **single source of truth + ports&adapters** (`#refactoring--design`) — the consumer extends
  through a sanctioned seam, not by mutating upstream-owned materialized files.

### B4. Mode-aware, fail-fast validators

`check_harness_sync` / `overlay_resolver` and the materialization itself must understand **both**
clone-mode and package-mode ledgers (no `remote_sha` in package mode is valid, not an error), and
must **fail loudly with an actionable message** when the overlay is half-materialized (symlink
target missing, sentinel drift, stale effective tree) instead of silently degrading.

- *Concept:* **fail fast** (Nygard §5.5) + **validate at load** — a half-materialized overlay is
  a detectable, named failure, not a silent fallback.

### B5. Reversible cleanup / `gc`

Provide `workbay-bootstrap clean` (or `gc`) that **safely** reclaims orphaned overlay state — old
clones (`.workstate/remote`), dangling symlinks, superseded generated trees, vestigial tracked
duplicate skills/templates — **only after** confirming no live symlink/validator resolves through
them, printing what it will remove first.

- *Concept:* **steady-state reclaimer** (`#resilience--failure-modes`) — anything install accretes needs a
  same-rate reclaim path; **bugs are survived, not eliminated** so cleanup must be confirm-then-act,
  never a blind `rm -rf` of a load-bearing clone.

### B6. Unambiguous tracked-vs-overlay boundary

Install should not leave generic upstream artifacts as **tracked consumer duplicates** (the 11
skills / 14 templates here), and repo-specific files should not be **force-tracked under a
gitignored overlay dir** (the `docs/workbay/contracts|rules` co-location here is fragile: a new
consumer file is silently ignored). Define and validate one boundary: overlay-delivered =
gitignored; consumer-owned = a tracked, non-ignored path (e.g. `local/…`).

- *Concept:* **leaky abstraction** (`#refactoring--design`) — don't blend two ownership domains in one
  regenerated directory.

### B7. Digest maintenance is a command, not a manual step

When a `mode:patch` base legitimately changes (e.g. a rename sweep), surface
`workbay-bootstrap overrides-relock` to recompute `overrides.lock.json` digests, rather than
requiring the consumer to hand-edit the lock (as was needed here).

---

## Part C — Semantic compaction reinjection: deliver it, don't just ship it

The handoff package **fully implements** semantic compaction reinjection — after a 50k-token
compaction the SessionStart `reinject-context.py` hook re-surfaces handoff concepts ranked by
**local-ONNX embedding** cosine-similarity + MMR dedup (top-K via
`build_semantic_reinjection_packet()` / `ReinjectionConfig`; off by default, byte-identical when
off / model absent / `embeddings` extra missing; **never hits the network**). **None of it is
active in this consumer**: the architecture is shipped but not *delivered*. The same
materialization mechanism (Part B) should close the three install-side gaps (detail in
`workstate-migration-upstream-asks.md` § M).

### C1. Provision the embedding model artifact idempotently

`EmbeddingProvider.from_env()` reads `WORKBAY_HANDOFF_EMBEDDING_{MODEL,TOKENIZER,…_SHA256}` paths
that `workbay-bootstrap install` never writes, so the provider always returns `None` and
reinjection silently degrades. Install (default-active, `--no-embeddings` opt-out) should download
**the package's pinned model** (`Alibaba-NLP/gte-base-en-v1.5`, int8 ONNX, 768-d, ~147 MB — the
download MUST match the package's `model_id` and embedding dimension), **verify SHA256**, and write the env
vars into a harness-owned surface (`.workbay/embedding.env` or `.claude/settings.json env:`);
`repair` re-downloads on absence/mismatch.
- *Concept:* **verify-then-trust + idempotent repair** — pinned digest, converges on re-run; **fail
  fast** on digest mismatch instead of degrading silently.

### C2. Wire the SessionStart reinject hook

`reinject-context.py` is on disk but **no `SessionStart` entry** is written, so the hook never
fires. Install/repair should wire it alongside the Stop hook (`compact-session.py`) — the same
hook-wiring the improved materializer (B2) already owns.

### C3. A supported activation path + observable delivery state

Semantic mode is gated on `WORKBAY_REINJECT_SEMANTIC=1`, which no install step sets. Provide a
first-class toggle (default-on when a provider resolves, else a one-time post-install advisory), and
have `workbay-bootstrap doctor` **report the delivery state** — hook wired? `embeddings` extra
installed? model present + digest-valid? `anchor_vector` backfilled? semantic enabled? — so the
operator sees *why* reinjection is or isn't active.
- *Concept:* **fail-loud observability** (Nygard) — the silent degrade path is correct behavior, but
  the operator must be able to *see* it, not guess.

### C4. Migrate the hook's names so the wiring survives re-sync

`reinject-context.py` still reads `WORKSTATE_REINJECT_*` env-var names (its import was already
locally sed-patched to `workbay_handoff_mcp`, and that patch reverts on the next materialization).
Complete the rename in the **payload** so the hook is correct as-shipped (ties into Part B's
"consumer must not hand-patch overlay-owned files").

---

## Part D — Greenfield posture: no legacy fallback, fail fast, de-hoist the overlay tooling

This is a **greenfield** consumer (no production data, no legacy installs to migrate). Two
consequences for the overlay surface:

### D1. No legacy clone fallback — fail fast

The repo resolves **only** the canonical `.workbay/remote` overlay home and **fails fast** (loud,
actionable: "run `workbay-bootstrap install`") when it is absent — never silently degrading onto a
stale `.workstate/remote` clone. The consumer now centralizes this in one seam
(`scripts/_overlay_clone.py`, single source of truth — no overlay path hardcoded across scripts).
**Ask:** the bootstrap should drop the legacy `.workstate-overlay.json` overlay *mode* entirely for
greenfield consumers (dead code once a canonical ledger exists) and ship the hoisted tooling
**workstate-free**.

### D2. De-hoist the general overlay tooling (repo↔workbay boundary)

`overlay_resolver.py`, `check_harness_sync.py`, `generate_agent_workflows.py`,
`apply_cursor_skills_only_surface.py`, `check_skills.py`, `lint_hoisted_paths.py` are **general
agent-harness tooling hoisted into the consumer** (E17-10) — not repo-specific, yet the consumer
carries, patches, and must keep them workstate-free (the source of the residual
`.workstate-overlay.json` / payload-name references and the brittle path coupling). **Ask:** workbay
should own these as **package-provided** modules/CLIs (or expose the overlay home from the install
ledger) so consumers neither hoist nor hand-patch them. The consumer then keeps only repo-specific
config + the thin `_overlay_clone` seam — and that seam disappears once the package exposes the home.

- *Concept:* **Ports & Adapters + single source of truth** (Farley) — the repo depends on a workbay
  *port*, not on hoisted copies of workbay internals; **remove dead code** (the legacy mode) for the
  greenfield case.

### D3. Cross-harness portability

Overlay resolution is harness-agnostic (the clone is shared across Claude/Codex/Cursor/Grok); the
`_overlay_clone` seam resolves identically for every harness, and the produced effective trees are
per-harness. Any de-hoisted package surface must preserve this (one resolution, N harness trees).

---

## Acceptance criteria

1. `engineering-heuristics.md` ships in the payload; canonical `branch-review-guide` /
   `planning-review-guide` deep-link it; a fresh consumer's review lens is the full 8-book rubric
   with **no local untracked files** required.
2. `refactor` materializes in every harness tree and is cross-referenced from
   `incremental-implementation` + `branch-review`.
3. `incremental-implementation` carries a produce-first shaping gate; `plan-analyze` carries a
   design/failure-mode pass.
4. `workbay-bootstrap install` is idempotent and convergent from any partial state
   (characterization test: corrupt each B0 symptom, install, assert converged).
5. A mode-switch/rename leaves **zero** orphaned clone/symlink/sentinel; `clean`/`gc` reclaims
   safely with a dry-run.
6. Validators pass under **both** ledger modes and fail loudly on a half-materialized overlay.
7. A consumer can add a rules/guide enrichment that **survives re-materialization**.
8. Semantic reinjection is **one bootstrap step from active**: model provisioned (digest-verified),
   SessionStart hook wired, toggle documented, `doctor` reports delivery state; the silent degrade
   path is preserved **and** observable; the reinject hook ships with `workbay`-correct names.
9. The consumer resolves the overlay through a **single seam** with **no scattered hardcoded paths**
   and **no `.workstate` literal in repo-specific code**; resolution is canonical-only + fail-fast
   (no legacy clone fallback); the general overlay tooling is **package-provided (de-hoisted)** and
   ships workstate-free; resolution stays cross-harness (one resolution, N harness trees).

## Test posture (apply the concepts to the mechanism)

- **Characterization tests** (Fowler Ch4) capturing on-disk state before/after install, mode-switch,
  rename, and cleanup — the migration must be verifiably behavior-preserving.
- **Idempotency test** — install∘install == install on every B0 partial state.
- **Fail-fast tests** — each half-materialized state yields a named, actionable error, not a silent
  pass (this consumer's `check-skills` reported `OK (0 skills)` on a broken overlay — a false green).

## Appendix

- `engineering-heuristics.md` — the general lexicon to adopt upstream (attached, this bundle).
- Consumer-side audit + the half-materialized symptoms: `docs/workbay/workstate-migration-upstream-asks.md`
  (§ "Refactoring-lens enforcement gaps" + § "Hand-completion status / installer-gated remainder").
