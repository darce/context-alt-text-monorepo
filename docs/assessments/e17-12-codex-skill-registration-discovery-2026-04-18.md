# E17-12 Slice 1 — Codex skill-registration discovery report

- **Date**: 2026-04-18
- **Task ref**: E17-12
- **Scope note**: [docs/scopes/e17-12-codex-skill-discoverability-scope.md](../scopes/e17-12-codex-skill-discoverability-scope.md)
- **Task plan**: [docs/tasks/17.0/E17-12-codex-skill-discoverability-task-plan.md](../tasks/17.0/E17-12-codex-skill-discoverability-task-plan.md)
- **Codex binary**: `/Applications/Codex.app/Contents/Resources/codex` (166 MB, macOS arm64, build reports userAgent `codex-subagent-bridge/0.116.0`)
- **Probe harness**: `packages/codex-subagent-bridge` `AppServerClient._request(method, params)` driving Codex over stdio JSON-RPC
- **Probe scripts** (not committed): `/tmp/e17-12-probe.py`, `/tmp/e17-12-probe2.py`, `/tmp/e17-12-probe3.py`, `/tmp/e17-12-probe4.py`
- **Verified commit**: `cdccf6a31ed94d6e9863bb5c052b9dc882bacc55` on `feature/e17-12`

## Outcome

**(a) Static declaration works.** Codex natively scans `<cwd>/.codex/skills/<skill-name>/SKILL.md` on every `skills/list` call and surfaces each entry with `scope: "repo"`. No per-call parameters, no session hooks, and no per-user config mutation are required. **Slice 2 proceeds** along the static-declaration branch; the implementation artifact is a set of repo-committed `SKILL.md` files (or symlinks back to `.claude/skills/`) under `.codex/skills/`, generated from `config/agent-workflows/portable_commands.json` by `scripts/generate_agent_workflows.py`.

Secondary finding: `perCwdExtraUserRoots` works (shape C only) but is per-call and ephemeral, so it cannot be used to influence the Codex harness's own internal `skills/list` dispatch from repo-committed config; it is useful only for in-process probes. `skills/config/write` toggles enabled-state for an already-discovered path but does not register new roots. There is no static config.toml / env-var surface for extra skill roots.

## Methodology

Four probe scripts drove a fresh `AppServerClient` against the packaged Codex binary with the repo cwd set to the E17-12 worktree, exercising the hypotheses laid out in the task plan (Slice 1 acceptance: "wire-level request/response for `skills/list` and `skills/config/write`" plus the three candidate paths).

1. **Probe 1** — Baseline `skills/list`; `perCwdExtraUserRoots` as map (hypothesis from fixture comment); `skills/config/write` on an in-repo SKILL.md path.
2. **Probe 2** — Retry `perCwdExtraUserRoots` with shape A (`[path]`), shape B (`[{cwd, roots}]`), shape C (`[{cwd, extraUserRoots}]`), shape D (top-level `extraUserRoots`).
3. **Probe 3** — Persistence test: after shape C succeeds, issue subsequent `skills/list` calls without the extra-roots param and after `skills/config/write`.
4. **Probe 4** — Project-scope test: create a temporary `<repo>/.codex/skills/probe-test/SKILL.md`, issue `skills/list` with no extra params, and observe the response scope for that path.

Static-surface sweep: `strings` against the Codex Mach-O binary for `skill_root`, `extra_user_root`, `skills_config`, `CODEX_SKILL*`, `skills.toml`, `project_skill*`, `add_skill_root`, `.claude/skills`.

## Findings

### Capabilities advertised at initialize

`initialize` response:
```
{
  "userAgent": "codex-subagent-bridge/0.116.0 (Mac OS 15.5.0; arm64) ...",
  "platformFamily": "unix",
  "platformOs": "macos"
}
```
The server returns `capabilities: null`. No skill-specific capability bit is advertised, so clients cannot negotiate feature availability from `initialize` alone.

### `skills/list` baseline (no extra roots)

Request: `{"cwds": ["<REPO>"], "forceReload": true}`. Response lists only user-scope (`~/.codex/skills`) and system-scope skills — `Excel`, `PowerPoint`, `commit2git`, `openai-docs`, `skill-creator`, `skill-installer`. The repo's `.claude/skills/` directory is not scanned by default.

### `perCwdExtraUserRoots` shape disambiguation

Four shapes tested:

| Shape | Payload | Result |
|---|---|---|
| Map `{cwd: [path]}` | `{"<REPO>": ["<.claude/skills>"]}` | Rejected: `-32600 invalid type: map, expected a sequence` |
| A: `[path]` | `["<.claude/skills>"]` | Rejected: `expected struct SkillsListExtraRootsForCwd` |
| B: `[{cwd, roots}]` | `[{cwd:"<REPO>", roots:["..."]}]` | Rejected: `missing field extraUserRoots` |
| **C: `[{cwd, extraUserRoots}]`** | `[{cwd:"<REPO>", extraUserRoots:["..."]}]` | **Accepted.** All 11 repo-local skills appear with `scope: "user"`. |
| D: top-level `extraUserRoots` | `{extraUserRoots:["..."]}` | Silently ignored (baseline response). |

Shape C is the only accepted form. All paths must be absolute (the binary string `"skills/list perCwdExtraUserRoots extraUserRoots paths must be absolute"` confirms the constraint).

### `perCwdExtraUserRoots` does NOT persist

Within a single session: issue shape C, receive the full repo skill list. Immediately issue `skills/list` again without `perCwdExtraUserRoots` — response collapses back to user+system only. `skills/config/write {enabled: true, path: "<.claude/skills dir>"}` returns `{effectiveEnabled: true}` but does not cause later `skills/list` calls to surface skills from that directory. `skills/config/write` is a per-path enabled-state toggle, not a root-registration primitive.

Consequence: an in-session probe that injects `perCwdExtraUserRoots` can only influence its own read. It cannot affect `skills/list` dispatches originating inside the Codex harness (TUI, app-server auto-invocations), so a `.codex/hooks.json` session-start hook that calls this RPC does nothing useful for the user-facing harness.

### Project-scoped `.codex/skills/` is natively scanned

Creating `<REPO>/.codex/skills/probe-test/SKILL.md` and issuing a plain `skills/list {cwds: [REPO], forceReload: true}` returns the new skill with `scope: "repo"` alongside the standard user + system entries. The directory was a fresh creation; no prior `skills/config/write` or registration call was made. Removing the directory and re-issuing `skills/list` drops it from the response.

This is the static-declaration path the scope note hypothesized (option (a)). It is repo-committed, it is reproducible across fresh clones, it requires no per-user config mutation, and it survives Codex restarts.

### Static config surface sweep

`strings` pass across the Codex binary yields:

- `perCwdExtraUserRoots`, `extraUserRoots`, `forceReload`, `SkillsListParams`, `SkillsListExtraRootsForCwd` — the `skills/list` parameter surface already covered above.
- `skills/config/write`, `SkillsConfigWriteParams` — the per-path toggle, not a root register.
- `skills/changed` — notification channel; not a write primitive.
- No `project_skill_root`, `skills.toml`, `skills_config`, `add_skill_root`, `CODEX_SKILL_ROOTS`, or comparable key exists in the binary.
- Adjacent and out of scope here: a whole `externalAgentConfig/detect|import` surface handles `~/.claude`, `CLAUDE.md`, `AGENTS.md`, settings.json — a first-run migration path from other agent harnesses into Codex home-scope. It mutates `~/.codex/` and is explicitly excluded by the scope Not-Doing list; flagged only for future reference.

## Decision

Adopt path **(a)**: ship `.codex/skills/<skill-name>/SKILL.md` entries as generated outputs of `scripts/generate_agent_workflows.py`, keyed off `config/agent-workflows/portable_commands.json`. Each generated `SKILL.md` either duplicates the canonical `.claude/skills/<skill>/SKILL.md` body or (preferable) is a symlink back to it so the manifest stays the only registry. `make check-agent-workflows` gains a Codex assertion that every entry in the manifest has a matching `.codex/skills/<slug>/SKILL.md`.

Slice 2 is in scope. Slice 3 docs reconciliation still runs, but it now documents shipped parity rather than retiring the gap-closing claim.

## Non-Goals Reconfirmed

- `perCwdExtraUserRoots` is only a diagnostic surface for repo tooling; not part of Slice 2's delivery.
- `externalAgentConfig/import` is the first-run migration API for importing Claude/other-harness configs into Codex home scope; it mutates `~/.codex/` and stays out of scope.
- Native slash-command `/branch-review` UI chip parity is still out of scope; this slice confirms `$-prefix` resolution only.
