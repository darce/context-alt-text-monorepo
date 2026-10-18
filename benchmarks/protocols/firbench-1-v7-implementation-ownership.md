# FIRBENCH-1 v7 implementation ownership — corrected planning contract

**Planning only; implementation dispatch remains on HOLD.** The actual independent Solxhigh review `e0e24aae` (MCP `reviewrun1366`, D-P0-H2-OWN-01..06) has run. This second author corrects the callable contracts, freeze data order, complete software gate, persisted integration matrix and report finite-JSON obligations. The composed plan still requires independent re-review. No product implementation, test execution, inference, Monte Carlo, numerical acceptance or adoption is claimed.

The authoritative machine-readable plan is [firbench-1-v7-implementation-ownership.json](firbench-1-v7-implementation-ownership.json). This Markdown explains it. The author owns root JSON fields **except `worker_verification`**, and lane fields **except `owned_paths`, `new_paths`, `tests`, `red_case`, `green_command`, `verification_receipt`**. Existing lane IDs/order and protected values are preserved. The sibling owns those protected fields and its worker-verification Markdown. The coordinator composes exact authorized fields and verifies unowned semantic values/order; typing order creates no precedence. Missing sibling fields are pending composition, never evidence that verification passed.

## Source and evidence

The task supplies source `7e2d2cff958ce7d648a5b1083ded6f08cb70005d` as attribution. The checked history-stripped orphan base is `e1d8fc412416b2a3893f15e0528d92fde66eac9f`, tree `e759c2b6fa314caa67876efd48ae8db50261a510`. Earlier plan provenance is retained under JSON `source.previous_plan_source`. Historical source-map attribution `870710fd` is not a current-identity problem. No old VM history or private maps were consulted.

The actual H2 and cell proposal bytes match the existing JSON source pins: H2 SHA-256 `fce057de4e9d927b16fa7f1cb1b6d25d971cd3f4947b163e713f38c6ab6cd5d4`; cell SHA-256 `c6d6bd0710612520a88a1a55fdd3f17be5b2ae2193895080414bf3e7d20e5794`. Other inherited document pins remain recorded provenance, without a new claim that all historical evidence was reopened.

Bounded known-path source reads establish the following anchors; the codebase index excludes scripts and cannot establish their absence:

- `firbench_contract.py`: `IntervalMethod` 273, `IntervalSpec` 418, `FrameContractError` 122, `_parse_manifest` 846, `manifest_sha256` 549, `validate_interchange` 1116. There is no pre-existing `validate_h2_diagnostics` API to infer.
- `firbench_score.py`: `PairedInterval` 86 has eight fields, not the three-key interval wire; `decide` 844, `_paired` 797, `_check_h2_leg` 827. V1 records and percentile behavior stay unchanged.
- Default CLI wiring is `_load_collaborators` 84 → `firbench_runtime.default_collaborators` 598–619 → `firbench_score_io.score_run` 1237. `firbench_cli.report_run` 593–606 imports **`firbench_cluster_io`**, calls `materialize_clusters`, then `firbench_report.render_report`. The wrong-module reinjection does not apply.
- Comparison original-seal validation at `firbench_cli.py:668` currently uses the v1 parser; `_compatibility_scores` 710 validates scores-v1. Generic mixed-version refusal cannot establish working v2 comparison.
- Report `_binding_json` 2379 rejects named nonfinite constants but lacks an overflow finite-tree check; untyped manifest metadata loads at 2727 and enters `view_data` 2926. `_ui_json` 1982 and `report.json` emission 2987 lack strict finite encoding. These static observations support the future obligations below; no full v2 report was run here.

## Parallel starts and ownership authority

Keep the eleven existing lanes, in their existing order: H2-CON-M, H2-CON-S, H2-KERN, H2-DEC, H2-SIO, H2-CLI, H2-REP, H2-CLU, H2-CAL, CELL-V7, H2-INT. Their exact writable paths and test files come from the protected JSON lane fields, not a duplicated table in this document. `shared_path_partitions` and lane `owned_sections` describe allowed implementation sections subject to those authoritative scopes. A scope conflict blocks dispatch until composed; it never expands ownership implicitly.

`IF-H2V2` and `IF-CELL` make author starts independent of other authors' merged code. Real implementation imports and data are joined later. H2-CON-M/H2-CON-S retain their contract/interchange partition; H2-DEC/H2-KERN retain the dispatch/insertion versus appended-kernel partition. V1 parser bodies, defaults, schemas, fixtures, existing tests and `firbench_selftest.py` have zero authorized changes. The new cell runner and separate H2 calibration module remain proposal-required modules.

The separately active **E1-artifact-pointers** author owns its pointer implementation in `firbench_cli.py` and new `firbench_evidence.py`. **Only H2-CLI** must use the reviewed pointer CLI commit or prove exact disjoint sections against the actual E1 changes. `IF-E1-CLI-BASE` is a typed compatibility constraint pending review, with no fabricated commit hash or API claim. Preserve the new evidence delegation and optional report `--evidence-db`/`--artifact-id` plumbing. Other ten lanes do not wait for that branch. This planning author does not edit either implementation file.

The logical frontier of eleven authors is not measured machine admission capacity [GRPH-31]. These are future author lanes, not subagents launched by this task.

## Frozen callable contracts

`IF-H2V2.call_contracts` and `record_definitions` are normative, prospective interfaces available to independent authors. They give defining modules, owners, exact signatures, representations, nulls, errors and caller responsibilities. Canon does not supply these project APIs or choose numerical defaults [GRPH-33; Principle 1].

H2-CON-S defines this pure checker in `scripts.eval_harness.firbench_contract`:

```python
validate_h2_diagnostics(
    diagnostics: Mapping[str, object] | None, *,
    interval: Mapping[str, object] | None,
    kernel_reason: str | None,
    verdict_reason: str | None,
    kernel_evaluated: bool,
    n_boot: int,
    level: float,
) -> None
```

All keyword context is required. It accepts the exact **wire** shape, not an implicitly recognized kernel result or dataclass. Kernel-owned frozen dataclasses define the proposal's exact 12 diagnostic keys and required nested 14 audit keys. Callers explicitly project diagnostics, convert tuple arrays to lists and reasons to enum strings. They project a `PairedInterval` to exactly `{lower, upper, level}`; passing its entire eight-field `asdict` is invalid. The contract module never imports the kernel to recognize a record.

B comes from `decision.interval.n_boot`; level is the actual H2 Holm level. The validator checks exact keys/types, finite values, integer counts, all six proposal §11 invariants, histogram sums and exact-rational selected ranks. It returns `None` or raises existing `FrameContractError` with the specified `h2_diagnostics.<field-path>:`, `h2_context.<argument>:` or `h2_interval.<field>:` prefix. It mutates and repairs nothing. Process interruptions remain interruptions.

`kernel_reason` is one of the four method refusals or null. `verdict_reason` is the actual H2 hypothesis reason, distinct from an overall/H1 reason. A finite kernel interval can retain its diagnostics when the later verdict refuses for MDE or non-confirmatory frame; its kernel reason remains null. Not-evaluated H2 has null diagnostics/interval/kernel reason and no fabricated draw audit. Finite quantile status may have a null numeric diagnostic under Rule E; a nonrepresentable diagnostic is not zero or a method failure. No checker demands hidden draw tuples or certifies exact rounding from wire values alone.

H2-CAL defines these callables and their explicit frozen dataclasses in `scripts.eval_harness.firbench_h2_selftest_v2`:

```python
run_calibration_v2(
    *, decision: DecisionManifestV2,
    context: H2CalibrationContextV2,
    packets: Sequence[H2CalibrationPacketV2],
) -> H2CalibrationEnvelopeV2

reconcile_calibration_v2(
    records: Sequence[H2CalibrationRecordV2 | Mapping[str, object]],
    *, context: H2CalibrationContextV2,
) -> H2CalibrationAggregateV2
```

The context explicitly carries the route/case/design/branch, requested R, B, seed, level and actual protocol/fixture/canonical-decision/spec hashes. The fixture/input layer validates the raw freeze bytes before constructing it; the callable checks context against the parsed decision and packet schedule. It does not authenticate unseen bytes or fetch hidden global configuration. Packets carry real `LegResults` with exact indices 1..R for one group. Direct packets call the real paired kernel; forced/natural decision packets call real `decide_v2`. Forcing changes only the nonselected arm, with selected/reference input hashes checked.

The return envelope contains exactly the declared context identity, records and aggregate; JSON lists are explicit projections of typed tuples. Each calibration record has the proposal's exact 15 keys. Completed kernel-bearing records copy the real diagnostics/audit; completed no-kernel records have null diagnostics/draw counts. Direct records do not invent a verdict state or H1/H2 reach flags. A boundary contract error or no-result interruption has null result fields and B/0/B. Never-started requested work uses `process_incomplete`, not a fourth status or an extra R term. A hard kill returns no envelope and blocks acceptance; no adapter promises to return through host loss.

The reconciler owns aggregate validation, not `validate_h2_diagnostics`. It checks individual records using that explicit per-call checker, then sums execution/reason/state/null marginals, reason × phase × selected-status cross-counts, audit categories, histogram bins and available extrema with null counts. It never applies a per-call `classified ∈ {0,B}` invariant to branch totals. Error/incomplete B/0/B contributes only to record draw totals, not nonexistent diagnostics/categories. Exactly R records remain in the denominator, without replacement, hidden draws or AU/SF pooling. Errors use `FrameContractError` with `h2_calibration.<field-path>:`. The actual envelope and recomputed aggregate are mandatory H2-INT assertions.

## Freeze data order and complete software gate

Author starts may use the frozen interfaces while the separate freeze author works. Actual hash checking waits for actual freeze outputs. `external_frozen_inputs[*].binding_owners` assigns existing authors to bind PF-H2/PF-CELL bytes, spec identity, constants, fixture schedules and known-answer packets **before** G-MERGE compares those committed values. Both PF nodes are explicit blocking inputs to G-MERGE in `blocked_by` and named edges. Missing bytes or unresolved values mean HOLD. Verification neither supplies defaults nor waits for itself to authorize embedding [GRPH-01, GRPH-32].

The blocking order is:

1. Eleven author outputs plus actual PF-H2/PF-CELL outputs → **G-MERGE**: per-author path/section proof against declared bases, unchanged v1 surfaces, actual bound-byte/hash checks and H2-CLI pointer-base compatibility. Separately authorized E1/freeze diffs are inventoried and preserved using actual receipts; they are not falsely counted as H2-authored paths.
2. G-MERGE → **G-V1**; then **G-INT** and **G-CELL** consume actual joined producers and v1 evidence.
3. **IF-WORKER-RECEIPTS** carries all eleven actual RED/GREEN receipts defined by sibling root `worker_verification`, not a prose assertion or an invented receipt schema.
4. **G-SOFTWARE** consumes that named artifact, G-V1/G-INT/G-CELL evidence and the complete union of authoritative `lanes[i].tests`, on the actual joined tree. No subset selection, missing receipt, stale commit, collection failure or unexpected skip can pass. It emits a tree/hash/command-bound software receipt only after real checks [TEST-06; Principles 2/18].
5. **SEAL-H2/SEAL-CELL** bind the actual PF inputs, integrated source/runner identity and required pre-outcome values after the complete software gate. **G-SW-H2/G-SW-CELL** check sealed deterministic packets/parity and consume the real software receipt.
6. **RUN → NUM → ADOPT** remains separate downstream work, also requiring RD-GATES. No run is dispatched here.

No numerical result feeds PF or SEAL; no model/default/software gate can override the user's pre-outcome freeze. Canon supplies no seed, B/R, model, margin, threshold or policy. Freeze before outcomes and adoption after gates remain distinct [EXP-22].

## Persisted default integration and strict report JSON

JSON `integration_matrix` is normative. **Every I01–I09 row is instantiated separately for both AU and SF** against the actual PF-H2 deterministic packets. Synthetic model/assets/input seams and deterministic fault hooks sit below real producers. No fake default collaborators, contract/kernel/decision return, score-IO payload, calibration envelope, cluster/report/comparison result or mocked aggregate may make the join pass (MCP18674).

The persisted chain uses actual CLI parsing/run/score, `_load_collaborators` → `runtime.default_collaborators` → score IO → real input pairing/kernel/decision/validation. Actual CLI report calls cluster IO, then the renderer. The named real calibration callable and comparator are included. This requires:

- Finite, null/refusal, earlier-stop, later-MDE/frame and incomplete paths; method/reason/trace, full all-B audit, raw/canonical bindings and returned-type/persisted-copy equality. Every proposal §10.4 row is checked directly and through reachable decision routes; an impossible route records its actual earlier stop.
- Replay with identical pinned inputs reproduces interval/refusal/audit/ordered trace and deterministic scores/cluster/report bytes without changing timings or inputs. Raw-byte mutation that leaves canonical identity unchanged still refuses; canonical/seal/spec mismatch also refuses.
- A **successful compatible v2/v2 comparison** within each route, with valid original seals and real percentile metrics/comparison-v1 output. Also require mixed v1/v2 and differing supported-policy refusals after original-seal validation, with a corrupt-original-seal precedence control. An unavailable genuinely supported different-policy pair is HOLD, never fabricated registry support. Keep v1/v1 positive comparison and its required semantics.
- Actual calibration envelopes for direct/forced/natural groups, exact record null rules and R/B/category/histogram/extrema/cross-count reconciliation. No hidden IO/calibration substitute or numerical acceptance claim.

H2-REP owns strict finite v2 report input and emission, including **untyped loaded metadata**, inline `_ui_json`/`_page` data and `report.json`. Reject named `NaN`/`Infinity`/`-Infinity`, recursively detect exponent overflow such as `manifest.synthetic_extra: 1e999`, and serialize strict finite JSON with `allow_nan=False`. A `parse_constant` hook alone does not detect exponent overflow. Complete input/cross-binding validation and strict serialization precede report directory creation or output replacement.

Focused report and persisted G-INT negatives cover those values, nested metadata, malformed diagnostics, missing/partial all-B audit and raw/canonical/method binding mismatch. Each refuses before creating fresh **report outputs** and leaves existing HTML/JSON/CSV bytes unchanged. Valid finite/null controls must render and emit strict finite JSON. Null intervals show the actual inconclusive reason, never a bound, zero-width interval or pass. Preserve required valid v1 report/score/schema/seal semantics; tightening a shared helper does not authorize a v1 method/default change.

## Canon and preserved holds

Heuristics canon **v0.26.2** is read from the pinned mirror; release manifest SHA-256 `46636aa71f2e2e0c413b6ccff1cae4959543026c6ee7e4abde2bc7f30645a260` matches. Stable rules used at their decisions above are:

- **[GRPH-01] Model the work as a DAG, then topological-sort**, *The Algorithm Design Manual*, ch. 7: legal freeze/owner/check data order.
- **[GRPH-32] An edge exists only where data moves**, practice label `bootstrap`: named actual freeze and receipt inputs.
- **[GRPH-33] A node without a contract cannot be parallelised**, practice label `bootstrap`: explicit callable inputs/representations/errors.
- **[TEST-06] Watch it fail once / predict the failure**, *Modern Software Engineering*, ch. 8: consume all sibling RED/GREEN evidence before software acceptance.
- **[GRPH-31] Critical-path schedule the task DAG**, *The Algorithm Design Manual*, ch. 17; *Scheduling: Theory, Algorithms, and Systems*, ch. 5 and §D.4: logical independence is separate from measured resource admission.
- **[EXP-22] No circular analysis (double-dipping)**, *Statistics Done Wrong*, ch. 6: no outcomes select freezes or retune failures.

Principles **1** (Author the contract before the components), **2** (Specify what would prove you wrong) and **18** (A machine consumes contracts, not prose) support the explicit APIs, disconfirming worker receipts and machine-checked gate artifact. Referenced TEST-06 cards `falsification-disconfirmers` and `measurement-integrity` are unavailable in this mirror; no unseen card text is claimed read. Inherited EXP-23/AUDIT-11/CARD-27 mappings and source limitations remain in JSON/the accepted proposals without supplying a new API or default here.

H2 v6 **126/2000 = .063 > .060** and cell v6 **1113/2000 = .5565 < .77** remain **FAILED**, with original seeds/receipts unchanged. V1 compatibility, H1/descriptive/cell percentile paths and verified ONNX gte-base prior art are preserved; no new model or real inference is introduced. No v7 power/coverage/boundary gain, private-pixel, real GT/QC, contextual observation, capture, budget or adoption claim follows from this planning work.

Remaining implementation holds are independent re-review after sibling composition; actual PF outputs/spec/route seals; actual worker verification and full software results; and H2-CLI's pending reviewed pointer base or exact disjoint-section proof. The other ten authors remain independent. No product/test/fixture edits, pointer implementation, private images/maps/DBs/row records, old VM history, subagents, push/merge/rebase/deploy, MC or real inference occurred.

**Planning validation executed:** strict duplicate-key JSON parse; all 33 existing protected lane fields byte-identical, eleven lane IDs/order and existing root/lane key order unchanged; protected `worker_verification` remains absent pending sibling composition. The blocking DAG has 33 declared nodes, 103 named edges (55 blocking), exact `blocked_by`/edge agreement, no author-start prerequisites or outcome-to-freeze paths, actual PF dependencies before G-MERGE, all eleven worker receipt inputs and G-SOFTWARE before both seals. All 62 coverage IDs are unique with valid endpoints. The three proposed signatures parse as Python; record shapes have exactly 12/14/15 fields; nine matrix rows require both routes; original failure objects are unchanged. Only the two owned planning files differ from the orphan baseline; `git diff --check` is clean. **No product tests ran.**
