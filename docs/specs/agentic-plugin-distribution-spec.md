# Agentic Plugin Distribution Specification

> **Metadata**
>
> - **Date**: 2026-05-15
> - **Author**: Claude
> - **Status**: Draft
> - **Source artifacts**:
>   - [docs/scopes/hoist-agentic-system-to-remote-scope.md](../scopes/hoist-agentic-system-to-remote-scope.md) (superseded in part)
>   - [docs/scopes/e17-10-hoisted-surface-cleanup-scope.md](../scopes/e17-10-hoisted-surface-cleanup-scope.md)
>   - [docs/scopes/e17-12-codex-skill-discoverability-scope.md](../scopes/e17-12-codex-skill-discoverability-scope.md)
> - **Owning epic**: E17 - Workflow Integrity & Hoisting (task E17-15)
> - **Package version target**: `agentic-protocol-monorepo` v0.2 (plugin-emitting generator); MCP runtime package pins unchanged (`mcp-workbay-handoff==0.2.0`, `mcp-workbay-orchestrator==0.5.0`)

This spec defines how skills, slash-commands, and MCP server registrations are distributed to the two consuming AI harnesses (Claude Code and Codex) as native plugins, with a single canonical source of truth in `agentic-protocol-monorepo`. It replaces the symlink + bootstrap-CLI model from the hoist scope with harness-native plugin manifests, eliminates the SKILL.md / `.claude/commands/<name>.md` duplication observed in this monorepo, and preserves the existing `uvx mcp-workbay-handoff==0.2.0` / `uvx mcp-workbay-orchestrator==0.5.0` package-pin install path. The MCP source repositories remain private; this task does not migrate runtime installation to `git+ssh` refs.

**Constraints:** The MCP server source repo (`darce/workbay`) and the `agentic-protocol-monorepo` itself remain **private** under the user's GitHub account. No public marketplace listing, no new package publication step, and no public discoverability work are in scope. VS Code Copilot is explicitly out of scope. Greenfield policy applies to the generator and plugin manifests; the consuming monorepo retains backward-compatible MCP install commands during a single migration window.

**Why now:** Three converging signals — duplicated skill bodies in `.claude/skills/<name>/SKILL.md` and `.claude/commands/<name>.md` waste tokens at picker time, the hoist-scope symlink model degrades when harnesses cache plugins in their own dirs (`~/.claude/plugins/cache/`, `~/.agents/plugins/`), and Codex's `request_plugin_install` tool plus Claude's `.claude-plugin/plugin.json` manifest are now mature enough to replace prose-driven adapters with deterministic pointers. This work re-decides the hoist model and therefore requires an ADR.

## Repository Ownership and Porting Boundary

This planning artifact lives in `context-alt-text-monorepo` because E17 planning, review findings, and branch lifecycle state currently live here. Once the spec, ADR, and task plan pass review and land on this repo's main branch, the implementation plan is intended to be ported to `agentic-protocol-monorepo` as the executable work package for the shared plugin system.

Repository ownership is split as follows:

- **This monorepo:** planning review, ADR/task-plan staging, and Tier 3 consumer cleanup after a working plugin tree exists.
- **`agentic-protocol-monorepo`:** canonical skill body layout, plugin registration manifest, deterministic plugin generator, emitted Claude/Codex plugin trees, and plugin-distribution documentation.
- **Remote MCP server repos:** referenced by plugin `mcpServers` definitions through the current runtime package pins. No MCP server code or packaging changes are required by this spec unless a later implementation task discovers that the plugin manifest cannot launch the existing entrypoints.

---

## Spec Items

### APD-001: Single canonical skill body in agentic-protocol-monorepo

**Trace:** Hoist-scope §"canonical source", picker-duplication evidence (`/skills` shows SKILL.md + commands.md), `.claude/skills/branch-review/SKILL.md` byte-identical to `~/Development/agentic-protocol-monorepo/.claude/skills/branch-review/SKILL.md`
**Priority:** P0
**ADR gate:** Yes — supersedes the hoist scope's symlink + bootstrap-CLI decision.

Every skill must have exactly one authored body file. The canonical location is `agentic-protocol-monorepo/packages/agentic-system/skills/<skill-name>/SKILL.md`. Consumer repos never hand-author or vendor a copy. The generator (APD-002) produces all harness-specific surfaces from this single body; no per-harness translation, no prose adapters.

**Before** (`<this-monorepo>/.claude/skills/branch-review/`):

```text
SKILL.md                    104 lines, hand-authored
../commands/branch-review.md 23 lines, generated thin adapter
```

Both surface in the Claude Code picker. Tokens duplicated on every selection.

**After** (`agentic-protocol-monorepo/packages/agentic-system/skills/branch-review/`):

```text
SKILL.md                    104 lines, canonical, single copy
```

Consumer monorepo holds **no** authored skill bodies. Harness-specific files (`.claude-plugin/`, `.codex-plugin/`) are emitted by the generator and gitignored or written into the harness cache directly.

**Done when:**

- `agentic-protocol-monorepo/packages/agentic-system/skills/<name>/SKILL.md` is the sole authored source for every cross-harness skill.
- This monorepo's `.claude/skills/` and `.claude/commands/` directories are emitted, not authored (or eliminated entirely in favour of harness cache install).
- Running `rg -l '^# Branch Review' apps/ docs/ packages/ .claude/ .codex/` returns at most one path per skill (the emitted artifact, if it lives in-tree at all).
- The picker no longer shows two entries for the same skill.

---

### APD-002: Generator emits Claude and Codex plugin manifests from one input

**Trace:** Hoist-scope §"thin generated harness adapters", `.claude-plugin/plugin.json` spec, Codex `.codex-plugin/plugin.json` + `request_plugin_install`
**Priority:** P0
**ADR gate:** Yes — manifest shape and emission contract is the core architectural decision.

`agentic-protocol-monorepo` ships a build command (`make plugins-build` or equivalent) that reads the canonical skill bodies plus a single registration manifest (`agentic-system.toml` or `plugins.yaml`) and emits, per harness:

- **Claude:** `.claude-plugin/plugin.json` with `skills`, `slash-commands`, and `mcpServers` keys. Skill files are referenced by relative path; bodies are copied into the plugin output directory.
- **Codex:** `.codex-plugin/plugin.json` with `skills`, `commands`, `mcpServers`, and (optional) `apps`/`hooks`. Same skill bodies, same byte content.

The generator MUST be deterministic: two clean runs produce byte-identical output. MCP server entries reference the existing package-pin invocations used by this monorepo's harness config (`uvx mcp-workbay-handoff==0.2.0 ... serve-stdio`, `uvx mcp-workbay-orchestrator==0.5.0 ... serve-stdio`); the generator does not republish, repackage, or retag the MCP servers.

**Before** (current state):

```text
config/agent-workflows/portable_commands.json       (manual, drifts)
.claude/commands/<name>.md                          (generated thin adapter)
.codex/prompts/<name>.md                            (generated thin adapter)
.github/copilot-instructions.md                     (hand-synced surface)
```

**After** (post-APD-002):

```text
agentic-protocol-monorepo/
  packages/agentic-system/skills/<name>/SKILL.md     (canonical)
  packages/agentic-system/plugins.yaml               (registration manifest)
  packages/agentic-system/scripts/build_plugins.py   (deterministic generator)
  dist/claude/.claude-plugin/plugin.json             (emitted)
  dist/claude/skills/<name>/SKILL.md                 (copied)
  dist/codex/.codex-plugin/plugin.json               (emitted)
  dist/codex/skills/<name>/SKILL.md                  (copied, byte-identical)
```

**Done when:**

- One source body produces both Claude and Codex plugin trees with no per-harness handwritten files.
- A diff of `dist/claude/skills/<name>/SKILL.md` against `dist/codex/skills/<name>/SKILL.md` shows zero byte differences for every cross-harness skill.
- `make plugins-build && git diff dist/` is empty on a clean run.
- The emitted `.mcp.json` / `mcpServers` block uses the same `uvx mcp-agent-*==...` package-pin form currently installed in this monorepo's settings.

---

### APD-003: Claude plugin install path uses harness cache, not in-repo files

**Trace:** Claude Code plugin docs (`~/.claude/plugins/cache/`), oh-my-pi `claude-plugins.ts` discovery proof, current `.claude/skills/<name>/SKILL.md` clutter
**Priority:** P0
**ADR gate:** Yes — install boundary affects every consumer repo.

Consumer monorepos install the agentic-system Claude plugin via Claude's native plugin mechanism (manifest reference pointing at the private `agentic-protocol-monorepo` git ref, or via `claude plugin install <path>` against a cloned working copy). The plugin lives in `~/.claude/plugins/cache/agentic-system@<sha>/`. Consumer repos do **not** check in `.claude/skills/` or `.claude/commands/` for cross-harness skills.

A small `.claude/settings.json` reference (plugin pin or local path) is the only Claude-related artifact this monorepo retains. Project-local-only skills (if any are introduced later) remain in `.claude/skills/` and are explicitly out of plugin scope.

**Before:**

```text
.claude/skills/branch-review/SKILL.md          (hand-authored, drift risk)
.claude/skills/branch-review/scripts/...
.claude/commands/branch-review.md              (generated adapter)
.claude/settings.json                          (hooks + permissions)
```

**After:**

```text
.claude/settings.json                          (hooks + permissions only)
.claude/plugins.json                           (pin to agentic-system@<ref>)
# .claude/skills/ and .claude/commands/ removed for cross-harness skills
```

**Done when:**

- This monorepo no longer ships cross-harness skill bodies under `.claude/skills/` or `.claude/commands/`.
- `claude /skills` shows each skill once, sourced from the plugin cache.
- A fresh clone + `claude plugin install <ref>` reproduces the working skill set without any local generation step in the consumer repo.

---

### APD-004: Codex plugin install path uses request_plugin_install

**Trace:** Codex plugin architecture (`~/.agents/plugins/marketplace.json`, `request_plugin_install` tool), E17-12 scope (`$-prefix` Codex skill discoverability)
**Priority:** P0
**ADR gate:** Yes — install boundary is symmetric to APD-003.

The agentic-system Codex plugin is installable via Codex's native `request_plugin_install` flow or by referencing the private `agentic-protocol-monorepo` git ref in `~/.agents/plugins/marketplace.json`. Plugin contents land in `~/.agents/plugins/agentic-system/`. The Codex prompts directory (`.codex/prompts/` in this monorepo) MUST NOT carry hand-authored bodies for cross-harness skills.

If Codex requires an in-repo registry pointer (analogous to Claude's `plugins.json`), it is the only Codex-related artifact in the consumer monorepo besides `.codex/AGENTS.md` and existing CLI config.

**Done when:**

- `agentic-protocol-monorepo` publishes a Codex plugin tree (or marketplace entry pointing at the private ref) consumable by `request_plugin_install`.
- `codex /skills` (or the `$-prefix` discovery path from E17-12) lists each skill once.
- This monorepo's `.codex/prompts/` directory is empty of cross-harness skills, or contains only emitted (gitignored) artifacts.

---

### APD-005: MCP server sources remain private, installed via uvx package pins

**Trace:** User-explicit constraint ("keep repos private"), current install command in `.mcp.json`, `.vscode/mcp.json`, and `.codex/config.toml`, E17-10 scope §"4 canonical external repos"
**Priority:** P0
**ADR gate:** No — this is a constraint, not a new design decision. Documented here so the ADR cannot accidentally relax it.

MCP servers (`mcp-workbay-handoff`, `mcp-workbay-orchestrator`) MUST remain installable via the current `uvx` package-pin flow and MUST NOT be listed in Anthropic's marketplace, Codex marketplace, or any new public index as part of this work. The plugin manifests emitted by APD-002 reference the existing package names and pins verbatim. Plugin installation is the registration mechanism; MCP runtime install remains the pre-existing `uvx` flow.

A future packaging or source-distribution task may flip this to `git+ssh`, private package index, or another mechanism; that task is explicitly out of scope here (see Deferred).

**Done when:**

- Emitted `.claude-plugin/plugin.json` and `.codex-plugin/plugin.json` `mcpServers` entries contain `uvx` commands pinned to `mcp-workbay-handoff==0.2.0` and `mcp-workbay-orchestrator==0.5.0`.
- No new PyPI, npm, or marketplace publication step exists in `agentic-protocol-monorepo/Makefile` or CI.
- `darce/workbay` and `darce/agentic-protocol-monorepo` GitHub visibility remains "Private" at the end of E17-15.

---

### APD-006: Plugin uninstall is reversible and idempotent

**Trace:** Claude plugin lifecycle (`claude plugin uninstall`), Codex `request_plugin_install` removal semantics, hoist-scope §"deploy & uninstall mechanism"
**Priority:** P1
**ADR gate:** No — relies on harness-native uninstall; spec only requires that the generator does not break it.

Removing the agentic-system plugin from either harness MUST restore that harness to a clean state: no orphan skill files in `~/.claude/plugins/cache/`, no orphan MCP entries pointing at `darce/...` repos. The consumer monorepo MUST tolerate plugin absence — i.e., bare-repo hooks (`scripts/hooks/guard-main-branch.sh`) and Makefile targets do not silently depend on plugin-installed scripts.

**Done when:**

- `claude plugin uninstall agentic-system` removes all plugin-provided skills and MCP refs without breaking hooks or Make targets.
- The Codex-equivalent uninstall flow does the same.
- A consumer monorepo with the plugin uninstalled still runs `make context` (with degraded MCP messaging, expected) and never produces `ImportError` or missing-skill picker entries.

---

### APD-007: Generator and manifest documented in agentic-protocol-monorepo

**Trace:** Hoist-scope §"consumer onboarding", E17-10 §"canonical external repos"
**Priority:** P1
**ADR gate:** No.

`agentic-protocol-monorepo` ships a README section (or `docs/plugin-distribution.md`) describing: the manifest schema, how to add a new skill, how to add an MCP server entry, how to bump the install ref consumers point to, and how to publish a new plugin version (git tag in the private repo). Documentation MUST include the exact `uvx` package-pin form and the cache locations for both harnesses.

**Done when:**

- `agentic-protocol-monorepo/README.md` (or linked doc) describes the manifest schema and add-a-skill flow.
- A new skill can be added by an operator following only the documented steps, with no implicit knowledge of generator internals.

---

## Entity / Payload Schemas

### Plugin registration manifest (`plugins.yaml` in `agentic-protocol-monorepo`)

```yaml
version: 1
plugin:
  name: agentic-system
  description: Cross-harness skills, slash-commands, and MCP server registration.
  homepage: https://github.com/darce/agentic-protocol-monorepo  # private
skills:
  - name: branch-review
    body: skills/branch-review/SKILL.md
    harnesses: [claude, codex]
    slash_command: /branch-review
  - name: planning-review
    body: skills/planning-review/SKILL.md
    harnesses: [claude, codex]
    slash_command: /planning-review
  # ... one entry per skill
mcp_servers:
  - name: mcp-workbay-handoff
    command: uvx
    args:
      - mcp-workbay-handoff==0.2.0
      - --workspace-root
      - .
      - serve-stdio
  - name: mcp-workbay-orchestrator
    command: uvx
    args:
      - mcp-workbay-orchestrator==0.5.0
      - --workspace-root
      - .
      - serve-stdio
```

### Emitted Claude manifest (`dist/claude/.claude-plugin/plugin.json`)

```json
{
  "name": "agentic-system",
  "version": "0.2.0",
  "skills": [
    { "name": "branch-review", "path": "skills/branch-review/SKILL.md" }
  ],
  "slashCommands": [
    { "name": "branch-review", "skill": "branch-review" }
  ],
  "mcpServers": {
    "mcp-workbay-handoff": {
      "command": "uvx",
      "args": ["mcp-workbay-handoff==0.2.0", "--workspace-root", ".", "serve-stdio"]
    }
  }
}
```

### Emitted Codex manifest (`dist/codex/.codex-plugin/plugin.json`)

```json
{
  "name": "agentic-system",
  "version": "0.2.0",
  "skills": [
    { "name": "branch-review", "path": "skills/branch-review/SKILL.md" }
  ],
  "commands": [
    { "name": "branch-review", "skill": "branch-review" }
  ],
  "mcpServers": {
    "mcp-workbay-handoff": {
      "command": "uvx",
      "args": ["mcp-workbay-handoff==0.2.0", "--workspace-root", ".", "serve-stdio"]
    }
  }
}
```

Exact Codex schema keys (`commands` vs `slashCommands`, presence of `apps`/`hooks`) are resolved during ADR drafting against the live Codex plugin spec.

---

## Implementation Tiers

### Tier 1 — Ready to plan, blocked on ADR for execution

```text
APD-001  Canonical skill body in agentic-protocol-monorepo
APD-007  Generator and manifest documentation
```

Tier 1 is body relocation and documentation. No consumer-monorepo changes; no harness install changes. Safe to plan immediately, blocked on ADR acceptance before edits land in `agentic-protocol-monorepo`.

### Tier 2 — Generator and emission

```text
APD-002  Generator emits Claude and Codex plugin manifests
APD-005  MCP server sources remain private, uvx package pins preserved
```

Tier 2 requires the manifest schema decided in the ADR and depends on Tier 1's canonical body layout.

### Tier 3 — Consumer migration and uninstall hygiene

```text
APD-003  Claude plugin install via harness cache
APD-004  Codex plugin install via request_plugin_install
APD-006  Plugin uninstall is reversible and idempotent
```

Tier 3 touches this monorepo: removes `.claude/skills/<name>/SKILL.md` for cross-harness skills, removes `.claude/commands/<name>.md`, prunes `.codex/prompts/<name>.md`, and replaces them with a single plugin pin. Sequenced after Tier 2 emits a working plugin tree.

---

## Deferred or Rejected Directions

- **VS Code Copilot plugin distribution.** Copilot lacks a first-party plugin manifest equivalent. Defer until either Copilot ships one or the user adopts a different IDE assistant. Existing `.github/copilot-instructions.md` continues to be hand-synced via the current `make generate-agent-workflows` adapter; that adapter is not in scope for replacement here.
- **New public marketplace listing (Anthropic plugin marketplace, Codex marketplace, npm, additional PyPI publication work).** Explicitly user-rejected ("keep repos private"). Existing MCP runtime package pins remain unchanged. Revisit source/package publication only when the user signals MCP features are stable.
- **Vendoring oh-my-pi.** Rejected — oh-my-pi's `claude-plugins.ts` proved Claude's plugin format is multi-harness consumable, but its broader scope (cross-agent skill loader, Pi-specific UX) is unrelated to this work. Borrow the discovery insight, do not import the package.
- **Protocol-neutral skill body rewrite** (ACP-style `distribution.uvx.package` envelopes around skill bodies). Rejected for v1 — adds a translation layer when SKILL.md is already byte-compatible across Claude/Codex. Revisit if a third harness with incompatible body format appears.
- **Bootstrap CLI symlink model from the hoist scope.** Superseded by harness-native plugin install. The hoist scope's overlay-precedence concept survives only as the per-repo `.claude/settings.json` (hooks + plugin pin) override, not as a symlink layer.
- **Per-repo override of plugin-shipped skill bodies.** Rejected — if a repo needs a behavioural override, it adds a local-only skill under `.claude/skills/<repo-specific-name>/` with a distinct name, never shadowing the plugin's canonical body.
- **Auto-generating skill bodies from a higher-level YAML.** Rejected — current SKILL.md prose is intentionally human-authored guidance; deterministic generation belongs at the manifest/registration layer, not the body layer.

---

## Spec-Review Gate

No implementation may start until:

1. This spec has been reviewed with findings recorded in MCP.
2. All spec review findings are resolved.
3. An ADR (e.g. `docs/adrs/ADR-NNN-agentic-plugin-distribution.md`) supersedes the hoist-scope symlink + bootstrap-CLI decision and accepts:
   - Single canonical body in `agentic-protocol-monorepo` (APD-001).
   - Generator output contract for Claude and Codex manifests (APD-002).
   - Harness-cache install path for both harnesses (APD-003, APD-004).
  - MCP source privacy with existing `uvx mcp-agent-*==...` runtime pins (APD-005).
4. An `E17-15-agentic-plugin-distribution-task-plan.md` has been reviewed with findings resolved and references this spec.
5. The Codex plugin manifest schema (exact key names, optional sections) has been verified against the live Codex plugin documentation, not inferred.

---

## Validation

### Current-state verification

```bash
# APD-001: duplicate skill bodies across this monorepo and agentic-protocol-monorepo
diff -q .claude/skills/branch-review/SKILL.md \
        ~/Development/agentic-protocol-monorepo/.claude/skills/branch-review/SKILL.md

# Picker duplication: SKILL.md + commands.md both present for same skill
ls -1 .claude/skills/branch-review/SKILL.md .claude/commands/branch-review.md

# Existing MCP runtime package pins in settings
rg -n "mcp-agent-(handoff|orchestrator)==" .mcp.json .vscode/mcp.json .codex/config.toml
```

### Tier 1 validation (in `agentic-protocol-monorepo`)

```bash
# Canonical bodies present, exactly once each
find packages/agentic-system/skills -name SKILL.md | sort
# Documentation exists
test -f packages/agentic-system/docs/plugin-distribution.md || \
    test -n "$(rg -l 'plugin manifest' packages/agentic-system/README.md)"
```

### Tier 2 validation (in `agentic-protocol-monorepo`)

```bash
# Generator is deterministic
make plugins-build
git diff --exit-code dist/

# Emitted manifests reference uvx package pins, not marketplace publication
rg -n "uvx" dist/claude/.claude-plugin/plugin.json dist/codex/.codex-plugin/plugin.json
rg -n "mcp-workbay-handoff==0.2.0|mcp-workbay-orchestrator==0.5.0" dist/claude/.claude-plugin/plugin.json dist/codex/.codex-plugin/plugin.json
rg -n "marketplace|publish" dist/ && echo "FAIL: public publish leaked" || echo "OK"

# Claude and Codex skill bodies are byte-identical
diff -q dist/claude/skills/branch-review/SKILL.md \
        dist/codex/skills/branch-review/SKILL.md
```

### Tier 3 validation (in this monorepo, post-migration)

```bash
# Cross-harness skill bodies no longer authored in-repo
test -z "$(find .claude/skills -name SKILL.md 2>/dev/null)" || \
    echo "WARN: residual in-repo skill bodies"
test -z "$(find .claude/commands -name '*.md' 2>/dev/null)" || \
    echo "WARN: residual generated commands"

# Plugin pin present
test -f .claude/plugins.json || test -n "$(rg -l 'agentic-system' .claude/settings.json)"

# Harness still finds the skills via plugin cache
claude /skills 2>&1 | rg -c '^branch-review$' | grep -q '^1$'
```

---

## Traceability

| Source artifact / signal | Spec items |
| --- | --- |
| Hoist scope §"canonical source" | APD-001, APD-002, APD-007 |
| Hoist scope §"thin generated harness adapters" | APD-002 |
| Hoist scope §"deploy & uninstall mechanism" | APD-006 |
| Hoist scope symlink/bootstrap-CLI decision | Superseded — see Deferred |
| E17-10 §"4 canonical external repos" | APD-005 |
| E17-12 Codex `$-prefix` discoverability | APD-004 |
| Picker duplication evidence (`/skills` shows SKILL.md + commands.md) | APD-001, APD-003 |
| oh-my-pi `claude-plugins.ts` (Claude format is multi-harness consumable) | APD-002 |
| hermes-agent `acp_registry/agent.json` (distribution envelope pattern) | Considered, rejected for v1 — see Deferred |
| User constraint: "keep repos private" | APD-005, Deferred |
| User constraint: "claude & codex plugin architecture" | APD-002, APD-003, APD-004, Deferred (Copilot) |
