# Tech-Debt Archive or Transfer Candidates

This folder holds tech-debt notes that should no longer compete with active app implementation tasks in `docs/tasks/tech-debt/`.

| File | Disposition | Reason |
| --- | --- | --- |
| `dynamic-ip-ssh-access.md` | Archive | Tailscale is now documented as the canonical OCI SSH path and deploy scripts default to Tailscale MagicDNS. |
| `hardcoded-local-paths-in-tracked-configs.md` | Archive | Tracked tool configs no longer contain hardcoded `/Users/daniel/...` paths. |
| `terminal-guard-test-performance.md` | Archive | The terminal guard test suite now uses in-process classification checks and passed in under one second. |
| `pds-pipeline-stability-26-task-plan.md` | Archive after closure evidence | App implementation is present; only lifecycle/review close evidence remains to confirm. |
| `lane-orchestration-followups.md` | Transfer or archive | This is agentic/MCP process debt, not app tech debt; if still relevant, move to the agentic protocol surface. |
| `maint-aomcp-quality-fixes-20260419.md` | Transfer or archive | The in-monorepo MCP package sources are gone; residual quality work belongs to the standalone MCP repos. |
| `migrate-pip-to-uv.md` | Ownership decision | If this means description-service app install speed, keep a new app-scoped task here; if it means shared agentic tooling installs, move it to the agentic protocol repo. |
