# BAKEOFF-QWEN-DURABLE-GATE2-SOL

Re-gate of tip `47527daba`, including the accepted ignored-code change (SOLD2-01). The full diff base `a994816f5` → tip could not be re-run here: this clone is history-stripped (HEAD `456ee25`, "sandbox base"), and neither `a994816f5` nor `47527daba` is present as an object. The reviewed artifact is the checked-out tree. Its tree `3bc52ad6` matches `source_tree` in `.workbay-source-provenance` (source commit `3e9cd3822`), and it carries the `47527dab` change at `run_qwen_cohort_operation.py:157`: `--exclude-standard` is absent and the suffix pathspec is present. Each finding below was reproduced against that code. Only this report is changed.

**The gate fails.** Three open high findings (SOLD2-02, SOLD2-03, SOLD2-04), two open medium findings (SOLD2-06 and SOLD2-07, both new in this pass), and one open low finding (SOLD2-05, deferred). SOLD2-01 is high and **fixed** at `47527daba`, accepted per #7750.

Rule authority is the Canon v0.26.2 table supplied in #7750 and #7751. The canon directory is absent in the sandbox by design and is not listed as a blocker. Applicable checks: [RLSE-33] **Check before effects**, [RLSE-21] **The artifact that runs is the artifact reviewed**, [NDM-06] **Stop on a violated expectancy**, [TEST-20] **Known-good baseline**, and [API-08] **No unbounded retry**. AGT-10 and DIAG-07 are cited in the comments of `classify_preclaim`. FLOW-01 is the immutable-evidence rule from #7751.

**Test run.** The lane test command ran exactly once, using `$lane_root/.venv/bin/python`, with `lane_root` from `git rev-parse --show-toplevel`. Result: exit 0, `364 passed, 79 subtests passed in 11.07s`. Before that run, both lane modules imported from inside the lane. The lane owns scripts, not an installable package, so the package import-origin control does not apply. This run is the local verification that #1245 reports as absent, so that absence no longer blocks the gate.

**Probes.** Each open finding was reproduced in disposable temp repositories under `/tmp`. The probes ran as local uid 1002, the uid the recipe's children use, and called the `DIFF` text extracted from the generated `preclaim_script`. No ssh, sudo, GPU, Docker, network or live operation was run, and no repository file was written. Results are summarised per finding below.

## Findings

**SOLD2-01 (high, fixed).** The `DIFF` child lists `ls-files --others` without `--exclude-standard` (`run_qwen_cohort_operation.py:157`; zero hits for that flag in any lane file). A sanity probe with an ignored `__pycache__/shadow.cpython-312.pyc` shows the file in the listing and refuses. The eight ignored-code cases in `test_ignored_import_capable_code_is_not_clean_and_is_refused` (four filenames × two ignore modes, `test_cohort_admission.py:1975-1999`) pass in the lane run. Accepted. Not re-verified in this pass: the red-before run, since the history is absent, and the live root counts, since there was no VM access.

**SOLD2-02 (high, open).** `git diff HEAD` honours the index flags copied into the private index. Probe: tracked `apps/prototype-description-service/shadow.py` with `--assume-unchanged` and changed content gives `DIFF` rc 0 with empty stdout (clean). The recipe's `git diff --name-only` is also empty, and `import shadow` succeeds on the changed file. `--skip-worktree` gives the same result. The flag alone, with content unchanged, is also clean. A changed module is therefore imported after a clean preclaim. Fix (#7751 item 3): write `ls-files -v` to `"$d/v"` and refuse any line matching `^([a-z]|S) `. Do not clear the bits with `update-index`. Tests: assume-unchanged with changed content refuses, skip-worktree with changed content refuses, and the flag alone refuses.

**SOLD2-03 (high, open).** The suffix pathspec is a denylist. Probe: a nested repo at `apps/prototype-description-service/untracked_namespace/` containing `child.py` gives `DIFF` clean, and `import untracked_namespace.child` succeeds. An extensionless directory symlink `untracked_link` to a scratch package gives `DIFF` clean, and `import untracked_link.mod` succeeds. Fix (#7751 item 4): write `ls-files --others --directory --no-empty-directory` to `"$d/o"` with no pathspec and no `--exclude-standard`. Print every line that is not exactly an entry in `KNOWN_RUNTIME_ENTRIES`, which holds `:memory:.ses` and `prototype_description_service.egg-info/`, and add the import-time check that rejects `'` and newlines. Do not add suffixes or a name classifier.

**SOLD2-04 (high, open).** `git diff HEAD` compares HEAD with the worktree only. Probe: commit A, stage B, restore the worktree to A. `DIFF` gives rc 0 with empty stdout (clean). The recipe's `git diff --name-only` (index against worktree) prints `apps/prototype-description-service/shadow.py`. Preclaim therefore accepts a root that the recipe refuses after the GPU claim. Fix (#7751 item 2): run `diff --cached --name-only HEAD` and `diff --name-only` as separate commands, each with its own rc check. Add the cancellation test from #7751.

**SOLD2-05 (low, open, deferred).** A finite fsmonitor hook outlives a timed-out `DIFF`. Probe: with a slow hook and a 0.5 s timeout, `subprocess.run` raised `TimeoutExpired`. The hook's shell was still alive afterwards, and one scratch directory was left in `TMPDIR`, because the killed shell skips the EXIT trap. Deferred as QDSG2-05 (process-group reaping), so it is out of scope for this fix. #7751 item 1 (`core.fsmonitor=false`) removes the fsmonitor route used by this probe but not the general timeout cleanup.

**SOLD2-06 (medium, open, new in this pass).** A repo-config `core.fsmonitor` runs its hook inside the uid-1002 `DIFF` child, before the claim. Probe: `core.fsmonitor` set in `.git/config` to a script that touches a marker. The marker was created, and `DIFF` returned rc 0 with empty stdout. The hook is not part of the reviewed tree ([RLSE-21]) and runs before the claim ([RLSE-33]). Fix is already in #7751 item 1: `git -c core.fsmonitor=false -c core.untrackedCache=false -C "$1"` on every git call in `DIFF`, with the marker test. The untracked-cache setting is defence in depth. A probe with a cached untracked listing did not hide a new module, so no untracked-cache defect is claimed.

**SOLD2-07 (medium, open, new in this pass).** A tracked symlink in the import tree can point outside the reviewed tree. Probe: commit `apps/prototype-description-service/tracked_link` as a symlink to an outside directory containing `mod.py`, then change the target after the commit. `DIFF` gives rc 0 with empty stdout (clean), and `import tracked_link.mod` prints the changed value. The current tree has seven tracked symlinks, all outside `apps/prototype-description-service` (under `config/agent-workflows/` and `scripts/consumer-hooks/git/`), so this is latent and not present in the snapshot. Fix: in the `DIFF` child, write `ls-files -s` to `"$d/s"` and refuse any line with mode `120000` whose path is under `apps/prototype-description-service/`, using the same rc handling as item 5. Test: a committed symlink to an outside target refuses after the target changes, and the seven existing symlinks stay clean. This is not in #7751, so the orchestrator needs to decide whether to fold it into FIXD.

## Scope limits

- Read in this pass: `run_qwen_cohort_operation.py` lines 150-200 (`preclaim_script`, `DIFF`, and the generated child) and 196-240 (`classify_preclaim`). In `test_cohort_admission.py`, lines 1923-1999 (the untracked, log, `.ses` and ignored-code tests) and the test names from 1710 to 2004.
- Not re-read: the rest of `run_qwen_cohort_operation.py`, `cohort_admission.py`, `workspace/prepare_qwen_ab.py`, `workspace/test_prepare_qwen_ab.py`, `references/`, and the rest of the test file. The earlier report's read-through of those is not re-verified here.
- Prior fixes SOLD-01 to SOLD-05 and FIXB are carried by the 364-test green suite. They were not re-derived in this pass.
- Not verified: the base→tip diff (the objects are absent), the red-before run of the eight ignored-code tests, and the live VM counts of ignored import-capable files.
- Rejected and deferred items are not reopened. No retries, no root `os.access`, no stub-only seam test, no unkillable-test fix, and no new suffix or name classifier. Each fix above keeps the uid-1002 child, the rc checks and the exit classes unchanged.

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
      "evidence": "No --exclude-standard in any lane file (0 hits). DIFF lists ls-files --others with the *.py/*.pyc/*.so/*.pth pathspec. Sanity probe: ignored __pycache__/*.pyc is listed and refused. Eight ignored-code tests (test_cohort_admission.py:1975-1999) pass in the lane run.",
      "consequence": "The former command admitted ignored shadow modules; checkpoint 47527daba closes that omission.",
      "fix": "Accepted 47527daba. Red-before and live root counts not re-verified in this pass.",
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
      "evidence": "Probe: assume-unchanged or skip-worktree on tracked apps/prototype-description-service/shadow.py with changed content gives DIFF rc 0, empty stdout, recipe git diff --name-only empty, and import shadow succeeds. The flag alone (content unchanged) is also clean.",
      "consequence": "A changed module is imported after a clean preclaim.",
      "fix": "#7751 item 3: ls-files -v into \"$d/v\"; refuse lines matching ^([a-z]|S) ; do not clear bits. Tests: assume-unchanged changed, skip-worktree changed, flag alone all refuse.",
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
      "evidence": "Probe: nested repo apps/prototype-description-service/untracked_namespace/child.py gives DIFF clean and import succeeds. Extensionless dir symlink untracked_link -> scratch package gives DIFF clean and import succeeds.",
      "consequence": "Nested Git packages and extensionless directory symlinks import code while the suffix listing is empty and admission accepts.",
      "fix": "#7751 item 4: ls-files --others --directory --no-empty-directory into \"$d/o\", no pathspec, no --exclude-standard; print lines not exactly in KNOWN_RUNTIME_ENTRIES (:memory:.ses and prototype_description_service.egg-info/); import-time check rejecting ' and newline.",
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
      "evidence": "Probe: commit A, stage B, restore worktree to A. DIFF rc 0, empty stdout (clean). Recipe git diff --name-only prints apps/prototype-description-service/shadow.py.",
      "consequence": "Preclaim accepts a root that the recipe's own git diff refuses after the GPU claim.",
      "fix": "#7751 item 2: diff --cached --name-only HEAD and diff --name-only as separate commands, each with its own rc check; cancellation regression.",
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
      "evidence": "Probe: slow fsmonitor hook, DIFF with 0.5 s timeout raised TimeoutExpired; hook shell still alive; one scratch dir left in TMPDIR (SIGKILL skips the EXIT trap).",
      "consequence": "A timed-out preclaim leaves a live descendant and a temporary index directory.",
      "fix": "Deferred as QDSG2-05 (process-group reaping, out of scope for FIXD). #7751 item 1 removes the fsmonitor route of this probe only.",
      "canon": [
        "AGT-10",
        "DIAG-07",
        "FLOW-01"
      ]
    },
    {
      "id": "SOLD2-06",
      "severity": "medium",
      "status": "open",
      "file": ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py",
      "line": 157,
      "title": "Repo-config core.fsmonitor runs a hook in the DIFF child",
      "evidence": "Probe: core.fsmonitor in .git/config set to a script that touches a marker. Marker created; DIFF rc 0, empty stdout.",
      "consequence": "Code outside the reviewed tree runs in the uid-1002 child before the claim.",
      "fix": "#7751 item 1: git -c core.fsmonitor=false -c core.untrackedCache=false -C \"$1\" on every git call in DIFF; marker-never-created test.",
      "canon": [
        "RLSE-21",
        "RLSE-33"
      ]
    },
    {
      "id": "SOLD2-07",
      "severity": "medium",
      "status": "open",
      "file": ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py",
      "line": 157,
      "title": "Tracked symlink in the import tree can point outside the reviewed tree",
      "evidence": "Probe: committed apps/prototype-description-service/tracked_link -> outside dir with mod.py; target changed after commit. DIFF rc 0, empty stdout; import tracked_link.mod prints the changed value. Current tree: 7 tracked symlinks, none under apps/prototype-description-service (latent).",
      "consequence": "The imported code changes without any change to HEAD or the index.",
      "fix": "Not in #7751. In DIFF: ls-files -s into \"$d/s\"; refuse mode 120000 entries under apps/prototype-description-service/ with the item 5 rc handling. Test: committed symlink to an outside target refuses after the target changes; the seven existing symlinks stay clean.",
      "canon": [
        "RLSE-21",
        "RLSE-33"
      ]
    }
  ],
  "coverage": [
    {
      "file": ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py",
      "functions": [
        "preclaim_script (DIFF text and generated child, lines 150-200)",
        "classify_preclaim (lines 196-240)"
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
        "bootstrap_source",
        "pilot_checks",
        "module_digest",
        "main"
      ],
      "read_fully": false
    },
    {
      "file": ".task-state/bakeoff-rounds-20261017/qwen-ab/test_cohort_admission.py",
      "functions": [
        "test_an_untracked_python_file_that_is_not_ignored_is_not_clean_and_is_refused (1923)",
        "test_a_log_file_matched_by_gitignore_stays_clean (1931)",
        "test_an_untracked_ses_runtime_file_that_is_not_ignored_stays_clean (1950)",
        "test_an_untracked_import_capable_file_is_not_clean_and_is_refused (1963)",
        "test_ignored_import_capable_code_is_not_clean_and_is_refused (1977)"
      ],
      "read_fully": true
    },
    {
      "file": ".task-state/bakeoff-rounds-20261017/qwen-ab/test_cohort_admission.py",
      "functions": [
        "preclaim test names 1710-2004 (headings only)",
        "remaining test bodies"
      ],
      "read_fully": false
    },
    {
      "file": ".task-state/bakeoff-rounds-20261017/qwen-ab/cohort_admission.py",
      "functions": [],
      "read_fully": false
    },
    {
      "file": ".task-state/bakeoff-rounds-20261017/qwen-ab/workspace/prepare_qwen_ab.py",
      "functions": [],
      "read_fully": false
    },
    {
      "file": ".task-state/bakeoff-rounds-20261017/qwen-ab/workspace/test_prepare_qwen_ab.py",
      "functions": [],
      "read_fully": false
    }
  ],
  "canary_checked": [
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:157",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:176",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:196",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/run_qwen_cohort_operation.py:200",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/test_cohort_admission.py:1923",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/test_cohort_admission.py:1931",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/test_cohort_admission.py:1950",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/test_cohort_admission.py:1963",
    ".task-state/bakeoff-rounds-20261017/qwen-ab/test_cohort_admission.py:1977"
  ],
  "commands_run": [
    "lane_root=\"$(git rev-parse --show-toplevel)\"; git status; git log -1; test -x \"$lane_root/.venv/bin/python\" => exit 0",
    "git cat-file -t 47527daba / a994816f5 / 3e9cd3822 => objects absent (history stripped; HEAD 456ee25)",
    "$resolved_python -B -c origin check: import cohort_admission and run_qwen_cohort_operation, assert both under lane root => exit 0",
    "PYTHONDONTWRITEBYTECODE=1 $resolved_python -m pytest .task-state/bakeoff-rounds-20261017/qwen-ab/test_cohort_admission.py .task-state/bakeoff-rounds-20261017/qwen-ab/workspace/test_prepare_qwen_ab.py -q => exit 0 (364 passed, 79 subtests passed in 11.07s)",
    "grep -c exclude-standard over lane .py files => 0 hits in every file",
    "git ls-files -s | awk mode 120000 => 7 tracked symlinks, none under apps/prototype-description-service",
    "probe.py: DIFF child (extracted from preclaim_script) against temp repos under /tmp, as uid 1002 => exit 0",
    "probe_symlink.py: tracked symlink with out-of-repo target changed after commit => exit 0",
    "untracked-cache probe in a temp repo (core.untrackedCache true, directory mtime restored) => exit 0; new module listed under both settings"
  ]
}
```
