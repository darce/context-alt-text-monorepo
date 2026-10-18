# VLM-REALIGN-01 Anchor-Verification Audit (2026-07-12)

> **Task**: `VLM-REALIGN-01` · **Lane**: `VLM-REALIGN-01-audit` · **Branch**: `feature/vlm-realign-01`
>
> Read-only verification of concrete anchors cited in VLM-3 / VLM-4 / VLM-5 task plans against the current worktree. Plans themselves were **not** modified ([AGT-02](../../strategy/engineering-heuristics.md): no unresolved anchors).
>
> **Path convention**: plan paths like `scene/...` resolve under `apps/prototype-description-service/` unless noted. Status: `verified` = present as cited; `drifted` = present but path/line/role changed; `missing` = not found (or hyphen-path typo with no match).

---

## VLM-3 — `docs/tasks/vlm/VLM-3-gpu-detailed-tier-task-plan.md`

| anchor | kind | status | current value |
| --- | --- | --- | --- |
| `docs/scopes/gpu-detailed-tier-oci-bursty-scope.md` | artifact doc | verified | present |
| `docs/workbay/rules/backend-python-guidelines.md` | artifact doc | verified | present |
| `docs/workbay/rules/testing-python.md` | artifact doc | verified | present |
| `docs/epics/v0.3.1/self-hosting-epic.md` | artifact doc | verified | present |
| `docs/workbay/contracts/image-description-api.md` | contract | verified | present |
| `docs/tasks/vlm/VLM-2B-detailed-tier-decision-memo.md` | artifact doc | verified | present |
| `docs/tasks/19.0/E19-1-florence-large-async-worker-impl-notes.md` | artifact doc | verified | present |
| `docs/tasks/vlm/VLM-3-gpu-detailed-tier-decision-memo.md` (planned new) | artifact doc | drifted | exists (Slice 3 already landed) |
| `docs/tasks/vlm/VLM-3-gpu-spike-2026-07-08.json` | artifact doc | verified | present (Slice 1 spike) |
| `infra/oci/main.tf` | file path | verified | present |
| `infra/oci/main.tf:114` (A1-only claim) | file:line | drifted | line ~114 is GPU security-list block; A1 backend at `oci_core_instance.acx_backend` L200; GPU host `oci_core_instance.acx_gpu_burst` L235 |
| `infra/oci/variables.tf` + `gpu_shape` / `VM.GPU.A10.1` | terraform | verified | `variable "gpu_shape"` default `VM.GPU.A10.1` L51 |
| `infra/oci/gpu-lifecycle/` (planned new) | file path | missing | hyphen path absent; real dir is `infra/oci/gpu_lifecycle/` (`controller.py`, `reaper.py`, `__main__.py`) |
| `infra/oci/gpu_lifecycle/controller.py` | file path | verified | present (`GpuLifecycleController`) |
| `infra/oci/gpu_lifecycle/reaper.py` | file path | verified | present (idle reaper CLI) |
| `scene/application/description_adapter.py` | file path | verified | under description-service |
| `description_adapter.py:35` `DescriptionAdapter` | file:line / symbol | verified | `@runtime_checkable class DescriptionAdapter` L35 |
| `AdapterResult` (`description_adapter.py:20` in related VLM-4; implied contract) | symbol | verified | `class AdapterResult` L20 |
| `scene/config/profiles.py` | file path | verified | present |
| `DescriptionProfile.GPU_PHI4` (`profiles.py:87`) | file:line / symbol | verified | `GPU_PHI4` ProfileSpec starts L88 (`available=False`); also `GPU_QWEN30B` L100 `available=True` |
| `scene/interface_adapters/http/routers/deps.py` | file path | missing | no such path; actual `scene/interface_adapters/http/deps.py` |
| `get_description_adapter` (`deps.py:15`) | file:line / symbol | drifted | `def get_description_adapter()` at `http/deps.py:155`; GPU branch L197–`get_gpu_description_adapter()` |
| `scene/infrastructure/provider/hosted_provider_adapter.py` | file path | verified | present (remote-adapter template) |
| `scripts/eval_harness/bakeoff.py` `BakeoffClient` / `main` / `fetch_run_record` | file / symbols | verified | `BakeoffClient` L67; `main` L218; uses `cli.fetch_run_record` |
| `scripts/eval_harness/remote_client.py:54` `RemoteSceneClient` | file:line / symbol | drifted | `class RemoteSceneClient` L56 |
| `scripts/eval_harness/report.py` `build_reports` | symbol | verified | `def build_reports` L324 |
| `scripts/eval_harness/` harness tree | file path | verified | present |
| `scene/infrastructure/vlm/gpu_remote_adapter.py` (planned new) | file path | drifted | exists; `class GpuRemoteDescriptionAdapter` L105, `describe` L139 |
| `scene/infrastructure/vlm/unavailable_adapter.py:23` | file:line / symbol | verified | `class UnavailableDescriptionAdapter` L23 |
| `scene/domain/description.py:12` `DescriptionAdapterKind.GPU` | file:line / symbol | verified | `class DescriptionAdapterKind` L12; `GPU = "gpu"` L17 |
| `scene/application/settings/vlm.py:29` `worker_concurrency` / `async_inline` | file:line / symbol | verified | L29–30 |
| `scene/config/settings.py` `DescriptionSettings` (`:19`) | file:line / symbol | drifted | `class DescriptionSettings` L26 |
| `ACX_GPU_ENDPOINT_URL` | env var | verified | `DescriptionSettings.gpu_endpoint_url` ← `os.environ.get("ACX_GPU_ENDPOINT_URL")` L56 |
| `ACX_DESCRIPTION_ADAPTER` | env var | verified | profile switch L33 |
| `scene/interface_adapters/http/schemas/responses.py` `VisualFactsResponse` (`:75`) | file:line / symbol | drifted | `class VisualFactsResponse` L103; `tier`/`result_generation` L129–130 |
| `DescribeJobResult` (responses) | symbol | verified | `class DescribeJobResult` L139 |
| `scene/interface_adapters/http/schemas/requests.py` `DescribeImageEnvelope` (`:100`) | file:line / symbol | verified | `class DescribeImageEnvelope` L100; optional `tier` L122 |
| `scene/interface_adapters/http/routers/describe.py` | file path | verified | present |
| `describe.py:192` `/describe/multipart` | file:line / route | drifted | `POST /describe/multipart` at L424–429 (`async def describe_image_multipart`) |
| `POST /describe/async` + `GET /describe/jobs/{job_id}` (planned net-new) | route | drifted | already present: `POST /describe/async` L553–558; `GET /describe/jobs/{job_id}` L623–624 |
| `scene/application/describe_jobs.py` (planned new) | file path | drifted | exists (`InMemoryDescribeJobStore`) |
| `scene/application/description_worker.py` (planned new) | file path | drifted | exists (`run_describe_job`) |
| `recognition/worker/scan_worker.py` | file path | verified | present |
| `db/migrations/versions/001_identity_schema.py` | file path | verified | present |
| `scene/tests/test_gpu_remote_adapter.py` | file path | verified | present |
| `scene/tests/test_describe_jobs.py` | file path | verified | present |
| `scene/tests/test_describe_tier_degrade.py` | file path | verified | present |
| `scene/tests/test_eval_harness_bakeoff.py` | file path | verified | present |
| Current-state: “no GPU host / A1 only” | state claim | drifted | GPU subnet + `acx_gpu_burst` instance in `main.tf` |
| Current-state: “no async describe worker / job store” | state claim | drifted | async routes + `describe_jobs`/`description_worker` landed |
| Current-state: “GPU → Unavailable only” | state claim | drifted | `GPU_QWEN30B` available + `get_gpu_description_adapter` wiring |
| `terraform validate` (Slice 1 proof) | make/tool cmd | verified | cited as operator check only (not re-run this audit) |

---

## VLM-4 — `docs/tasks/vlm/VLM-4-anti-hallucination-generation-task-plan.md`

| anchor | kind | status | current value |
| --- | --- | --- | --- |
| `docs/scopes/anti-hallucination-caption-generation-scope.md` | artifact doc | verified | present |
| `docs/tasks/vlm/VLM-3-gpu-detailed-tier-task-plan.md` | artifact doc | verified | present |
| `docs/workbay/rules/backend-python-guidelines.md` | artifact doc | verified | present |
| `docs/workbay/rules/testing-python.md` | artifact doc | verified | present |
| `scene/application/description_adapter.py` | file path | verified | present |
| `description_adapter.py:35` `DescriptionAdapter` | file:line / symbol | verified | L35 |
| `description_adapter.py:20` `AdapterResult` | file:line / symbol | verified | L20 |
| `describe.py:192` describe route | file:line | drifted | multipart handler L424–429 |
| `deps.py:15` `get_description_adapter` | file:line / symbol | drifted | `http/deps.py:155` (`routers/deps.py` missing) |
| `responses.py:75` `VisualFactsResponse` | file:line / symbol | drifted | L103 |
| `scripts/eval_harness/` | file path | verified | present |
| `scripts/eval_harness/report.py` `build_reports` | symbol | verified | L324 |
| `scene/tests/seed/bakeoff_golden.json` | file path | verified | present |
| `scene/application/visual_facts_pass.py` (planned **new**) | file path | drifted | **already exists** (E20-FUSION); `VisualFactsPrior` L31; `VisualFactsPass.describe` L70 (staticmethod) |
| `scene/tests/test_visual_facts_pass.py` (planned new) | file path | drifted | already exists |
| `scene/infrastructure/vlm/ensemble_decode.py` (planned new) | file path | verified | still absent (planned Slice 2) |
| `EnsembleDecodeConfig` / `EnsembleDescriptionAdapter` / `combine_token_distributions` | symbol | missing | no symbols until `ensemble_decode.py` lands |
| `scene/tests/test_ensemble_decode.py` (planned new) | file path | verified | still absent |
| `scene/infrastructure/vlm/gpu_remote_adapter.py` | file path | verified | present (VLM-3 landed) |
| `GpuRemoteTokenTrace` (planned VLM-3 extension) | symbol | missing | not in `gpu_remote_adapter.py` |
| `scene/config/profiles.py` `DescriptionProfile` / `ProfileSpec` | symbol | verified | L30 / L42 |
| `scene/interface_adapters/http/deps.py` `get_description_adapter` | file / symbol | verified | path correct when not under `routers/` |
| `scene/interface_adapters/http/routers/deps.py` | file path | missing | wrong path (see VLM-3) |
| `docs/tasks/vlm/VLM-4-decision-memo.md` (planned new) | artifact doc | verified | still absent |
| `scene/infrastructure/vlm/clip_rerank.py` / `WhitenedClipReranker` (stretch) | file / symbol | verified | still absent |
| `ACX_GPU_ENDPOINT_URL` | env var | verified | present in settings |
| arXiv 2505.17529 / 2606.18553 / 2505.06934 | external paper | verified | citation-only (not repo paths) |
| pytest `scene/tests/test_ensemble_decode.py` `test_visual_facts_pass.py` | test cmd | drifted | `test_visual_facts_pass.py` exists; ensemble tests still planned |

---

## VLM-5 — `docs/tasks/vlm/VLM-5-describe-job-consolidation-task-plan.md`

| anchor | kind | status | current value |
| --- | --- | --- | --- |
| `packages/shared-contracts/schemas/image-description-response.schema.json` | contract | verified | present |
| `docs/workbay/rules/testing-python.md` | artifact doc | verified | present |
| `docs/workbay/rules/backend-python-guidelines.md` | artifact doc | verified | present |
| `infra/oci/gpu_lifecycle/reaper.py` | file path | verified | present; load keys `queue_depth`/`in_flight`/`written_at` |
| `infra/oci/README.md` | file path | verified | present |
| `scene/application/describe_jobs.py` | file path | verified | present (`InMemoryDescribeJobStore`) |
| `InMemoryDescribeJobStore` | symbol | verified | L53 |
| `DescribeJobStatus` | symbol | verified | L20 in `describe_jobs.py` (not yet moved to domain) |
| `_DEFAULT_MAX_RETAINED_IMAGE_BYTES` `describe_jobs.py:50` | file:line / symbol | verified | L50 (`256 * 1024 * 1024`) |
| byte-budget enforce `describe_jobs.py:80-81` | file:line | verified | L80–81 (`_retained_image_bytes + image_len > …`) |
| `max_jobs=1000` `describe_jobs.py:59` | file:line | verified | L59 |
| `_evict_over_capacity_locked` `describe_jobs.py:224` | file:line / symbol | drifted | `def _evict_over_capacity_locked` L220 |
| `write_load_snapshot` `describe_jobs.py:113-143` | file:line / symbol | drifted | `load_snapshot` L113–131; `write_load_snapshot` L133–144 (method on store) |
| `scene/application/description_worker.py` `run_describe_job` | file / symbol | verified | `async def run_describe_job` L67 |
| `_result_payload` `description_worker.py:32-53` | file:line / symbol | verified | L32–53 |
| timeout guard `description_worker.py:162-171` | file:line | drifted | `asyncio.wait_for` L163–174 |
| `scene/application/describe_run_repository.py` | file path | verified | present |
| `_require_rls_bypass` `describe_run_repository.py:179` | file:line / symbol | verified | L179 |
| `reclaim_interrupted_runs` | symbol | verified | L198 |
| planned repo methods `create_single_run` / `set_item_*` / `purge_expired_single_runs` / `get_single_run_item` | symbol | missing | not implemented yet (Slice 1 target) |
| `scene/application/describe_run_worker.py` `run_describe_job` | file / symbol | verified | L50 (name collision with volatile worker — live) |
| `scene/application/describe_async_worker.py` (planned new) | file path | verified | still absent |
| `run_async_describe_job` | symbol | missing | planned |
| `scene/application/describe_load.py` (planned new) | file path | verified | still absent |
| `load_snapshot` / `write_load_snapshot` (module-level, planned) | symbol | missing | only store methods today |
| `scene/application/visual_facts_service.py` `build_visual_facts_envelope` | symbol | verified | L71 |
| `scene/application/description_repository.py:48` `insert_or_get_existing` | file:line / symbol | verified | L48 |
| `scene/domain/describe_run.py` | file path | verified | present |
| planned `RunKind` / `describe_job_status` / domain `DescribeJobStatus` | symbol | missing | domain has `DescribeRunStatus`/`DescribeItemStatus` only |
| `scene/interface_adapters/http/routers/describe.py` | file path | verified | present |
| `POST /scene/describe/async` | route | verified | router prefix + `POST /describe/async` L553–558 |
| `GET /scene/describe/jobs/{job_id}` | route | verified | L623–624 |
| `ACX_ASYNC_ALLOW_EMPTY_TENANT_CLAIM` `describe.py:434-435` | file:line / env | drifted | env check at L575–576 (`enqueue_describe_image`); still present |
| empty-claim poll `describe.py:483-485` | file:line | drifted | poll empty-claim 400 at L628–630 |
| tenant set/require `describe.py:436-438` | file:line | drifted | enqueue tenant wiring L578–579 |
| `_run_describe_job_and_dump_load` try/finally `describe.py:471-475` | file:line / symbol | drifted | `async def _run_describe_job_and_dump_load` L616–620 |
| `_ASYNC_JOBS` | symbol | verified | L88 |
| planned `_ASYNC_ADMISSION` | symbol | missing | not yet |
| `scene/interface_adapters/http/routers/describe_run.py` | file path | verified | present |
| `POST /scene/describe/run` | route | verified | L215 |
| `GET/DELETE /scene/describe/run/{run_id}` + items | route | verified | L285 / L299 / L316 |
| `describe_run.py:223-224` “database session unavailable” | file:line | drifted | L222–223 |
| `db/models/scene.py` `DescribeRun` / `DescribeRunItem` | symbol | verified | L82 / L128; **no** `run_kind` / item `visual_facts`/`tier`/`result_generation` yet |
| `db/migrations/versions/001_identity_schema.py` tables | schema | verified | `image_description_runs` / `_items` exist; planned additive columns/index absent |
| planned `run_kind` / item result columns / `idx_image_description_runs_single_active` | schema | missing | not in migration or ORM |
| `api/main.py` lifespan reclaim ~L141–153 | file:line / symbol | drifted | `_lifespan` + `run_startup_reclaim` L118–134 |
| `db/tenant_context.py:65-66` `set_tenant_context` | file:line / symbol | verified | RESET bypass + SET tenant L65–66 |
| `db/tenant_context.py:77` / `enable_rls_bypass` L109 | file:line / symbol | verified | bypass SET L77; `enable_rls_bypass` L109 |
| `ACX_DESCRIBE_LOAD_PATH` / `/run/acx/describe-load.json` | env / path | verified | describe.py L546; reaper docstring |
| `ACX_ASYNC_MAX_RETAINED_IMAGE_BYTES` / `ACX_ASYNC_MAX_PENDING_JOBS` / `ACX_ASYNC_JOB_RETENTION_HOURS` | env var | missing | planned renames; store still uses ctor defaults only |
| `DescribeJobResult` `responses.py:114` `status: str` | file:line | drifted | `class DescribeJobResult` L139; `status: str` L143 |
| `class-describe-controller.php:181` multipart | file:line | drifted | multipart call is `class-describe-media-service.php:181`; controller delegates via `describe_media` L272–273 |
| `class-describe-controller.php:342` bulk `/scene/describe/run` | file:line | verified | L342 |
| `scene/tests/test_describe_run_repository.py` | file path | verified | present |
| `scene/tests/test_describe_route.py` | file path | verified | present |
| `scene/tests/test_describe_run_contract.py` | file path | verified | present |
| `scene/tests/test_describe_run_reclaim.py` | file path | verified | present |
| `scene/tests/test_describe_run_routes.py` | file path | verified | present |
| `scene/tests/test_describe_jobs.py` / `test_describe_tier_degrade.py` | file path | verified | present (to-be-deleted after port) |
| planned `test_describe_async_repository.py` / `test_describe_async_worker.py` / `test_describe_load.py` | file path | verified | still absent |
| `make test` / `make check` under description-service | make target | verified | `Makefile` has `test:` and `check:` |
| VLMRP-S4-05 (handoff finding id only) | finding ref | verified | plan correctly avoids pasting body |

---

## Summary of drift

| plan | verified | drifted | missing |
| --- | ---: | ---: | ---: |
| VLM-3 | 32 | 16 | 2 |
| VLM-4 | 14 | 8 | 4 |
| VLM-5 | 42 | 12 | 10 |
| **Total** | **88** | **36** | **16** |

### Highest-impact drifts (re-plan before implementation)

| plan | issue |
| --- | --- |
| VLM-3 | `infra/oci/gpu-lifecycle/` → `infra/oci/gpu_lifecycle/`; deps path is `http/deps.py` not `routers/deps.py` |
| VLM-3 | Slices 1–5 largely **already landed** (GPU adapter, async routes, job store, spike/memo/bakeoff artifacts, terraform GPU) — plan Current State is stale |
| VLM-4 | `visual_facts_pass.py` + tests **already on branch** (not new); ensemble stack still correctly planned-absent |
| VLM-4/3 | line anchors for describe multipart (`:192`), `VisualFactsResponse` (`:75`), `get_description_adapter` (`:15`) all moved |
| VLM-5 | async route line anchors moved (~434→575, ~471→616, ~483→629); WP multipart lives in media service L181 not controller L181 |
| VLM-5 | planned DB columns / `describe_async_worker` / `describe_load` / env renames still correctly absent |

**Heuristic applied:** [AGT-02](../../strategy/engineering-heuristics.md) — no unresolved anchors: every concrete path/symbol/line above was checked with `ls` / `rg -n` / `sed -n` in this worktree on `feature/vlm-realign-01`.
