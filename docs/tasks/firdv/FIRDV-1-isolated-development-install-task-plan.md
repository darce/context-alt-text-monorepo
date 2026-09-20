# Task Plan

> **Metadata**
>
> - **Date**: 2026-09-19
> - **Author**: Codex
> - **Status**: draft; not implemented or live-verified
> - **Owning Epic**: [E24](../../epics/v0.5.0/fir-development-and-measurement-epic.md)
> - **Epic Short ID**: FIRDV
> - **Task ID**: `FIRDV-1`
> - **Target Branch**: `feature/firdv-1`
> - **Review Coverage Target**: 2

## Objective and intake

A fresh LocalWP site must use an isolated remote FIR-only backend and its own 128D identity database, then save a real remote self-hosted description. User confirmed this topology and self-hosted-only model scope; [scope](../../scopes/fir-development-and-measurement-wave.md) records proposed failure policy and the separate quality gate. This task implements the initial 128D integration baseline. The requested final 512D development route is delivered by FIRDV-3 S6 using these same isolation/readiness contracts; completing this task alone does not complete the wave. See the [start-here guide](../../roadmaps/fir-localwp-512d-implementation-roadmap-2026-09-19.md). This is not a production switch or an occlusion accuracy claim.

## Load before work

- [Current-state assessment](../../assessments/current/fir-development-wave-assessment-2026-09-19.md), especially deployment/image/auth gaps.
- [FIR23-STACK plan](../fir23-stack/FIR23-STACK-task-plan.md), handoff decision **4315** (tooling merged), **3250** (isolated development), and current runtime code rather than stale “not implemented” prose.
- `apps/prototype-description-service/.env.fir.example`, `apps/prototype-description-service/docker-compose.env.yml`, root `scripts/deploy/recognition-service.sh`, [GPU environment runbook](../../runbooks/gpu-demo-env-flip.md) §1b.
- `apps/prototype-description-service/recognition/infrastructure/embeddings/{runtime_factory,face_pipeline_adapter}.py`, `recognition/application/embedding/manifest.py`, `recognition/config/settings.py`.
- Installed WorkBay branch/TDD/offload instructions; discover code with codemap and semantic prior work through handoff. Confirm current HEAD and active ownership before editing.

## Target contract

| Boundary | Required evidence / behavior |
| --- | --- |
| WordPress → API | PHP multipart image-byte upload to authenticated remote ingress; no fetch of a LocalWP `.local` URL. Site-specific tenant/key and plugin settings. TLS validation stays enabled. |
| API and worker | Both effective profiles are `face_pipeline`, dimension 128, same declared model/preprocessing contract and pinned application image digest. Missing or contradictory evidence refuses readiness. |
| Model assets | YuNet/SFace loaded from the mounted directory, weight hashes and runtime/toolchain recorded; active embedding token `opencv-sface@128d/l2/cosine`. Validate actual loaded assets, not filenames alone. |
| Database | Actual server/extension versions, database/role identity, applicable vector column typmods, representative embeddings/centroids and model stamps prove 128D compatible space. Empty tables require schema/model proof, not a fabricated sample. |
| Isolation | Compose project `acx-dev-fir`, own network, PG storage, blob namespace and credentials; no production/dev-incumbent writes. Independent immutable image reference and rollback. Names alone do not establish isolation. |
| Description | Actual self-hosted remote model ID/revision and serving profile in correlated run evidence; a seeded/stub response cannot satisfy smoke acceptance. |
| Failures | No InsightFace fallback. Unknown/abstained faces never become unverified names. If captioning without identity is supported, preserve that explicit status; otherwise emit the existing typed failure. Service outages remain failures and retry costs remain observable. |

## S1 — runtime evidence contract: RED, then implementation

**First bounded slice.** Add an offline validator consuming a redacted runtime snapshot. Proposed home: `apps/prototype-description-service/scripts/validate_fir_dev_runtime.py`; proposed tests: `recognition/tests/unit/test_fir_dev_runtime_contract.py` within that application. These paths are **planned**, not executable today; use an existing equivalent if discovery finds one and document the substitution before implementation.

Snapshot schema v1 includes `captured_at`, deployment/environment and tenant identifiers, source git SHA, API/worker image digests, effective profile/dimension/model/preprocessing IDs, loaded weight hashes, actual database identity/version/extension, typed vector-column inventory, embedding provenance summary, authentication-enabled status, storage/network identifiers and description adapter/model identity. No passwords, keys, connection URLs, image pixels or personal names. Each item identifies how it was observed; env declarations alone are explicitly `declared`, never `observed`.

Validator returns a machine-readable status plus stable reason codes: `ready`, `incomplete` (required evidence missing), or `invalid` (contradiction), with nonzero exit for the latter two. A stale snapshot is not current readiness; freshness is a supplied policy value recorded with the result. Do not invent an arbitrary production SLO. Non-finite vectors, wrong dimension, foreign model stamps or model-hash mismatch invalidate the relevant check. Empty storage can be ready to enroll if schema and loaded runtime are verified; nonempty storage needs row/provenance checks.

RED cases: valid empty FIR store; valid enrolled FIR store; API128/worker512; DB512 with both envs128; same dimension but different model/preprocessing; missing model hashes; unverified actual DB; stale snapshot; auth disabled; seeded description adapter; API/worker different image; forbidden shared storage; and a report-redaction fixture with sentinel secrets. Failure assertions target reason codes and public contract, not an implementation's helper structure.

After tests are reviewed, implement the validator. Keep live probes separate from this pure contract. Existing dimension checks stay authoritative inside the runtime; this instrument joins observed evidence across deployment boundaries.

## S2 — deployment isolation and evidence collection

Adapt FIR23 tooling rather than create another deployment system. Resolve the current shared `dev` image tag into a separately pinned dev-fir image; preserve API/worker agreement and image variant required for real captions. Turn on API-key authentication and provision a dedicated tenant using existing key flows. Use secret references and redacted diagnostics.

Add a read-only operator evidence collector using existing service/admin/deploy mechanisms. It must query actual database schema and runtime status under appropriate scoped access; application JSON env fields cannot prove database typmods. Do not expose a new public database-inspection API just for this task. Database credentials stay remote. Verify all applicable vector-bearing tables/views through schema discovery, not a single hard-coded media column.

Test config rendering and fail-closed mapping with temporary configuration fixtures. Assert only dev-fir resources are selected by stop/reset/rollback operations. Update private ingress or authenticated TLS routing for the remote API. A public WordPress endpoint is unnecessary. Register the dev-fir GPU load producer **only after** its own fresh `describe-load.json` exists; verify the other environments can still start/stop safely. Reuse existing deadlines and lease controls.

## S3 — provision and verify the isolated remote stack

Inspect remote resource inventory first. If `alt_context_dev_fir` or its volume already exists, identify contents/owner and preserve it; use a fresh named resource or an explicit migration plan instead of destructive reset. Create the isolated role/database/storage/network, apply migrations under `PGVECTOR_DIM=128`, mount verified YuNet/SFace assets read-only and start FIR API/worker. Record exact PostgreSQL and pgvector versions and image digests; no PG19 migration.

Run the evidence collector/validator against actual state. Enroll a tiny authorized smoke set by re-extracting FIR vectors from original pixels. Do not import 512D vectors, old cluster IDs, or an incumbent gallery. Check representative embeddings and derived centroids. Confirm loaded model identity and no runtime route to InsightFace. Record the resource inventory and rollback procedure with secrets removed.

## S4 — fresh LocalWP installation and end-to-end smoke

Create a new site, suggested name `altcontext-fir-dev`, after checking for a name collision. Record its actual filesystem location, WP/PHP/plugin revisions and plugin build source. Use its own WP database and clean plugin settings. Configure the authenticated remote endpoint and dedicated tenant/key in server-side settings. Do not clone stale recognition/job/cluster state from the existing demo.

From the plugin UI: upload a small authorized fixture → scan through FIR → inspect/confirm a roster identity → request a real remote description → save the result as a WP draft/attachment field. Keep confirmation in the loop; no automatic unverified naming. Capture request/run IDs and sanitized output evidence. Repeat with an unknown person and a multi-person fixture to check name placement, not just presence of the right names. An existing grounding gate may limit the supported case; report that limitation instead of enabling unqualified multi-person behavior.

Prove the remote service received bytes and did not fetch the local site's URL. Check tenant separation with a second fixture tenant or sanctioned isolation test. Retain media evidence locally/private; checked-in runbooks use opaque IDs and redacted summaries.

## S5 — failure, restart and rollback acceptance

Exercise malformed/missing landmarks, unknown identity, unavailable model/description service, expired credentials, request retry and service restart. Use deterministic fixtures for destructive fault injection; do not corrupt a live shared DB. Record terminal states and ensure a retried logical request does not duplicate enrollment or caption saves.

Restart the isolated stack and verify persistence. Rehearse rollback to its previous pinned image/config against compatible schema (restore a dedicated snapshot when needed). Confirm incumbent dev/prod resource identities and health remain unchanged. A DB destructive reset is not the rollback plan. Deliver a reproducible runbook and readiness report distinguishing observed live evidence from tests.

## Verification and acceptance

S1 planned test command from `apps/prototype-description-service`:

```sh
uv run pytest recognition/tests/unit/test_fir_dev_runtime_contract.py
```

The RED dispatch must demonstrate meaningful assertion failures against the missing behavior, not merely a broken import or zero collected tests. The implementation dispatch must pass these cases and affected existing FIR/deploy tests. S3/S4 require live evidence; mocked tests cannot mark SC-01 or actual DB readiness complete. Run repository-required review checks at the relevant slice boundaries. Scope **SC-01, SC-02, SC-03** are mandatory; record partial coverage of SC-08 provenance.

Deliverables: code/tests, redacted actual-state report, LocalWP setup/recovery runbook, image/DB/model fingerprints, smoke request IDs, explicit limitations. Human occlusion labels and calibrated production thresholds are not prerequisites for this development smoke.

## First dispatch brief — tests only

```text
Task: FIRDV-1 S1 RED only. Backend codex-remote; model gpt-5.6-luna;
reasoning_effort max. Read this plan, linked current-state assessment and
app rules. Confirm current code with codemap and retrieve related handoff
decisions. Add only deterministic contract tests/fixtures for the redacted
runtime-snapshot validator. Cover actual DB/model/API/worker disagreement,
missing evidence, authentication, real description adapter and redaction.
Do not implement the validator, change production defaults, deploy, touch
credentials/private corpus, run a GPU, or bundle benchmark changes.
Run the targeted command and report collected cases plus expected assertion
failures. Hand off reviewed RED tests in a distinct commit. Stop at RED.
```

Use WorkBay preflight/manifest/dispatch and an explicit bounded budget/timeout accepted by the installed runner. The current codex-remote runner requires a minimum 120000 token budget parameter (advisory provider cap), and accepts `max`; use a 900 s bounded pass for this slice and inspect the typed outcome. Do not pass the unsupported `turn_timeout_seconds` knob. Missing transport scripts in an isolated worktree must be repaired from the installed runner, not worked around by changing backend. Review RED before a separate implementation dispatch.

## Not doing / remaining decisions

No corpus relabeling, recognition threshold tuning, model bake-off spend, PG major upgrade, public demo replacement or production default change. Proposed unknown/outage handling must match the existing typed API and UX and be recorded if resolved differently. Remote resource availability, LocalWP actual site path, model assets and credentials are implementation preflight facts; none was verified live by this planning task.

## Consolidated checklist

- [ ] S1 RED tests reviewed, then validator implemented and targeted tests pass
- [ ] S2 independent deployment/auth/evidence collector implemented and failure mappings verified
- [ ] S3 actual isolated remote API/worker/model/database evidence passes validation
- [ ] S4 fresh LocalWP saves a real FIR-backed remote description with correlated run evidence
- [ ] S5 unknown/outage/retry/restart/rollback evidence and reproducible runbook complete
- [ ] SC-01–SC-03 acceptance recorded; partial/proposed evidence never marked live-verified
