# BAKEOFF-INC-REBIND-20261020: Sol merge gate, round 2

Verdict: **fail**. The assigned suite passes, and the ordinary publication, late-conflict, and CLI-boundary controls are improved. A failure after the prospective has been linked can still leave that commit marker without its matching remote recipe when marker rollback fails (IRG2-01, high). The identical-bytes publication race also lacks a committed regression (IRG2-02, medium). Fix both before merge. The remaining findings are low and may be deferred under the brief's severity policy. This is a review only; no implementation or test files were edited.

## Subject and round-1 adjudication

The requested subject is `af9a823f7559928a501546dfa327f289d21034f6`, relative to base `455b8f35e`. This sandbox has stripped history, so that commit object cannot be inspected. The implementation Git blob is `c5a1ede00b55aa186db9301a76a33847ce4edd00` and the test Git blob is `cc633867ace2ccf610cad9ada5945cf2d01c956d`, matching the supplied round-2 diff indexes. The round-1 report was read before this review.

- **IRG-01 — not fixed in full.** `writer_lock()` takes an exclusive, non-blocking directory-fd `flock`; planning and publication occur inside it (`rebind_incumbent_recipe.py:179-191,286-288`). Each staged file is fsynced, linked without clobbering, and the remote is published and directory-synced before the prospective (`205-228`). Only successful links enter `linked`, and rollback checks device/inode identity (`225-226,241-250`). The suite covers a second-link failure on a fresh directory, preservation of an identical preexisting remote, and a residual-path refusal (`test_rebind_incumbent_recipe.py:307-387`). However, rollback continues to delete the remote when removal of an already-published prospective fails (`253-262`). A diagnostic reproduced a sole prospective remaining after refusal. There is also no directory-sync barrier between marker removal and remote removal during rollback; a crash before its single final sync does not establish durable removal order. See IRG2-01.
- **IRG-02 — fixed.** `os.link()` refuses an occupied destination atomically; `FileExistsError` compares its bytes and refuses a late difference (`221-226`). The late-conflict control leaves competitor prospective bytes intact, removes the run's remote, and leaves no run-created mixed pair (`test_rebind_incumbent_recipe.py:350-366`). The child-process lock-contention control passes on Linux using an actual directory fd, returns exit 3 with exactly one JSON line, and writes nothing (`413-422`). No lock file is created. The identical-byte acceptance branch is correct in the diagnostic but has the regression gap in IRG2-02.
- **IRG-03 — fixed for the specified input and CLI boundary.** Recipe UTF-8 encoding failures become `Refusal` before either digest comparison (`79-85`). JSON read/decode errors become `Refusal` (`62-70`), and `main()` catches exactly `Refusal` and `OSError`, without bare `Exception` (`299-305`). Publication errors enter rollback before reaching that boundary (`266-276`). The surrogate and output-I/O child-process controls pass with one JSON refusal line and exit 3 (`test_rebind_incumbent_recipe.py:424-450`). Rollback's diagnostic masking is separately recorded as low IRG2-03.

## Regression and diagnostic evidence

- The input checks retain the schema, unchanged prepared status, `execution_started is False`, calculated digest, immutable recipe pin, old contract subject, absence of an existing rebind block, and nonempty unique preserved-function names. Bare and wrapper inputs produce identical outputs.
- Each of the four old substitution literals must occur exactly once. Missing and duplicated targets refuse. Parsing, forbidden residues, the durable `SOURCE` assignment, and assignment AST equality remain checked. The Qwen runner is imported by its file path; its `REPO_EXPR` and `PYTHON_EXPR` are used directly. Preserved functions and decorators are compared through exact source segments; subject validation requires 40 lowercase hex characters distinct from the old subject. The happy-path control checks exact rebound bytes and the complete rebind block, with status unchanged.
- `run_qwen_cohort_operation.py:101-138` confirms that `source_binding()` returns `<SOURCE_ROOT>/<SOURCE>.venv/bin/python`, matching `repo.parent/(SOURCE+'.venv')/'bin/python'`. No venv-layout regression was found.
- Fresh publication leaves exactly the two expected outputs. Handled second-link and late-conflict failures leave no `.tmp` files in the suite. Identical reruns preserve bytes and inodes, return `ALREADY_REBOUND`, and stage nothing. In forward publication the prospective is linked only after the remote and its directory entry have been fsynced. The remaining unsafe failure/rollback order is IRG2-01.
- Resolved the lane root with `git rev-parse --show-toplevel`, selected its managed `.venv/bin/python`, and checked that importing `rebind_incumbent_recipe` resolves inside this worktree. This lane owns standalone scripts, with no lane-local Python package configuration. Ran the sole assigned suite **once**, using the selected interpreter: `"$resolved_python" -m pytest .task-state/bakeoff-rounds-20261017/incumbent-ab/test_rebind_incumbent_recipe.py -q`. **Exit 0: 26 passed, 27 subtests passed.** Bytecode and pytest cache writes were disabled through environment variables. No packages were installed and no broader suite was run.
- A temporary-directory diagnostic using the synthetic test recipe and patched digest linked both outputs, injected `EIO` at the post-prospective directory fsync, and denied unlink of the prospective during rollback. The CLI returned 3 with one JSON refusal naming the marker, but only `incumbent-pilot-durable.prospective.json` remained; the matching remote had been deleted. The remaining JSON parsed and carried the expected recipe and digest. This reproduces IRG2-01 without executing any recipe. Persistence across power loss was assessed from syscall order, not simulated.
- Another diagnostic injected `ENOSPC` at the prospective link, denied remote rollback, then injected `EIO` at rollback's directory fsync. The CLI returned 3, but its reason contained only the fsync error, omitting both the original publication failure and the surviving remote path (IRG2-03).
- A third diagnostic wrote byte-identical competitor remote bytes immediately before the remote `os.link`, then failed the prospective link. The CLI refused, retained the competitor remote's bytes and device/inode, and removed all temporary files. This verifies current behavior, without filling the committed-suite gap in IRG2-02. Merely appending the staged file's identity on `FileExistsError` would still encounter the inode guard; the inbox's claim that this mutation alone necessarily deletes the competitor is too strong.

## Assignment-inbox disposition and verification limits

All five inbox items were inspected: the identical-byte race gap is IRG2-02; rollback-fsync masking is IRG2-03; the undocumented filesystem requirement is IRG2-04; the output-order coupling is IRG2-05; and the unused subprocess-helper branch is IRG2-06. These are reported with proposed fixes only.

The production-pin success run on the real stored artifact with SHA-256 `603f1a9b1e65f5c1ade9e3753d7afad5099ece8e872ab3bb2cac167a7bdac3f5` remains the separate coordinator-side post-merge gate specified by the brief. Its absence does **not** contribute to this fail verdict.

Canon verification is **unavailable**: `/Users/daniel/Development/heuristics-canon-current` does not exist in this sandbox, so its `AGENTS.md`, release manifest, digests, rows, and verification cards could not be read or certified. The fix brief and source cite `v0.26.2 RLSE-21 FLOW-01`; the assignment footer cites `v0.25.3 (e680f230f0f7)`. These are supplied version claims, not verified release citations. The orchestrator must supply the pinned read-only authority and resolve that discrepancy before asserting canon compliance. This report applies the explicit review protocol without inventing canon text or using a maintainer checkout.

No codebase-memory graph tools are exposed in this session. After reading its skill and checking tool availability, this review used the exact implementation, tests, and Qwen runner source as the coverage fallback.

## Findings

```FINDINGS
[
  {
    "id": "IRG2-01",
    "severity": "high",
    "file": ".task-state/bakeoff-rounds-20261017/incumbent-ab/rebind_incumbent_recipe.py",
    "line": 256,
    "summary": "Rollback removes the remote even when removal of the already-linked prospective fails. Injecting a directory-fsync failure after the prospective link, followed by a prospective-unlink failure, returns REFUSED but leaves only the consumable prospective and deletes its matching recipe. Also, the single fsync after both unlinks does not durably order marker removal before remote removal if rollback crashes.",
    "fix": "Make rollback honor the marker-to-recipe dependency: remove the run's prospective first and fsync its directory before removing the remote. If marker removal or that sync fails, retain the matching remote, clean independent temporary files, and report the residual paths and original publication failure. Preserve device/inode ownership checks and preexisting files. Add controls for failure after both links, failed prospective rollback, and the required sync-before-remote-unlink order."
  },
  {
    "id": "IRG2-02",
    "severity": "medium",
    "file": ".task-state/bakeoff-rounds-20261017/incumbent-ab/test_rebind_incumbent_recipe.py",
    "line": 350,
    "summary": "No committed test reaches byte-identical FileExistsError acceptance during publication and then exercises rollback. The preexisting-identical test skips remote publication during planning, while the race test uses different bytes. Current code preserves the competitor in a diagnostic, but this supported ownership-sensitive branch lacks a regression.",
    "fix": "Add a controlled os.link race that creates a separate byte-identical REMOTE after planning but before its link, then fails the PROSPECTIVE link. Assert refusal, unchanged competitor bytes and device/inode, absence of the prospective, and no temporary files. Keep the competitor out of this run's rollback ownership set."
  },
  {
    "id": "IRG2-03",
    "severity": "low",
    "file": ".task-state/bakeoff-rounds-20261017/incumbent-ab/rebind_incumbent_recipe.py",
    "line": 262,
    "summary": "An OSError from rollback's final directory fsync escapes before publish can report stuck paths, masking the original publication failure and any residual-path information. A second-link ENOSPC plus a stuck remote and rollback-fsync EIO reproduced a refusal containing only EIO.",
    "fix": "Account for rollback sync failures alongside cleanup failures and compose a Refusal that preserves the original publication error, surviving paths, and sync error. Add a combined failure control asserting all three remain visible."
  },
  {
    "id": "IRG2-04",
    "severity": "low",
    "file": ".task-state/bakeoff-rounds-20261017/incumbent-ab/rebind_incumbent_recipe.py",
    "line": 222,
    "summary": "The prescribed no-clobber protocol requires filesystem hard-link support, but the CLI documentation does not state that requirement. A mount that rejects hard links refuses with only the filesystem errno. Linux directory flock works in the lane control; that does not establish support on every mount.",
    "fix": "Document the supported platform and filesystem requirements for directory flock, hard links, and directory fsync; provide a contextual refusal for an unsupported hard-link operation while preserving rollback. Retain the mandated no-clobber protocol rather than falling back to overwriting os.replace."
  },
  {
    "id": "IRG2-05",
    "severity": "low",
    "file": ".task-state/bakeoff-rounds-20261017/incumbent-ab/rebind_incumbent_recipe.py",
    "line": 196,
    "summary": "plan_writes iterates only PUBLISH_ORDER, so a future output added to render's files mapping without an order entry would be silently omitted. The current two names agree, so this is a latent maintenance issue.",
    "fix": "Require unique publication-order entries and exact equality between the rendered output keys and the publication-order keys before inspecting or writing outputs. Preserve remote-first, prospective-last ordering and refuse an inconsistent output set."
  },
  {
    "id": "IRG2-06",
    "severity": "low",
    "file": ".task-state/bakeoff-rounds-20261017/incumbent-ab/test_rebind_incumbent_recipe.py",
    "line": 79,
    "summary": "Every cli_subprocess caller passes pinned=True, leaving its default unpinned branch unused while the production-pin refusal test duplicates that invocation directly. This is helper duplication with no current runtime defect.",
    "fix": "Route the existing unpinned refusal control through cli_subprocess so both branches have callers, or simplify the helper to a pinned-only interface and keep the explicit unpinned invocation."
  }
]
```
