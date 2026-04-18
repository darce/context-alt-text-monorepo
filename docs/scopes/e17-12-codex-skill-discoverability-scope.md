# E17-12. Codex harness $-skill discoverability — scope note

- **Date**: 2026-04-18
- **Task ref**: E17-12
- **Source**: [packages/agent-handoff-mcp/docs/assessments/codex-harness-slash-tools-and-skill-discovery-investigation-2026-04-18.md](../../packages/agent-handoff-mcp/docs/assessments/codex-harness-slash-tools-and-skill-discovery-investigation-2026-04-18.md)
- **Intake decision**: `e17-12_scope_intake_codex_skill_discoverability` (handoff ledger id 1963)

## Problem

The merged E17-4 / E17-7 portable-workflow work delivered manifest + generated adapters + instruction-text router, but did not wire the Codex harness into repo-local skill discovery. As a result `$branch-review` does not resolve in Codex even though `.claude/skills/branch-review/` exists, and `/branch-review` is only recognized when the model reads the router prose in `docs/agentic/instructions.md` or `CLAUDE.md`.

The assessment offers three options: (A) correct the docs and accept instruction-only routing, (B) add real Codex skill-root registration, (C) declare UI-level parity impossible from the repo.

## MVP Scope

Land the smallest repo-committed change that makes `$-prefix` skills under `.claude/skills/` resolve in the Codex harness for **any fresh clone**, without per-user config mutation or changes to the Codex product itself.

Work is structured as three slices:

1. **Discovery (time-boxed).** Probe the live Codex app-server for the skill-root registration surface actually available to repo-committed config: `skills/list`, `skills/config/write`, `perCwdExtraUserRoots`, and any project-level skill-root declaration. Output: a decision record that chooses between slice 2 and slice 3.
2. **Implementation (conditional on slice 1).** If slice 1 confirms a repo-only path exists, ship the smallest registration artifact — generated from `config/agent-workflows/portable_commands.json` — that registers `.claude/skills/` as a skill root for the Codex harness on a fresh clone. No handwritten Codex command/prompt files; manifest remains the single source.
3. **Docs reconciliation.** Update `docs/tasks/17.0/E17-4-workflow-integrity-task-plan.md`, `docs/tasks/17.0/E17-7-handoff-evolution-and-portable-workflow-task-plan.md`, and `docs/agentic/instructions.md` so shipped claims match shipped behavior. If slice 1 shows a repo-only path exists, document it. If it does not, explicitly retire the UI-level parity claim and describe Codex routing as instruction-level only. Runs regardless of slice 2's branch.

## Success Criteria

- `$branch-review` (and at least one other portable skill) resolves in the Codex harness against the repo-local `.claude/skills/` directory without per-user Codex config edits.
- `docs/tasks/17.0/E17-4-*`, `docs/tasks/17.0/E17-7-*`, and `docs/agentic/instructions.md` accurately describe Codex parity — no overstated "UI-level discoverability" claims.
- `config/agent-workflows/portable_commands.json` remains the only registry; any Codex-side artifact that ships is generated from it (`scripts/generate_agent_workflows.py`), not handwritten.
- `make check-agent-workflows` continues to verify Claude, VS Code/Copilot, and Codex outputs together.

## Assumptions

- Codex exposes a skill-root registration surface usable from repo-committed config (evidence: the checked-in protocol fixture at `packages/codex-subagent-bridge/tests/fixtures/codex_app_server_protocol.v2.schemas.json` describes `skills/list`, `skills/config/write`, `perCwdExtraUserRoots`, and `SkillsChangedNotification`). The live behavior must still be confirmed in slice 1.
- The repo's Codex surface continues to live under `.codex/` (currently `config.toml` + `hooks.json`); any new generated artifact will land there or alongside it.
- `agent-handoff-mcp` and `agent-orchestrator-mcp` MCP wiring under `.codex/config.toml` is orthogonal to skill discovery and remains untouched.

## Not-Doing

- **No Codex product patches.** All changes live in this monorepo.
- **No mutation of per-user machine config** (`~/.codex/`, global user profile) as part of normal workflow. Bootstrap steps, if any, must be repo-committed and reproducible.
- **No expansion to other harnesses.** Cursor, Zed, JetBrains, etc. stay out of scope; Claude and VS Code/Copilot parity is already shipped.
- **No re-architecture of `portable_commands.json`.** Schema stays as-is.
- **No native slash-command UI parity (`/branch-review` as a Codex chip).** Only `$-prefix` skill resolution is pursued; if the discovery slice shows slash-UI parity is also free, it can be evaluated separately but is not a success criterion here.
- **No truth-in-advertising-only outcome.** Docs reconciliation must either describe shipped behavior that closes the gap or explicitly retire the gap-closing promise — not merely soften existing claims.

## Next Step

Draft the E17-12 task plan in `docs/tasks/17.0/E17-12-codex-skill-discoverability-task-plan.md` on `main`, sequenced as Discovery → Implementation (conditional) → Docs Reconciliation. Planning-review runs before any feature branch is created.
