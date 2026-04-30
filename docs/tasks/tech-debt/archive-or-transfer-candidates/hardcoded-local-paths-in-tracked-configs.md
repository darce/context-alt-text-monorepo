# Tech Debt: Hardcoded Local Paths in Tracked Configs

## Summary

Three tracked config files contain absolute paths tied to `/Users/daniel/...`. They work for the current single-developer setup but break on clone for any other machine or CI.

## Affected Files

| File | Instances | Purpose |
|---|---|---|
| `.codex/config.toml` | 7 | Codex sandbox MCP server config, PYTHONPATH, cwd |
| `.mcp.json` | 2 | Claude Code MCP server `--workspace-root` args |
| `.vscode/settings.json` | 1 | Python interpreter path |

## Proposed Fix

1. Add `.codex/config.toml`, `.mcp.json`, and `.vscode/settings.json` to `.gitignore`.
2. Create `*.example` templates with placeholder paths (e.g., `${WORKSPACE_ROOT}`, `<your-pyenv-path>`).
3. Document the setup step in `BOOTSTRAP.md`: copy templates and fill in local paths.

## Risk

Low. Greenfield project, single developer. No CI currently consumes these files. The concern is future onboarding friction, not current breakage.

## Related

- `.github/hooks/test_terminal_guard.py` has 7 hardcoded paths but these are test fixture strings (parsed, not resolved) and are functionally correct.
- ~377 instances in `docs/` are prose examples in task plans and playbooks -- not actionable.
