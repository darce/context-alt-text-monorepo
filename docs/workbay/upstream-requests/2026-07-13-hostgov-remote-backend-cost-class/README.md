# Upstream request — hostgov admission force-classes remote-API offload as `heavy`; misplaced `host_memory:` block fails silently

**Target repo:** `agentic-protocol-monorepo` / `darce/workbay` (`workbay-orchestrator-mcp` — hostgov admission).
**Consumer:** `context-alt-text-monorepo` (package-mode install, 8 GiB operator laptop).
**Affected release:** `mcp-workbay-orchestrator==0.2.8`, `workbay-protocol==0.2.2` (monorepo tag current `main` ea82b0ff).
**Discovered while:** enabling grok-cli offload lanes on the 8 GiB laptop — hostgov refused every dispatch, and the documented config knobs had no effect.

## Summary

Two independent hostgov defects made grok offload unshippable on a small host and cost a full debugging session:

1. **`cost_class="heavy"` is hardcoded at every offload admission site**, so a grok-cli lane — whose local worker is a remote-API CLI driver (~0.5 GiB RSS), not a co-resident model — is sized against `rss_per_heavy_gib` and gated as if it ran inference locally. A `COST_LIGHT` class that is **never gated** already exists but is never selected for remote backends.
2. **The `host_memory:` policy block is silently ignored unless nested under `orchestrator:`.** Placed at YAML top-level (a natural mistake), the loader returns empty and falls back to enforce-defaults (os_reserve 3.0 / rss_per_heavy 2.5 → ~5.5 GiB needed) with **no warning** on any surface. The operator sees "admission refused" with correct-looking config on disk.

Combined effect: on an 8 GiB host, grok offload is refused permanently, and the two supported levers for fixing it (edit the `host_memory` values; rely on backend cost) either no-op silently or don't apply to remote backends. We worked around it by hand-lowering `rss_per_heavy_gib` to 0.5 globally — which now **under-reserves for genuinely heavy local backends** on the same host.

---

## Defect 1 — remote-API backends miscategorized as `heavy` co-resident workers

hostgov already models cost tiers (`host_resources.py:54-58`):

```python
COST_HEAVY = "heavy"
COST_LIGHT = "light"
_GATED_COST_CLASSES = (COST_HEAVY, COST_SUITE)   # light is never gated
```

But all three offload admission call sites hardcode `heavy` regardless of the resolved backend (`api.py`):

```python
api.py:1001   admission = _evaluate_host_admission(paths["workspace_root"], cost_class="heavy")
api.py:1986   admission = _evaluate_host_admission(paths["workspace_root"], cost_class="heavy")
api.py:2119   admission = _evaluate_host_admission(paths["workspace_root"], cost_class="heavy")
```

`offload_preflight` already resolves the backend profile — it distinguishes `grok-cli` from `codex-subagent` throughout `offload_pass.py` (e.g. `offload_pass.py:1160 elif resolved_backend == "grok-cli"`). The admission call is the one place that discards that knowledge.

For `grok-cli`, inference runs on the **grok API (remote)**. The local process is a CLI driver — no model weights resident. Sizing it against `rss_per_heavy_gib` (default 2.5 GiB) is wrong by ~5×, and forcing it into `_GATED_COST_CLASSES` means an 8 GiB host with any real memory pressure can never admit it, even though the actual local cost is trivial and swap-tolerant.

**Ask:** derive `cost_class` from the resolved backend's offload profile instead of hardcoding `"heavy"`.
- Remote-API backends (`grok-cli`, and any future backend whose inference is not in-process) → `COST_LIGHT` (never gated), or a new `COST_REMOTE_API` tier gated only on a small fixed CLI-driver RSS (`rss_per_light_gib`, default ~0.5–0.75 GiB) plus the swap-floor check.
- Genuinely in-process backends (a local model, or `codex-subagent` if it runs heavy locally) → `COST_HEAVY` as today.
- The backend→cost_class mapping belongs on the profile that `offload_preflight` already resolves, so `_evaluate_host_admission` receives the right class rather than a literal.

This removes the need for consumers to hand-detune the global `rss_per_heavy_gib` (which corrupts sizing for real heavy workers on the same host).

## Defect 2 — misplaced `host_memory:` block is a silent no-op

`load_host_memory_policy` (`host_resources.py:420`) reads `docs/workbay/contracts/harness-protocol.yaml` and parses via `_parse_host_memory_block` (`host_resources.py:390`), which only accepts the block when it is:

```
orchestrator:            # indent 0
  host_memory:           # indent 2
    os_reserve_gib: ...  # indent 4
```

A block written at YAML top level (`host_memory:` at indent 0 — a very easy mistake, since it reads as its own section) yields an empty dict → `load_host_memory_policy` returns `defaults` (`host_resources.py:429-430`). The loader already carries a `warnings` list and emits warnings for unknown keys, malformed values, and non-finite numerics — but **not** for "a top-level `host_memory:` key exists while `orchestrator.host_memory` is absent." So the operator gets enforce-defaults with zero signal, and every downstream `admission_refused` looks like a genuine memory shortfall rather than an unparsed config.

**Ask:**
- In `_parse_host_memory_block` / `load_host_memory_policy`, detect a top-level `host_memory:` key with no `orchestrator.host_memory` block and emit a `warnings` entry: `host_memory: block found at top level; must be nested under 'orchestrator:' — ignored, using defaults`.
- Surface the **effective policy + its warnings + the source path** in the `offload_preflight` response (today it returns the `admission` snapshot but not which policy produced it). An operator editing the yaml has no supported way to confirm the edit took effect without importing `load_host_memory_policy` directly — which is what we had to do.

## Reproduction (both defects)

```
# 8 GiB host, grok-cli offload. host_memory block placed at yaml top level.
offload_preflight(agent="grok-cli", token_budget=50000, reasoning_effort="high")
# -> admission_refused: "derived width 0 (available RAM minus OS reserve < rss_per_heavy)"
#    cost_class: "heavy"   <- Defect 1 (should be light/remote for grok)
#    policy silently = enforce-defaults despite edited on-disk values  <- Defect 2
```

## Consumer workaround in place (to be reverted once fixed)

`docs/workbay/contracts/harness-protocol.yaml` `orchestrator.host_memory`: nested the block correctly and set `os_reserve_gib: 0.5`, `rss_per_heavy_gib: 0.5`, `max_width: 1`, `swap_free_floor_mb: 256`. This admits grok at ~1 GiB available but **globally** under-reserves for any real heavy backend on this host — a stopgap, not a fix. Reverting to sane heavy defaults depends on Defect 1 landing so grok is no longer classed heavy.

## Suggested acceptance

- grok-cli offload admits on an 8 GiB host under normal (non-thrashing) memory with **default** heavy sizing untouched, because it is classed light/remote — not heavy.
- A top-level-misplaced `host_memory:` block produces a visible warning, not a silent default fallback.
- `offload_preflight` echoes the effective host_memory policy (values, source path, warnings) so config edits are verifiable from the tool surface.
