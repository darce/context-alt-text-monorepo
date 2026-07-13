# Upstream request — split `.workbay-bootstrap.json` into tracked pins vs machine-local install journal

**Target repo:** `agentic-protocol-monorepo` / `darce/workbay` (`workbay-bootstrap` installer, manifest schema).
**Consumer:** `context-alt-text-monorepo` (package-mode install).
**Affected release:** `workbay-v0.3.18` — `workbay-bootstrap==0.3.14` (monorepo tag `v0.1.46`), schema_version 2.
**Discovered while:** a pre-merge close-check flagged the root worktree dirty on `.workbay-bootstrap.json` after a routine `workbay install` — no pin had changed.

## Summary

`.workbay-bootstrap.json` mixes two things with opposite lifecycles:

1. **Pins / declared intent** — `schema_version`, `source_kind`, `package_version`, `stack_distribution`, `stack_version`, `stack_members`, `profile`, `surfaces`. Lockfile semantics: must be tracked, changes only on upgrade, makes installs reproducible on any checkout [TEST-08 determinism].
2. **Execution journal** — per-run action entries recording what the installer did on *this machine, this run*: `{"path": ".gitignore", "action": "already_present"}`, `{"path": ".claude/settings.local.json", "action": "merged", "kind": "hook_adapter", ...}`, `core.hooksPath` set-actions, etc.

Because (2) lives inside the tracked file, **every mechanical install/re-install run dirties the ledger even when nothing about the declared stack changed**. The consumer then either commits ritual churn ("chore: ledger sync" with zero semantic content), carries permanent dirt that trips working-tree integrity gates (our pre-merge close-check rejects it), or allowlists the ledger — which defeats the point of tracking it.

Heuristics (verified against `heuristics-canon` `lexicons/engineering.md`, fetched 2026-07-13):

- **[ARCH-05]** volatile shared asset ripples to every consumer — a tracked file mutated by every install run puts the highest-churn artifact in the system into every consumer's git history and every reviewer's diff.
- **[RES-07]** anything that accumulates needs same-rate reclaim — the actions array is an append-style log wearing a config file's clothes; logs belong in a purgeable stream, not in a lockfile.
- **[TEST-08]** determinism — the pins half *earns* its commit precisely because it makes installs reproducible; burying it under journal noise degrades the signal "did the pinned stack actually change?".

## Observed evidence (v0.1.46 consumer)

After `workbay install` on a clean v0.1.46 checkout, `git diff .workbay-bootstrap.json` shows **only** journal entries — no pin change:

```diff
+    {
+      "path": ".gitignore",
+      "action": "already_present"
+    },
+    {
+      "path": ".claude/settings.local.json",
+      "action": "merged",
+      "kind": "hook_adapter",
+      "opt_in_flag": "--install-claude-reinject-hook-local"
+    },
```

This dirt then blocked an unrelated feature branch's pre-merge `integrity_check(kind="close")` (`working_tree_integrity` violation), forcing an operator disposition for pure installer bookkeeping.

## Requested change

Split the manifest at the schema level:

1. **`.workbay-bootstrap.json` (tracked)** keeps only pins + surfaces (declared intent). Idempotent re-install of the same stack version leaves it byte-identical. A dirty ledger then *means* version/surface drift — a reviewable event.
2. **Per-run action journal moves to a machine-local, gitignored stream** — e.g. `.workbay/install-log.jsonl` (append one JSON object per action, per run, with timestamp + package_version). `.workbay/` is already gitignored in consumers, and the journal keeps full auditability (better, actually: today's format overwrites rather than accumulates history).
3. `doctor` / `verify` read the journal from the new location; migration shim tolerates legacy inline `actions` for one minor version.

## Acceptance sketch

- `workbay install` twice at the same pin → `git status` clean after the second run (and after the first, on an already-installed tree).
- Upgrading the stack pin → exactly the pins/surfaces diff in the tracked ledger, action detail in the journal.
- `workbay doctor` surfaces the last install run's actions from `.workbay/install-log.jsonl`.

## Workaround in the meantime

Consumers commit the journal churn as standalone chores to keep close-check gates clean (this repo, 2026-07-13), which pollutes history but preserves gate integrity.
