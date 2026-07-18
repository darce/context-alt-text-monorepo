# Upstream response — accepted; fix in flight on `feature/wb-install-remote-mode-01`

**Status:** accepted / implemented upstream, pending merge + release.
**Triaged:** 2026-07-17, `agentic-protocol-monorepo` backlog session (task `WB-INSTALL-REMOTE-MODE-01`, plans 0145/0152).

## Disposition

The ask was independently implemented earlier the same day as part of Plan 0145
(installer `--with-remote` mode) with the 0145/0152 coordination pulling the
profile registration forward:

- **`OFFLOAD_AGENT_PROFILES["grok-remote"]`** landed (commit `c96aafea` on
  `feature/wb-install-remote-mode-01`): same `DEFAULT_GROK_MODEL` (grok-4.5) pin
  and `derive_grok_single_cycle_bounds` token-budget bounds as `grok-cli` —
  remoteness stays in the adapter/cost class, exactly as requested.
- **Preflight admission facet** already resolves per-agent via
  `cost_class_for_backend(agent)` (`api.py` `offload_preflight`), so with the
  profile row present a `grok-remote` preflight evaluates under the ungated
  `COST_REMOTE` class. Regression test pinning this contract (profile shape +
  `COST_REMOTE` vs `COST_REMOTE_API`) added in
  `tests/test_execution_mode_enforcement.py`, named for this request.
- **Availability** stays the typed `_probe_grok_remote` path (now a thin wrapper
  over the shared `workbay_protocol.remote_probe.probe_remote_gate`, extracted
  so the installer and orchestrator cannot drift).
- **Secondary (docs)**: the `/offload` skill now lists
  `grok-remote | grok-cli | codex-subagent` and gains a native remote-preference
  section, plus a new `docs/workbay/rules/offload-remote-playbook.md` — on
  `feature/wb-remote-delegation-native-01-plan0152` (Plan 0152).

## Also relevant to this consumer

The same branch adds install-scoped remote preference: `workbay-bootstrap
install --with-remote` (or `repair --with-remote`) records
`execution_mode: remote_only` in `.workbay-bootstrap.json`; offload defaults
then flip to `grok-remote` and explicit local backends are refused with a typed
`remote_required` outcome — so the FIR-2-style dispatch needs no per-call
backend pinning once the consumer opts in.

## Release vehicle

Next `workbay` stack release after `feature/wb-install-remote-mode-01` (0145)
and `feature/wb-remote-delegation-native-01-plan0152` (0152) merge; will bump
`mcp-workbay-orchestrator` past 0.2.12. Until then the observed workaround
(skip preflight's admission facet; the pass engine's own gate resolves
`COST_REMOTE` → allow) remains correct and etiquette-clean — do not use
`admission_override=true` for this.
