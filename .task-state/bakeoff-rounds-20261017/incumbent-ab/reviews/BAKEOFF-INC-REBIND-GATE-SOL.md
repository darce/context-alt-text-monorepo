# BAKEOFF-INC-REBIND-20261020: Sol merge gate

Verdict: **fail**. The normal validation path passes the lane suite, but publication can leave incomplete outputs or overwrite a conflicting artifact, and some invalid inputs bypass the refusal protocol. Fix the three findings below before merge. This is a review only; no subject files were changed.

The requested subject is `1b108bfc447d0291bf11ee43ef07d4e8665f6fa6`, relative to base `455b8f35e`. This sandbox has stripped history, so those commits could not be checked directly. The inspected implementation and test Git blob IDs are respectively `a0de2dcba75de9891ff0b0018ccd0b718e7fc1ff` and `7aba70a0799b152f17da195805c96dc611d4285a`, matching both supplied diff indexes.

## Checks and evidence

- Input validation checks schema, status, `execution_started is False`, the calculated and pinned recipe digests, the old contract subject, and a nonempty unique preserved-function list. Bare and wrapper inputs have positive controls.
- The four replacements count their exact old literals before changing text. Missing and duplicate targets refuse before output planning. Parsing, forbidden residues, the source commit, assignment ASTs, preserved-function source segments, and subject format have checks. The substitution loop performs only those replacements.
- `run_qwen_cohort_operation.py` is imported by file path. Its `REPO_EXPR` and `PYTHON_EXPR` match the rebound assignments. Its `source_binding()` returns `/home/gate/bakeoff-rounds-20261017-inputs/source/<SOURCE>.venv/bin/python` (line 138), exactly the layout produced by `repo.parent/(SOURCE+'.venv')/'bin/python'`. No venv-layout mismatch was found.
- Rendering preserves status and populates the expected rebind fields. Identical existing outputs are omitted from the write plan. A conflicting second target already present during preflight refuses before either file is written; the existing regression exercises that case. Both files are staged, flushed, and fsynced before individual `os.replace` calls. These protections do not cover the publication failures in IRG-01 and IRG-02.
- Ran the sole assigned suite once through the required managed interpreter: `"$resolved_python" -m pytest .task-state/bakeoff-rounds-20261017/incumbent-ab/test_rebind_incumbent_recipe.py -q`, after resolving the Git lane root and its `.venv/bin/python`. **Exit 0: 15 passed, 25 subtests passed.** The subject import resolved inside this lane. No packages were installed. The positive and negative assertions are meaningful controls, but every positive recipe fixture substitutes a synthetic digest; the subprocess control proves only production-pin refusal.
- Separate temporary-directory diagnostic probes reproduced each finding without executing a recipe or changing subject files. For IRG-01, failing the second `os.replace` left only `incumbent-pilot-durable.prospective.json`. For IRG-02, inserting different remote-file bytes after `plan_writes()` led to their silent replacement. For IRG-03, invoking the real CLI with JSON containing an unpaired surrogate in `executable_recipe` returned **exit 1, empty stdout, and `UnicodeEncodeError`**; an injected filesystem denial also escaped `main()` without JSON.

## Verification limits

The stored prospective artifact with recipe SHA-256 `603f1a9b1e65f5c1ade9e3753d7afad5099ece8e872ab3bb2cac167a7bdac3f5` is absent from the supplied checkout. An unmodified, production-pin successful rebind could not be verified. Supply that immutable artifact and demonstrate success plus an identical rerun before accepting the implementation.

Canon verification is **unavailable**. The required read-only checkout `/Users/daniel/Development/heuristics-canon-current` is absent, and neither its `AGENTS.md` nor release manifest/rows/cards is available in this sandbox. No manifest digest or release version is certified here. The dependency brief names v0.26.2 for RLSE-21/FLOW-01, while the assignment footer names v0.25.3; those are supplied claims, not independently verified canon citations. Obtain the pinned checkout and resolve its manifest authority before claiming canon compliance. The findings below follow the explicit immutable-output and CLI requirements in the brief without guessing canon text.

Graph tools are not exposed in this session; the review used the exact implementation, test, and Qwen runner source files directly.

## Findings

```FINDINGS
[
  {
    "id": "IRG-01",
    "severity": "high",
    "file": ".task-state/bakeoff-rounds-20261017/incumbent-ab/rebind_incumbent_recipe.py",
    "line": 190,
    "summary": "The two output publications are not a transaction. If the prospective os.replace succeeds and the remote os.replace raises, the finally block removes only staged temporary files and leaves the published prospective without its matching remote recipe. A second-replace PermissionError reproduces this incomplete output, violating the complete-output requirement despite staging both files first.",
    "fix": "Give publication of the pair a transaction boundary. For a new output directory, stage the complete pair in a sibling directory and publish it together; define an equally safe policy for existing partial outputs. At minimum, handle a later publication failure by rolling back only files newly published by this invocation under writer exclusion, preserving all preexisting bytes. Add a second-publication-failure control that asserts neither a partial new pair nor a modified preexisting artifact remains. Preserve the required temporary-file publication behavior."
  },
  {
    "id": "IRG-02",
    "severity": "medium",
    "file": ".task-state/bakeoff-rounds-20261017/incumbent-ab/rebind_incumbent_recipe.py",
    "line": 191,
    "summary": "The different-bytes refusal is checked only in plan_writes. Destinations are neither reserved nor protected until commit_writes calls os.replace, which overwrites them unconditionally. Creating a different remote artifact after planning reproduces a successful silent overwrite. Two invocations targeting the same directory with different reviewed subjects can therefore destroy an immutable output or interleave their output pairs.",
    "fix": "Serialize competing CLI writers with an output-directory transaction lock acquired before inspecting destinations and held through publication or rollback; replan and compare both destinations while holding that lock. If independent writers are supported, use a publication protocol that atomically refuses an occupied destination rather than relying on an existence check followed by overwriting replacement. Add a controlled competing-writer regression proving that a late conflict preserves its bytes and never yields a mixed pair."
  },
  {
    "id": "IRG-03",
    "severity": "medium",
    "file": ".task-state/bakeoff-rounds-20261017/incumbent-ab/rebind_incumbent_recipe.py",
    "line": 219,
    "summary": "main catches only Refusal, but expected input and filesystem errors escape as other exception types. For example, JSON can decode executable_recipe containing an unpaired surrogate; recipe.encode at line 74 then raises UnicodeEncodeError, so the real CLI exits 1 with empty stdout and a traceback instead of one REFUSED JSON line and exit 3. Filesystem errors from destination reads, staging, or replacement likewise bypass the protocol.",
    "fix": "Convert recipe-encoding failures to Refusal during input validation, and handle expected filesystem failures at the CLI boundary after the publication cleanup/rollback required by IRG-01. Emit exactly one structured refusal and return 3 without masking unexpected programming errors. Add subprocess controls for malformed Unicode and a representative output I/O failure, checking exit code, JSON-line count, and output preservation."
  }
]
```
