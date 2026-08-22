## DEMO-UX-1-D-9 — FIXED

canon rows satisfied:

- **MEAS-11** — satisfied the acceptance question, “What observable would differ if this claimed intangible increased?” The decision observable is not “a draft exists somewhere”; it is a non-empty WordPress attachment `_wp_attachment_image_alt` value, which is what the reported `wp/v2/media.alt_text` probe exposes. I traced the transition from draft/review state to that durable field.
- **AGT-02** — satisfied “Did I verify this claim against the source, not memory?” Every route, gate, command, and write named below was resolved in the current checkout. The live deployment state that the checkout cannot prove is explicitly separated under residual risk.
- **RLSE-05** — satisfied “Can data appear saved here while not durable?” Every plugin writer reads `_wp_attachment_image_alt` back and refuses full-success status when it diverges. The remaining silent-failure gap is in demo release acceptance: deploy/seed/walkthrough can all pass without checking that any alt text is durable.

verdict:

**(A) never run**, precisely: the repository's recorded 100-item demo provisioning/import/walkthrough never runs a description write/apply step against the seeded library. The current library has had no successful write/apply after its import (or after any later re-import/reset). **(B) is false**: the plugin has direct, verified writes to WordPress `_wp_attachment_image_alt`; generated text is not trapped in an AltContext-only store.

The repo cannot rule out an unrecorded operator *attempt* that failed before writing all items. Thus “never run” here means no successful application and no invocation in the shipped/recorded demo flow, not a claim about every manual shell command ever typed on the host.

what changed (files + why):

- `LANE_REPORT.md` only, per the read-only lane contract. No repository source was edited.

evidence chain, file:line by file:line:

1. **The 100-item demo was provisioned as recognition-only.** `docs/tasks/15.0/E15-29-public-demo-go-live-task-plan.md:14-22` defines the demo as 100 celebrity images for face clustering and explicitly says “recognition-only (no VLM).” The retained live record agrees: `docs/tasks/15.0/E15-29-demo-smoke-log.md:5-19` identifies a recognition-only backend, records `make deploy-demo`, and records `./seed/import.sh` producing exactly 100 attachments. Its only inference exercise is recognition/clustering at `:22-26`; success criteria at `:34-40` contain no description or alt-text condition.
2. **Seed import cannot create alt text.** `infra/oci/demo/seed/import.sh:28-42` enumerates images and runs only `wp media import ... --porcelain`. There is no `--title`, `--caption`, `--alt`, metadata update, AltContext describe command, or apply call.
3. **Deploy cannot create alt text.** `scripts/deploy/sync-demo.sh:57-78` copies the import script/media/plugin; `:107-114` runs only WordPress/plugin bootstrap. `infra/oci/demo/bootstrap-wp.sh:92-134` installs core, permalinks, and the plugin. Neither invokes seed import automatically nor description generation/apply. `infra/oci/demo/walkthrough-runbook.md:21-26` asks the operator only to scan, recognize, and curate. The automated proof described at `:52-62` likewise covers settings, scan, cluster avatar, and degraded state, not alt coverage.
4. **Individual generation is intentionally read-only until approval.** The REST route defaults `write_alt` to false in `apps/prototype-wp-alt-context/src/api/class-describe-controller.php:143-169`. `DescribeMediaService::describe_media()` generates/records the result, then returns without writing unless explicit write intent is present (`src/api/services/class-describe-media-service.php:198-230`). In the current Workbench, `MediaAltSuggest.generate()` requests a draft at `js/admin/pages/workbench/MediaAltSuggest.tsx:273-305`; the operator's **Accept** action passes that draft to `useCorrectMediaAlt` at `:585-625`.
5. **Accepted/approved draft reaches a real WordPress write.** `useCorrectMediaAlt` calls `correctDescriptionHistoryItem(mediaId, altText)` at `js/admin/hooks/useCorrectMediaAlt.ts:99-110`. That sends `POST .../history/{media_id}/correction` at `js/admin/api/describeApi.ts:357-375`. The route is registered to `DescribeController::correct_description_history_item` at `src/api/class-describe-controller.php:218-248`; delegation to `DescriptionHistoryService::record_correction()` is at `:341-355`. The exact accepted-description WordPress write is **`DescriptionHistoryService::record_correction()` in `apps/prototype-wp-alt-context/src/api/services/class-description-history-service.php:123-179`**, specifically `update_post_meta( $media_id, self::ALT_META, $normalized_alt_text )` at **line 177**, where `ALT_META` is `_wp_attachment_image_alt` (`:31-39`). It immediately reads back and verifies the durable value at `:178-189`; the subsequent human-edit audit write is also verified at `:231-280`. This is the end-to-end answer requested by the finding.
6. **Bulk generation also has a real, separate apply path.** Workbench selection submits a describe run at `js/admin/pages/workbench/MediaSelection.tsx:62-73` and `:155-173`. Once terminal, `BulkDescribeReviewLink` sends the operator to “Review & apply drafts” (`js/admin/pages/workbench/BulkDescribeReviewLink.tsx:13-33`). `DescribeRunApplyView.onApply()` calls the apply mutation at `js/admin/pages/DescribeRunApplyView.tsx:244-273`; the API posts to `/runs/{runId}/apply` at `js/admin/api/describeApi.ts:428-445`; the REST route delegates to `DescribeController::apply_describe_run_drafts()` at `src/api/class-describe-controller.php:299-315`. The exact bulk WordPress write is **`apps/prototype-wp-alt-context/src/api/class-describe-controller.php:935`**: `update_post_meta( $media_id, '_wp_attachment_image_alt', $draft )`, followed by read-back verification at `:936-941` and provenance verification at `:973-1070`.
7. **There are two additional non-bulk writers, further disproving (B).** Explicit `write_alt=true` reaches `DescribeMediaService::apply_alt_text_write_policy()` and writes `ALT_TEXT_META_KEY` (`_wp_attachment_image_alt`) at `src/api/services/class-describe-media-service.php:348-360,485-501`. WP-CLI `generate --write` writes the same key in `src/cli/class-description-command.php:271-307,381-400`; the command is registered as `wp alt-context describe` in `apps/prototype-wp-alt-context/alt-context.php:291-304`.

write gates found:

- **Capability:** all described REST routes use `can_manage_recognition`; it requires `current_user_can('manage_options')` in `src/api/class-abstract-recognition-proxy-controller.php:55-60`. WP-CLI is an operator shell path, not this REST capability path.
- **Explicit review/write intent:** single-image REST defaults to draft-only (`write_alt=false`); the Workbench proposal is not durable until **Accept/Save**. Bulk generation and bulk application are deliberately two separate actions/routes. This is a gate, not a missing writer.
- **Bulk terminal state:** only `completed` and `completed_with_errors` are applyable (`src/api/class-describe-controller.php:602-633`). Apply also requires the locally recorded submitted media-ID set (`:643-677`), strict membership (`:693-730`), an attachment target and non-empty draft (`:752-783`), and a compare-and-swap-stable alt snapshot (`:921-928`). Existing alt is preserved unless explicitly selected for overwrite (`:785-892`). None of these prevents applying the observed empty-alt JPEG seed when its run and drafts are valid.
- **CLI bounds/write switch:** `generate` is dry-run unless `--write` is present and refuses an unbounded library run; `--limit` selects missing-alt candidates (`src/cli/class-description-command.php:139-160,271-307`). Candidate enumeration caps at 100 and supports JPEG/PNG/WebP (`src/api/services/class-description-candidate-service.php:29-40,59-106,127-132`). This exactly covers the 100 JPEG/JPEG-like demo seed.
- **Budget/config availability:** single-image generation (and therefore the CLI loop) checks `acx_description_budget_max_attempts`; default `-1` is unlimited (`src/api/services/class-description-budget-service.php:13-50`). A configured exhausted limit, unreadable attachment, missing recognition URL, auth failure, backend failure, or unavailable adapter would fail generation, not silently report a durable alt write. The current production values are not in the repo.
- **Feature flag/review state/bulk-only:** no feature flag controls the `_wp_attachment_image_alt` write, there is no hidden approval-state enum beyond the explicit user action/terminal-run gates above, and writing is not bulk-only (correction, single-write-intent, CLI, and bulk paths all exist). Person-naming policy changes draft content only; it does not gate alt persistence.

operator command/flow for (A):

Safest UI flow: in Workbench, filter/select the missing-alt seed, choose **Describe selected**, wait for terminal completion, choose **Review & apply drafts**, review the drafts, then choose **Apply all 100 without alt text** (the primary label is computed in `js/admin/pages/DescribeRunApplyView.tsx:244-273`). This preserves the intended human-review gate.

For a headless demo population after reviewing a dry-run, from `/opt/acx-backend/demo`:

```bash
docker compose -f docker-compose.demo.yml run --rm --no-deps wpcli \
  wp alt-context describe status --limit=100 --format=json
docker compose -f docker-compose.demo.yml run --rm --no-deps wpcli \
  wp alt-context describe generate --limit=100 --format=json
docker compose -f docker-compose.demo.yml run --rm --no-deps wpcli \
  wp alt-context describe generate --limit=100 --write --format=json
```

Do **not** add `--force` for this empty-alt seed. The command emits per-row statuses and exits non-zero when any row is `failed` or `partial` (`src/cli/class-description-command.php:163-240`), satisfying RLSE-05 rather than silently accepting a partial library.

rg-006 command audit:

- The command name is registered (`alt-context.php:291-304`), `generate` accepts `--limit` and explicit `--write` (`class-description-command.php:139-160`), limit 100 is legal (`:559-569`), and the actual writer/read-back is at `:381-400`.
- The documented E20 contract says `wp alt-context describe generate/status` support `--media-id`, `--limit`, `--write`, `--force`, and JSON/table output (`docs/tasks/20.0/E20-3-wp-cli-generate-and-status-task-plan.md:47-50,107-114`). A no-dependency stub execution of the current command code exercised `--limit=100 --write` and reported `count=100 written=100`, with item 100 present in `_wp_attachment_image_alt` (GREEN output below).
- **No broken documented command was found.** There is nevertheless an operator-documentation/release-acceptance omission: the live demo seed, deploy, reset, and walkthrough runbooks contain no description population step and no `alt_text > 0` acceptance probe. That omission is why an otherwise green demo deployment can retain zero alt text; it should be a follow-up release finding under RLSE-05, not mislabeled as (B).

RED output (test-first lanes):

N/A — investigation/read-only lane; the brief did not request TDD and no source fix was authorized. Attempting the existing PHPUnit suite produced the environment failure below, not a product RED, so it is not presented as TDD evidence:

```text
sh: 1: vendor/bin/phpunit: not found
Script vendor/bin/phpunit handling the test event returned with error code 127
```

GREEN output:

```text
PASS: bounded --limit=100 --write path reports count=100 written=100 and persists item 100.
PASS: four WordPress alt-meta writers found; demo automation contains no description-generation or alt-meta application invocation.
No syntax errors detected in apps/prototype-wp-alt-context/src/api/class-describe-controller.php
No syntax errors detected in apps/prototype-wp-alt-context/src/api/services/class-describe-media-service.php
No syntax errors detected in apps/prototype-wp-alt-context/src/api/services/class-description-history-service.php
No syntax errors detected in apps/prototype-wp-alt-context/src/cli/class-description-command.php
```

Also green with exit 0 and no output:

```text
python3 scripts/test_e15_28_demo_seed_and_epic.py
bash -n infra/oci/demo/seed/import.sh infra/oci/demo/bootstrap-wp.sh scripts/deploy/sync-demo.sh
git diff --check
```

residual risk / what a reviewer should attack:

- **Repository-only certainty boundary:** source proves (B) false and proves the official demo path omits generation/apply. It cannot distinguish “no human ever attempted it” from “a human attempted it and all generation requests failed.” Read-only production access that would settle this is: counts/timestamps from `${wpdb->prefix}acx_description_usage`; attachment meta counts for `_acx_description_provenance`, `_acx_description_provenance_pending`, and `_acx_description_human_edit`; description-run/item records; and backend audit events `description.generated` / `description.cache_hit` for the demo tenant. No credential is needed in this report, and none was requested or handled.
- **Runtime command proof boundary:** the command implementation was executed against repository WordPress stubs because this worktree has no Composer `vendor/bin/phpunit`; it was not run against the live demo, per the no-network/no-auth contract. Production recognition URL/key, remaining tenant quota, WordPress description budget, deployed plugin SHA, and active backend `ACX_DESCRIPTION_ADAPTER` must be checked by the authorized operator before the 100-item write. The service code defaults to the deterministic model-free `seeded` adapter (`apps/prototype-description-service/scene/config/settings.py:26-45`; resolver at `scene/interface_adapters/http/deps.py:155-176`), but private deployment env may override it.
- **Quality risk:** the default seeded adapter chooses from a small fixture pool and always emits a non-empty draft (`apps/prototype-description-service/scene/application/seeded_adapter.py:20-33,47-70`). It proves plumbing, not accurate alt text for celebrity images. An operator should not bulk-publish those drafts merely to make the coverage metric nonzero; use the review flow and confirm the live adapter/quality target first.
- **Release regression to attack:** add a fail-loud post-seed/post-deploy observable (for example, an expected nonzero or explicitly waived alt count) and record the intended adapter/provenance. Today `sync-demo.sh`'s smoke accepts a healthy homepage without asserting the demo's central alt-text outcome, so zero coverage is silently compatible with “success.”
