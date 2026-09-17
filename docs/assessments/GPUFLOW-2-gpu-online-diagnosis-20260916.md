# GPUFLOW-2 GPU-online diagnosis — 2026-09-16

Status: Slice 0 assessment committed as an operator evidence gate. The cause is
classified; the remaining live values below are deliberately marked
`NOT CAPTURED` because this read-only agent has no VM, network, Docker, journal,
or deployed-environment access.

## Decision

The classified root cause is **stale API deployment**, not an exhausted
readiness probe. The two API hosts were recorded by the planning session at
`commit_sha 51ff7022` (2026-09-16 23:01 UTC), before the GPUFLOW-1 demand-lease
producer was deployed. With the service still on that build, a stopped GPU has
no `lease_demand` publication for a single-image Suggest, so the start cycle
sees zero work and does not issue `START`. This is the frozen Slice 0
classification and is not re-derived from an agent-side live probe
([task plan:203-212](../tasks/v0.5.0/GPUFLOW-2-durable-describe-roster-identity-and-cluster-recovery-task-plan.md#L203-L212)).

The stale-deploy finding does not close the wave. Gate R remains open until the
operator records the checks in [Gate R](#gate-r--operator-evidence-checklist)
on the integrated HEAD. Provisioning or environment failures remain named
operator gates, not reasons to substitute a CPU-only release.

## a3_required: false

A3 is **not required by this diagnosis**. The tree has an explicit lifecycle
path from readiness timeout/stall to a typed fallback and then to a `DEGRADED`
snapshot: `WarmReadinessWait` supplies timed-out/stalled IDs to the fallback
builder ([infra/oci/gpu_lifecycle/reaper.py:3055-3087](../../infra/oci/gpu_lifecycle/reaper.py#L3055-L3087));
the start cycle selects `DEGRADED` whenever fallbacks exist and writes the
fallback reason into the snapshot ([infra/oci/gpu_lifecycle/reaper.py:3279-3319](../../infra/oci/gpu_lifecycle/reaper.py#L3279-L3319)).
The API reader rejects missing, malformed, unknown, future-skewed, and stale
snapshots rather than fabricating `READY` ([apps/prototype-description-service/scene/application/gpu_state.py:1-6](../../apps/prototype-description-service/scene/application/gpu_state.py#L1-L6),
[apps/prototype-description-service/scene/application/gpu_state.py:119-165](../../apps/prototype-description-service/scene/application/gpu_state.py#L119-L165)).
No repository evidence shows the reaper/state snapshot reporting `READY` while
the adapter is unready. The unresolved gap is deployment proof, not a tree
provenance gap; the deployed version and the last two start-cycle excerpts are
therefore Gate R inputs.

## Recorded evidence boundary

The planning session recorded the following facts at 2026-09-16 23:01 UTC.
They are copied here verbatim as the frozen Slice 0 baseline; they are not new
agent captures.

| Evidence item | Recorded value | Status | Source / consequence |
| --- | --- | --- | --- |
| API service commit | Both API hosts: `commit_sha 51ff7022` | CAPTURED by planning session | The task plan records both host values and identifies the build as pre-demand publication ([task plan:207-210](../tasks/v0.5.0/GPUFLOW-2-durable-describe-roster-identity-and-cluster-recovery-task-plan.md#L207-L210)). |
| Lifecycle timers | Start timer active at 30 s; reap timer active at 2 min | CAPTURED by planning session | The timer cadence is consistent with the repository's controller comments ([apps/prototype-description-service/scene/application/describe_load.py:67-74](../../apps/prototype-description-service/scene/application/describe_load.py#L67-L74)). |
| GPU lifecycle snapshot | `gpu-state.json`: `stopped`, with an instance OCID | CAPTURED by planning session | A stopped instance is the state for which the controller can emit `START` when trustworthy work exists ([infra/oci/gpu_lifecycle/controller.py:71-97](../../infra/oci/gpu_lifecycle/controller.py#L71-L97)). |
| Environment load files | All environment files reported zero work and legacy keys; no `lease_demand` or `revision` | CAPTURED by planning session | Current producer code emits `lease_demand` and a positive `revision` ([apps/prototype-description-service/scene/application/describe_load.py:392-449](../../apps/prototype-description-service/scene/application/describe_load.py#L392-L449)). |
| GPU intent | No intent file | CAPTURED by planning session | Automatic lifecycle behavior remains the expected mode; an operator `stop` would suppress `START` ([docs/workbay/contracts/gpu-lifecycle.md:56-72](../../docs/workbay/contracts/gpu-lifecycle.md#L56-L72)). |
| Demo plugin | Version `0.0.23` | CAPTURED by planning session | This identifies the client surface whose 120-second ceiling is recorded below. |
| A10 service limit and `acx_gpu_burst` instance list | **NOT CAPTURED** | Operator pending | Gate R must confirm quota and the intended instance; quota and capacity are separate checks ([infra/oci/GPU-BURST-PROVISIONING.md:21-31](../../infra/oci/GPU-BURST-PROVISIONING.md#L21-L31)). |
| API-host adapter and endpoint environment | **NOT CAPTURED** | Operator pending | The deployed values must be read from the API host, not inferred from a checked-in example. |
| Deployed `gpu_lifecycle` version and `reaper.py` fallback path | **NOT CAPTURED** | Operator pending | The tree path exists; deployed provenance is required before treating it as live. |
| Last two start-cycle journal excerpts | **NOT CAPTURED** | Operator pending | Expected lines and command are in Gate R. |
| `/health/detailed` body | **NOT CAPTURED** | Operator pending | The response must identify the configured adapter and readiness state. |
| WP transient circuit state | **NOT CAPTURED** | Operator pending | The WP uses a base-URL-derived circuit key ([apps/prototype-wp-alt-context/src/api/class-recognition-circuit-keys.php:11-18](../../apps/prototype-wp-alt-context/src/api/class-recognition-circuit-keys.php#L11-L18)). |
| WP outbox failed rows by age | **NOT CAPTURED** | Operator pending | The table records `status`, `last_attempted_at`, and `first_failed_at` ([apps/prototype-wp-alt-context/src/support/class-life-cycle-manager.php:898-923](../../apps/prototype-wp-alt-context/src/support/class-life-cycle-manager.php#L898-L923)). |

## Repository evidence and causal trace

### 1. Current producer-to-controller contract

The current producer resolves one shared load path and keeps refreshes below the
120-second stale guard ([apps/prototype-description-service/scene/application/describe_load.py:187-220](../../apps/prototype-description-service/scene/application/describe_load.py#L187-L220)).
Its snapshot counts queued/running single work, adds eligible demand leases,
publishes `batch_in_progress`, `lease_demand`, a monotonic `revision`, and
`written_at` ([apps/prototype-description-service/scene/application/describe_load.py:392-449](../../apps/prototype-description-service/scene/application/describe_load.py#L392-L449)).
The controller's `start_needed_instances` emits `START` only when work is
present (or an explicit start intent is active), and only for `STOPPED`
instances ([infra/oci/gpu_lifecycle/controller.py:71-97](../../infra/oci/gpu_lifecycle/controller.py#L71-L97)).

Therefore the captured `51ff7022` deployment plus zero-work legacy snapshots is
sufficient to classify the observed no-start behavior as deploy skew. A
current-main code inspection cannot prove that the deployed process is running
these functions; Gate R must repeat the check against the running image.

### 2. Timeout → fallback → `DEGRADED` → snapshot

| Stage | Tree behavior | Live proof status |
| --- | --- | --- |
| Readiness wait | The worker polls the GPU `/health` endpoint until a bounded `warmup_timeout_seconds` deadline; timeout raises rather than inventing readiness ([apps/prototype-description-service/scene/application/describe_run_worker.py:178-227](../../apps/prototype-description-service/scene/application/describe_run_worker.py#L178-L227)). | **NOT CAPTURED** on the deployed unit. |
| Fallback decision | The lifecycle start path converts timed-out IDs to `reason="readiness_timeout"`, stalled IDs to `reason="readiness_stall"`, and start failures to `reason="start_failed"` ([infra/oci/gpu_lifecycle/reaper.py:3055-3087](../../infra/oci/gpu_lifecycle/reaper.py#L3055-L3087)). | **NOT CAPTURED**; journal excerpt required. |
| State publication | Any fallback selects lifecycle `DEGRADED`; `_state_reason` requires a non-empty reason, and `write_gpu_state_snapshot` writes the state atomically ([infra/oci/gpu_lifecycle/reaper.py:3279-3319](../../infra/oci/gpu_lifecycle/reaper.py#L3279-L3319), [infra/oci/gpu_lifecycle/state_snapshot.py:304-313](../../infra/oci/gpu_lifecycle/state_snapshot.py#L304-L313), [infra/oci/gpu_lifecycle/state_snapshot.py:479-516](../../infra/oci/gpu_lifecycle/state_snapshot.py#L479-L516)). | **NOT CAPTURED**; compare `gpu-state.json.reason` to the journal reason. |
| API read | `_ensure_gpu_ready` blocks `UNKNOWN`/`DEGRADED` as unavailable and returns a starting envelope for `STOPPED`/`STARTING`/`WARMING` ([apps/prototype-description-service/scene/interface_adapters/http/routers/describe.py:765-849](../../apps/prototype-description-service/scene/interface_adapters/http/routers/describe.py#L765-L849)). | Current tree path is present; deployed response is **NOT CAPTURED**. |
| Reason forwarding | The current typed helper includes `code`, message, operation IDs, timing, optional warmup ETA, and `Retry-After`, but no lifecycle reason ([apps/prototype-description-service/scene/interface_adapters/http/routers/describe.py:336-359](../../apps/prototype-description-service/scene/interface_adapters/http/routers/describe.py#L336-L359)). | This is a Slice A contract gap, not a reason to reclassify the stale deploy. |

The lifecycle state reduction is fail-closed: an empty instance list is
`DEGRADED`, and a current `DEGRADED` or `READY` probe verdict outranks
`WARMING`; OCI `RUNNING` alone does not prove readiness
([infra/oci/gpu_lifecycle/state_snapshot.py:233-256](../../infra/oci/gpu_lifecycle/state_snapshot.py#L233-L256)).
This is why the A3 decision is false while the deployed-version gate remains
mandatory.

### 3. Residual client defects after the redeploy

The service's default GPU warm-up budget is 510 seconds, with the same setting
carried into the GPU run policy ([apps/prototype-description-service/scene/config/settings.py:18-39](../../apps/prototype-description-service/scene/config/settings.py#L18-L39), [apps/prototype-description-service/scene/application/describe_run_worker.py:160-175](../../apps/prototype-description-service/scene/application/describe_run_worker.py#L160-L175)).
The client still caps a Suggest's total warming window at 120 seconds and
clears the lease when that ceiling is reached
([apps/prototype-wp-alt-context/js/admin/hooks/useDescribeMedia.ts:27-35](../../apps/prototype-wp-alt-context/js/admin/hooks/useDescribeMedia.ts#L27-L35), [apps/prototype-wp-alt-context/js/admin/hooks/useDescribeMedia.ts:121-148](../../apps/prototype-wp-alt-context/js/admin/hooks/useDescribeMedia.ts#L121-L148), [apps/prototype-wp-alt-context/js/admin/hooks/useDescribeMedia.ts:171-195](../../apps/prototype-wp-alt-context/js/admin/hooks/useDescribeMedia.ts#L171-L195)).
The client tests pin this ceiling and retry behavior, including the 5-second
fallback when no ETA is supplied ([apps/prototype-wp-alt-context/js/admin/hooks/__tests__/useDescribeMedia.test.tsx:380-423](../../apps/prototype-wp-alt-context/js/admin/hooks/__tests__/useDescribeMedia.test.tsx#L380-L423)).
This is the A5 residual; it is not evidence that the lifecycle readiness probe
exhausts prematurely.

The idle workbench chip is intentionally suppressed when there is no active run:
`MediaSelection` passes `isRunRelevant={runId !== null || isRunning}`
([apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaSelection.tsx:557-565](../../apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaSelection.tsx#L557-L565)),
and `GpuTierStatus` returns `null` when that flag is false
([apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaSelection.tsx:760-773](../../apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaSelection.tsx#L760-L773)).
The chip's vocabulary otherwise has explicit `unknown`, `stopped`, `starting`,
`warming`, `ready`, and `degraded` labels
([apps/prototype-wp-alt-context/js/admin/pages/workbench/gpuStatePresentation.ts:40-58](../../apps/prototype-wp-alt-context/js/admin/pages/workbench/gpuStatePresentation.ts#L40-L58), [apps/prototype-wp-alt-context/js/admin/pages/workbench/gpuStatePresentation.ts:65-106](../../apps/prototype-wp-alt-context/js/admin/pages/workbench/gpuStatePresentation.ts#L65-L106)).
This is the A8 residual: idle absence is a UI visibility defect, not A3
readiness-probe exhaustion.

## Recognition evidence rows

No live database or operator export was available to this lane. `NOT CAPTURED`
means no numeric value or identity identifier is inferred from a name in UI copy,
a fixture, or an image filename.

### Katy Perry representative row

The repository stores the necessary fields separately: `MediaIdentity` has
`occlusion_severity` and `quality_score` ([apps/prototype-description-service/db/models/identity.py:62-74](../../apps/prototype-description-service/db/models/identity.py#L62-L74)),
and `IdentityClusterRepresentative` stores the representative `identity_id`
and its bounded `quality_score` ([apps/prototype-description-service/db/models/identity.py:244-280](../../apps/prototype-description-service/db/models/identity.py#L244-L280)).
The current guided-demo assessment identifies the Katy cluster as
`68adc97c-f81f-42c3-9e5c-061f16770361`, but that is a tree context identifier,
not the requested live representative row ([docs/assessments/current/guided-prototype-face-recognition-2026-09-05.md:296-300](current/guided-prototype-face-recognition-2026-09-05.md#L296-L300)).

| field | value | status |
| --- | --- | --- |
| cluster label | `Katy Perry` | Tree/demo context only |
| cluster id | `68adc97c-f81f-42c3-9e5c-061f16770361` | Tree/demo context only |
| representative identity id | **NOT CAPTURED** | Operator DB capture required |
| `representative_quality` / stored `quality_score` | **NOT CAPTURED** | Operator DB capture required |
| representative `occlusion_severity` | **NOT CAPTURED** | Operator DB capture required |
| representative media id | **NOT CAPTURED** | Operator DB capture required |
| representative decision | **NOT CAPTURED** | Do not change ranking until C1 calibration is accepted |

The current selector's quality multiplier can consume sharpness, embedding norm,
and occlusion, but it is a no-op when factors are missing or floors are no-op
([apps/prototype-description-service/recognition/application/persistence/representative_selector.py:111-156](../../apps/prototype-description-service/recognition/application/persistence/representative_selector.py#L111-L156)).
Its diverse-representative seed is still the highest-confidence face
([apps/prototype-description-service/recognition/application/persistence/representative_selector.py:206-251](../../apps/prototype-description-service/recognition/application/persistence/representative_selector.py#L206-L251)).
That is sufficient tree evidence for the planned C4 follow-up, but not a
numeric claim about the Katy row.

### Emma Watson triple

The required triple is a live/fixture capture, not a name-resolution claim.
The following values remain pending:

| pair / decision | value | status |
| --- | --- | --- |
| three identity ids | **NOT CAPTURED** | Operator or C1 fixture export required |
| identity-to-identity pairwise cosine (1–2) | **NOT CAPTURED** | Compute from the persisted normalized embeddings |
| pairwise cosine (1–3) | **NOT CAPTURED** | Compute from the persisted normalized embeddings |
| pairwise cosine (2–3) | **NOT CAPTURED** | Compute from the persisted normalized embeddings |
| refinement decision for each pair | **NOT CAPTURED** | Record accepted, split, or abstained with reason |
| resulting cluster / merge-suggestion ids | **NOT CAPTURED** | Never infer from rendered name text |

The schema enforces unit-norm embeddings and persists the cluster member count and
representative identity separately ([apps/prototype-description-service/db/models/identity.py:87-105](../../apps/prototype-description-service/db/models/identity.py#L87-L105), [apps/prototype-description-service/db/models/identity.py:108-123](../../apps/prototype-description-service/db/models/identity.py#L108-L123)).
The C1/C2 plan requires pair-level verification and abstention for a mixed
residual, so this row must remain pending until those numbers exist
([task plan:340-350](../tasks/v0.5.0/GPUFLOW-2-durable-describe-roster-identity-and-cluster-recovery-task-plan.md#L340-L350)).

### Perry/Trudeau mixed group membership

The bundled guided assets include a Katy Perry/Justin Trudeau press image, and
the guided recognition assessment records the tree/demo cluster IDs for Katy and
Trudeau ([apps/prototype-wp-alt-context/js/admin/assets/guided/CREDITS.md:5-13](../../apps/prototype-wp-alt-context/js/admin/assets/guided/CREDITS.md#L5-L13), [docs/assessments/current/guided-prototype-face-recognition-2026-09-05.md:296-300](current/guided-prototype-face-recognition-2026-09-05.md#L296-L300)).
That does not prove that one live residual cluster contains members from both
named people. The membership evidence is therefore:

| field | value | status |
| --- | --- | --- |
| residual cluster id | **NOT CAPTURED** | Operator/C1 export required |
| Perry member identity ids and media ids | **NOT CAPTURED** | Operator/C1 export required |
| Trudeau member identity ids and media ids | **NOT CAPTURED** | Operator/C1 export required |
| pair-level failing member | **NOT CAPTURED** | Required for abstention proof |
| disposition | **PENDING; expected `abstained` / suggestion, never attached** | This is the frozen C2 acceptance rule, not a captured result ([task plan:346-350](../tasks/v0.5.0/GPUFLOW-2-durable-describe-roster-identity-and-cluster-recovery-task-plan.md#L346-L350)) |

## Gate R — operator evidence checklist

Run as the operator account with the least privilege that can read each
artifact; use `sudo` only where the deployment runbook requires it. The `gate`
account cannot read the Docker socket, journal, or compose environment, so a
missing value from that account is **NOT CAPTURED**, not zero.

### Deploy and lifecycle proof

- [ ] **Integrated commit on every API host.** On each staging and production API
  host, run:

  ```bash
  curl -fsS https://<api-host>/health | jq '{commit_sha,image_variant}'
  ```

  Expected: `commit_sha` equals the integrated HEAD SHA (not `51ff7022`) and
  `image_variant` is the intended deployed variant. Attach both bodies and the
  image digest to the Gate R result.

- [ ] **A10 limit and instance list.** Run:

  ```bash
  oci limits value list --compartment-id <tenancy_ocid> \
    --service-name compute --region us-ashburn-1 \
    --query "data[?contains(\"name\",'a10')]"
  oci compute instance list --compartment-id <compartment_ocid> \
    --region us-ashburn-1 --query "data[?contains(\"display-name\",'acx_gpu_burst')]"
  ```

  Expected: the A10 limit is at least `1`, and the instance list contains the
  intended `acx_gpu_burst` instance with its OCID, shape, lifecycle state, and
  private endpoint address. A zero limit or missing instance is an operator
  gate; do not close the wave around it.

- [ ] **API environment and preflight.** Read the deployed producer env without
  printing secrets, then run the repository check with the actual paths:

  ```bash
  sudo grep -E '^(ACX_DESCRIPTION_ADAPTER|ACX_GPU_ENDPOINT_URL|ACX_GPU_ENDPOINT_ALLOWLIST)=' \
    /path/to/prod/.env
  set +e
  sudo /path/to/preflight-gpu-env.sh --check-reaper \
    /path/to/prod/.env /path/to/demo/.env
  preflight_exit="$?"
  set -e
  printf 'preflight_exit=%s\n' "$preflight_exit"
  ```

  Expected: adapter is one of `gpu_qwen30b` or `gpu_qwen30b_ensemble` for a GPU
  deployment, endpoint is an `http://` or `https://` private/allowlisted URL,
  and exit code is `0`. The script's accepted adapter, URL, privacy, and shared
  snapshot-path checks are defined at
  [scripts/deploy/preflight-gpu-env.sh:913-995](../../scripts/deploy/preflight-gpu-env.sh#L913-L995);
  its exact two-file invocation is the deployment contract
  ([scripts/deploy/preflight-gpu-env.sh:17-30](../../scripts/deploy/preflight-gpu-env.sh#L17-L30)).
  If the adapter is not `gpu_*`, the endpoint is unset/non-private, or the
  preflight is non-zero, record the failed value and the named re-check as an
  operator gate under RLSE-02.

- [ ] **Deployed lifecycle code and journal.** On the lifecycle host run:

  ```bash
  sudo sha256sum /opt/acx-gpu/infra/oci/gpu_lifecycle/reaper.py
  sudo grep -n -E 'readiness_timeout|readiness_stall|fallback_on_boot_failure' \
    /opt/acx-gpu/infra/oci/gpu_lifecycle/reaper.py
  sudo journalctl -u acx-gpu-start.service -n 200 --no-pager \
    | grep -E 'START|readiness_timeout|readiness_stall|DEGRADED|gpu-state'
  ```

  Expected: the deployed file contains the fallback path; attach the last two
  complete start-cycle excerpts, including whether the cycle decided or
  refused `START`, its load revision, and its state/reason publication. A
  missing fallback path is a deployment gate and routes to infra-ready-degrade
  only after the integrated image check is complete.

### Runtime evidence after deploy

- [ ] **Load revision before and after one cold Suggest.** Before the click and
  30 seconds after it, record every declared environment file:

  ```bash
  for env in dev staging prod; do
    sudo jq '{queue_depth,in_flight,batch_in_progress,lease_demand,revision,written_at}' \
      "/run/acx-write/$env/describe-load.json"
  done
  ```

  Expected after the integrated service accepts a cold Suggest against a
  stopped GPU: the relevant environment has `lease_demand >= 1`, a positive
  monotonic `revision`, and a fresh `written_at`; the next start cycle has one
  `START` for the stopped instance. The recommended run is not a gate by itself,
  but it provides the A5/A9 cold-boot measurement.

- [ ] **GPU state and health.** Record:

  ```bash
  sudo jq . /run/acx/gpu-state.json
  curl -fsS https://<api-host>/health/detailed | jq .
  ```

  Expected: state transitions `stopped` → `starting`/`warming` → `ready` for a
  successful cold path, or `degraded` with a non-empty lifecycle reason for a
  bounded readiness failure. The health body must identify the same configured
  adapter profile; never infer `ready` from an OCI `RUNNING` state alone.

- [ ] **WP circuit and outbox.** On the WordPress host, query the existing sync
  health endpoint and read-only tables:

  ```bash
  curl -fsS https://demo.altcontext.com/wp-json/acx/v1/recognition/sync/health \
    | jq '{breaker,outbox}'
  wp db query "SELECT CASE WHEN first_failed_at IS NULL THEN 'missing_first_failed_at' WHEN first_failed_at >= DATE_SUB(NOW(), INTERVAL 1 DAY) THEN '<1d' WHEN first_failed_at >= DATE_SUB(NOW(), INTERVAL 7 DAY) THEN '1-7d' ELSE '>=7d' END AS age_bucket, COUNT(*) AS rows, MIN(first_failed_at) AS oldest_first_failure, MAX(last_attempted_at) AS newest_attempt FROM wp_acx_sync_outbox WHERE status = 'failed' GROUP BY age_bucket ORDER BY age_bucket"
  ```

  Expected: the breaker state is explicitly `open` or `closed`, the failed
  count is numeric in each age bucket, and the outbox result is attached with
  age. For the exact route-family transient, compute the base key from the
  configured recognition URL using `RecognitionCircuitKeys::for_base_url()` and
  inspect the `describe` suffix; do not paste the URL or transient value into a
  public report. The
  health controller reads the base key and failed count at
  [class-sync-health-controller.php:61-79](../../apps/prototype-wp-alt-context/src/api/class-sync-health-controller.php#L61-L79),
  while the describe proxy uses the `describe` route-family suffix
  ([class-abstract-recognition-proxy-controller.php:552-569](../../apps/prototype-wp-alt-context/src/api/class-abstract-recognition-proxy-controller.php#L552-L569)).

## B7 decision

The orchestrator decision is taken for this wave: **compact per-image icon
toggle with a tooltip/`aria-label`; no global decorative-image configuration**.
The control remains scoped to the selected image/row so it cannot violate the
alt/decorative exclusivity invariant. This assessment does not dispatch or alter
B7 code.

## Handoff and residual risk

This assessment is complete for the agent-owned Slice 0 artifact. The stale
deploy classification is actionable, `a3_required` is explicit, and every
operator-only value has a named capture or re-check. Residual risks for
`infra-ready-degrade` and the downstream A lanes are:

1. Until Gate R records the integrated HEAD on both API hosts, current-main
   lifecycle code remains unproven in production and no live `START` claim is
   valid.
2. The deployed adapter, private endpoint, A10 limit, and instance state remain
   unverified; any failed check blocks Gate R and requires the named re-check.
3. Even after redeploy, A5 must replace the client 120-second total ceiling with
   the service-advertised 510-second startup budget, and A8 must make idle
   status visible. These are residual client defects, not grounds for A3.
4. The Katy/Watson/Perry-Trudeau recognition values remain unmeasured here;
   C1/C4/C2 must not invent thresholds, representative scores, pairwise cosines,
   or merge membership from names or image fixtures.
