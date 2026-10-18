# APP-1 evaluator adjudication — 2026-09-22

Bounded documentation-only adjudication of the already recovered evaluator review
`APP1-EVAL-RV-01..06`. This is not a new broad review and makes no production or
test change. The report is based on the exact current source and the preserved
review delta.

## Scope and provenance

- `.review/CHANGE.diff` is the two-file evaluator delta associated with
  `0307f770b..5d5717c3f`. `git apply --reverse --check .review/CHANGE.diff`
  returned 0, proving the current runner and unit test contain the patch. The
  forward check correctly failed because the checkout is already at the patched
  state. The history-stripped checkout does not independently resolve those
  commit objects.
- Reviewed source: `apps/prototype-description-service/scripts/run_app_portal_evals.py`.
  Reviewed tests: `apps/prototype-description-service/recognition/tests/unit/test_run_app_portal_evals.py`.
- Plan 0002 names RV01–03 as release-evidence concerns and RV04–06 as medium
  candidates. The governing contract is F5 in
  `docs/assessments/current/app1-usage-evidence-adjudication.md`: a clean result
  requires every declared case and artifact to be present and passing; skipped,
  not-run, missing, or unverified evidence is non-clean. Plan 0002 also says a
  narrow green subset must not be called a full release pass.
- Rules applied at the release-evidence boundary: [CARD-06], [Principle 13],
  and [GRPH-14] from the [heuristics canon](https://github.com/darce/heuristics-canon).
  These are used as evidence-integrity constraints, not as proof of a live
  provider, browser, PostgreSQL, or deployment rehearsal.

## Verdict

Severity is assigned once here. “Confirmed” means the current code produced the
stated failure under a bounded reproduction; it does not claim live APP-1
rehearsal evidence.

| Finding | Classification | Severity | Reproduction outcome | Owning path |
| --- | --- | --- | --- | --- |
| **APP1-EVAL-RV-01** | **Confirmed** | **High** | A nonempty artifact containing `not proof: arbitrary nonempty text` yielded runner status `0`, ledger `passed`, and `additional_evidence_present: true`. | `scripts/run_app_portal_evals.py:_artifact_evidence` |
| **APP1-EVAL-RV-02** | **Confirmed** | **High** | Selecting only `deterministic` from `deterministic` + `browser` yielded status `0`, `full_suite: false`, and `required_case_ids: [A]`; case `B` was not executed or represented in the group ledger. | `scripts/run_app_portal_evals.py:_required_case_ids_for_selection`, `run_evals` |
| **APP1-EVAL-RV-03** | **Confirmed** | **High** | An evidence-only artifact containing a valid JUnit testcase with `<failure>` passed with `max_failures: 0`; no pytest subprocess ran, so the JUnit threshold was bypassed. | `scripts/run_app_portal_evals.py:_run_group`, `_artifact_evidence` |
| **APP1-EVAL-RV-04** | **Confirmed** | **Medium** | A declared base node `test_case` and a passing JUnit node `test_case[small]` produced status `1` and ledger `not_run`; parametrized execution is not matched. | `scripts/run_app_portal_evals.py:_junit_case_candidates`, `_match_junit_case` |
| **APP1-EVAL-RV-05** | **Rejected** | — | An evidence-only case pointing to a nonexistent JUnit/artifact path produced status `1`, ledger `not_run`, and an explicit `missing required artifact` reason. | Existing `_artifact_evidence` path check; no fix required |
| **APP1-EVAL-RV-06** | **Confirmed** | **Medium** | A passing matched test with a missing required artifact produced overall status `1` but ledger `passed` with `additional_evidence_present: false`; the release is blocked, but its per-case record is false. | `scripts/run_app_portal_evals.py:_run_group` case-ledger construction |

## Bounded reproductions

One simple Python harness was run from
`apps/prototype-description-service/`. It used `tempfile.TemporaryDirectory`, a
small injected `command_runner`, and synthetic JUnit XML; it wrote no repository
files. The harness returned exit 0 and printed the following actual outcomes.

### RV01 — artifact presence is not proof content

The manifest declared an executable passing case, `additional_evidence_required:
true`, and an artifact whose complete content was `not proof: arbitrary nonempty
text`. The runner only calls `Path.is_file()` and `stat().st_size > 0`
(`run_app_portal_evals.py:571-595`). It returned:

```text
status=0
ledger.status=passed
ledger.additional_evidence_present=true
failure_reasons=[]
```

This violates the APP-1 evidence bar: a nonempty file is not a verified proof
artifact. The repair must use typed artifact/proof validation (including the
declared schema/provenance or digest contract) rather than treating arbitrary
bytes as evidence.

### RV02 — selected groups can report a clean partial run

The manifest declared two required cases, `A` in `deterministic` and `B` in
`browser`, then invoked `run_evals(..., groups=["deterministic"])`. The current
selection logic intersects release-gate IDs with selected groups
(`run_app_portal_evals.py:548-555`) and records, but does not fail on,
`full_suite: false` (`run_app_portal_evals.py:797-835`). It returned:

```text
status=0
full_suite=false
selected_groups=["deterministic"]
required_case_ids=["A"]
ledger=[A: passed]
```

The preserved APP-1 manifest itself stores a `--group deterministic` command.
That command is suitable for a slice run, but its clean exit cannot be a release
verdict. The fix packet must make release-mode selection fail closed, or require
an explicit non-release/slice disposition that cannot be consumed as a gate.

### RV03 — JUnit threshold and evidence semantics can be bypassed

The manifest used `max_failures: 0` and an evidence-only case with no `test`.
Its artifact was syntactically valid JUnit containing one testcase and one
`<failure>` element. Because `ran_pytest` is false, `_run_group` skips the JUnit
report/zero-case/failure/skip threshold checks (`run_app_portal_evals.py:623-667`)
and `_artifact_evidence` accepts the nonempty file. The actual result was:

```text
status=0
ledger.status=passed
ledger.junit_identity=null
failure_reasons=[]
```

Thus a required evidence artifact can itself report a threshold violation while
the evaluator emits a clean result. The fix packet must give evidence-only JUnit
references an explicit type and apply the same parse/threshold/provenance checks,
or reject JUnit as an untyped evidence artifact.

### RV04 — parameterized JUnit nodes are not matched

The declared test was
`recognition/tests/test_param.py::test_case`. The synthetic passing JUnit
contained the real pytest-shaped node
`recognition/tests/test_param.py::test_case[small]`. The candidate builder only
adds exact `file::name`/classname forms; it does not expand a declared base node
to its parameterized children. The actual result was:

```text
status=1
ledger.status=not_run
failure_reasons=[required case RV04 was not executed (...test_case missing from JUnit)]
```

This is a false negative, not a green-release bypass. The repair must define
one-to-many base-node matching and fail if any matched parameter fails or if no
parameter instance is present.

### RV05 — nonexistent evidence-only path fails closed

The evidence-only case declared `artifact=/tmp/.../does-not-exist.xml` and no
`test`. The actual result was:

```text
status=1
ledger.status=not_run
ledger.additional_evidence_present=false
failure_reasons=[required case RV05 missing required artifact ...]
```

The prior concern that a nonexistent evidence-only JUnit reference can pass is
not reproducible against the current source. No repair is included for this
finding; preserve this behavior in the fix packet's regression coverage.

### RV06 — missing artifact leaves a false `passed` ledger status

The declared test matched a passing JUnit testcase, while its required artifact
path did not exist. The runner correctly returned nonzero, but the actual ledger
was:

```text
status=1
ledger.status=passed
ledger.additional_evidence_present=false
failure_reasons=[required case RV06 missing required artifact ...]
```

The ledger assignment records the JUnit outcome before checking the artifact and
does not demote it when `_artifact_evidence` fails
(`run_app_portal_evals.py:677-713`). The fix must make the ledger status reflect
the missing artifact (`not_run`/`failed` under the chosen schema) while retaining
the non-clean exit.

## One disjoint fix packet

The single packet is owned by the evaluator surface:

- `apps/prototype-description-service/scripts/run_app_portal_evals.py`
- `apps/prototype-description-service/recognition/tests/unit/test_run_app_portal_evals.py`

It should add regression coverage for the six reproductions and implement only
these same-file behaviors: fail release-mode partial selection; validate typed
proof artifacts and evidence-only JUnit thresholds/provenance; match and account
for parameterized nodes; and demote a passing ledger entry when required
evidence is missing. RV05 needs no production repair, only a preserved negative
test. No manifest, production route, database, provider, or unrelated harness
path belongs in this packet.

## Verification boundary

- The requested `uv run ... pytest recognition/tests/unit/test_run_app_portal_evals.py`
  command was attempted but could not start: `uv` tried to remove
  `/home/gate/grok-sandbox/.venv-lane-feature-app-1-eval-adjudicate-591a2015/.../bin/alembic`
  on a read-only filesystem.
- Direct pytest fallback was also blocked by the environment: the lane
  interpreter lacks `pytest-timeout`, and overriding that requirement then
  exposed a missing `numpy` dependency while loading `recognition/tests/conftest.py`.
- The six direct runner reproductions and the separate RV03 aggregate probe did
  run successfully with the lane interpreter. No claim of a complete project
  test run, live provider rehearsal, or review completion is made here.
