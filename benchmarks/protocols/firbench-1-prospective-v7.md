# FIRBENCH-1 prospective v7 synthetic protocol candidate

**Status: composed candidate pending all three author groups and independent whole-protocol freeze review. `freeze_complete=false`. This isolated root/cell/wire correction grants no execution, numerical acceptance, adoption or real-data ratification.**

The [prospective JSON](firbench-1-prospective-v7.json) is authoritative for values and exact artifact bindings. This lane owns its root values except `h2_branch`, plus this Markdown. The current method and case corrections are consumed unchanged; their presence does not establish independent acceptance of the whole protocol. No new random results were generated or inspected.

## 1. Authority, composition and source

The coordinator must compose exact authored fields from the root/cell/wire, H2 method and H2 case groups, verify unchanged unowned values and key order, obtain each group's independent review, and obtain an independent freeze gate on the exact composed bytes before execution. Method component PASS `c534fa64` is supplied dispatch evidence; case review remains pending. Ownership component PASS is bound below. No full method-review digest or case PASS is invented.

Current input is supplied public source `18856d8ebced122e8bcf6258033a11bd288c294a`, tree `ed914da3d27acb89c0d5ac0ac643d4ba3e742676`, mapped by `.workbay-source-provenance` to parentless sandbox input `b42875833c4314f54e0174bee195ad4a84c4b1f2` with that exact tree. These are input identities before this lane's commits. Earlier author identities are historical lineage in JSON `source.historical_author_source`; source-map `870710fd` is not current identity. Only this checkout's bounded public producers and the approved canon mirror were read. No old VM Git, private corpus, images, identity maps, DBs, pseudonyms or row values were accessed or transferred [GRPH-14].

The exact unchanged proposals are incorporated by full-file identity and section selectors:

| Contract | Verified full-file SHA-256 | Normative section |
| --- | --- | --- |
| [Cell proposal](firbench-1-cell-design-v7-proposal.md) | `c6d6bd0710612520a88a1a55fdd3f17be5b2ae2193895080414bf3e7d20e5794` | Entire §8, from `## 8.` to before `## 9.` |
| [H2 proposal](firbench-1-h2-method-v7-proposal.md) | `fce057de4e9d927b16fa7f1cb1b6d25d971cd3f4947b163e713f38c6ab6cd5d4` | Entire §11, from `## 11.` to before `## 12.` |

Both sections are normative in full, including tables, field types, invariants, refusals, null rules, trace, seals and replay. The current [normative method](firbench-1-h2-v2-normative-method.md), bound by JSON `/h2_branch/normative_method`, completes operation/RNG conventions and supersedes §11's older §§7–8-only method-hash boundary: registration hashes the **entire exact normative method file**. Historical ownership PF-H2 hash-scope prose is completed by that same rule, not a second registry. Other §11 requirements remain binding. Unknown/mismatched registered method bytes refuse scoring/replay.

The [normative case grid](firbench-1-h2-v2-case-grid.json) and [case explanation](firbench-1-h2-v2-case-grid.md) supply current laws, truths, designs, exact deterministic packets/tuples, outer streams and integer gates. Their authority and exact digest are in `/h2_branch/normative_case_grid`. Neither this note nor the root correction changes a case or method value. A remaining inconsistency requires reconciliation and independent review before execution.

## 2. Cell design and typed output

Cell H1 is paired FNIR(SFace) minus FNIR(AuraFace), within each cell, resampling whole PSUs with the unchanged percentile method: B=10000, seed=2429382368, level=.95, strict lower bound >0. All draws and all mates, including upstream misses, remain present. The planted clear_mask effect is .10; untreated clear_clear retains the control packet. No two-cell alpha split or CELL-CONFIRM-10 is introduced.

C26 has 52 size-1 and 26 size-4 PSUs **per cell**: 156 raw mates, 78 PSUs, squared-size sum 468 and size-weighted mean 3. Together: 312 mates, 156 PSUs and squared-size sum 936. With `deff=1+2*ICC`, planning arithmetic gives:

| ICC | Per-cell numeric `attained_n_eff` | Separate `attained_n_eff_exact` | Whole exact planning n_eff |
| --- | --- | --- | --- |
| .05 | 141.8181818181818 | `1560/11` | `3120/11` |
| .10 | 130 | `130/1` | `260/1` |
| .20 | 111.42857142857143 | `780/7` | `1560/7` |

JSON `design.per_cell_output_records_by_icc` declares each numeric/exact output pair. Rational-string planning maps are explicitly labelled as planning quantities; they are not the output wire. This follows actual `_sizing`/`_public_sizing` behavior. The exact whole target is 260 only at .10; sensitivity targets remain null. Raw faces or whole-design n_eff do not substitute for per-cell adequacy [EXP-23; AUDIT-11].

C26 follows the reviewed prospective 10% sizing slack, not observed v6 power: analytic required n_eff is about115.3469, 1.10 times that is126.8816, and k=26 is the smallest allowed composition with `5*k` meeting it. The selected composition and any future failure stand without resizing [EXP-12; EXP-18; EXP-22; CARD-27].

R=2000 on each of six fixed rows. CELL-POWER-10 requires clear_mask detect_count≥1540 **and** untreated clear_clear detect_count≤64, both scored_count=2000 and n_psu=78. CELL-NULL-10 separately requires each cell detect_count≤64 and scored_count=2000. All rates divide by2000. The four .05/.20 rows are mandatory report-only sensitivities. Missing intervals, incomplete replicates or dropped draws give failed/incomplete evidence, never a smaller denominator. Null calibration does not replace the untreated-cell predicate [EXP-13].

Cell master label `FIRBENCH-1/cell-power/v7` gives1113108719; suites cell_power=9/cell_null=10 use the reviewed SeedSequence rules and ICC keys5/10/20. V1 master2208172209, registry1–8 and all existing seeds/defaults remain unchanged. No suite seed states or outcomes were generated here; the downstream software receipt must record the six suite seeds.

The explicit new output template is `benchmarks/results/firbench-1-prospective-v7/cell-power-v7/<CASE-ID>/acceptance.json`. It is a prospective path, not an output created here. The writer must refuse existing case outputs and aliases/collisions with historical v6 paths; no overwrite or retry. This is a routine prospective identity choice, independent of outcomes [EXP-22].

## 3. Complete mixed-scope cell adapter

The complete hash-bound cell §8 contract is adopted, not just `_cell_decision` or its gate summary. Construct the declared whole-fixture synthetic manifest through the existing `_synthetic_decision`, H2=auraface versus insightface, min_n_independent=50, cell_floor_n_independent=30, unchanged planning ICC and FPIR target=.01. SIM-G0 is `report_only`; empty readings are not a measured guardrail pass.

Start with actual `_results(design, decision, packet, auraface)`, then preserve these five `LegResults` fields:

| Field | Required input |
| --- | --- |
| `frame` | Whole-fixture `design.frame.spec` |
| `unit_psu_ids` | Entire `packet.background_psu`, original order **and multiplicity**; never cell-filter, deduplicate, add nonmated units or substitute mated faces |
| `h2_leg` | `auraface` |
| `guardrails` | `{}` for the synthetic report-only marker |
| `legs` | All three keys sface/auraface/insightface, each a matching `LegArrays`; only these mated arrays are restricted to the identical ordered cell face IDs |

Each leg retains its own outcomes and matching per-face PSU assignments/weights; unit weights are1.0. Assert identical face IDs, PSU assignments and weights across all three arrays. Keep **every cell mate**, including all upstream misses, without outcome filtering [FIR12; EXP-23].

Validate inputs; count the union of complete background PSU IDs and all restricted leg PSU IDs exactly as real `decide` does. Assert round-robin background covers every whole-fixture PSU and this union equals that whole-fixture set. The whole-frame field alone supplies no counts. Apply the unchanged ≥50 global PSU gate, then whole-fixture nonmated FPIR resolvability (`n_eff≥3/.01=300`) from the complete background tuple, then the separate ≥30 distinct cell-mated-PSU gate. Neither background n_eff nor whole-design n_eff is the cell power denominator [AUDIT-07; AUDIT-11; GRPH-32].

| Whole PSUs | Cell PSUs | Output |
| --- | --- | --- |
|49|29 or30|scored=false, no interval, `insufficient_independent_psus`, scope `whole_fixture`|
|50 with resolvable FPIR|29|scored=false, no interval, same reason, scope `cell`|
|50 with resolvable FPIR|30|Eligible: real `decide` H1 interval/state; ordinary H1 nonrejection still counts as scored when the interval exists|
|≥50 with unresolvable FPIR|29 or30|scored=false, no interval, `primary_fpir_unresolvable`, scope `whole_fixture`|

Scope labels are adapter metadata, not scorer enums. On eligible inputs call real `decide` with that complete mixed-scope object and read **H1 alone**: scored iff its interval exists, detected iff state=superior. Never force H1; never condition counts on overall verdict, global H1, H2 state/MDE/interval.

At the downstream G-CELL software gate, test refusals and precedence separately; require exact `_cell_decision`/real-H1 bound and detection parity only on the eligible known-answer domain with identical ordered inputs, weights, seed, B and level. Test background retention/multiplicity, all-three-leg alignment and upstream misses against the actual new runner adapter. Test absence at this planning stage is not itself a planning blocker; a later deterministic failure blocks software acceptance/execution. Clear_mask's dominant harm is false negative; clear_clear's is false positive [FAIR-04; Principle2].

## 4. H2 method, routes and complete wire

The reviewed method candidate remains `paired_psu_studentized_h2_v2`, config `firbench-h2-studentized/v2`, integer method_version2. It is H2-only opt-in; H1, v1 replay, cells and every descriptive/attribution/comparison interval stay percentile. The exact method/case hashes already in `h2_branch` are authoritative. Earlier root questions about method hashing, seed labels, coverage thresholds, truths, D1/D2, SF laws and deterministic tuples are obsolete in the composed candidate; their authored resolutions require the reviews in section1, not another user default-selection round.

H=`len(hypotheses)`=2, H2 step_index=2, alpha2=.05, level=.90. K denotes **paired PSU count** only. Base interval B=10000 and seed2429382368 are the sole kernel sources. The estimand is `E[S_j]/E[M_j]`; strict finite upper bound <.05 is necessary for H2 non-inferiority, subject to actual earlier/later decision gates. Endpoints tied at the margin do not reject.

One protocol envelope contains separately sealed **AU** (auraface versus insightface) and **SF** (sface versus insightface) experiments. Each has a distinct declared decision ID/manifest/raw binding/canonical seal. Both routes are obligations; neither selects, pools with or rescues the other. No conflict exists between a shared envelope and two seals, so H2-BLK-08 is removed [EXP-22; CARD-27]. The original law's SF truth3/20 is preserved as a harm control, never relabelled boundary1/20; current SF boundary and spanning inputs come from the case contract.

The full incorporated H2 §11, together with the reviewed ownership IF-H2V2 completion, requires:

- Separate unchanged v1 records/parsers and explicit v2 records/dispatch. Exact Python int2 alone selects v2; every other payload passes unmodified to the original v1 parser. Parsed nonboolean numeric1 remains accepted, including `1`, `1.0`, `1e0`, `10e-1` and decimal spellings rounding to binary64 1.0. Their v1 dataclass/canonical hash/seal stays identical while raw digests bind distinct original bytes. `true`, absent/unknown versions and existing malformed bodies retain rejection; `2.0`/`2e0` never select v2. Loader hooks/number parsing and v1 methods/defaults/hashes/accept-reject semantics remain unchanged.
- Exact11-key config, three-field `H2IntervalResultV2`,12-key diagnostics with nested14-key draw audit, and15-key calibration record. All field types, enums, required/unknown keys, finite/null conditions, Rule E and all six cross-field invariants are normative. All B original tuples remain classified or explicitly unattempted under the pre-draw rules; no partial delivered result, discarded zero-SE draw or replacement. Seven category totals and eight-bin sign totals reconcile. Intentional infinite t statuses are never JSON endpoints. Numeric failure precedence and actual ordered trace remain intact.
- Separate scores-v2 schema, strict `validate_scores(payload, *, decision)`, actual method/reason/diagnostics copied from the typed verdict, explicit three-key interval projection and strict finite JSON (`allow_nan=False`). Preserve descriptive structures and optional face_outcomes. H1 diagnostics null; H2 diagnostics null until evaluated. Null intervals render the real inconclusive reason, never a bound or success.
- Distinct **raw** decision-file SHA-256 and **canonical** manifest-body SHA-256. V2 canonical body excludes only seal and binds all validated fields with sorted compact ASCII finite JSON. Persisted v2 requires both bindings and its original versioned seal against the same file: raw mismatch refuses even if canonical identity is unchanged. Existing v1 canonical dataclass/hash/seal and legacy loading semantics remain untouched.
- Real comparison/original-seal, cluster IO, report and calibration adapters. Original seals validate before projection; compatibility includes full method/config/version/spec identity. Successful compatible v2/v2 comparison retains percentile metrics and comparison-v1 output; mixed/differing supported H2 policies refuse verdict comparability. Never discard diagnostics to export scores-v1.
- Exactly one actual calibration record per requested route/case/design/branch/replicate, aggregates derived only from records. Completed earlier stops have null draw counts; contract_error/process_incomplete records carry B/0/B and null state/reason/interval/diagnostics/booleans. Unknown is never inferred as false or pass. No partial scores-v2, resume, replacement or sealed-run retry; every requested replicate remains accounted for.

The case grid's declared numerical obligations remain unchanged and separately reviewable. Neither finite endpoints nor synthetic software fixtures establish calibration, coverage, power or numerical acceptance.

## 5. Adopted reviewed ownership and actual software joins

This correction adopts the exact independently reviewed ownership artifacts as a **normative planning dependency**, rather than a merely proposed eleven-group table:

| Artifact | Verified SHA-256 |
| --- | --- |
| [Ownership JSON](firbench-1-v7-implementation-ownership.json) |`d2eb9210881f9f648d432dfe59947dbf1a67fc70e603d7becfed8326cffcda77`|
| [Ownership Markdown](firbench-1-v7-implementation-ownership.md) |`f3ea2d06a66d841a21377f0ddb264e7d30b26b12b78188157ee54d8f93592c8f`|
| [Worker verification](firbench-1-v7-worker-verification.md) |`9426186ea9730a69b4679734e571c4b6369e4452a58d0d8ff5bd5ed92fc27499`|
| [Actual ownership gate2 PASS](../../.task-state/firbench-1/reports/D-p0-h2-ownership-gate-2.json) |`c28573a1628212d54705a0d81a53d22c43c722b1f5cdc7316a128def93f4d86a`|

All three subject hashes match the report's SOURCE check and its findings are empty. This discharges the component's earlier re-review dependency; it does not approve implementation or the whole freeze. Adopt exact lane paths/section partitions/tests, IF-H2V2 call contracts/record types/context/errors, IF-CELL, pointer constraint, freeze binding owners, edges/joins, I01–I09 integration matrix and worker receipt contract. JSON `implementation_ownership` binds and indexes them [Principles1/18; GRPH-32].

| Owner | Required boundary |
| --- | --- |
|H2-CON-M|Versioned manifest parser/spec registry/canonical hash/seal; unchanged v1|
|H2-CON-S|scores-v2 schema, versioned score and diagnostic validation|
|H2-KERN|Typed H2 kernel, full diagnostics/audit and finite/numeric policy|
|H2-DEC|Actual decision dispatch/precedence, retained diagnostics and trace|
|H2-SIO|Real score IO, raw/canonical binding and exact wire conversion|
|H2-CLI|Default wiring, score/report/replay/comparison and original seals|
|H2-REP|Strict finite report input/inline JSON/report.json, actual null reasons|
|H2-CLU|Actual score-version/binding validation before clustering output|
|H2-CAL|Real calibration adapter, context/envelope/records and pure reconciliation|
|CELL-V7|New fixture/runner, mixed-scope adapter, typed sizing/parity/refusals|
|H2-INT|Complete joins and persisted replay for both route seals|

Only **H2-CLI** additionally waits for the actual reviewed pointer CLI commit or reviewed exact disjoint-section proof, retaining evidence delegation and optional report `--evidence-db`/`--artifact-id`. The exact reviewed pointer bytes/signature remain unknown. This explicit dependency does not serialize the other ten authors; logical independence does not establish resource admission.

Bounded reads of the current actual producers confirm the following existing boundaries, with exact source digests in JSON `producer_contracts_verified`. They do not assert that future v2 APIs exist:

- `firbench_contract.py`: `_parse_manifest`846–861, loader892–910, canonical serializer541–557 and `seal`931–946.
- `firbench_score.py`: `LegArrays`/`LegResults`108–150 and `decide`844–945; `firbench_selftest.py`: sizing240–262, allocation/background557–586, synthetic manifest713–745, complete `_results`1139–1156.
- `firbench_score_io.py`: `_decision_binding`952–974 and actual scores-v1 validation1233; `firbench_cli.py`: raw-bound score490–533, original seal674–684, compatibility715+, report593–606.
- Default chain is actual CLI `_load_collaborators`84 → `firbench_runtime.default_collaborators`598 → actual score IO. CLI report already calls **cluster_io** before renderer. `firbench_cluster_io._load_run`259–298 currently validates scores-v1; `firbench_report.render_report`2697–2736 currently loads scores-v1. These are required real compatibility changes.

The software gate must exercise these real parser/kernel/decision/IO joins on prescribed deterministic synthetic packets for **both AU and SF**. No guessed `frozen_interfaces` mocks, replacement collaborators or fabricated score/calibration/report/comparison results qualify. Synthetic inputs, model/assets seams and deterministic fault hooks belong below real producers. Calibration uses actual reviewed callable/context/envelope/reconciler contracts; no invented overload [MCP18674; Principle1; GRPH-32].

Require finite/null/earlier-stop/later-refusal/incomplete paths; original-seal precedence; compatible v2/v2 and v1/v1 positive comparisons; mixed/differing-supported-policy refusals; raw-only, canonical and method-spec mismatch controls; exact persisted interval/refusal/audit/trace and score/cluster/report replay. Report checks include untyped nested metadata, named NaN/Infinity/-Infinity and exponent overflow `1e999`; `parse_constant` alone cannot catch overflow. Refuse before fresh report outputs or replacement of existing outputs; include valid finite/null controls and unchanged-output snapshots. The current renderer is not claimed repaired.

Actual frozen PF-H2/PF-CELL bytes/constants/packets must be bound by assigned owners **before** G-MERGE compares them. Then G-V1, real G-INT/G-CELL, all eleven acknowledged behavioral RED-before-production/whole-suite GREEN receipts and fresh joined-tree evidence feed G-SOFTWARE. Use the exact reviewed worker contract and complete union of lane tests. Missing APIs, setup/collection errors, stale receipts, unexpected skips or mocked aggregate success cannot pass. G-SOFTWARE precedes branch seals; G-SW-H2/G-SW-CELL then check sealed deterministic conformance. Runs, numerical gates and adoption remain later work, with real-data gates also required for adoption. No outcome feeds freeze or seals [EXP-22; GRPH-32; Principle2].

## 6. Preserved failures, disconfirmers and limits

V6 H2 `126/2000=.063>.060` and cell clear_mask `1113/2000=.5565<.77` remain **FAILED**. Original v6 fixtures, seeds, receipts and outputs are not overwritten, pooled, retried or rescued. A v7 result would be a new prospective experiment. All v1 methods/defaults/accept-reject sets/hash/version behavior, H1 and descriptive percentile paths, all-B retention and missed-mate FNIR semantics remain protected. Verified ONNX gte-base prior art is preserved without new inference or method selection.

A cell null failure or cell power failure independently disconfirms its claim. Any frozen H2 gate failure stands under its original route/case/design; no seed retry, selective row omission, gate change or post-outcome resizing. Deterministic wire/parity/binding failures block software acceptance. A component planning PASS cannot supply a missing whole-freeze review or software/numerical receipt [EXP-22; Principle2].

GT/QC/occasion reports retain their existing checked hashes as non-numerical evidence; no report content or private data was inspected here. Real exhaustive GT, QC, contextual measurement production, capture occasions, budget and seals remain **unknown/unqualified**. Availability figures or historical software results do not establish them. MEAS-29 is unmet. Unknown external qualification does not block prospective synthetic design. The absent canonical real manifest is not replaced by the fixture policy mirror; real ratification remains separate.

Cell compute estimates remain explicitly unvalidated extrapolations, not measurements; H2 cost follows the full bound case schedule, without dropping rows. Timing/budget cannot select a gate, method, seed or route. No benchmark, product test, Monte Carlo/bootstrap outcome, implementation, real inference or private transfer occurred in this correction.

## 7. Canon and static verification

Heuristics canon v0.26.2 was read only from the approved read-only mirror, with the available CARD-27 supplement. JSON records exact release/lexicon/supplement identities. Only matched rows and relevant principles/supplement were consulted; unavailable reasoning cards and original books are not claimed read. The current correction does not add a statistical formula or claim a source guarantees the selected method's finite-sample behavior.

Stable rules cited at their use above: EXP-12/13 (*Trustworthy Online Controlled Experiments*, ch2/19); EXP-18/22/23 (*Statistics Done Wrong*, ch2/6/3); AUDIT-07/11 (*Sampling: Design and Analysis*, ch1/5); FAIR-04 (*NIST FRVT Part3*); GRPH-14 (*Building Knowledge Graphs* and *Mental Models*, ch8); GRPH-32 (practice label `bootstrap`). Principle1 authors contracts, Principle2 names disconfirmers and Principle18 requires machine-checkable boundaries. CARD-27 requires prospective margin/method/harm/alpha and independent-unit sizing; it selects **no formula or project default**.

Planning validation is static: strict JSON/key/type checks, exact artifact hash/section bindings, rational sizing, current source-anchor reads, root-only scope/key-order checks, byte-identical `h2_branch` preservation, unchanged product/test artifacts and `git diff --check`. No software conformance or numerical acceptance is inferred. The independent composed freeze gate remains required.
