# Upstream request — clean install silently reverts local surface edits, and three install paths have no recovery

**Filed:** 2026-08-04
**Consumer:** `context-alt-text-monorepo`
**Versions:** `workbay` 0.3.31, `workbay-bootstrap` 0.3.22, `workbay-system` 0.3.21,
`mcp-workbay-handoff` 0.2.16, `mcp-workbay-orchestrator` 0.2.16, `workbay-protocol` 0.2.3
**Discovered during:** a deliberate clean reinstall (`--source package --profile all
--with-remote --with-embeddings`) onto an existing v0.3.21 overlay
**Outcome:** install eventually succeeded, after three aborted attempts and one silent
regression that `doctor` did not detect

Each defect below is graded against the engineering/security heuristics canon
(`heuristics-canon`, v0.19.0). Rule text is quoted verbatim so the request can be
checked without the canon to hand.

---

## 1. A reinstall silently reverts local edits to regenerated surfaces, and `doctor` reports "no drift" — HIGH

**Symptom.** The consumer's `.codex/hooks.json` carried a hand-applied fix on 15
commands, wrapping each guard invocation so it anchors to the repo root:

```sh
sh -c 'root="$(git rev-parse --show-toplevel …)"; …'
```

instead of the generated bare relative form:

```sh
python3 scripts/hooks/_run_guard.py …
```

(That patch exists because of the still-open request
`2026-07-29-codex-hook-cwd-anchor-and-worktree-blindness`.)

The reinstall reverted all 15 commands to the bare form. No warning, no receipt
entry, no prompt. `workbay doctor` then exited 0 with **no drift detected** —
correctly, from workbay's point of view: the regenerated file is exactly what
workbay expects.

**Why it is asymmetric and therefore surprising.** In the same install,
`.codex/config.toml` **survived** its local edits, because that surface is
*merged*. `.codex/hooks.json` is *regenerated whole*. Both are listed in the
ledger's `surfaces` array with the same `source` classification, so nothing on the
consumer side distinguishes "your edits survive here" from "your edits are
destroyed here" until after the fact.

**Canon.**

- **RLSE-05** (`engineering.md:678`) — trigger: *failure path leaves the user
  believing success*. **"Silent failure is the worst failure**: a crash is honest;
  silent data loss is a trust violation, P0 by definition." Check: *"Can data
  appear saved here while not durable?"* Here the inverse: can committed local
  work disappear while every status surface reads green? It can.
- **API-11** (`engineering.md:501`) — **"Must Ignore, round-trip whole**: ignore
  unknown fields on read but preserve them on write; stripping destroys other
  services' data through you." Check: *"Does this write path preserve fields this
  service doesn't understand?"* The hooks generator does not.
- **RES-17** (`engineering.md:128`) — **"Write-ahead of intent before in-place
  mutation**: before overwriting persistent structures, write a note in a
  well-known log describing what you will do." Check: *"Where is the durable intent
  recorded before in-place structures change, and can recovery find it?"* Nowhere —
  the pre-image is not retained.
- **Reasoning card CARD-07 `fail-loudly-succeed-quietly`** — mechanism claim:
  *"Design the success and failure channels so failure is impossible to miss and
  success is impossible to confuse with noise."* `doctor`'s green is exactly the
  "silence reads as health" trigger the card names.
- **Reasoning card CARD-12 `perceived-enforced-boundaries`** — mechanism claim: *"A
  grouping the surface implies but the system does not enforce is a lie the user
  (or operator) believes."* The ledger's uniform `surfaces` list implies one
  contract; two are enforced. This is also **Principle 10** (perceived boundaries
  must match enforced boundaries).
- **AGT-16** (`engineering.md:86`) — **"Confirm only when refusal is plausible** …
  prefer an undoable operation when recovery is cheap, and reserve confirmation for
  actions that can destroy data or resist reversal." Overwriting a hand-edited
  hooks file *is* the destructive case that earns a prompt or a refusal.

**Requests.**

1. Before regenerating any whole-file surface, diff the on-disk file against the
   pre-image workbay last wrote (record a content hash per surface in the ledger at
   write time). If they differ, **refuse by default** and name the file, with
   `--force-regenerate-surfaces` to override. This is the RES-17 write-ahead and the
   AGT-16 confirmation in one step.
2. When the overwrite does proceed, write the pre-image to
   `.workbay/backups/<iso>/<surface-path>` and record its location in the install
   receipt, so the revert is recoverable without a consumer-side backup ritual.
3. Make the merge-vs-regenerate distinction **declared and visible**: add a
   `write_mode: merge | regenerate` field per surface entry in
   `.workbay-bootstrap.json`, and print it in `workbay status`. Today the consumer
   can only learn it by losing work.
4. Teach `doctor` a drift facet that compares each regenerated surface against its
   recorded pre-image hash, so "workbay overwrote your edits" is reportable at all.
   A doctor that cannot see this class of change is, per CARD-07, a sensor that
   stays quiet when broken.

---

## 2. `--with-embeddings` hard-fails on a runtime tool the `package` source path never provisions — HIGH

> **This is a recurrence, not a new finding.** The same root cause —
> `_resolve_gitonly_member_specs` has no `package` branch, so package-mode installs
> never reach the gitonly tool install — was diagnosed on 2026-07-05 and tracked
> upstream as `WB-BOOTSTRAP-PKGMODE-BRIDGE-GAP-01` on task
> `MAINT-crash-codexbridge-daemon-20260705` (assessment:
> `agentic-protocol-monorepo/docs/assessments/orchestration-crash-codex-bridge-daemon-removal-2026-07-05.md`).
> That resolution predicted verbatim: *"a fresh package-mode install will reproduce
> the gap until that lands."* It did, 30 days later. Only the casualty changed —
> then the `workbay-codex-bridge` dependency, now the `[embeddings]` extra. The gap
> is generic to the step, so every future consumer of it is a new symptom.
> **This section is a severity escalation on an existing finding, not a new request.**

**Symptom.** Install aborted at exit 2:

```
embeddings runtime-verify failed: the mcp-workbay-handoff uv-tool interpreter
cannot import the embeddings stack (ModuleNotFoundError: No module named 'numpy').
Repair: re-run `workbay install --target <T> --with-embeddings` (R1 attaches the
[embeddings] extra to the runtime tool), or reinstall `mcp-workbay-handoff[embeddings]`
via `uv tool install`
```

The first repair branch is the exact command that just failed — re-running it loops.

**Cause.** The step that attaches the extra is `_install_gitonly_mcp_tools`
(`install.py:963`), which is reached only when
`_resolve_gitonly_member_specs` (`install.py:933`) returns member specs. For
`source_kind == "package"` that function requires either a release-tag
`--remote-ref` **and** a remote URL, or a vendored clone at
`<target>/<CLONE_SUBDIR>/packages/mcp-workbay-handoff/pyproject.toml`. With neither
it returns `None`, and `install_plan.py:476` records:

```python
receipt.deferred("gitonly_mcp_tools", reason="no_resolvable_member_specs")
```

A **deferred** step — not a failure, not surfaced to the operator. Three steps
later, `_verify_embeddings_runtime` (`install.py:3056`) hard-verifies the tool that
step would have installed, and fails closed. So `--with-embeddings` promises to
provision a runtime the plan silently declined to provision.

**Canon.**

- **AGT-10** (`engineering.md:80`) — trigger: *except-and-continue with no durable
  record*. **"Degrade loudly**: a swallowed error that keeps the session alive must
  still land in a log." Check: *"If this failure matters next week, where is it
  written?"* The deferral is written to a receipt no operator reads, and the
  failure it causes points elsewhere.
- **AGT-21** (`engineering.md:91`) — **"Exit status is the outcome contract**:
  return 0 for success and distinct nonzero codes for the failure reasons." Check:
  *"Can a caller branch on this outcome without parsing message text?"*
- **REF-20** (`engineering.md:335`) — **"Define errors out of existence**:
  respecify so the case is normal behavior; most catastrophic distributed failures
  are error-handling bugs." Check: *"Can the spec make this a successful no-op or
  clamped result?"* Yes — provision the tool instead of verifying and refusing.
- **SECD-05** (`security.md:255`) — trigger names **"Installer defaults"**
  explicitly. **"Fail-safe defaults**: default deny and degrade to a documented safe
  state." Failing closed is right; failing closed on a precondition the installer
  itself declined to establish is not.

**Requests.**

1. If `--with-embeddings` is requested and the runtime tool cannot be resolved for
   provisioning, **fail at plan time with that reason**, not at verify time with a
   downstream import error. Preconditions belong in preflight.
2. Better: make the `package` source path provision the runtime tool from the same
   resolved package specs the rest of the install uses, so the extra is attached
   regardless of `source_kind`.
3. Promote `receipt.deferred("gitonly_mcp_tools", …)` to a **printed warning** when
   `embeddings_mode == "verified"` — a deferral that invalidates a requested flag is
   not best-effort.
4. Drop the self-referential first repair branch, or gate it on the case where
   re-running actually would attach the extra.

---

## 3. Deleting `.workbay-bootstrap.json` is an unrecoverable state — HIGH

**Symptom.** A genuine from-scratch install (ledger removed, generated surfaces
removed) aborts:

```
workbay_handoff_mcp.state_init.ForeignStateReuseError: Refusing to reuse
pre-existing handoff state without an adjacent .workbay-bootstrap.json /
.workbay-overlay.json manifest. Re-run init-state with --force-reuse-state to
accept this existing DB.
```

**Cause.** The refusal itself is correct and well-designed. The problem is that
`--force-reuse-state` exists on the handoff server's `init-state`
(`state_init.py:49,84`) but `workbay install` has **no passthrough**:
`_run_init_state` (`install.py:3437`) builds the argv and appends `init-state`
with no way for the operator to add the flag. The named remedy is unreachable from
the surface that hit the error. There is no `--reset-state` either. The only exit is
to restore a ledger the operator was told to delete — which we had to do, meaning
the "clean" install was not clean.

**Canon.**

- **SECD-08** (`security.md:258`) — **"Make the safe path the easy path**: design so
  the least-effort and high-stress actions are the safe ones (psychological
  acceptability), because dialog fatigue and baroque controls train bypass." Check:
  *"Under time pressure, what will a competent user actually do?"* Delete
  `.task-state/` — the destructive option, because it is the only reachable one.
- **REF-20** (`engineering.md:335`) — *"Can the spec make this a successful no-op or
  clamped result?"*
- **AGT-08** (`engineering.md:79`) — **"Rejection is specification**: satisfy the
  named requirement or escalate with evidence; never vary cosmetically, never
  bypass." A rejection that names a requirement the caller structurally cannot
  satisfy inverts this rule.

**Requests.**

1. Add `workbay install --force-reuse-state`, passed through to `init-state`. The
   remedy an error names must be reachable from the surface that raised it.
2. Add `workbay install --reset-state` (archive `.task-state/` to
   `.task-state.bak-<iso>/`, then init fresh) so "start over" has a supported,
   non-destructive path.
3. Rewrite the message to name the flag on the surface the operator is holding
   (`workbay install --force-reuse-state`), not the internal subcommand.
4. Document in `CONSUMER.md` that the ledger is **not** safe to delete for a clean
   install — it is load-bearing state, not a cache.

---

## 4. `--target` is not cwd-independent — MEDIUM

**Symptom.** Run from an unrelated repo with an explicit `--target`:

```
FileNotFoundError: plugin override manifest not found:
  /Users/daniel/Development/heuristics-canon-research/workbay-overrides/workbay-system/overrides.yaml
```

A relative `--plugin-overrides` resolved against the **caller's** cwd, not
`--target`. Separately, `init-state` shells out through `git rev-parse
--show-toplevel`, which resolves the **caller's** repository, so the step fails or
targets the wrong root even with `--target` correct.

**Canon.**

- **AGT-20** (`engineering.md:90`) — trigger: *tool … resolves sources so a global
  setting beats a local one*. **"Config precedence follows preference lifetime**:
  read system file, then user dotfile, then environment, then command line, so later
  and more local settings override earlier and more global ones." Check: *"Does the
  most local, shortest-lived setting win?"* No — ambient cwd beats an explicit flag.
- **AGT-19** (`engineering.md:89`) — **"Don't configure what you can detect."** The
  target is already stated; nothing should re-detect it.

**Requests.**

1. Resolve every relative path argument against `--target`, not `os.getcwd()`.
2. Pass `cwd=target` to the `init-state` child (and any other `git rev-parse`
   caller), or pass `--workspace-root` in place of the rev-parse entirely.
3. Preflight: if `git rev-parse --show-toplevel` from the caller's cwd disagrees
   with `--target`, refuse with that comparison in the message.

*Related:* same root cause family as
`2026-07-29-codex-hook-cwd-anchor-and-worktree-blindness`, still unfixed in
`workbay-system` 0.3.21.

---

## 5. A failed install leaves partial state, with no rollback and no resume — MEDIUM

**Symptom.** Three consecutive aborts (§2, §3, §4) each left the target partially
written — plugin trees materialized, ledger rewritten or absent, surfaces half
regenerated. Recovery was manual: restore backups by hand, re-derive the original
flag set from the previous ledger, re-run.

**Canon.**

- **FLOW-01** (`engineering.md:259`) — **"Immutable inputs, new-dataset outputs**:
  prefer … writing a complete new output version with an atomic cutover; write in
  place only with idempotent keys and a re-run safety argument, because unguarded
  in-place mutation makes retries and re-runs corrupt the source."
- **RES-19** (`engineering.md:130`) — **"Recovery redo must be idempotent**: a crash
  can interrupt a checkpoint after durable intent but before completion." Check:
  *"If recovery runs twice on the same committed intent, is the store still
  correct?"*
- **RLSE-08** — **"Rollback written before ship."**
- **Reasoning card CARD-15 `reversible-commitments`** — required action 1: *"When
  options differ in reversibility, take the reversible side unless a written
  exemption says otherwise (Principle 3). Write rollback before ship, including data
  written by the new build."*
- **Reasoning card CARD-06 `evidence-before-commitment`** — *"Durable state …
  requires inspectable evidence before the commit, not after the harm"*; its scope
  explicitly covers *characterization before legacy edit*. Read the existing overlay
  before overwriting it.

**Requests.**

1. Stage the install into `.workbay/staging/<iso>/` and cut over atomically, so an
   abort leaves the previous overlay wholly intact.
2. Failing that, make abort paths restore the pre-install ledger and surfaces from
   the backup written in §1.2.
3. Make `workbay install` re-runnable from a partial state without operator
   archaeology: derive omitted flags from the existing ledger (`profile`,
   `execution_mode`, `embeddings_mode`, `plugin_overrides_path`, the Claude-local
   hook opt-ins) and print the effective flag set before executing. Today a bare
   re-run silently *downgrades* an overlay by dropping flags the previous install
   had.

---

## 6. Three install channels drift, with no system of record — MEDIUM

**Symptom.** On this machine the same stack existed at three versions
simultaneously:

| Channel | What installs it | State found |
|---|---|---|
| `workbay` uv tool | local package dirs in `agentic-protocol-monorepo` | 0.3.31 |
| `mcp-workbay-handoff` / `-orchestrator` uv tools | public tag `darce/workbay@v0.1.54` | 0.1.54, **no `[embeddings]` extra** |
| consumer `.venv` | `uv pip install` / `make provision-env` | 0.2.15, no numpy |

The consumer `.venv` is what `scripts/hooks/mcp_launch.py` actually executes, so it
is the copy that matters at runtime — and it was the stalest. The only signal was
`doctor`'s `reinject_readiness_unavailable` warning, which does not say "your three
channels disagree."

**Canon.**

- **DATA-14** (`engineering.md:200`) — **"No dual writes**: without a single order
  authority the copies diverge permanently and silently; derive the second from the
  first's change log." Check: *"Which system is the system of record?"* Undefined here.
- **REF-09** (`engineering.md:324`) — **"Mutable/derived-data drift**: stored value
  computable from other data can desync; compute on demand."
- **Reasoning card CARD-02 `correction-at-source`** — mechanism claim: *"A
  correction is real only when it updates the source of truth that recomputation
  will read; surface patches return after the next rebuild."* Required action 5:
  *"Treat mirrored fields and cubes as optimisations with freshness, not as
  sources."*

**Requests.**

1. Name one system of record for the stack version and derive the others. The
   ledger's `stack_members` map already has the right shape — make it authoritative
   rather than descriptive.
2. Add a `doctor` facet that compares `stack_members` against what is actually
   importable in (a) each uv tool env and (b) the consumer `.venv`, and reports the
   disagreement as drift.
3. Have `workbay install` update the consumer `.venv` as part of the install when
   `mcp_launch.py` shims are in the MCP config — it already knows the specs.

---

## Posture note

Three of the six defects are the same shape: **an installer that fails closed on a
precondition it declined to establish, or succeeds quietly over work it destroyed.**
The canon's framing for that is **SECD-05**, whose trigger literally names
*"Installer defaults"* — *"default deny and degrade to a **documented safe state** …
because the default is the configuration most deployments keep"* — and
**CARD-01 `contract-before-components`**, required action 5: *machine-facing
outcomes are schema, status, or named evidence, not prose.*

The single highest-leverage change is §1.1 + §1.3: **declare the write mode of each
managed surface and refuse to clobber a modified one.** It closes the silent-revert
class outright, and it makes the merge/regenerate asymmetry a contract instead of
folklore.

---

## Local state

Nothing was fixed locally beyond restoring `.codex/hooks.json` from a pre-install
byte backup. The workbay source tree was not modified. The consumer overlay is
currently at `workbay` 0.3.31 / `workbay-bootstrap` 0.3.22 / `workbay-system` 0.3.21
with all three channels unified onto local sources at 0.2.16; `doctor` exits 0.
