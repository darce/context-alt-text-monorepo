Code verdict: **pass** for the supplied diff, with no code findings. The overall merge gate remains incomplete because the required implementation brief and pinned heuristics canon are unavailable in this sandbox. This report does not authorize merge or live execution until the orchestrator closes those review-input gaps.

The prescribed lane suite exited **0**: **418 passed, 105 subtests passed in 16.33s**. It was run once using the managed lane-root interpreter, without installing packages:

```sh
lane_root="$(git rev-parse --show-toplevel)" || { echo 'cannot resolve lane root' >&2; exit 1; }
resolved_python="$lane_root/.venv/bin/python"
if [ ! -x "$resolved_python" ]; then echo 'lane interpreter unavailable' >&2; exit 1; fi
PYTHONDONTWRITEBYTECODE=1 "$resolved_python" -m pytest .task-state/bakeoff-rounds-20261017/qwen-ab/workspace/test_prepare_qwen_ab.py .task-state/bakeoff-rounds-20261017/qwen-ab/test_cohort_admission.py .task-state/bakeoff-rounds-20261017/qwen-ab/test_run_qwen_cohort_operation.py -q
```

The review owns only this report; no subject file was changed. The reviewed local blobs match all four postimage hashes in the supplied diff: runner `2159785f4c2b895378cf935782e12f049661e459`, runner tests `4b73374b20ce346d4a9e87641869436292b19e8e`, preparer `c31b037f36d13511f0a54920de9ff70175ab2bb3`, and preparer tests `0c705baaaa48cbec8c9e9474a7e2ac315e11e339`. The sandbox has stripped history, so subject commit `5447b66c6f4fbe205ff3824974dee1668f1a1fda` and base `d60d1628a` could not be inspected as commits. The lane owns no installable Python package; the reviewed scripts were additionally loaded by explicit local paths and their origins confirmed inside this worktree.

Lease arithmetic was recomputed from identity 60, setup 300, metadata 30, restore 270, control 80, and client C. Resume is `740+C`; serving-build is `600+C`; pre-client is `300+C`. START reserve is 300 seconds.

| Mode | Client C | Resume | Serving-build | Pre-client | Reserve + floors |
| --- | ---: | ---: | ---: | ---: | ---: |
| Full | 650 | 1390 | 1250 | 950 | 1690 |
| Pilot | 420 | 1160 | 1020 | 720 | 1460 |
| Replacement | 420 | 1160 | 1020 | 720 | 1460 |

Every resume threshold is reachable with the supplied real remaining-lease interval of 1600–1655 seconds. The deadline remains `monotonic()+min(C,int(expires-time.time()-270))`, with the generated assertion `>=C-1` (649 full, 419 pilot/replacement) allowing evaluation overhead. Its cap remains 650/420 seconds and preserves the authoritative expiry bound and 270-second restoration reservation. The setup call remains `guest(command,570)`. With an advancing mocked clock, isolated actual replacement deadline statements accepted 720/690 seconds remaining and refused 689.9/500; no recipe effects were executed. An initial supplemental probe used a frozen monotonic clock and failed its own boundary expectation; the corrected advancing-clock probe passed. The suite also accepts full client 760 at exactly `300+740+760=1800` and rejects 761. The `15*count` lower bound still rejects oversized cohorts that cannot fit this budget. Scheduling floors do not guarantee completion within the unchanged helper timeouts; subsequent lease guards still refuse insufficient remaining time.

Replacement preparation was checked against an actual archived `corpus-revision-r2.json` at `/home/gate/bakeoff-next-model-corpus-r2-adj-r3-2efe63d15a274e459f4ce48bd20e25b9/references/inputs/corpus-revision-r2.json`. Its digest is the production pin `66a2efb3c2bdeea52baa28ec8570336a20aed21e3c32f646ab9d7a7911f8b240`. Without patching constants, preparation and `verify_prepared` succeeded for `QWEN-R2-038` / `workbay-qwen-r2-038.scope` (recipe SHA-256 `32e230d646181855561f91a7fe3d1091f6a9cc0ef165f76705551c0b9453c660`). The embedded config is derived from frozen `qwen-gsq-02.json` and contains only `original-038`, old SHA-256 `648573b4d21c3e1b7d8029246ed20f5a516f685f6c698af2249109183cf524bd`, new SHA-256 `710a6798653ef868338136da63e2c176e892d73bac342e395bf0df640e70022e`, and path `/home/gate/bakeoff-rounds-20261017-inputs/results/LEXICON-AB-FROZEN-120-R2/corpus-revisions/r2/original-038.jpg`. The image-parent check and `images_dir` both bind to that R2 revision directory; the R1 frozen images directory is absent from this recipe. Runtime hashing checks the selected image before requests.

Named negative inputs covered by the passing suite include unpinned revision bytes, an R1/outside-R2 path, wrong old/new digests, `original-039`, multiple replacements, reused outputs, nonempty identity context, and replacement receipts claiming 20 images or 60 POSTs. Generated input, cohort, request-budget and completion checks follow count 1 / POST budget 3. Runner `--pilot` is required for full and replacement and forbidden for pilot. The remaining fixed 2-image/6-POST evidence checks validate the prerequisite pilot itself. No current-operation 20-image/60-POST requirement was found in the reviewed runner path.

Pilot and full recipes reproduce the recorded Part A SHA-256 values `1267ffc711ba352dda18a3ee14f4469ee24a205029ef4bcb4172e4172ddb8d51` and `4abe6b7ef18a469670c8dceae96e9702e55e950afa819ad8e90dc9faf02a196e`. Historical Part A bytes were unavailable for a separate commit-to-commit comparison. All three modes pass `source_binding`: repo `/home/gate/bakeoff-rounds-20261017-inputs/source/ab94e904ca25e2e031ad241f2600aa0406201c15`, its adjacent `ab94e904ca25e2e031ad241f2600aa0406201c15.venv/bin/python`, and the existing results-root workspace. No sandbox-root or `.venv-lane-` binding remains in the generated recipes.

The actual replacement recipe starts with `safe_withdraw=False` and contains the unchanged late-bind block exactly once. The passing composed-refusal tests demonstrate that refusals before ownership acquisition, including a live prior GPU lease and invalid predecessor evidence, make no public STOP/withdraw calls. Existing effect helpers and cleanup behavior remain unchanged. No GPU, SSH, service, controller, or live capacity-return operation was performed.

Required review inputs still unavailable: `.task-state/bakeoff-rounds-20261017/r2-038/BAKEOFF-R2-038-QWEN.brief.md` is absent, so comparison used the supplied dependency brief and diff. `/Users/daniel/Development/heuristics-canon-current` is absent, as is the lane-local bundled canon pointer. Consequently its AGENTS.md, release-manifest digests, authoritative release version, row text and card Verification requirements could not be verified. The supplied brief cites v0.26.2 while the task footer cites v0.25.3; neither is asserted here as a verified canon release. The orchestrator must supply or independently verify those inputs before treating this as a completed harmonizing gate. Codebase Memory tools were unavailable; source inspection used local text and AST reads.

```FINDINGS
[]
```
