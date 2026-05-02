# Local vs OCI Description-Service: Drift Detection & Consolidation/Retirement Decision

**Status:** Deferred (tech-debt registry entry)
**Origin:** Superseded `MAINT-local-vs-oci-description-service-assessment-20260430`. Closed as `wontfix`/archived 2026-05-02 because E15-12 (recognition-source selector) and ACXDEV-1 (dev backend switcher) durably solved the *switching ergonomics* portion of the original scope. The remaining *drift detection* and *consolidation/retirement* questions are real but unaddressed; they live here so they can be revived as a focused task if drift surfaces or a strategic call is needed.

## Background

The plugin can talk to two description-service implementations:

- **Local** — in-process / same-host service used by LocalWP and dev workflows.
- **OCI** — remote service deployed via `mk/deploy.mk` and `scripts/deploy/recognition-service.sh`.

E15-12 made the active backend an explicit `service|local` mode contract (settings API, runtime resolution, UI copy, tests). That fixed runtime ergonomics and eliminated the accidental blank-URL fallback. It did **not** answer:

1. Whether the two implementations have drifted in behavior (validation, error shape, latency budgets, response schema, retry semantics).
2. Whether one of them should be retired or both kept indefinitely.

## Open Questions

- **Drift surface**: do local and OCI return identical schemas for the same input? Identical error shapes? Identical recognition outputs given the same model versions? Are there code paths that exist only on one side?
- **Drift trigger**: what would make us *notice* drift today? Is there a parity smoke we can run periodically, or do we only learn about drift when a user reports a UX difference?
- **Retirement criteria**: under what conditions would we retire local? Under what conditions would we retire OCI? What does each cost to keep alive?
- **Consolidation path**: if both stay, is there a shared contract surface (OpenAPI / typed client) that both implementations must conform to, with a parity test suite enforcing it?

## Why Defer

- Switching ergonomics — the user-visible failure mode that motivated the original assessment — is now solved in code with tests, not a doc.
- No active drift incident is open. Nobody is blocked.
- A meaningful drift assessment requires running both backends side-by-side with matching inputs; that is a small experiment, not a paragraph in a doc.

## Reopen Triggers

Convert this entry into a dated task plan (and revive a MAINT or feature task) if **any** of the following occur:

- A user-visible behavior difference between local and OCI is reported.
- A schema or contract change ships to one backend without the other (catch via `docs/agentic/contracts/` review).
- A consolidation/retirement decision becomes load-bearing for a roadmap item (e.g., self-hosting epic needs to commit to one path).
- Recognition-service code paths visibly diverge in `apps/prototype-description-service/` vs. the local fallback.

## When Picked Up

Promote into `docs/tasks/<epic>/<slug>-task-plan.md` with at least:

- A parity smoke that runs the same fixture inputs against local and OCI and diffs the responses.
- A short written assessment covering the four "Open Questions" above.
- A consolidation/retirement recommendation with explicit accept/defer rationale.
- Owning surfaces: `apps/prototype-description-service/`, `scripts/deploy/recognition-service.sh`, `infra/oci/`, plugin `class-abstract-recognition-proxy-controller.php`.

## References

- E15-12 task plan: `docs/tasks/15.0/E15-12-standard-deployment-reset-and-recognition-source-task-plan.md`
- E15-12 scope: `docs/scopes/e15-12-deploy-reset-and-recognition-source-scope.md`
- ACXDEV-1 (plugin backend switcher): plan landed in commit `8fab4d63`
- Original MAINT objective: "Assess local vs OCI description-service implementations: drift, switching ergonomics, consolidation/retirement options. Output: docs/assessments/local-vs-oci-description-service-assessment-2026-04-30.md" (assessment doc was never written; intentionally not produced).
