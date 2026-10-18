VERDICT: 5 confirmed, 1 refuted, 0 unverified, 0 new.

## D1 — CONFIRMED — HIGH

- **Evidence:** The configured ref stays symbolic: scripts/deploy/recognition-service.sh:151 says:
  > GIT_REF="${GIT_REF:-HEAD}"

  Every direct GIT_REF resolution in recognition-service.sh is listed below; grep found no GIT_REF rev-parse in scripts/deploy/lib/*.sh.

  | Site | Verbatim resolution | Use | Reuses an earlier SHA? |
  | --- | --- | --- | --- |
  | recognition-service.sh:999, do_build | sha="$(git -C "${REPO_ROOT}" rev-parse "${GIT_REF}")" | Docker build arg and image tags at :1009, :1012-1013 | No |
  | recognition-service.sh:1025, do_build_remote | sha="$(git -C "${REPO_ROOT}" rev-parse "${GIT_REF}")" | Remote image tag/build arg and generation directory | No |
  | recognition-service.sh:1325, do_push_sha | local sha; sha="$(git -C "${REPO_ROOT}" rev-parse "${GIT_REF}")" | SHA-named registry push | No |
  | recognition-service.sh:3190, probe_cutover_api_health | expected_sha="$(git -C "${REPO_ROOT}" rev-parse "${GIT_REF}" 2>/dev/null || true)" | Fallback candidate expected version only when argument 3 is empty | No; ordinary do_restart supplies its own value |
  | recognition-service.sh:3263, do_restart | expected_sha="$(git -C "${REPO_ROOT}" rev-parse "${GIT_REF}" 2>/dev/null || true)" | Candidate/canonical restart health expectation; passes it to the cutover probe | No |
  | recognition-service.sh:4002, _ship_selected_env | sha="$(git -C "${REPO_ROOT}" rev-parse "${GIT_REF}")" | Fresh local value before preflights; not passed to later stages | No |
  | recognition-service.sh:4528, do_verify | expected_sha="$(git -C "${REPO_ROOT}" rev-parse "${GIT_REF}")" | Expected commit compared with production /health | No |

  The incident’s effective sequence is therefore build/push/restart at c580e4da, followed by do_verify resolving HEAD to 6ddc5863 after the other session committed. The given incident log records production returning c580e4da and verify expecting 6ddc5863.
- **Mechanism:** GIT_REF stores HEAD by default, and each stage independently resolves it. A ref update between stages changes the expected SHA even though the image and running container remain the ones built and restarted earlier. The verify mismatch then enters the failure path.
- **Failure scenario:** Deploy starts on c580e4da with GIT_REF=HEAD; another session commits 6ddc5863 after restart; do_verify expects 6ddc5863 from the same symbolic string and rejects the healthy c580e4da image. This matches the supplied incident.
- **Canon:** FLOW-01 applies: use an immutable input snapshot and an output tied to that snapshot, so the artifact identity and its verification expectation stay aligned.
- **Fix design:** After REPO_ROOT is set and before dispatch, resolve and validate one readonly DEPLOY_SHA with git -C "$REPO_ROOT" rev-parse --verify "${GIT_REF}^{commit}". Replace all seven resolutions above with DEPLOY_SHA, including the probe fallback. Pass that same value through do_build/do_build_remote, do_push_sha, do_restart, probe_cutover_api_health, _ship_selected_env, and do_verify.
- **Regression test:** scripts/deploy/tests/test_recognition_deploy.py — stub git so HEAD changes from SHA_A to SHA_B after build; assert build arg, registry tag, cutover expectation, and verify all use SHA_A, and the healthy SHA_A response does not trigger rollback.

## D2 — CONFIRMED — HIGH

- **Evidence:** Both builders label from a resolved SHA but consume the live service directory. recognition-service.sh:1005-1013 contains:
  > cd "${SERVICE_DIR}"
  > docker build \
  >   --platform "${PLATFORM}" \
  >   --build-arg "GIT_COMMIT_SHA=${sha}" \
  >   ${target_args} \
  >   -t "${IMAGE_BASE}:${tag}" \
  >   -t "${IMAGE_BASE}:${sha}" \
  >   .

  In remote mode, recognition-service.sh:1092 says:
  > "${SERVICE_DIR}/" "${SSH_TARGET}:${build_dir}/" || rsync_rc=$?

  bounded-remote-build.sh:337 and :342 say:
  > --build-arg "GIT_COMMIT_SHA=$acx_sha"
  > acx_build_args+=(-t "${acx_image}:${acx_sha}" .)

  The remote generation directory is its current Docker context. The other build inputs are visible in Dockerfile:67 and :157-164:
  > COPY pyproject.toml uv.lock ./
  > COPY api/ api/
  > COPY db/ db/
  > COPY recognition/ recognition/
  > COPY roster/ roster/
  > COPY scene/ scene/
  > COPY shared/ shared/
  > COPY scripts/ scripts/
  > COPY pyproject.toml .

  recognition-service.sh:768-772 says:
  > DEPLOY_CLEAN_PATHS=("apps/prototype-description-service" "scripts/deploy")
  > dirty="$(git -C "${REPO_ROOT}" status --porcelain --untracked-files=normal -- "${DEPLOY_CLEAN_PATHS[@]}" 2>/dev/null)" || {

  That covers tracked and non-ignored changes in the service tree, including the service Dockerfile, application files, compose/Caddy files, and systemd/acx-env.service.template shipped from that tree. The deploy logic and its two sourced libraries are under scripts/deploy and are also in the clean scope. I found no root infra/ or config/ file consumed or shipped by this build/deploy path; the templates it does read are under SERVICE_DIR, and generated unit/cutover files come from recognition-service.sh. These inputs are in the checked paths.

  The clean check omits ignored files. The service .gitignore:1 and :6-7 says:
  > scripts/eval_harness/out/
  > *.onnx
  > *.onnx.partial

  Dockerfile:163 copies scripts/; neither the rsync excludes at recognition-service.sh:1072-1091 nor .dockerignore names scripts/eval_harness/out/. Therefore ignored output there can enter the image. The rsync and Docker ignore rules only exclude this exact ONNX path (recognition-service.sh:1084; .dockerignore:42):
  > --exclude='recognition/infrastructure/face_pipeline/models/*.onnx' \
  > recognition/infrastructure/face_pipeline/models/*.onnx

  Thus ignored ONNX files elsewhere under copied directories, and .onnx.partial files even under that models directory, can enter the image. This matches the code comment at recognition-service.sh:767: “Gitignored files (e.g. a stray *.onnx) are not detected and can still ship.”
- **Mechanism:** docker build uses the current contents of SERVICE_DIR, while the SHA is resolved separately. Remote rsync likewise copies the current directory, not a tree materialized from that SHA. A preflight can pass while a later worktree edit or ignored artifact changes the context; the image label then describes a different source tree or carries unintended files.
- **Failure scenario:** The deploy resolves SHA_A and passes the clean check. A subsequent edit changes a copied module, or an ignored scripts/eval_harness/out result or unfiltered ONNX file is present. Local Docker or rsync builds from that live content but tags/labels it SHA_A. The dirty check does not catch the ignored-file case.
- **Canon:** FLOW-01 applies: build from an immutable commit snapshot so source inputs and image identity form one version.
- **Fix design:** Add a snapshot helper that materializes the complete repository at DEPLOY_SHA with git archive or a detached temporary worktree. Point SCRIPT_DIR, SERVICE_DIR, runtime template reads, and both Docker contexts at that private snapshot. Archive-only tracked contents also exclude ignored/untracked scratch by construction. Keep the remote rsync and Docker .dockerignore weight filters consistent for defense in depth.
- **Regression test:** scripts/deploy/tests/test_recognition_deploy.py — make committed SHA_A contain a known file, add a worktree-only edit plus ignored scripts/eval_harness/out and ONNX sentinels, capture local Docker and remote rsync contexts, and assert both contexts match SHA_A and contain none of those untracked sentinels.

## D2b — CONFIRMED — HIGH

- **Evidence:** recognition-service.sh:795-797 compares HEAD with origin/main:
  > head="$(git -C "${REPO_ROOT}" rev-parse HEAD)"
  > upstream="$(git -C "${REPO_ROOT}" rev-parse origin/main 2>/dev/null || echo unknown)"

  It does not compare GIT_REF. The builder resolves GIT_REF at :999 or :1025 while reading the live SERVICE_DIR. The current runbook documents selecting a commit explicitly at docs/runbooks/deploy-recognition-cicd.md:212:
  > CONFIRM=PROMOTE GIT_REF="$GOOD_SHA" REMOTE_BUILD=1 scripts/deploy/recognition-service.sh deploy prod
- **Mechanism:** A synced current HEAD passes the production preflight even when GIT_REF names a different, older commit. The build then packages HEAD’s live tree under the older SHA build argument and registry tag.
- **Failure scenario:** HEAD and origin/main are SHA_B, but GIT_REF=SHA_A. The production preflight passes on SHA_B; rsync/build reads SHA_B’s service tree and publishes it as SHA_A. A consumer trusting the tag or APP_GIT_COMMIT_SHA gets the wrong artifact identity.
- **Canon:** CARD-11 applies because the SHA label is not evidence of source contents if the build uses a separate, mutable tree. FLOW-01 also supports binding the build to the selected commit.
- **Fix design:** Use the single DEPLOY_SHA for both the context and identity. For normal prod deploys, preflight_branch_synced must compare DEPLOY_SHA with origin/main and fail when they differ. The current runbook also documents an intentional historical-SHA prod recovery at docs/runbooks/deploy-recognition-cicd.md:212; preserve that only through an explicit rollback path that still materializes the exact DEPLOY_SHA, or update the runbook to promote the already-built known-good image. Do not let the normal prod path build HEAD under an older SHA. Non-prod historical refs must likewise build from their exact commit.
- **Regression test:** scripts/deploy/tests/test_recognition_deploy.py — set HEAD=origin/main=SHA_B and GIT_REF=SHA_A; assert a prod deploy refuses before build because DEPLOY_SHA differs from origin/main, and a permitted non-prod build reads SHA_A’s file content and labels it SHA_A.

## D3 — CONFIRMED — HIGH

- **Evidence:** _ship_selected_env calls these once at recognition-service.sh:4013-4014, before preserve_rollback_tag and before either builder:
  > preflight_git_clean "$env"
  > preflight_branch_synced "$env"

  grep found only those call sites beyond the two function definitions at :769 and :790. The sync check itself snapshots HEAD at :795 and compares it to origin/main at :797; there is no checkout lock or later guard on that result.
- **Mechanism:** The preflight is a check-then-act decision against one mutable checkout state. Later stages independently read the symbolic ref and live service files, so the condition established at startup is not held for the transaction.
- **Failure scenario:** HEAD equals origin/main at preflight. A concurrent commit changes HEAD before verify; the image built earlier still reports the old SHA while verify expects the new SHA. A concurrent checkout can also change later template reads after the earlier clean check.
- **Canon:** DATA-18 applies as a check-then-act gap: the decision is made from a snapshot while concurrent writers can change the state before action.
- **Fix design:** Resolve DEPLOY_SHA once, compare that exact commit to origin/main for prod, and use a private DEPLOY_SHA snapshot for every later build, script, and template read. The transaction’s immutable target then survives checkout changes; do not re-resolve it between preflight and action. If prod policy requires DEPLOY_SHA still be origin/main immediately before promotion, compare again at that gate (a checkout lock cannot stop origin/main itself from advancing).
- **Regression test:** scripts/deploy/tests/test_recognition_deploy.py — let both preflights pass, advance the fake HEAD before the build and again before verify, and assert every stage still consumes the initial DEPLOY_SHA and its private snapshot.

## D10 — CONFIRMED — HIGH

- **Evidence:** There is no local lock around Git or the checkout. test_shared_tag_lock.py:314-318 asserts the event order:
  > assert (tmp_path / "events").read_text().splitlines() == [
  >     "first-started",
  >     "first-released",
  >     "second-started",

  Its :330-360 case repeats that the holder stays locked until its wrapped command ends. The implementation at recognition-service.sh:3693-3703 locks this remote path and holds a remote flock via SSH:
  > lock_path="${ACX_DEPLOY_BACKUP_ROOT}/locks/tag-${tag}.lock"
  > "sudo install -d -m 700 $(remote_quote "${ACX_DEPLOY_BACKUP_ROOT}/locks") && sudo flock -w ${timeout} $(remote_quote "${lock_path}") sh -c 'printf \"LOCKED\\n\"; exec cat >/dev/null'" \

  Its shown call sites are the environment-tag push at recognition-service.sh:1344 and rollback tag restore at :3756:
  > with_shared_tag_lock "${tag}" do_push_tag --locked "${tag}" "${source_digest}"
  > with_shared_tag_lock "${env_tag}" restore_env_tag_to_rollback --locked "${env}" "${restart_runtime}"

  That lock serializes operations on one remote registry/environment tag; it does not serialize commits, checkout changes, local builds, context rsync, or verification.

  A second lock is named at recognition-service.sh:158:
  > REMOTE_BUILD_LOCK="${REMOTE_BUILD_DIR}.lock"

  The comments at :1033-1035 say it serializes remote BuildKit setup/bootstrap/prune/build on the VM. The acquire command at :1114 is:
  > remote_command="command -v flock >/dev/null 2>&1 && acx_deadline_epoch=\$(date +%s) && acx_deadline_epoch=\$((acx_deadline_epoch + ${remaining})) && flock -w ${remaining} $(remote_quote "${REMOTE_BUILD_LOCK}") bash -s --"

  It runs after the source rsync at :1070-1092 and never locks the local Git checkout. No test in test_shared_tag_lock.py covers checkout isolation.
- **Mechanism:** Separate sessions can mutate refs or worktree files while this deploy is running. The tag lock and remote builder lock protect different remote resources; neither gives this process a stable local source snapshot. This directly permits D1’s symbolic-ref drift and D2’s live-context drift.
- **Failure scenario:** Deploy A builds from HEAD=SHA_A. Session B commits SHA_B onto the shared branch before A verifies; A’s verify resolves HEAD to SHA_B and can reject and roll back the healthy SHA_A image. If B checks out files while A is still reading contexts/templates, A can also consume a mixed set of live inputs.
- **Canon:** DATA-18 applies because concurrent writers can invalidate an earlier checkout/preflight observation before later action.
- **Fix design:** Execute from a private snapshot containing DEPLOY_SHA, the deploy script and libraries, and shipped templates. Once every input is pinned/copied, a long-held checkout lock is not needed for correctness: a Git ref/worktree change cannot alter the private snapshot. A short lock is only needed if the chosen snapshot implementation mutates shared worktree metadata or temporary paths.
- **Regression test:** scripts/deploy/tests/test_recognition_deploy.py — run two deploy drivers against one checkout, change the shared HEAD and replace source files while the first is paused, then assert each driver’s build context, templates, and verify SHA remain bound to its own private DEPLOY_SHA snapshot.

## D10b — REFUTED — LOW

- **Evidence:** The only local library source statements are at recognition-service.sh:200 and :202, before function definitions and before dispatch:
  > source "${SCRIPT_DIR}/lib/ocir-auth.sh"
  > source "${SCRIPT_DIR}/lib/bounded-remote-build.sh"

  The main command is a top-level dispatch after the function definitions, not a function called by a final line. recognition-service.sh:4917-4923 says:
  > if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  >   cmd="${1:-}"; shift || true
  >   case "$cmd" in
  >     deploy) [[ -n "${1:-}" ]] || fail "deploy requires <env>"; do_deploy "$@" ;;

  The other textual source at :4719 is the remote command string “source ${remote_dir}/.env” inside do_reset (:4686); it reads the target host’s environment file and is not a stage-time source of a deploy library.

  A /tmp toy script sourced a library, paused inside an already loaded function, and atomically replaced the library path. It printed loaded-before-edit. This confirms that the already sourced function stayed in memory through that replacement.
- **Mechanism:** Although Bash reads script input as it executes, this invocation has parsed the function definitions and top-level dispatch before calling do_deploy, and both deploy libraries are sourced at startup. A later commit or atomic checkout replacement does not cause those functions to be sourced again during the deploy. The live build/config paths remain exposed under D2 and D10, but the proposed lazy library re-read mechanism is not present.
- **Failure scenario:** No failure scenario is confirmed for this hypothesis: editing a library path after startup does not replace the function already sourced by the running process. (A separate process started later could read the new version.)
- **Canon:** none; the hypothesized source-read mechanism is refuted by the actual source locations and the local atomic-replacement experiment.
- **Fix design:** No D10b-specific code fix is needed. As part of the D2/D10 snapshot fix, execute the script from a private copy and keep library sourcing before dispatch; this also protects against future stage-time file reads.
- **Regression test:** scripts/deploy/tests/test_recognition_deploy.py — if a focused guard is desired, start a driver, atomically replace the repository library after dispatch starts, and assert its already loaded helper retains the original behavior. No test should claim the current script re-sources deploy libraries mid-run.

## New defects

None. The ignored build-context inputs described under D2 are part of the assigned build-context hypothesis.

## Method

- Read recognition-service.sh ranges 140-215, 761-810, 996-1130, 1315-1360, 1439-1471, 1857-1884, 3176-3335, 3684-3757, 3989-4080, 4518-4650, 4686-4722, and 4915-4935; searched all GIT_REF/rev-parse and source sites in recognition-service.sh and scripts/deploy/lib/*.sh.
- Read bounded-remote-build.sh ranges 330-350; test_shared_tag_lock.py ranges 1-18, 287-360; Dockerfile ranges 60-70 and 157-164; service .gitignore ranges 1-7; .dockerignore ranges 1-68; and docs/runbooks/deploy-recognition-cicd.md ranges 206-215.
- Ran a toy Bash experiment in /tmp that atomically replaced an already sourced library while its function was pending; the running function printed loaded-before-edit. No VM or network reproduction was available.
