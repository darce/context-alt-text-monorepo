# Migrate pip to uv for dependency installation

**Priority:** Low (quality-of-life improvement)
**Effort:** ~30 minutes
**Risk:** None — drop-in replacement, no structural changes

## Current state

The project uses `pyproject.toml` + `setuptools` with standard `pip install -e ".[dev]"` for dependency management. Fresh installs take 30-60 seconds due to pip's serial resolution and download.

## Proposed change

Replace `pip` with `uv pip` in the Makefile's `install` and `setup` targets. uv is a drop-in replacement that reads the same `pyproject.toml` — no changes to project structure, build backend, or dependency specs.

### What changes

- Makefile: `pip install` → `uv pip install` in `install`/`setup` targets
- Optional: `python -m venv` → `uv venv` for venv creation

### What stays the same

- `pyproject.toml` (no changes)
- `setuptools` build backend
- `.python-version` (pyenv still manages Python versions)
- All optional dependency groups (`dev`, `face`, `gpu`, `dashboard`)
- ruff, mypy, pytest configuration

## Why

- 10-20x faster installs (2-5 seconds vs 30-60 seconds)
- Better dependency resolution (fewer conflicts)
- uv respects pyenv's `.python-version` automatically
- Already adopted in the media-archive project

## Prerequisites

- `uv` installed: `pipx install uv`

## Consolidated Triage Checklist (2026-04-30)

**Disposition:** Ownership decision needed; transfer/archive candidate until scope is clarified.
**Evaluation basis:** Current `main` install commands and agentic/tooling package split.

- [ ] Decide whether `uv` is a required developer prerequisite or an optional fast path with pip fallback.
- [ ] If the target is `apps/prototype-description-service`, create a new app-scoped task that names the affected Makefile/scripts/docs explicitly and move it back to active tech debt.
- [ ] If the target is shared agentic/MCP/bootstrap install speed, move this to `/Users/daniel/Development/agentic-protocol-monorepo/docs` or the owning external package repo.
- [ ] If no current install pain remains, archive this note as a stale quality-of-life proposal.
