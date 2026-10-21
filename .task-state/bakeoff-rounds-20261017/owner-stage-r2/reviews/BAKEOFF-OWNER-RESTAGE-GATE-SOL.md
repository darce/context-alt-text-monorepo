Verdict: **fail**. Three generator defects block approval: the production Git loader rejects the source tree, the retained bridged stage fails the eight-file inventory guard, and readiness can pass while the intended STOP still exceeds its native-job budget. The preparer rebind and the generated predecessor proof otherwise satisfy the inspected contracts. This is a review only; no subject file was changed and no remote program was executed.

```FINDINGS
[
  {
    "id": "ORG-01",
    "severity": "high",
    "file": ".task-state/bakeoff-rounds-20261017/owner-stage-r2/build_long_window_native_r2.py",
    "line": 241,
    "summary": "git_tree enumerates the whole qualification directory and requires every entry to be a regular procedure blob. That directory also contains ROOT-HANDOFF.md, fixture producers, tests, evidence/ and reviews/. Running the unmocked loader against the submitted Git tree raises Refused: non-regular procedure entry: evidence, even though the eight required files have the approved manifest and matching pins. Merely skipping subdirectories would still fail verify_tree because of the extra regular files. All successful generation tests replace this loader with an eight-file dictionary, hiding the production failure.",
    "fix": "Select exactly approved-scripts.json and the seven named procedure scripts from the immutable source commit; validate each selected entry's blob type/mode and retain all digest and exact embedded-set checks. Leave the qualification's documentation, fixtures and evidence untouched. Add a real-Git red/green control with the approved eight files alongside unrelated files and subdirectories, plus missing/nonregular pinned-entry refusals."
  },
  {
    "id": "ORG-02",
    "severity": "high",
    "file": ".task-state/bakeoff-rounds-20261017/owner-stage-r2/build_long_window_native_r2.py",
    "line": 89,
    "summary": "The exact eight-entry inventory rule is also applied to CURRENT_STAGE at line 196. A retained procedure continuing a window that still names /root/owner-stop-contract-r3/procedure carries a ninth file, procedure-predecessor.json: this is the protected continuation layout documented in ROOT-HANDOFF.md and enforced by validate_procedure. Rejecting that receipt prevents restaging the already bridged procedure before the new stage is created. A private eight-file fixture passes this guard, then fails with procedure inventory mismatch when the sealed predecessor receipt is added.",
    "fix": "Distinguish the original eight-file predecessor/new pre-proof stage from the existing bridged stage. For CURRENT_STAGE, allow only the exact expected scripts, manifest and protected predecessor receipt, and validate that receipt's binding and hashes read-only against the unchanged R3 window/procedure. Do not delete the receipt or loosen inventories to arbitrary extras. Add a valid nine-file retained-stage control and invalid/missing/extra receipt controls."
  },
  {
    "id": "ORG-03",
    "severity": "high",
    "file": ".task-state/bakeoff-rounds-20261017/owner-stage-r2/build_long_window_native_r2.py",
    "line": 182,
    "summary": "Readiness uses view(paths, 'stop', None), which projects only records at highest_sequence. The real STOP guardian uses its sealed predecessor sequence as floor (owner-custody.py:385-386), potentially retaining many more records. Thus using the same native_job function and five-second limit does not prove that STOP's actual view fits the unchanged 60000-byte budget. With 340 private authority records, the generated readiness function returned status 0 for a 730-byte newest-only view, while the same real view/native_job at predecessor floor 1 required 164035 bytes and returned child exit 71 with no result.",
    "fix": "Bind readiness read-only to the exact sealed predecessor sequence the intended STOP will use, or establish a conservative floor whose successful view bounds that STOP view. Keep the existing native_job implementation, five-second limit and 60000-byte budget. Include a negative control where newest-only projection fits but the predecessor projection overflows, and a positive control with large history strictly below the predecessor floor."
  }
]
```

The required lane suite ran once using the managed lane interpreter, resolved from `git rev-parse --show-toplevel` in the same shell invocation:

```sh
"$resolved_python" -m pytest .task-state/bakeoff-rounds-20261017/owner-stage-r2/test_build_long_window_native_r2.py .task-state/bakeoff-rounds-20261017/qwen-ab/workspace/test_prepare_qwen_ab.py -q
```

Exit **0**: **49 passed, 104 subtests passed in 10.27s**. `PYTHONDONTWRITEBYTECODE=1` and `PYTEST_ADDOPTS='-p no:cacheprovider'` prevented source/cache writes. No packages were installed and no other test suite was run. These paths contain standalone scripts, not an owned importable project package; the repository root declares `package = false`. Direct generator/preparer module loads resolved inside this lane. The suite has real refusal controls for digests, pin mismatches, source/output drift and missing/duplicated rebind targets, but does not execute the generated stage workflow or exercise the real Git loader.

Additional private review probes used the same interpreter. They loaded generated definitions without the final `run()` call, exercised the actual decoder and predecessor serializer/validator, checked the real Git loader, compared preparer outputs, and ran the actual `view`/`native_job` against temporary state. The first predecessor probe stopped because its private-path mapping omitted the validator's final `os.stat`; the corrected mapping passed. These are local library/fixture checks, not root or live acceptance evidence. ORG-02's inventory isolation bypassed ownership checks only to exercise the exact entry-set predicate; the predecessor validator fixture mapped the hard-coded old path and root UID to private owned files.

The predecessor check is dispatched by `owner-window.py:96-98` into `owner-custody.py:219-250`. Field-by-field tracing found no proof defect:

- The generated proof is one JSON object followed by a real newline, not a literal backslash suffix. Its seven keys exactly match the validator's field set; all values are strings.
- `schema` is exactly `acx-owner-procedure-predecessor/v1`.
- `window_id`, `window_path` and `procedure` are the guarded original UUID, `/tmp/qwen-owner-window.rcqmefq9` and `/root/owner-stop-contract-r3/procedure`. The new procedure differs from the window's procedure as required. The validator rereads sealed `window.json` and requires equality.
- `manifest_sha256` comes from verification of the original R3 manifest against `991aa72e923562bec93659190e87f9d223514da3073b424df5d36a60f1e77406`; it is not the current-stage or new-stage digest.
- `owner_window_sha256` and `owner_custody_sha256` come from the corresponding verified R3 files. The validator reopens the old private directory, checks its exact seven-script-plus-manifest inventory, verifies every manifest pin and both helper hashes, and checks the directory's held/named identity.
- The proof is created exclusively with no-follow semantics at mode 0400. The merged reader additionally requires a root-owned regular single-link bounded file and stable held/named metadata. The private positive control accepted the generated proof; changing each of the seven fields separately produced the expected refusal. Original live R3 bytes were not available locally, so this control used pinned local script bytes and private path/UID mappings.

Other reviewed requirements:

- The eight selected local procedure bytes pass `verify_tree`, including manifest `cd399f1f0d55fd1dbf4eb980d0accbdb6b2ac27536f4f11a222b3262bdcbb495`, exactly seven pins and both fixed helper hashes. The generated decoder accepts those identical eight bytes and rechecks their pins. This does not cure ORG-01's source-selection failure.
- `window.json` is compared with the full expected dictionary; operation count is compared with `EXPECT_OPS` (24 for the assigned invocation). Both original/current manifest digests are fixed. ORG-02 prevents the current-stage guard from accepting the bridged layout.
- The explicit generated workflow creates fresh evidence/stage directories without `exist_ok`, writes with `O_EXCL|O_NOFOLLOW` and mode 0400, and performs no checkpoint, owner-window subcommand, fence/lock creation, GPU call, removal or rename. The invoked custody validation/view/native-job paths contain no retained-state writes. Window/authority snapshot dictionaries are compared exactly, including names, content hashes, sizes, inodes and modes as recorded; exceptions retain created evidence/stage paths without cleanup. The full workflow was not run.
- Readiness uses the real merged `view`, STOP mode, `native_job`, five seconds and the unchanged `<60000` serialization limit. Its different floor is the substantive mismatch in ORG-03. The different markers path is unused by `view` and is not a separate finding.
- All six immutable reference pins verify. For both `gsq` and `ud`, in both `pilot` and `full`, suppressing only `rebind_owner_stage` and comparing outputs proves exactly the three required substitutions plus the necessarily recomputed review-gate hash. The helper refuses missing or duplicated targets. Receipts carry the required `owner_stage`; generator and preparer stage/digest constants match. Reference files and `PINS` were not modified by the submitted diff.
- The config has the required name, owner, unit, CPU 0.5, memory 2147483648, forecast 1073741824, timeout 120, role and absolute program path; its additional `model = null` and source fields match the tested transport shape.

Verification limits: this sandbox starts at history-stripped commit `e89fae9cd8b9c6d11015d0fb7ff36f1bd3aea6b2`; neither named source `27bf69d5349c44033f419ec4fa73e893b4dd6b2d` nor subject tip `d6feefdc3513f7446bb5a392cdb4d31363a8e846` exists in its object database. The four reviewed subject blobs match the supplied diff IDs (`a7841e3e7`, `baba65007`, `0bc1267bf`, `e8dc41104`), and local procedure pins match the assigned manifest. The real-loader failure above was reproduced against this submitted snapshot; historical commit provenance and live retained-stage inventories cannot be independently certified here.

Canon review is **unavailable**: `/Users/daniel/Development/heuristics-canon-current`, its `AGENTS.md`, release manifest and row/card files are absent. Neither the brief's v0.26.2 nor runtime guidance's v0.25.3 can be certified, and no canon row text or digest verification is inferred. Supply the authorized pinned read-only release for that separate check. Codebase-memory discovery tools are also unavailable in this session; material call paths were verified directly from the bounded source files instead.
