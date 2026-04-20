# Changelog

All notable changes to `agent-orchestrator-mcp` are recorded here. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] — 2026-04-19

### Added

- **Hoist Agentic System MVP packaging metadata.** `pyproject.toml` now
  declares a `[tool.hoisted]` table for the standalone install surface:
  `git+ssh://git@github.com/darce/mcp-agent-orchestrator.git@v{version}`.
  The package dependency on `agent-handoff-mcp` is also pinned to the MVP
  handoff release tag `v0.1.0`.
