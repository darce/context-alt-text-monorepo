# Claude Model Subversion Label Mapping

> **Metadata**
>
> - **Date**: 2026-04-17 (revised 2026-04-21 after partial resolution by AHMCP-34)
> - **Project**: `agent-handoff-mcp`
> - **Status**: Tech-debt note (date-coded slug mapping + provenance fallback still open; dash-separated minor-version path resolved by AHMCP-34 commit `50072bb1`)
> - **Primary surface**: [src/agent_handoff_mcp/enums.py](../../src/agent_handoff_mcp/enums.py)
> - **Related enforcement**: [src/agent_handoff_mcp/shared_write_context.py](../../src/agent_handoff_mcp/shared_write_context.py)
> - **Related renderer**: [src/agent_handoff_mcp/dashboard_rendering.py](../../src/agent_handoff_mcp/dashboard_rendering.py)
> - **Related tests**: [tests/test_enums.py](../../tests/test_enums.py)
> - **Observed output**: [DASHBOARD.txt](../../../../DASHBOARD.txt)

## Resolution History

- **AHMCP-34 (commit `50072bb1`, 2026-04-21)** — landed the dash-separated minor-version regex path. `normalize_model_label("claude-opus-4-7")` now returns `Claude Opus 4.7`, and `build_write_actor` accepts the matching `Claude Opus 4.7` label. The Claude regex was extended with an optional 1-2 digit minor group plus a negative-lookahead boundary so date suffixes (`0520`, `20251001`) remain unparsed while true minor versions (`4-7`, `4-6`, `4-5`) render with a dot. Covered by `tests/test_enums.py`.

The two cases below remain open.

## Problem (remaining)

`DASHBOARD.txt` can still render decisions as `Claude Opus 4` for two reasons that are easy to conflate:

1. **Date-suffix collapse**: [normalize_model_label()](../../src/agent_handoff_mcp/enums.py) treats date-suffixed raw ids such as `claude-opus-4-0520` as `Claude Opus 4` rather than the subversioned marketing label like `Claude Opus 4.6`. The regex deliberately preserves this collapse for date suffixes (so unknown future date-coded slugs do not silently invent a subversion); resolving this case requires an explicit slug-to-subversion lookup table, not a regex change.
2. **Provenance fallback contamination**: when a decision write omits `actor.model` and `actor.model_label`, [_resolve_write_actor()](../../src/agent_handoff_mcp/shared_write_context.py) can fall back to `handoff_state.updated_by` from the singleton `id = 1` row. If that active row was last updated by Claude, a GPT-authored decision can be persisted with `agent = "Claude Opus 4"` even though no Claude model metadata was provided for the write.

The recent-decisions dashboard section renders `decisions.agent`, not `model_label`, so both failure modes surface as the same user-visible string even though they originate in different layers.

This causes two kinds of drift:

- **Loss of attribution precision for date-coded slugs**: operators cannot distinguish different Claude releases in `DASHBOARD.txt`, `CURRENT_TASK.json`, or decision/review provenance rows when only a date-suffixed raw id is supplied. Dash-separated minor-version raw ids are no longer affected (resolved by AHMCP-34).
- **Cross-agent attribution leakage**: omitted actor metadata can inherit `updated_by` from the active singleton row and misattribute a GPT-authored decision as Claude in `DASHBOARD.txt`.

## Scope

Implement the explicit slug-to-subversion mapping path for date-coded raw ids, and fix the adjacent provenance fallback mismatch in the same slice if this note is revived.

1. Add a canonical lookup table in [src/agent_handoff_mcp/enums.py](../../src/agent_handoff_mcp/enums.py) for known date-coded Anthropic raw model ids, for example:
   - `claude-opus-4-0520` -> `Claude Opus 4.6`
   - future known date-coded slugs -> `Claude Opus 4.7`, `Claude Sonnet 4.6`, etc.
   - The lookup is consulted before the regex fallback, so dash-separated ids continue to flow through the AHMCP-34 regex unchanged.
2. Keep dashboard and current-task renderers unchanged. They should continue to render the stored `model_label` without display-specific fallback logic.
3. Keep `shared_write_context.py` as the enforcement point so non-canonical caller-supplied labels are still rejected unless they match the canonical mapping for the supplied raw model id.
4. Remove the `updated_by` fallback for decision provenance when the write omits model metadata. A missing `actor.model` / `actor.model_label` should remain visibly missing or fall back to an explicit caller-supplied `actor.agent`, not inherit the active task's last updater.
5. Keep the dashboard renderer dumb: it should continue to render the stored `agent` column without trying to reverse-engineer model labels or compensate for write-side provenance gaps.
6. Update [tests/test_enums.py](../../tests/test_enums.py) and any writer-context / dashboard-rendering tests that currently assert collapsed labels for date-coded slugs (e.g. `claude-opus-4-0520` → `Claude Opus 4`) or inherited singleton agent fallback. The dash-separated minor-version assertions added by AHMCP-34 must remain.
7. Document the canonical mapping policy so future Anthropic model upgrades add the date-coded slug mapping atomically with tests.

## Non-Goals

- Do not change `DASHBOARD.txt` rendering logic.
- Do not infer `4.6` or `4.7` from a date-suffixed raw id (e.g. `0520`, `20251001`) by regex parsing alone — that case is reserved for the explicit lookup table. Dash-separated minor-version parsing (e.g. `claude-opus-4-7` → `Claude Opus 4.7`) is **not** a non-goal; it is already implemented by AHMCP-34 and must be preserved.
- Do not rewrite historical decision rows already stored with `Claude Opus 4` unless a separate backfill task is approved.
- Do not loosen `actor.model_label` validation to accept arbitrary human-entered subversion labels.
- Do not preserve the current singleton `updated_by` fallback merely to keep legacy rows looking populated.

## Why Explicit Mapping (for date-coded ids)

Date-coded Anthropic raw ids do not encode `4.6` or `4.7` in a mechanically derivable way — `0520` is a release date, not a minor version. A regex can reliably recover `opus` and `4`, but not the desired subversion label. If the desired output is `Claude Opus 4.6`, the code needs an authoritative mapping from the date-coded raw slug to the display label.

Dash-separated minor-version ids (`claude-opus-4-7`) are different and are already handled by the AHMCP-34 regex path.

This keeps the provenance contract deterministic:

- the raw `model` field preserves the vendor slug
- the canonical `model_label` field preserves the human-facing release label
- the `agent` field is derived from the current write actor, not inherited from an unrelated active-task row
- renderers stay dumb and stable

## Proof Criteria (remaining)

- `normalize_model_label("claude-opus-4-0520")` returns `Claude Opus 4.6`.
- `build_write_actor(...)` accepts `actor.model_label="Claude Opus 4.6"` when paired with the mapped date-coded raw model slug (`claude-opus-4-0520`) and rejects mismatched labels.
- A write that omits `actor.model` / `actor.model_label` does not inherit `handoff_state.updated_by="Claude Opus 4"` into a new GPT-authored decision row.
- `DASHBOARD.txt` and `CURRENT_TASK.json` show the expanded label for newly recorded date-coded rows without renderer-specific code changes, and no longer misattribute GPT-authored rows as Claude due to singleton fallback.
- New tests cover at least one mapped date-coded Opus slug, one mapped date-coded Sonnet slug if present, one unmapped date-coded Claude slug that still falls back to the major-version label behavior, and one decision-write path with missing model metadata. The existing AHMCP-34 dash-separated minor-version assertions in `test_enums.py` must continue to pass.

## Risks

- **Mapping drift**: Anthropic may publish new date-coded raw ids before the mapping table is updated. Mitigation: preserve a deterministic fallback to the major-version label for unmapped date-coded Claude slugs and document the upgrade step.
- **Historical inconsistency**: old rows remain labeled `Claude Opus 4` while new rows show `Claude Opus 4.6`. Mitigation: accept mixed history until a deliberate backfill is approved.
- **Test churn**: existing tests currently encode the date-coded collapsed-label policy. Mitigation: update only the canonical-label assertions tied to mapped date-coded slugs; preserve the AHMCP-34 dash-separated assertions.
- **Backward-compat expectations around populated `agent`**: some callers or tests may implicitly rely on never-null `agent` strings. Mitigation: prefer explicit caller-supplied `actor.agent` when model metadata is unavailable and update tests to distinguish explicit agent fallback from singleton leakage.

## Trigger to Revive

Revive this note when operator-facing provenance needs to distinguish Claude subversions for **date-coded** raw model ids in live decision/review output, or when a future Anthropic model rollout publishes date-coded slugs that should match repo documentation already naming the subversion explicitly. Dash-separated minor-version raw ids no longer need this work — see AHMCP-34 commit `50072bb1`.