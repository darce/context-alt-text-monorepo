# APP-1 legacy finding dispositions — 2026-09-22

Bounded bookkeeping against the current checkout and supplied integrated
receipts. This does not re-review repaired lanes, create findings, provision
accounts, deploy a scheduler, or claim live/provider evidence. Receipt labels
below are coordinator-supplied evidence; repository history was not re-verified
locally.

| stableID | originalscenario | currentexactsource/test/commit evidence | disposition |
| --- | --- | --- | --- |
| `W4USAG-ac21ad4e1d22ef24:M-292d3c26be369c4b9ea2dbc5` | Usage-composition flag off could silently disable admission. | `apps/prototype-description-service/recognition/interface_adapters/http/deps/portal_composition.py::install_portal_composition` wires `UsageAdmissionServiceFactory` into app state without a usage-enable flag; `recognition/interface_adapters/http/deps/usage_admission.py::get_usage_admission_service` validates configured callables, while `::admit_usage` keeps an explicit no-service path for direct/unresolved dependency calls. Wiring/contract coverage: `recognition/tests/unit/test_app1_usage_admission_wiring.py`, `recognition/tests/unit/test_app1_portal_contracts.py`; supplied HTTP receipt `HTTPcb401f2`. | **verifiedfixed** |
| `W4USAG-ac21ad4e1d22ef24:M-557b9b30cb07fe0c03dcda0f` | Admission timeout returned generic 500 with no transient mapping or rollback. | `recognition/interface_adapters/http/deps/usage_admission.py::admit_usage` catches `UsageAdmissionTimeoutError`, rolls back through `::_rollback_usage_transaction`, and emits bounded 503 `reservation_timeout` with `Retry-After`; `recognition/tests/unit/test_app1_usage_admission_wiring.py::test_reservation_timeout_maps_to_bounded_503_without_dispatch` asserts 503, header, rollback, and no dispatch/settlement. Supplied HTTP receipt `HTTPcb401f2`. | **verifiedfixed** |
| `W4USAG-ac21ad4e1d22ef24:M-aeafb97f2cd658c98b6d6e0f` | `402 allowance_exhausted` and `Retry-After` contract/tests were absent. | `recognition/interface_adapters/http/deps/usage_admission.py::_allowance_exhausted` emits 402 with `{"error": "allowance_exhausted"}` and the bounded retry header when applicable; `::admit_usage` maps `AllowanceExceededError`. Contract/wiring coverage is in `recognition/tests/unit/test_app1_usage_admission_wiring.py` and `recognition/tests/unit/test_app1_portal_contracts.py`; supplied HTTP receipt `HTTPcb401f2`. | **verifiedfixed** |
| `W4USAG-ac21ad4e1d22ef24:M-ae59bad2057e1dbacb66bd4d` | Sweeper scheduler/monitoring was absent. | `apps/prototype-description-service/scripts/usage_reservation_sweeper.py` provides a bounded one-run CLI (`--max-batches`, `--batch-size`, stale/no-progress/timeout bounds) and `UsageSettlementService.sweep_stale_reservations`; `recognition/tests/unit/test_app1_usage_sweeper.py` covers active-work protection, stale release, fail-closed stall, and non-zero exit. The supplied G3 receipts `G3core5573906`/`lifecycle62f73ba` support the core sweep, while `residual53df4cd` leaves operational follow-up; no scheduler deployment or monitoring receipt is present. | **named MEDIUM defer — APP1-usage-operations-followup** |
| `APP1-CONT-P04` | Older spec/UI-scope documents still said there was no implementation despite the landed foundation. | Current source and supplied evidence distinguish implementation from acceptance: `docs/assessments/current/app1-offline-evidence-reconciliation-20260922.md` records the W4 usage source/receipt matches and says original B1 UI remains unimplemented; `docs/specs/app-portal-account-billing-spec.md` still contains the older “current code is not this contract” gap framing. The continuation plan explicitly calls this a documentation-only classification (`docs/plans/0002-app-altcontext-launch-continuation-task-plan.md`); supplied evidence/UX/residual labels are `evidence0d1267f`, `b185b5f`, `UXf51327b`, and `residual53df4cd`. | **named MEDIUM defer — APP1-next-maintenance-wave** |

The two defer dispositions are documentation/operations follow-up only; no
auth, privacy, or schema invariant is being silently deferred. No live
provisioning, deployment, or provider rehearsal is claimed.

Verification: the mandated `uv run ... test_app1_portal_contracts.py` command
could not start because uv attempted to mutate the read-only lane virtualenv.
The existing lane interpreter imported `recognition` from this worktree and
ran the same scoped command successfully: **17 passed in 0.18s**.
