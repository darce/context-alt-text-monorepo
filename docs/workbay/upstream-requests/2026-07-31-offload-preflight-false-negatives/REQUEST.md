# Upstream request — three offload-dispatch environment defects

**Filed:** 2026-07-31
**Consumer:** `context-alt-text-monorepo`
**Versions:** `mcp-workbay-orchestrator` 0.2.15, `workbay-protocol` 0.2.3, `workbay-bootstrap` 0.3.21
**Discovered during:** FIR-7 offload dispatch (lane `fir7-floor`, backend `grok-remote`)

Three independent defects surfaced in a single dispatch. Two are advisory-warning
false positives; the third is a hard crash that aborts the pass before any work.

---

## 1. `lane_prompt.py` crashes when `<orchestrator_root>/.venv` lacks the workbay stack — HIGH

**Symptom.** `run_offload_pass` returns `outcome: "error"` at `wall_seconds: 0.19`,
before any agent turn:

```
offload pass crashed: RuntimeError: lane_prompt.py --check failed (exit 1):
  File ".../workbay_orchestrator_mcp/orchestration/lane_prompt.py", line 13
    from workbay_protocol import resolve_env_alias
ModuleNotFoundError: No module named 'workbay_protocol'
```

**Cause.** `_env.resolve_lane_python` probes `<orchestrator_root>/.venv` **first**
(documented: the lane subprocess must agree with the DB's schema, so the
interpreter is resolved from the root that resolves the DB). But
`_env.pythonpath_env` only injects
`<orchestrator_root>/packages/workbay-codex-bridge/src` into `PYTHONPATH` — it does
**not** inject the orchestrator's own tool-env `site-packages`. So the chosen
interpreter is required to have `workbay_protocol`, `workbay_orchestrator_mcp`, and
`workbay_handoff_mcp` installed, yet nothing in the install path guarantees it.

The packages *were* present in the uv tool env
(`~/.local/share/uv/tools/mcp-workbay-orchestrator/.../site-packages`, per
`uv-receipt.toml`), just not in the consumer checkout's `.venv` — which is the
interpreter actually selected.

**Why it is not caught by preflight.** `offload_preflight` returned `ok: true`. It
probes the *lane worktree's* venv, never the *orchestrator root's* venv — the one
`resolve_lane_python` will actually pick.

**Requests.**
1. Have `pythonpath_env` append the orchestrator package's own `site-packages` so a
   lane subprocess can always import the stack that spawned it, regardless of which
   interpreter `resolve_lane_python` selects.
2. Failing that, make `offload_preflight` probe the *resolved lane interpreter*
   (`resolve_lane_python(orchestrator_root)`) for the three imports `lane_prompt.py`
   performs, and fail fast with an actionable message instead of letting the pass
   crash. A pre-work import failure should be a typed refusal, not `outcome: error`.
3. `make provision-env` should install the workbay stack into the target venv. It
   currently installs only `codex-subagent-bridge`, which does not satisfy
   `lane_prompt.py`.

**Local workaround applied.** Installed `workbay-protocol`, `mcp-workbay-handoff`,
and `mcp-workbay-orchestrator` from the local `agentic-protocol-monorepo` clone into
the consumer root `.venv` with `uv pip install --no-sources`. (Deliberately not from
PyPI — a `--upgrade` from PyPI is a known clobber trap for this stack.)

---

## 2. Preflight probes `workbay_protocol.version`, a submodule that does not exist — MEDIUM

**Symptom.** Every `offload_preflight` call emits:

```
worktree env unready: lane .venv cannot import required workbay siblings
(workbay_protocol, workbay_protocol.version):
ModuleNotFoundError: No module named 'workbay_protocol.version'
— run `uv sync` in <worktree> before dispatch
```

**Cause.** `workbay_protocol` 0.2.3 exposes `__version__` as a module **attribute**;
it has no `version` **submodule**. Its actual submodules are `bootstrap`,
`branch_naming`, `brand`, `compaction`, `env_aliases`, `handoff`, `hooks`, `paths`,
`skills`. The probe therefore fails on a correctly-provisioned venv, and no
provisioning step can ever satisfy it.

**Impact.** The warning is unconditional and unfixable, so it trains operators to
ignore preflight warnings — which is how defect #1 above stayed invisible. It also
prescribes a remedy (`uv sync` at the virtual root) that is actively harmful in this
consumer: it prunes the lane venv from ~181 packages to ~5.

**Request.** Probe `getattr(workbay_protocol, "__version__")`, not
`importlib.import_module("workbay_protocol.version")`. Separately, reconsider the
`uv sync` remedy text — for a uv-workspace consumer, `uv sync` at the virtual root
is destructive to lane venvs.

---

## 3. Codemap project name derived as a path slug, not the indexed name — MEDIUM

**Symptom.** Every lane context packet degrades to empty:

```
codemap_unavailable:section_omitted:index_status:bad_json:
{"error":"project not found or not indexed", ...}
anchors: (none) / blast radius: (none) / code excerpts: (none)
```

**Cause.** The orchestrator queries the codemap under
`Users-daniel-Development-context-alt-text-monorepo` (a slugified absolute path).
`codebase-memory-mcp list_projects` shows the repo **is** fully indexed — 20,778
nodes, 91,520 edges, `head_sha` matching current `main` — but under the bare
directory name `context-alt-text-monorepo`.

Note both conventions are live in the same index: this repo is registered bare,
while `agentic-protocol-monorepo` is registered as the path slug
`Users-daniel-Development-agentic-protocol-monorepo`. So the orchestrator's
derivation is right for one and wrong for the other.

**Impact.** `include_context_packet=true` silently yields a zero-content packet. It
degrades typed (does not fail dispatch, as designed), but the worker cold-starts
blind while the packet *claims* `available: true` with `packet_bytes: 1424` — all of
it metadata and error notes. A caller reading `available: true` would reasonably
assume the structural channel worked.

**Requests.**
1. Resolve the codemap project by `root_path` match against `list_projects` rather
   than by deriving a name string; fall back to name derivation only if no
   `root_path` matches.
2. Set `available: false` when every section is omitted. `available: true` with
   `anchors: []`, `blast_radius: []`, `snippets: []` misreports a total failure as a
   success.

**Local workaround.** Coordinator supplied explicit file/line anchors inline in the
brief, and queries the codemap directly under the name `context-alt-text-monorepo`.

---

## Housekeeping note (not a request)

`list_projects` returns ~25 orphaned `pytest-of-daniel/pytest-N/...consumer`
projects whose `root_exists: false`. They appear to be leaked by
`test_make_task_finish_checklist*` runs. A test-teardown `delete_project` would keep
the operator-facing project list readable.
