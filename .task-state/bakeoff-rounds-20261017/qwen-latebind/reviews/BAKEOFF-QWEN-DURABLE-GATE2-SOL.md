# BAKEOFF-QWEN-DURABLE-GATE2-SOL

Review of base `a994816f5` through subject tip `47527daba`, including the accepted ignored-code fix. The supplied base-to-`19d0ef77c3c20635d5cb295818cec1c36320550b` diff and continuation #7750 define the subject. This sandbox is a history-stripped snapshot (`441d938`) on `feature/bakeoff-qwen-durable-source-20261020`. Only this report is changed.

The gate **fails**: three open high findings and one open low finding. SOLD2-01 is high, **fixed** at checkpoint `47527daba`. Rule authority is the supplied **Canon v0.26.2** table, per #7750. Applicable checks are [RLSE-33] **Check before effects**, [RLSE-21] **The artifact that runs is the artifact reviewed**, [NDM-06] **Stop on a violated expectancy**, and [TEST-20] **Known-good baseline** (Canon v0.26.2, supplied table).

The prescribed lane suite ran exactly once with the managed lane-root `.venv/bin/python`: **364 passed, 79 subtests passed in 11.96 s, exit 0**. Both admission-module import origins were inside this lane. The completion record was recovered from this session's command event after displayed tool output was truncated; the suite was not rerun. This lane owns scripts, not an installable package. No ssh, sudo, network, GPU, claim, or live operation was run. Discovery `rg` exits 1/2 below indicate no matches/missing paths, not suite failures.

All five prior fixes were reviewed across the full base-to-tip scope:

- SOLD-01/QDSG1-01: AST binding counts and exact module-level assignments reject same-line/static rebinding. The ten REBINDS cases, string-only binding, non-module assignment and star-import tests distinguish the former text-only validator. Runtime rebinding remains expressly excluded.
- SOLD-02/QDSG1-02: exact components and `normpath(p) == p` reject dot traversal, doubled separators and trailing slash; their negative table distinguishes the former permissive pattern.
- SOLD-03/QDSG1-03: required mappings/keys, rc/error checks and literal-True clean/executable/import checks are present. The flipped-field and malformed-map cases distinguish the former head/clean-only predicate.
- SOLD-04/QDSG1-04: children share a 20 s monotonic budget inside 30 s ssh; slow/hung-child assertions distinguish separate budgets. Environmental messages name field/child and request an operator re-run. These faults remain deterministic `source_unavailable`, exit 3, no auto-retry, per 19388/19403 and [API-08] **No unbounded retry** (Canon v0.26.2).
- SOLD-05/QDSG1-05 and FIXB: root does not open/create/chown index or scratch. The uid/gid-1002 shell finds linked-worktree indexes, copies privately, checks rc and uses stdout for cleanliness. The real-Git control demonstrates ordinary diff rewrites the original index; the fixed probe preserves bytes/mtime. Staged-only, unstaged-only and untracked-code cases refuse. SOLD2-02/04 cover further clean-signal omissions.

SOLD2-01 is closed: `--exclude-standard` is absent and all eight ignored-file/directory regressions at test lines 1975-1999 passed. The continuation supplies their accepted red-before/green-after evidence; that historical red run was not repeated. The `.ses` and ignored-log baselines still pass. The orchestrator's read-only VM evidence reports zero ignored import-capable files in both current roots, with the venv at sibling `<sha>.venv`; no new VM observation is claimed here.

Additional witnesses used disposable repositories and real Git/interpreter children. The harness executed the generated preclaim, changing only the GPU fixture path and dropping identity kwargs as `run_local` does. Local uid is 1002; the generated uid/gid/extra-groups/env kwargs were checked separately. A clean baseline passed. Real `prepare()` pilot/full output passed real `source_binding()`; recipes themselves were never executed.

- **SOLD2-02:** mark tracked `apps/prototype-description-service/shadow.py` with `git update-index --assume-unchanged` or `--skip-worktree`, then alter its marker. Both probes reported matching HEAD, rc 0, no errors, both roots clean and imports successful. Classification accepted; real import printed `unreviewed`. Copying the index preserves suppressing flags.
- **SOLD2-03:** a nested untracked Git repo `.../untracked_namespace` containing `child.py` was invisible to the listing while `import untracked_namespace.child` succeeded. An extensionless directory symlink `.../untracked_link` to a scratch package likewise enabled import with an empty listing. Both probes were accepted. The symlink is an untracked entry outside all four suffix patterns that enables code execution. The proposed filesystem-aware fix must retain ordinary `.ses`/log acceptance.
- **SOLD2-04:** HEAD/worktree marker A; stage B, restore only worktree A. Preclaim's combined `git diff HEAD` accepted clean. The recipe's `git diff --name-only` printed `apps/prototype-description-service/shadow.py`. Preclaim is looser than the recipe and allows the claim before recipe refusal. Check staged and unstaged deltas separately in the private index.
- **SOLD2-05:** a finite fsmonitor hook held a real Git descendant during the unchanged DIFF shell. A 0.2 s timeout returned in about 0.202 s, leaving that descendant alive and one private-index directory. SIGKILL skips the EXIT trap. Cleanup must stay uid 1002; the stale inbox's six-retry consequence does not apply because source failure is not retried.

Generator `replace_once` replacements preserve KEY/workspace, remove sandbox/venv-lane text and rebind the recipe's source loop. Probe identity is exactly `user=1002, group=1002, extra_groups=[]`; env matches the recipe and import cwd is the service directory. GPU/publication checks retain their order. Source binding precedes ssh; classification precedes `admit()`, `runner.run()` and claim persistence.

Production impact: no subject reference was found in `apps/`, `packages/`, `scripts/deploy/` or `.github/`. OCIR builds from the service directory; Dockerfile copies explicit service subdirectories, excluding top-level `.task-state/`. The changed files are bakeoff tooling, not production describe dependencies.

Prior rejected paths and specified wontfix/deferred items remain closed, including root `os.access`, repeated literals and a persistent prepare-to-validator seam test. No restore-in-sandbox, workspace move, root index-copy, evidence deletion, stub-only seam or unkillable-test fix is proposed. Live rebuild/retention acceptance is outside this diff. Coverage means the listed changed functions/sections were read fully; unrelated unchanged test bodies were not all reread. The command ledger ends at report preparation; sealing/commit results are in the handoff.

```FINDINGS
{
  "verdict": "fail",
  "findings": [
    {
      "id": "SOLD2-01",
      "severity": "high",
      "status": "fixed",
      "file": ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py",
      "line": 157,
      "title": "Ignored import-capable files were omitted",
      "evidence": "Current: git ls-files --others -- '*.py' '*.pyc' '*.so' '*.pth'; --exclude-standard removed.",
      "consequence": "The former command admitted ignored shadow modules; checkpoint 47527daba closes that omission.",
      "fix": "Accepted 47527daba; eight real-Git ignored-file/directory regressions now pass.",
      "canon": [
        "RLSE-33",
        "RLSE-21",
        "TEST-20"
      ]
    },
    {
      "id": "SOLD2-02",
      "severity": "high",
      "status": "open",
      "file": ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py",
      "line": 157,
      "title": "Copied index flags hide changed tracked modules",
      "evidence": "cp -- \"$idx\" \"$d/index\"; ... git -C \"$1\" diff HEAD --name-only",
      "consequence": "assume-unchanged or skip-worktree hides changed shadow.py; both roots report clean and imports succeed.",
      "fix": "Refuse those index flags or clear them only in the private index; add real-Git changed-module regressions.",
      "canon": [
        "RLSE-33",
        "RLSE-21",
        "NDM-06"
      ]
    },
    {
      "id": "SOLD2-03",
      "severity": "high",
      "status": "open",
      "file": ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py",
      "line": 157,
      "title": "Untracked enumeration misses importable directory roots",
      "evidence": "git ls-files --others -- '*.py' '*.pyc' '*.so' '*.pth'",
      "consequence": "Nested Git packages and extensionless directory symlinks import code while the listing is empty and admission accepts.",
      "fix": "Scan import-capable paths as uid 1002 across nested repos; refuse unverified directory symlinks; retain .ses/log acceptance.",
      "canon": [
        "RLSE-33",
        "RLSE-21",
        "TEST-20"
      ]
    },
    {
      "id": "SOLD2-04",
      "severity": "high",
      "status": "open",
      "file": ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py",
      "line": 157,
      "title": "Combined diff can cancel staged and unstaged changes",
      "evidence": "git -C \"$1\" diff HEAD --name-only",
      "consequence": "Stage B then restore worktree A=HEAD: preclaim accepts clean, but the recipe's git diff refuses after the claim.",
      "fix": "Check cached-versus-HEAD and worktree-versus-index separately in the private index; add a cancellation regression.",
      "canon": [
        "RLSE-33",
        "NDM-06",
        "TEST-20"
      ]
    },
    {
      "id": "SOLD2-05",
      "severity": "low",
      "status": "open",
      "file": ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py",
      "line": 176,
      "title": "Shell timeout leaves a descendant and private index",
      "evidence": "subprocess.run(['/bin/sh','-c',DIFF,'sh',root],timeout=t,**kw); trap 'rm -rf \"$d\"' EXIT",
      "consequence": "A real 0.2 s timeout left the Git/fsmonitor descendant alive and one temporary index directory; SIGKILL bypasses EXIT.",
      "fix": "Bound and reap the child's process group; clean scratch as uid 1002; add a real delayed-descendant regression.",
      "canon": [
        "AGT-10",
        "DIAG-07",
        "FLOW-01"
      ]
    }
  ],
  "coverage": [
    {
      "file": ".task-state/bakeoff-rounds-20261017/qwen-ab/cohort_admission.py",
      "functions": [
        "DETERMINISTIC",
        "AdmissionRefusal.__init__",
        "admit"
      ],
      "read_fully": true
    },
    {
      "file": ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py",
      "functions": [
        "need",
        "parse_args",
        "verify_prepared",
        "workspace_ok",
        "bound_names",
        "source_binding",
        "bind_generator",
        "run_git",
        "preclaim_script (including generated left/tree)",
        "classify_preclaim",
        "bootstrap_source",
        "pilot_checks",
        "module_digest",
        "main (including inputs)"
      ],
      "read_fully": true
    },
    {
      "file": ".task-state/bakeoff-rounds-20261017/qwen-ab/test_cohort_admission.py",
      "functions": [
        "test_transient_and_deterministic_sets_are_exact",
        "test_source_unavailable_is_deterministic_not_transient_and_admit_never_retries_it",
        "RECIPE/prepared",
        "source_binding tests and REBINDS (1006-1098)",
        "source_report/report and all classify_preclaim tests (1402-1572)",
        "completed/healthy_child/publish/FakeClock/roots",
        "run_preclaim/run_local/git_in/committed_repo",
        "_record_open/opened_paths",
        "preclaim composed, timeout, private-index and real-Git tests (1710-1999)",
        "rebind",
        "test_main_refuses_a_recipe_still_bound_to_the_sandbox_before_any_ssh",
        "test_main_refuses_an_unavailable_source_before_the_claim",
        "operator_checkout/stubbed_main and real_runner seams"
      ],
      "read_fully": true
    },
    {
      "file": ".task-state/bakeoff-rounds-20261017/qwen-ab/workspace/prepare_qwen_ab.py",
      "functions": [
        "sha",
        "require",
        "pinned",
        "assignment",
        "producer",
        "function_bytes",
        "replace_once",
        "validate_configs",
        "prepare",
        "main"
      ],
      "read_fully": true
    },
    {
      "file": ".task-state/bakeoff-rounds-20261017/qwen-ab/workspace/test_prepare_qwen_ab.py",
      "functions": [
        "make",
        "DurableSourceTests.test_pilot_and_full_recipes_bind_the_durable_source_root",
        "DurableSourceTests.test_reference_template_still_carries_the_replaced_lines",
        "DurableSourceTests.test_generated_module_level_repo_and_python_are_the_durable_expressions"
      ],
      "read_fully": true
    },
    {
      "file": ".task-state/bakeoff-rounds-20261017/qwen-ab/references/admission/run_selected_root_resume_qualification.py",
      "functions": [
        "git_blob",
        "inputs",
        "bootstrap",
        "run"
      ],
      "read_fully": true
    },
    {
      "file": ".task-state/bakeoff-rounds-20261017/qwen-ab/references/QWEN38-GSQ-ALL38-LONG-R20C.execution.remote.py",
      "functions": [
        "source/env bindings",
        "gate",
        "source-check and interpreter-use context"
      ],
      "read_fully": false
    },
    {
      "file": ".task-state/bakeoff-rounds-20261017/qwen-ab/references/LEXICON-MIMO-40-LAST40-R1.remote.py",
      "functions": [
        "source-check loop",
        "metadata_code/paired_client interpreter use"
      ],
      "read_fully": false
    }
  ],
  "canary_checked": [
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:40",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:54",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:59",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:60",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:61",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:63",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:71",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:74",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:75",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:82",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:83",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:84",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:86",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:87",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:88",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:90",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:91",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:97",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:98",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:99",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:101",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:103",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:108",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:110",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:115",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:118",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:120",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:121",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:123",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:125",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:126",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:128",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:130",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:143",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:157",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:163",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:165",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:169",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:171",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:172",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:174",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:176",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:177",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:180",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:181",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:183",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:186",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:187",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:188",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:199",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:201",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:203",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:205",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:208",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:212",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:221",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:222",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:224",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:228",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:232",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:241",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:251",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:253",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:256",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:258",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:259",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:260",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:263",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:266",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:269",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:271",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:278",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:294",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:298",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:305",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:306",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:310",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:312",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:313",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:316",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:317",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:319",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:321",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:343",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:344",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:351",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:353",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:354",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:358",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:361",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:363",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:364",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/workspace/prepare_qwen_ab.py:65",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/workspace/prepare_qwen_ab.py:71",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/workspace/prepare_qwen_ab.py:73",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/workspace/prepare_qwen_ab.py:80",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/workspace/prepare_qwen_ab.py:88",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/workspace/prepare_qwen_ab.py:96",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/workspace/prepare_qwen_ab.py:101",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/workspace/prepare_qwen_ab.py:112",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/workspace/prepare_qwen_ab.py:114",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/workspace/prepare_qwen_ab.py:116",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/workspace/prepare_qwen_ab.py:118",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/workspace/prepare_qwen_ab.py:121",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/workspace/prepare_qwen_ab.py:123",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/workspace/prepare_qwen_ab.py:126",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/workspace/prepare_qwen_ab.py:131",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/workspace/prepare_qwen_ab.py:132",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/workspace/prepare_qwen_ab.py:133",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/workspace/prepare_qwen_ab.py:140",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/workspace/prepare_qwen_ab.py:141",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/workspace/prepare_qwen_ab.py:145",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/workspace/prepare_qwen_ab.py:147",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/workspace/prepare_qwen_ab.py:148",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/workspace/prepare_qwen_ab.py:155",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/workspace/prepare_qwen_ab.py:157",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/workspace/prepare_qwen_ab.py:158",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/workspace/prepare_qwen_ab.py:161",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/workspace/prepare_qwen_ab.py:162",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/workspace/prepare_qwen_ab.py:185",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/workspace/prepare_qwen_ab.py:186",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/workspace/prepare_qwen_ab.py:228",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/workspace/prepare_qwen_ab.py:232",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/workspace/prepare_qwen_ab.py:233",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/workspace/prepare_qwen_ab.py:285",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/cohort_admission.py:31",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/cohort_admission.py:33",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/cohort_admission.py:77",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/cohort_admission.py:80",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/cohort_admission.py:364",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/cohort_admission.py:368",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/cohort_admission.py:371",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/references/LEXICON-MIMO-40-LAST40-R1.remote.py:136",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/references/LEXICON-MIMO-40-LAST40-R1.remote.py:137",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/references/LEXICON-MIMO-40-LAST40-R1.remote.py:138",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/references/LEXICON-MIMO-40-LAST40-R1.remote.py:223",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/references/LEXICON-MIMO-40-LAST40-R1.remote.py:242"
  ],
  "commands_run": [
    "pwd\n git status --short\n git rev-parse --show-toplevel\n git log -6 --oneline\n if [ -e .venv ]; then ls -ld .venv .venv/bin/python; fi\n=> exit 0",
    "cat /home/gate/.codex/skills/codebase-memory/SKILL.md\n rg --files -g AGENTS.md -g pyproject.toml .task-state/bakeoff-rounds-20261017/qwen-ab .task-state/bakeoff-rounds-20261017/qwen-latebind 2>/dev/null\n=> exit 2",
    "cat AGENTS.md\n rg --files --hidden --no-ignore -g AGENTS.md -g pyproject.toml .task-state/bakeoff-rounds-20261017/qwen-ab .task-state/bakeoff-rounds-20261017/qwen-latebind\n wc -l .task-state/bakeoff-rounds-20261017/qwen-ab/{cohort_admission.py,run_qwen_cohort_operation.py,test_cohort_admission.py,workspace/prepare_qwen_ab.py,workspace/test_prepare_qwen_ab.py}\n git ls-files .task-state/bakeoff-rounds-20261017/qwen-ab\n git status --porcelain=v1 --untracked-files=all\n=> exit 0",
    "nl -ba .task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py\n=> exit 0",
    "nl -ba .task-state/bakeoff-rounds-20261017/qwen-ab/workspace/prepare_qwen_ab.py\n=> exit 0",
    "lane_root=\"$(git rev-parse --show-toplevel)\" || { echo 'cannot resolve lane root' >&2; exit 1; }\nresolved_python=\"$lane_root/.venv/bin/python\"\nif [ ! -x \"$resolved_python\" ]; then echo 'lane interpreter unavailable' >&2; exit 97; fi\nPYTHONDONTWRITEBYTECODE=1 \"$resolved_python\" -B -c \"import pathlib,sys; root=pathlib.Path.cwd(); sys.path.insert(0,str(root/'.task-state/bakeoff-rounds-20261017/qwen-ab')); import cohort_admission,run_qwen_cohort_operation; print(cohort_admission.__file__); print(run_qwen_cohort_operation.__file__); assert all(pathlib.Path(m.__file__).is_relative_to(root) for m in (cohort_admission,run_qwen_cohort_operation))\" || exit $?\nPYTHONDONTWRITEBYTECODE=1 \"$resolved_python\" -m pytest .task-state/bakeoff-rounds-20261017/qwen-ab/test_cohort_admission.py .task-state/bakeoff-rounds-20261017/qwen-ab/workspace/test_prepare_qwen_ab.py -q\n=> exit 0",
    "sed -n '196,371{=;p;}' .task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py\n sed -n '1,59p' .task-state/bakeoff-rounds-20261017/qwen-ab/workspace/prepare_qwen_ab.py\n=> exit 0",
    "nl -ba .task-state/bakeoff-rounds-20261017/qwen-ab/cohort_admission.py\n=> exit 0",
    "sed -n '1,80p' .task-state/bakeoff-rounds-20261017/qwen-ab/references/QWEN38-GSQ-ALL38-LONG-R20C.execution.remote.py\n sed -n '130,145p' .task-state/bakeoff-rounds-20261017/qwen-ab/references/QWEN38-GSQ-ALL38-LONG-R20C.execution.remote.py\n cat .task-state/bakeoff-rounds-20261017/qwen-ab/references/admission/run_selected_root_resume_qualification.py\n=> exit 0",
    "nl -ba .task-state/bakeoff-rounds-20261017/qwen-ab/test_cohort_admission.py | sed -n '940,1120p;1400,1650p'\n=> exit 0",
    "nl -ba .task-state/bakeoff-rounds-20261017/qwen-ab/workspace/test_prepare_qwen_ab.py | sed -n '1,110p;700,739p'\n rg --files --hidden /home/gate/.codex/sessions /tmp 2>/dev/null | head -50\n=> exit 0",
    "cat .task-state/bakeoff-rounds-20261017/qwen-ab/references/admission/run_selected_root_resume_qualification.py\n rg -n --hidden --glob '!uv.lock' --glob '!pnpm-lock.yaml' 'qwen-ab|run_qwen_cohort_operation|prepare_qwen_ab|cohort_admission' apps packages Dockerfile* .github 2>/dev/null\n=> exit 2",
    "ls -t /home/gate/.codex/sessions/2026/10/20 | head -5\n=> exit 0",
    "rg -l '72840' /home/gate/.codex/sessions/2026/10/20/*.jsonl\n=> exit 0",
    "rg -o '[0-9]+ passed[^\"\\\\]{0,150}|Process exited with code [0-9]+|\"exit_code\": ?[0-9]+' /home/gate/.codex/sessions/2026/10/20/rollout-2026-10-20T19-11-36-01a15ab9-eb74-7fc2-a342-9904da968715.jsonl | tail -25\n=> exit 0",
    "nl -ba .task-state/bakeoff-rounds-20261017/qwen-ab/test_cohort_admission.py | sed -n '1,142p;1649,2015p;2120,2164p'\n=> exit 0",
    "lane_root=\"$(git rev-parse --show-toplevel)\" || exit 1\nresolved_python=\"$lane_root/.venv/bin/python\"\nif [ ! -x \"$resolved_python\" ]; then exit 97; fi\n\"$resolved_python\" -B - <<'PY'\nimport json,re\nfrom pathlib import Path\nlog=Path('/home/gate/.codex/sessions/2026/10/20/rollout-2026-10-20T19-11-36-01a15ab9-eb74-7fc2-a342-9904da968715.jsonl')\nfor line in log.read_text().splitlines():\n    item=json.loads(line)\n    payload=item.get('payload',{})\n    if payload.get('type') != 'function_call_output':\n        continue\n    output=payload.get('output','')\n    if '364 passed, 79 subtests passed in 11.96s' in output:\n        for match in re.finditer(r'\\{\"chunk_id\"[^\\n]*364 passed[^\\n]*', output):\n            print(match.group(0)[-3000:])\nPY\n=> exit 0",
    "rg '364 passed' /home/gate/.codex/sessions/2026/10/20/rollout-2026-10-20T19-11-36-01a15ab9-eb74-7fc2-a342-9904da968715.jsonl | cut -c1-600 | head -4\n=> exit 0",
    "lane_root=\"$(git rev-parse --show-toplevel)\" || exit 1\nresolved_python=\"$lane_root/.venv/bin/python\"\nif [ ! -x \"$resolved_python\" ]; then exit 97; fi\n\"$resolved_python\" -B - <<'PY'\nimport json\nfrom pathlib import Path\nfor line in Path('/home/gate/.codex/sessions/2026/10/20/rollout-2026-10-20T19-11-36-01a15ab9-eb74-7fc2-a342-9904da968715.jsonl').read_text().splitlines():\n    payload=json.loads(line).get('payload',{})\n    item=payload.get('item',{})\n    if payload.get('type')=='item_completed' and item.get('process_id')=='72840':\n        print(json.dumps({k:v for k,v in item.items() if k not in ('command','cwd','formatted_command')},indent=2))\n        break\nPY\n=> exit 0",
    "lane_root=\"$(git rev-parse --show-toplevel)\" || exit 1\nresolved_python=\"$lane_root/.venv/bin/python\"\nif [ ! -x \"$resolved_python\" ]; then exit 97; fi\nPYTHONDONTWRITEBYTECODE=1 \"$resolved_python\" -B /tmp/qwen-durable-gate2-probes.py\n=> exit 0",
    "rg --files --hidden -g '!**/node_modules/**' -g '*Dockerfile*' -g '*dockerignore*' -g '*ocir*'\n rg -n --hidden 'qwen-ab|run_qwen_cohort_operation|prepare_qwen_ab|cohort_admission' apps packages .github\n=> exit 1",
    "nl -ba .task-state/bakeoff-rounds-20261017/qwen-ab/test_cohort_admission.py | sed -n '1160,1400p;2017,2120p'\n nl -ba .task-state/bakeoff-rounds-20261017/qwen-ab/references/QWEN38-GSQ-ALL38-LONG-R20C.execution.remote.py | sed -n '128,143p'\n rg -n 'metadata_code|paired_client|cwd=|gate\\(\\[str\\(python\\)' .task-state/bakeoff-rounds-20261017/qwen-ab/references/LEXICON-MIMO-40-LAST40-R1.remote.py\n=> exit 0",
    "cat apps/prototype-description-service/Dockerfile\n cat apps/prototype-description-service/.dockerignore\n rg -n --hidden 'qwen-ab|run_qwen_cohort_operation|prepare_qwen_ab|cohort_admission' apps packages scripts/deploy .github\n git branch --show-current\n git diff --exit-code\n=> exit 0",
    "lane_root=\"$(git rev-parse --show-toplevel)\" || exit 1\nresolved_python=\"$lane_root/.venv/bin/python\"\nif [ ! -x \"$resolved_python\" ]; then exit 97; fi\nPYTHONDONTWRITEBYTECODE=1 \"$resolved_python\" -B /tmp/qwen-durable-gate2-probes.py\n=> exit 0",
    "rg -n '^(COPY|WORKDIR)|docker build|BUILD_CONTEXT|build_context' apps/prototype-description-service/Dockerfile scripts/deploy/recognition-service.sh\n rg -n 'for source_root|git.*diff' .task-state/bakeoff-rounds-20261017/qwen-ab/references/LEXICON-MIMO-40-LAST40-R1.remote.py\n git diff --exit-code -- .task-state/bakeoff-rounds-20261017/qwen-ab\n git status --short\n=> exit 0",
    "rg -n '^def |^class |    need\\(|    require\\(|    if |    return \\(' .task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py .task-state/bakeoff-rounds-20261017/qwen-ab/workspace/prepare_qwen_ab.py\n=> exit 0",
    "lane_root=\"$(git rev-parse --show-toplevel)\" || exit 1\nresolved_python=\"$lane_root/.venv/bin/python\"\nif [ ! -x \"$resolved_python\" ]; then exit 97; fi\nPYTHONDONTWRITEBYTECODE=1 \"$resolved_python\" -B /tmp/qwen-durable-gate2-probes.py\n=> exit 0",
    "id -u\n sed -n '1588,1615p' scripts/deploy/recognition-service.sh\n sed -n '159,180p' apps/prototype-description-service/Dockerfile\n git diff --exit-code\n=> exit 0"
  ]
}
```
