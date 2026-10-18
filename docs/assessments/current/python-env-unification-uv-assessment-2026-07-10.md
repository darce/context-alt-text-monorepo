# Python Environment Unification — pyenv → uv (Assessment)

> **Status:** Decision document. Authored 2026-07-10 under `DURABILITY-UV-PLANNING`.
> **Question:** Should pyenv be replaced with a uniform venv/uv surface across the monorepo? Goal: efficient venv management (recurring drift-linked errors) and the ability to reason about it.
> **Verdict:** **Yes — finish the migration that is already 80% done.** uv is already the installer everywhere except Docker and CI; pyenv's live footprint is one `.python-version` file and one Makefile interpreter probe. The work is mostly *deleting* legacy paths, and the single biggest lever is a root `pyproject.toml` with `[tool.uv.workspace]` — a seam the lifecycle code already prefers and currently finds dormant.
> **Heuristics basis:** [heuristics-canon lexicons/engineering.md](https://github.com/darce/heuristics-canon/blob/main/lexicons/engineering.md) (canonical; gitignored mirror: `docs/workbay/rules/engineering-heuristics.md`).

## Current state (inventory, 2026-07-10)

**Six distinct venv-creation code paths** and **four disagreeing Python pins** — this is the drift surface behind the recurring errors:

| # | Path | Mechanism | Uses uv.lock? |
|---|---|---|---|
| 1 | Lifecycle per-package sync | `uv sync --extra dev` per package (`scripts/workbay_lifecycle/uv_provisioning.py:109`) | yes |
| 2 | Lifecycle worktree-root venv | `uv venv` + pip pytest + editable installs (`uv_provisioning.py:363-471`) — legacy anti-pyenv-shim path | no |
| 3 | Lifecycle workspace sync | root `uv sync` gated on `[tool.uv.workspace]` (`uv_provisioning.py:277-320`) — **dormant, no root pyproject.toml exists** | yes |
| 4 | App setup script | `VIRTUAL_ENV= uv sync --locked --extra dev` (`apps/prototype-description-service/scripts/setup.sh:29`) | yes |
| 5 | Docker | `python -m venv` + `pip install ".[face]"` on `python:3.12-slim` (`Dockerfile:34`) | **no — unlocked ranges** |
| 6 | Docs scratch venvs | `python3 -m venv /tmp/...` + pip (CLAUDE.md, `docs/workbay/rules/testing-python.md:131`) | no |

**Python version pins disagree** ([REF-19] — the interpreter decision leaks into four modules, so drift is structural, not accidental):

- `3.12.7` — `apps/prototype-description-service/.python-version` (pyenv-format, the last live pyenv artifact)
- `>=3.12` — both `pyproject.toml`/`uv.lock` (desc-service, codex-subagent-bridge)
- `3.11` — CI `handoff-integrity.yml:34` — **below the packages' floor**; works only because CI installs external wheels, not repo packages ([rg-006] latent: any step that installs a repo package breaks)
- `3.12-slim` — Dockerfile

**pyenv's live footprint** (everything else is docs/archive):

- The `.python-version` file above.
- `WORKFLOWS_PYTHON` probe: `pyenv which python` first, fallback `python3` (`Makefile.d/workflows.mk:25`, `Makefile.d/plugins.mk:30`) — exists solely because system `python3` lacks PyYAML, i.e. a direct casualty of having no unified root env.
- Everything else pyenv-related is *defensive*: the lifecycle doctor traps pyenv shims as a hazard (`scripts/workbay_lifecycle/handlers/doctor.py:844-904` — bare `pytest` resolving outside the worktree venv, ~1s shim latency), and path #2 above exists to defeat shims.

**Documented drift pain (all reproduced in repo tooling/docs):** `task-start` fails on pre-existing `.venv` (`uv_provisioning.py:363-396`, fails loudly by design, manual `make provision-env --clear` recovery); pyenv-shim trap warnings; `PYTHONPATH` overlays for codex-subagent-bridge (`Makefile:37-38`); macOS-ARM insightface pip special-case into the uv venv (`install_insightface_mac.sh`); Docker installing from ranges while dev runs `--locked` — the container can silently diverge from every tested environment.

## Analysis

- **[ARCH-08] Choose boring/single technology.** Two interpreter managers (pyenv + uv) and six env-creation paths for two Python packages is the inverted ratio. uv already won inside this repo — the Makefiles standardize `UV := VIRTUAL_ENV= uv`, the MCP stack is `uv tool install`-managed, and the lifecycle module is literally named `uv_provisioning.py`. pyenv adds a second interpreter-resolution authority whose shims the tooling actively defends against: negative value.
- **[REF-19] One module owns the decision.** The Python version should be declared once (root `.python-version`, uv-native format) and consumed by uv everywhere — dev, worktrees, CI, Docker. Today four surfaces each own a copy and one (CI 3.11) is already wrong.
- **[DATA-14]-analog (no dual writes).** `uv.lock` is the system of record for dependency state; Docker's unlocked `pip install` is a second writer that diverges silently. Deployment must derive from the lock.
- **[RES-07] Reclaimer analogy.** Path #2 (root venv + editable installs) is accumulated scaffolding whose reason-to-exist (pyenv shims, no workspace) disappears once the workspace manifest lands; leaving it is unbounded complexity accretion. Delete-over-flag per greenfield policy.
- **[AGT-08] Rejection is specification.** The doctor's pyenv-shim traps are the codebase telling us pyenv is already treated as a fault condition, not a supported path.
- **[ARCH-06] Trade-offs.** What uv-only sacrifices: (a) arbitrary patch-level interpreter pinning per directory the pyenv way — uv covers this with `uv python pin`/managed interpreters; (b) the macOS insightface pip shim still bypasses `uv sync` — it stays a documented exception either way; (c) contributors without uv — mitigated by `setup.sh` already requiring it and `scripts/worktree-lane:49` hard-requiring `uvx`.

## Decision

Adopt **uv as the only interpreter + environment authority**. Phased, each phase independently mergeable:

### Phase 1 — Root uv workspace (the lever)

- Add root `pyproject.toml` with `[tool.uv.workspace]` members `apps/prototype-description-service`, `packages/codex-subagent-bridge`; root `uv.lock`.
- This activates the dormant lifecycle path #3 (`uv_provisioning.py:277-320`, seam "D3b" per its implementation notes): one `uv sync` per worktree, one root `.venv`, console scripts resolve locally.
- Retire path #2 (legacy root-venv editable machinery, `uv_provisioning.py:363-471`) once #3 is proven in a worktree `task-start` — this also removes the "pre-existing `.venv`" failure class, since workspace sync is idempotent where `uv venv` is not.
- Exit criteria: `make task-start` on a fresh worktree provisions via workspace sync; `pytest` resolves inside the worktree venv (doctor shim-trap silent); per-package `make test` targets unchanged.

### Phase 2 — Single Python pin, pyenv retired

- Root `.python-version` = `3.12` (uv-format); delete `apps/prototype-description-service/.python-version` (3.12.7 pyenv-format).
- Replace the `WORKFLOWS_PYTHON` pyenv probe (`Makefile.d/workflows.mk:25`, `plugins.mk:30`) with `uv run --project` against the workspace (PyYAML declared where the workflow scripts live — kills the probe's reason to exist).
- Grep-verify zero remaining functional `pyenv` references outside `docs/archive/`; the doctor's shim traps stay (defense in depth).
- Operator-level `pyenv` uninstall is out of scope — the repo simply stops depending on it.

### Phase 3 — CI on uv

- `handoff-integrity.yml`: `astral-sh/setup-uv` + `uv python install` honoring the root pin; fix the below-floor `3.11` ([rg-006]).
- Any future repo-package CI jobs use `uv sync --locked` — same command family as dev ([rg-006]: documented commands run as written, everywhere).

### Phase 4 — Docker derives from the lock

- `Dockerfile`: multi-stage with `uv sync --locked --no-dev --extra face` (uv's official image or standalone binary), replacing `python -m venv` + unlocked pip ([DATA-14]: the lock is the system of record).
- insightface Linux path already installs via the `face` extra; the macOS shim is dev-only and unaffected.
- Exit criteria: image build reproducible from lockfile; `docker-compose.prod.yml` services boot unchanged.

### Phase 5 — Docs + scratch convention

- Update CLAUDE.md / `docs/workbay/rules/testing-python.md` scratch-venv prescription from `python3 -m venv` + pip to `uv venv` + `uv pip install` (same isolation guarantee, one toolchain; external `git+ssh` refs unchanged).
- Sweep remaining `pyenv exec` prescriptions from non-archive docs.

## Explicitly out of scope

- No Poetry/PDM/conda evaluation — uv is the incumbent; this is consolidation, not selection ([ARCH-08]).
- No change to `uv tool install`-managed workbay MCP stack (`scripts/workbay/update.sh`) — already uv-native and isolated by design.
- No per-tenant/per-app Python version divergence support ([REF-12] YAGNI — both packages pin `>=3.12`).

## Risks

| Risk | Mitigation |
|---|---|
| Workspace sync changes import resolution for tests (editable → workspace members) | Phase 1 exit criteria run both packages' suites before path #2 is deleted; keep #2 behind one release until proven |
| `uv_provisioning.py` workspace path is untested in anger (dormant since authored) | It was built for exactly this manifest; treat first activation as the Phase 1 verification, with rollback = delete root pyproject.toml |
| Docker uv adoption changes layer caching / image size | Standard uv multi-stage pattern; verify image size and startup in staging compose before prod |
| insightface macOS shim breaks under workspace venv layout | Shim targets `.venv/bin/python` path — re-point to workspace venv; covered by existing setup.sh flow on ARM dev machines |

## Revisit triggers

- uv workspace proves incompatible with the per-worktree lane model (multiple concurrent worktrees sharing the uv cache is expected to work — hardlink cache — but unverified at lane fan-out scale).
- A package genuinely needs a different Python major/minor than the workspace pin.

## Sizing

Phases 1–2 ≈ 1 bounded task (config + deletions + lifecycle verification); Phases 3–5 ≈ 1 small task each. Net LOC is **negative** (path #2 deletion ~100 LOC, probe deletion, docs sweep) against ~40 lines of new manifest/CI/Dockerfile config.
