# Claude Model Subversion Label Mapping

> **Metadata**
>
> - **Date**: 2026-04-17
> - **Project**: `agent-handoff-mcp`
> - **Status**: Tech-debt note (no implementation slice yet)
> - **Primary surface**: [src/agent_handoff_mcp/enums.py](../../src/agent_handoff_mcp/enums.py)
> - **Related enforcement**: [src/agent_handoff_mcp/shared_write_context.py](../../src/agent_handoff_mcp/shared_write_context.py)
> - **Related renderer**: [src/agent_handoff_mcp/dashboard_rendering.py](../../src/agent_handoff_mcp/dashboard_rendering.py)
> - **Related tests**: [tests/test_enums.py](../../tests/test_enums.py)
> - **Observed output**: [DASHBOARD.txt](../../../../DASHBOARD.txt)

## Problem

`DASHBOARD.txt` can currently render decisions as `Claude Opus 4` for two separate reasons that are easy to conflate:

1. **Subversion collapse**: [normalize_model_label()](../../src/agent_handoff_mcp/enums.py) treats values such as `claude-opus-4-0520` as `Claude Opus 4` rather than a subversioned marketing label like `Claude Opus 4.6` or `Claude Opus 4.7`.
2. **Provenance fallback contamination**: when a decision write omits `actor.model` and `actor.model_label`, [_resolve_write_actor()](../../src/agent_handoff_mcp/shared_write_context.py) can fall back to `handoff_state.updated_by` from the singleton `id = 1` row. If that active row was last updated by Claude, a GPT-authored decision can be persisted with `agent = "Claude Opus 4"` even though no Claude model metadata was provided for the write.

The recent-decisions dashboard section renders `decisions.agent`, not `model_label`, so both failure modes surface as the same user-visible string even though they originate in different layers.

This causes two kinds of drift:

- **Loss of attribution precision**: operators cannot distinguish different Claude releases in `DASHBOARD.txt`, `CURRENT_TASK.json`, or decision/review provenance rows when they share the same major-family label.
- **Doc/runtime mismatch**: historical planning and assessment docs in the repo already use labels such as `Claude Opus 4.6` and `Claude Opus 4.7`, but the runtime canonicalizer rejects those labels for current raw model ids.
- **Cross-agent attribution leakage**: omitted actor metadata can inherit `updated_by` from the active singleton row and misattribute a GPT-authored decision as Claude in `DASHBOARD.txt`.

## Scope

Implement the explicit slug-to-subversion mapping path and fix the adjacent provenance fallback mismatch in the same slice if this note is revived.

1. Add a canonical lookup table in [src/agent_handoff_mcp/enums.py](../../src/agent_handoff_mcp/enums.py) for known Anthropic raw model ids, for example:
   - `claude-opus-4-0520` -> `Claude Opus 4.6`
   - future known slugs -> `Claude Opus 4.7`, `Claude Sonnet 4.6`, etc.
2. Keep dashboard and current-task renderers unchanged. They should continue to render the stored `model_label` without display-specific fallback logic.
3. Keep `shared_write_context.py` as the enforcement point so non-canonical caller-supplied labels are still rejected unless they match the canonical mapping for the supplied raw model id.
4. Remove the `updated_by` fallback for decision provenance when the write omits model metadata. A missing `actor.model` / `actor.model_label` should remain visibly missing or fall back to an explicit caller-supplied `actor.agent`, not inherit the active task's last updater.
5. Keep the dashboard renderer dumb: it should continue to render the stored `agent` column without trying to reverse-engineer model labels or compensate for write-side provenance gaps.
6. Update [tests/test_enums.py](../../tests/test_enums.py) and any writer-context / dashboard-rendering tests that currently assert collapsed labels like `Claude Opus 4` or inherited singleton agent fallback.
7. Document the canonical mapping policy so future Anthropic model upgrades add the slug mapping atomically with tests.

## Non-Goals

- Do not change `DASHBOARD.txt` rendering logic.
- Do not infer `4.6` or `4.7` generically from regex parsing alone.
- Do not rewrite historical decision rows already stored with `Claude Opus 4` unless a separate backfill task is approved.
- Do not loosen `actor.model_label` validation to accept arbitrary human-entered subversion labels.
- Do not preserve the current singleton `updated_by` fallback merely to keep legacy rows looking populated.

## Why Explicit Mapping

The current raw Anthropic model ids do not encode `4.6` or `4.7` in a generic, mechanically derivable way. A regex can reliably recover `opus` and `4`, but not the desired subversion label. If the desired output is `Claude Opus 4.6`, the code needs an authoritative mapping from known raw slugs to display labels.

This keeps the provenance contract deterministic:

- the raw `model` field preserves the vendor slug
- the canonical `model_label` field preserves the human-facing release label
- the `agent` field is derived from the current write actor, not inherited from an unrelated active-task row
- renderers stay dumb and stable

## Proof Criteria

- `normalize_model_label("claude-opus-4-0520")` returns `Claude Opus 4.6`.
- `build_write_actor(...)` accepts `actor.model_label="Claude Opus 4.6"` when paired with the mapped raw model slug and rejects mismatched labels.
- A write that omits `actor.model` / `actor.model_label` does not inherit `handoff_state.updated_by="Claude Opus 4"` into a new GPT-authored decision row.
- `DASHBOARD.txt` and `CURRENT_TASK.json` show the expanded label for newly recorded rows without renderer-specific code changes, and no longer misattribute GPT-authored rows as Claude due to singleton fallback.
- Tests cover at least one mapped Opus slug, one mapped Sonnet slug if present, one unmapped Claude slug that still falls back to the current major-version label behavior, and one decision-write path with missing model metadata.

## Risks

- **Mapping drift**: Anthropic may publish new raw ids before the mapping table is updated. Mitigation: preserve a deterministic fallback for unmapped Claude slugs and document the upgrade step.
- **Historical inconsistency**: old rows remain labeled `Claude Opus 4` while new rows show `Claude Opus 4.6`. Mitigation: accept mixed history until a deliberate backfill is approved.
- **Test churn**: existing tests currently encode the collapsed-label policy. Mitigation: update only the canonical-label assertions tied to mapped slugs.
- **Backward-compat expectations around populated `agent`**: some callers or tests may implicitly rely on never-null `agent` strings. Mitigation: prefer explicit caller-supplied `actor.agent` when model metadata is unavailable and update tests to distinguish explicit agent fallback from singleton leakage.

## Trigger to Revive

Revive this note when operator-facing provenance needs to distinguish Claude subversions in live decision/review output, or when a future Anthropic model rollout requires the runtime labels to match repo documentation that already names the subversion explicitly.