# FIRBENCH-1 v7 worker verification

Planning contract for D-P0-H2-OWN-01/04, based on supplied source
`7e2d2cff958ce7d648a5b1083ded6f08cb70005d` (sandbox base
`7b2a8f2025941945ea510bf567e4697cb63f0b50`). No implementation, worker RED,
MCP acknowledgement, GREEN result or numerical acceptance is claimed here.

The [ownership JSON](firbench-1-v7-implementation-ownership.json) is normative:
each lane's `red_case`, `green_command` and `verification_receipt`, and root
`worker_verification`, define the executable verification and receipt boundary.
The sibling owns the main ownership Markdown and gate configuration; it must
link this document and consume `worker_verification.gate_requirements`.
Existing joins, edges, interfaces and lane acceptance checks are not rewritten
by this change.

## Explicit test ownership

All eleven files below are new, under
`apps/prototype-description-service/scene/tests/`. Each is explicitly present
in **both** its sole owner's `owned_paths` and `new_paths`, as well as `tests`.
The first nine grants repair OWN-01; the last two already existed. `tests`
never grants implicit write permission. Existing product-file section
partitions still govern the two shared modules; all existing tests stay read-only
([Principle 18], *A machine consumes contracts, not prose*).

| Sole owner | New test filename | Required behavioral RED |
| --- | --- | --- |
| H2-CON-M | `test_eval_harness_firbench_contract_v2.py` | Valid integer-2 manifest must parse; rejected spellings alone cannot prove support. |
| H2-CON-S | `test_eval_harness_firbench_scores_schema_v2.py` | Real valid scores control succeeds; delivered partial all-B classification must refuse. |
| H2-KERN | `test_eval_harness_firbench_h2_kernel_v2.py` | Paired K=1 refuses before SE/draws, with 0 classified and B unattempted. |
| H2-DEC | `test_eval_harness_firbench_decide_v2.py` | Real kernel zero-SE refusal precedes the later MDE refusal; H1 stop is a companion control. |
| H2-SIO | `test_eval_harness_firbench_score_io_v2.py` | Actual verdict yields scores-v2 with unchanged method/reason/diagnostics/trace and distinct raw/canonical binding. |
| H2-CLI | `test_eval_harness_firbench_cli_v2.py` | Compatible sealed v2 runs reach the percentile comparator through default wiring. |
| H2-REP | `test_eval_harness_firbench_report_v2.py` | Exponent-overflow metadata refuses before any report output changes. |
| H2-CLU | `test_eval_harness_firbench_cluster_io_v2.py` | Valid bound scores-v2 materializes real clusters-v1 and replays identical bytes. |
| H2-CAL | `test_eval_harness_firbench_h2_selftest_v2.py` | Actual records copy real diagnostics and reconcile record-derived aggregates. |
| CELL-V7 | `test_eval_harness_firbench_cell_selftest_v7.py` | 49 global / 30 cell PSUs refuses whole-fixture eligibility before a cell interval. |
| H2-INT | `test_eval_harness_firbench_h2_v2_integration.py` | Both selected-leg routes complete real default score/report/comparison/calibration boundaries and replay. |

Each `red_case` names a specific test node, synthetic input, real entry points,
behavior, explicit assertion message, predicted failure and exact RED command.
These are predictions to verify, not observations.

## RED acknowledgement before production; entire-suite GREEN

Apply [TEST-06], **Watch it fail once / predict the failure** (*Modern Software
Engineering*, ch. 8), and [Principle 2], **Specify what would prove you wrong**:

1. Bind actual reviewed prerequisite/interface commits and signatures, write
   the owned test and predict its behavioral assertion before running it.
2. Execute `lanes[id].red_case.command.script` in Bash from the checkout root.
   Require pytest exit 1 at the named behavioral assertion, after successful
   collection/setup. Record actual baseline/test hashes, prediction, assertion,
   command, timestamps, log/JUnit/collection receipts in MCP. Receive and retain
   the MCP RED acknowledgement **before the production change for that behavior**.
3. Implement within the existing path/section grants. Run the exact
   `lanes[id].green_command.script`: the entire new owned suite, with unchanged
   acknowledged test bytes. Record its GREEN report in MCP.
4. The composed-tree gate reruns the same complete suites and retains fresh
   receipts for that actual tree. Worker-tree GREEN alone cannot prove a join.

An absent new API/module is a prerequisite problem, never behavioral RED.
Imports, `NotImplementedError`, `AttributeError`, collection/setup/environment
errors, arbitrary failure injection in the test, schema-only mocks and
fabricated producer results do not qualify. The executable reviewed baseline
must reach the predicted assertion against a real producer. If that baseline
is unavailable, record RED pending and withhold the covered production change;
do not invent a passing receipt or implement the behavior first and backfill
its RED history. H2-INT has no production grant: its RED acknowledgement must
precede the joined producer correction, whose owner/commit is recorded.

If the failure differs from the prediction, repair the test/prediction and
observe a new matching RED before proceeding. Any later test change requires
another acknowledged RED. Successful GREEN means exit 0, collected=passed>0,
and zero failures, skips, xfails, xpasses or deselections. Root
`worker_verification.receipt_contract.json_schema` validates required fields/types;
its additional acceptance rules check chronology, hashes and tree identity;
null placeholders in lane plans are not accepted receipts.

## Exact command environment and isolation

The JSON contains each complete command, including its sole suite filename;
no command expansion from prose is required. Both RED and GREEN scripts use:

- Retained VM Python
  `/home/gate/workbay-sandbox/.venv-lane-feature-firbench-1-909fa00d/bin/python`
  with `-B -m pytest -q -n 0 -o addopts=`. Its executable and pytest, xdist,
  NumPy and pytest-timeout availability were checked during planning. Recheck
  and record runtime versions before worker execution; no system-Python fallback
  or dependency installation is implicit.
- Service-root `PYTHONPATH`, `PYTHONDONTWRITEBYTECODE=1`,
  `RECOGNITION_RUNTIME_MODE=test`, unset `ACX_EVAL_BENCH`, `PYTEST_ADDOPTS` and
  `PYTEST_PLUGINS` / `PYTEST_DISABLE_PLUGIN_AUTOLOAD`, and all listed
  BLAS/OpenMP thread limits set to 1.
- A fresh lane/phase-specific `/tmp/firbench-<lane>-<red|green>.XXXXXX`
  directory for `TMPDIR`, pytest cache, basetemp, collection receipt, JUnit and
  the captured log; Bash `pipefail` preserves pytest failure through `tee`.
  Keep that scratch evidence until gate acknowledgement. Missing runtime
  prerequisites are setup failures, not RED or GREEN.

Persisted tests create a synthetic repository beneath pytest `tmp_path`, with
its own `benchmarks/private/firbench/...` run tree and byte-bound decisions,
frames, searches, caches and pinned timing receipts. Pass `repo_root` where
supported, or rebind only the existing repository/input seams. Never read
pre-existing private directories, DBs, maps, identities, images or models.
Scratch artifacts do not expand any implementation write grant.

## Real producer boundaries and independent work

Use actual `H2IntervalResultV2.interval/reason/diagnostics` and nested
`draw_audit`; actual `HypothesisVerdictV2.h2_diagnostics`; then one explicit
conversion to the scores-v2 JSON mapping. `validate_scores(payload, *, decision)`
returns `None` or raises `FrameContractError`. The sibling-owned IF-H2V2 must
supply the reviewed diagnostics-validator and calibration callable signatures,
context, record/wire representations and return/error contracts before those
calls execute. Schema-worker RED uses explicit frozen wire data with the real
validator; it does not wait for an unfinished writer. The composed-tree suites
then require actual score-IO output, so a fixture cannot substitute for the join. Do not invent an overload or calibration envelope here.
CELL-V7 likewise records its actual runner eligibility/known-packet callable
before RED; testing only v1 `decide` or copied eligibility dictionaries cannot
prove the new runner ([GRPH-33], **A node without a contract cannot be
parallelised**, bootstrap practice; [Principle 1]).

H2-INT and H2-CLI keep the actual default chain:
`cli._load_collaborators -> runtime.default_collaborators -> score_io.score_run`;
`cli.report_run -> cluster_io.materialize_clusters -> report.render_report`.
The current CLI already calls **cluster_io**. Synthetic seams belong below
these producers; replacing collaborators, the kernel, decision, validator,
writer, materializer, renderer or calibration return is not integration proof.

For both selected-leg routes require finite and null/inconclusive paths, copied
method/reason/diagnostics/ordered trace, raw and canonical bindings, and pinned
byte replay. Include a successful compatible v2-v2 percentile comparison as
well as mixed/differing-policy refusals after original-seal validation. Report
negative tests need a successful valid-v2 control, strict inline/report JSON,
and absent/existing-output snapshots; an unrelated schema refusal is no proof
of finite-input validation. CAL/CELL tests consume prescribed known-answer
packets and real adapters, without executing outer simulation loops, designing
numerical MC, tuning B/R/seeds or claiming numerical acceptance.

Only H2-CLI carries `E1-POINTER-CLI-BASE`: bind the actual reviewed pointer CLI
commit or reviewed exact disjoint sections; preserve evidence delegation and
optional report `--evidence-db` / `--artifact-id`. Its exact signature/commit is
**pending review**, represented by a typed constraint and null identity rather
than a fabricated hash. This plan grants no pointer implementation edits.
The other ten author lanes start independently ([GRPH-32], **An edge exists
only where data moves**, bootstrap practice).

## Gate consumption and preserved history

The sibling's gate configuration must consume the root `gate_requirements`:
G-INT and G-SW-H2 require all ten H2 lane receipts, including real integration;
G-CELL and G-SW-CELL require CELL-V7. Together they require all eleven complete
suite receipts, alongside unchanged v1 regression checks. Missing, stale,
unacknowledged or unexecuted receipts fail the software gate. No lane start is
serialized by this receipt requirement; final gate checks consume actual
named evidence ([GRPH-32], [Principle 18]).

V1 compatibility, existing tests and percentile defaults remain protected.
The historical v6 H2 failure `.063 > .060` and cell failure `.5565 < .77`
remain FAILED. This planning change does not replace them or authorize runs.

Canon v0.26.2 rule titles, source labels and locators above were read from the
read-only mirror at `/home/gate/firbench-1-context/canon-0.26.2`:
`lexicons/engineering.md#test-06`, `lexicons/graph-theory.md#grph-32` /
`#grph-33`, and `PRINCIPLES.md` sections 1, 2 and 18. The canon supplies
verification discipline, not FIRBENCH APIs, constants or defaults.
