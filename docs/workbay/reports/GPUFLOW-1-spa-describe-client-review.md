FINDINGS: [{"id":"GPUFLOW-1-SPADESCRIBECLIENT-R-01","severity":"high","file_path":"apps/prototype-wp-alt-context/js/admin/api/describeApi.ts","line":675,"summary":"The success parser accepts a contract-invalid null operation_id","evidence":"validateOptionalOpaqueId is called with allowNull=true at describeApi.ts:675, and the new test at describeApi.test.ts:608-621 requires parseVisualFactsResponse to accept operation_id:null. The shared image response schema defines operation_id as a non-null string at image-description-response.schema.json:326-330, while the multipart success branch requires the key at scene-describe-multipart.schema.json:13-17."},{"id":"GPUFLOW-1-SPADESCRIBECLIENT-R-02","severity":"medium","file_path":"apps/prototype-wp-alt-context/js/admin/api/describeApi.ts","line":1553,"summary":"The warm-up ETA extractor accepts negative values","evidence":"resolveDescribeErrorDetailNumberField returns any finite number at describeApi.ts:1553-1555, with no nonnegative check; its only positive/absent tests are describeApi.test.ts:997-1010. warmup_eta_seconds is required to be nonnegative or null by scene-describe-multipart.schema.json:52-58 and image-description-api.md:287-292."}]
Verdict: fail

# GPUFLOW-1 spa-describe-client review

| scope | value |
| --- | --- |
| base | `1f6d97fc7` |
| tip | `39332bdba` |
| files | `apps/prototype-wp-alt-context/js/admin/api/describeApi.ts`; `apps/prototype-wp-alt-context/js/admin/api/__tests__/describeApi.test.ts` |

The supplied delta changes exactly the two declared SPA paths. It extends the client types and validators for operation/run timing and nested typed errors, but the findings below leave the new boundary unsafe for accepted multipart responses and run-item data.

## FINDINGS

### GPUFLOW-1-SPADESCRIBECLIENT-R-01 — high

File: `apps/prototype-wp-alt-context/js/admin/api/describeApi.ts:675-677`; regression locked by `apps/prototype-wp-alt-context/js/admin/api/__tests__/describeApi.test.ts:608-621`.

Evidence: `parseVisualFactsResponse` allows an explicit `operation_id: null` because it passes `true` to `validateOptionalOpaqueId`. The added test names this as a valid GPUFLOW multipart success shape. The base shared schema permits the key only as a nonempty string (`packages/shared-contracts/schemas/image-description-response.schema.json:326-330`), and the multipart success branch requires `operation_id` to be present (`packages/shared-contracts/schemas/scene-describe-multipart.schema.json:8-17`). This violates `[rg-015]`/`[CARD-07]`: a boundary parser must not turn a contract-invalid success into an apparently usable response.

Impact: A successful accepted operation can reach Suggest and downstream timing consumers without the opaque lease identity required for retry binding and correlation. The test makes the invalid null form a permanent client contract, masking a producer or proxy defect instead of failing closed.

Fix: Reject `null` whenever `operation_id` is present in an accepted multipart success, while retaining `startup_id: null` as valid. If a legacy CPU/base response may omit operation metadata, keep that as an explicitly legacy shape rather than accepting a present null operation ID in the GPUFLOW success parser.

### GPUFLOW-1-SPADESCRIBECLIENT-R-02 — medium

File: `apps/prototype-wp-alt-context/js/admin/api/describeApi.ts:1542-1555`; coverage at `apps/prototype-wp-alt-context/js/admin/api/__tests__/describeApi.test.ts:997-1010`.

Evidence: `resolveDescribeErrorDetailNumberField` is documented for `warmup_eta_seconds`, but returns any finite number and never checks `value >= 0`. The tests cover `12` and an absent field only. The published typed-error contract and schema require `warmup_eta_seconds` to be nonnegative or null (`docs/workbay/contracts/image-description-api.md:287-292`; `packages/shared-contracts/schemas/scene-describe-multipart.schema.json:52-58`).

Impact: A malformed starting response can surface a negative countdown or produce an invalid retry schedule in the warming UI, undermining the bounded-wait guarantee in `[CARD-09]` and the no-invented/validated-metadata rule in `[rg-015]`.

Fix: Return `null` for negative values as well as non-finite/non-number values, and add a negative ETA regression. Keep the helper’s unknown result null so callers do not derive a replacement ETA.

## Verification

- Changed-path check over `.review/CHANGE.diff`: exactly the two declared SPA-owned source/test paths.
- `lane_root="$(git rev-parse --show-toplevel)"; resolved_python="$lane_root/.venv/bin/python"; "$resolved_python" -m pytest scripts/tests/test_composer_lock_tracked.py -q -p no:cacheprovider` — 1 passed.
- The lane row’s Vitest command is `vitest run`; it was not executable in this sandbox because `apps/prototype-wp-alt-context/node_modules/.bin/vitest` is absent. No SPA test pass is claimed.
