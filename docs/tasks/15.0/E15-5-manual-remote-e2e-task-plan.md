# E15-5. Remote E2E Verification + ARM Evidence (MVP-critical)

> **Task Short ID**: E15-5
> **Status**: scoped -- not started
> **Epic**: [E15. Public Demo Launch Readiness](../../epics/v0.4.0/public-demo-launch-readiness-epic.md) Phase 4
> **Predecessors**: [E15-3](./E15-3-wordpress-demo-provisioning-task-plan.md) (WP demo live)
> **Blocks**: MVP demo-URL-live signal. Once this closes, E15 MVP is shippable.
> **Sibling**: [E15-4](./E15-4-local-reset-bootstrap-hardening-task-plan.md) continues in parallel but does not gate E15-5.
> **Apr 2026 scope split**: Original Slices 2, 3, and 4 (budget alerts, Tailscale SSH hardening, Hetzner fallback plan) moved to [E15-5a](./E15-5a-oci-operational-hygiene-task-plan.md). This task now owns only the public-demo remote round-trip plus the ARM evidence artifact.

---

## Objective

Prove that the full WP -> backend -> recognition round trip works against the live system and capture the missing ARM-compatibility evidence artifact delegated from E14. OCI operational hygiene now lands in [E15-5a](./E15-5a-oci-operational-hygiene-task-plan.md) before this task runs.

## MVP Exit Criteria

1. A manual round-trip through the live WP demo returns recognition results, captured in a run log.
2. The ARM compatibility evidence artifact is captured and linked from this task.

Both are required. Partial completion does not unlock E15-5.

## Slice Plan

### Slice 1 -- Manual round-trip + run log

- From the public WP URL, trigger a recognition scan against the seeded media.
- Capture: timestamp, WP origin, backend correlation IDs (pulled from `/metrics` or log tail), observed latency percentiles, any errors.
- File the evidence as `docs/tasks/15.0/E15-5-mvp-round-trip-log.md`.
- Reuse the `E15-22 proof bundle` headings from `docs/tasks/15.0/E15-3a-localwp-oci-run-log.md` or `docs/tasks/15.0/E15-3-mvp-run-log.md` when the build and seeded-media set match; if the live site requires recapture, keep the same headings so avatar/progress success criteria are not redefined.
- Capture the ARM compatibility evidence that E14 delegated into this task: `uname -m`, container image architecture, a representative `pip freeze` or install transcript showing `aarch64` wheels where relevant, and a passing integration-test transcript against the live A1 instance. File it as `docs/tasks/15.0/E15-5-arm-compat-evidence.md`.
- If the round-trip fails, open a blocker against the active handoff and stop here; resolve before continuing.

Exit: run log filed; green round-trip confirmed.

## Deliverables

- `docs/tasks/15.0/E15-5-mvp-round-trip-log.md`
- `docs/tasks/15.0/E15-5-arm-compat-evidence.md`
- `docs/tasks/15.0/E15-5-mvp-round-trip-log.md` preserves the named `E15-22 proof bundle` sections for representative avatar evidence, monotonic processed-count evidence, and `Scan complete` timing evidence.

## Dependencies Not Owned Here

- E15-3 WP demo live (hard predecessor).
- E15-5a OCI operational hygiene complete enough that the backend is cost-safe, SSH-reachable, and backed by a documented fallback plan before public-demo execution.

## Risks

- **Round-trip fails** -- indicates a gap between E15-1/E15-2 verification and real-world use. Mitigation: Slice 1 stops immediately and opens a blocker; root-cause before continuing.
- **ARM evidence incomplete** -- the environment is working but the artifact is too thin to satisfy the E14 follow-on requirement. Mitigation: do not close the task until `uname -m`, image architecture, dependency evidence, and an integration-test transcript are all captured.

## Consolidated Checklist

> **Checklist scope rule:** Describe work being delivered, not finding status. Do not add rows like `(BR-04 closed)` or "resolve handoff issue X"; finding status lives in MCP / `DASHBOARD.txt`.

## Context and Ownership

- [ ] Loaded the live-demo task context, E14 ARM evidence requirement, and current handoff state before running the remote pass.
- [ ] Confirmed no extra external dependency context is required beyond the live WP demo, backend observability surfaces, and ARM evidence anchors already cited here.
- [ ] Kept the April 2026 scope split intact: E15-5 owns only the remote round-trip and ARM artifact, while OCI hygiene remains in E15-5a.

### Checklist for Slice 1: Manual round-trip + run log

- [ ] Trigger a live recognition scan from the public WP demo against the seeded media set.
- [ ] Capture timestamp, WP origin, backend correlation IDs, latency evidence, and any errors in `E15-5-mvp-round-trip-log.md`.
- [ ] Reuse or recapture the same `E15-22 proof bundle` headings that E15-3a and E15-3 use, so live-demo execution does not redefine avatar/progress success.
- [ ] File `E15-5-arm-compat-evidence.md` with `uname -m`, image architecture, dependency evidence, and a passing live A1 integration-test transcript.

## Review Readiness

- [ ] A failed live round-trip opens a blocker immediately and stops task closure.
- [ ] The ARM evidence artifact is complete enough to satisfy the E14 delegation without follow-up archaeology.
- [ ] The remote pass consumes the same E15-22 proof bundle headings used by E15-3a/E15-3, even if screenshots or transcripts are recaptured on the live site.
- [ ] Handoff records the slice-complete decision only after both deliverables are attached.

## Success Criteria

- [ ] The live public-demo round-trip succeeds and is documented in `E15-5-mvp-round-trip-log.md`.
- [ ] The live run log preserves the seeded-media avatar/progress proof bundle contract inherited from E15-22.
- [ ] The ARM compatibility evidence artifact is captured, linked, and sufficient to close the outstanding E14 follow-on.

## Handoff

When done, set `E15-5` status to `done`, archive, and record a slice-complete decision covering the remote E2E pass plus the ARM evidence artifact. E15 Phase 4 closes only when [E15-4](./E15-4-local-reset-bootstrap-hardening-task-plan.md) and [E15-5a](./E15-5a-oci-operational-hygiene-task-plan.md) are also complete.
