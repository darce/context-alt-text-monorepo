# FIRBENCH-1 H2 v2 prospective case grid

This is owned planning work for the second-author correction of FB1-P0-FREEZE-01 after HOLD b97ee0fa / reviewrun1364. No Monte Carlo, bootstrap outcome, inference, timing probe, or real-data qualification is produced. The accompanying JSON is normative for the case grid. The coordinator must compose its five owned H2 fields with sibling method and contract work before claiming a complete protocol. Unowned legacy blocker prose is not rewritten in this lane.

The checked public export attributes source `505618d530f476665fcc0d0c0bf1c8a58d17d277`; its local parentless sandbox base is `d5e67fb2208756448c77af4e8fccb187cb68e9bc`, tree `c6350c1852b568f89a3d83a5f1f0d76a21956b3f`. The historical source-map `870710fd` is provenance only. No private source, image, map, database, pseudonym, or real row values are inputs.

The accepted H2 proposal, read through all of §10, is SHA-256 `fce057de4e9d927b16fa7f1cb1b6d25d971cd3f4947b163e713f38c6ab6cd5d4`; the cell proposal is `c6d6bd0710612520a88a1a55fdd3f17be5b2ae2193895080414bf3e7d20e5794`. Method mathematics and wire semantics refer normatively to that exact H2 text, §§7–8 and 11. The sibling owns final method bytes and their registration. This grid binds the logical configuration at its root and does not select another algorithm.

Before outcomes, both AU and SF are required under separate route seals in one protocol envelope. R=2000 and B=10000 remain fixed. H=len(hypotheses)=2, step_index=2, alpha2=.05 and H2 level=.90; K denotes paired PSU count. H1 remains the original percentile method and strict lower>0 test. All v1 defaults, hashes, records, accepted version spellings and method behavior remain unchanged.

The old v6 .063 boundary failure and .5565 cell-power failure remain FAILED. Neither new route can replace, pool with, or rescue them. The original SF law has truth .15; it is a harm control, not a .05 boundary. Unknown external GT, QC, observation and budget stay unqualified and do not block this synthetic planning contract.

Prospective choices use [EXP-22], **No circular analysis (double-dipping)** (*Statistics Done Wrong*, ch. 6): no outcome-selected seed, truth, gate, design, omission, or retry. [EXP-23], **Pseudoreplication check** (*Statistics Done Wrong*, ch. 3), and [AUDIT-11], **Account for cluster design effect** (*Sampling: Design and Analysis*, ch. 5), require independent PSUs and explicit weighted variance sizing. Canon v0.26.2 relevant lexicons were hash-checked against its read-only release manifest; the supplied CARD-27 supplement was read. CARD-27 requires prospective commitments and does not supply formulas or numerical defaults. The full row grid and analytic derivations are sealed below.

The full input inventory is now the literal [`firbench-1-h2-v2-case-grid.json`](firbench-1-h2-v2-case-grid.json): **77 native datasets, 254 stochastic evaluation rows, and 248 structural evaluation rows**. The JSON lists every row, law, design, branch, truth, threshold, output root and seed identity. It contains no outcome. Compressed fixed arrays and draw lists have exact expansion rules, with no sampling or choices left to an executor. Two empty-pair decision entries are logical reports; they do not claim H1 can reach H2.

## Prospectively chosen laws and sizes

[EXP-12], **Power and practical significance** (*Trustworthy Online Controlled Experiments*, ch. 2), supports sizing from a declared effect. These numerical choices are project design decisions, not canon defaults. Every original PSU is independent. For each PSU, draw the eight-pattern probabilities once from Dirichlet(9π) on positive-mass categories, then conditionally independent face patterns. This gives contrast ICC .10. All eight joint probabilities are literal rational entries in `joint_laws`. The bits are ordered SFace, AuraFace, InsightFace.

For added natural-power laws, the nonselected arm is part of the original joint law: AU uses SFace miss probability .85; SF uses AuraFace miss probability .02, independent of the selected/reference pair in π before the PSU Dirichlet draw. This makes H1 a genuine native alternative. It is not a post-generation forcing operation. The forced branch subsequently changes only the nonselected arm to the proposal's route-specific constant. Selected/reference arrays, mates, weights and kernel draws must hash identically across forced/natural branches. The original global null law, whose H1 is null, cannot provide an unconditional natural H2 power claim and is not silently reused for one.

For a selected/reference pair, let d be its mean contrast, q its discordance probability, and c its both-miss probability. The probabilities in order 00,01,10,11 are `1-q-c, (q-d)/2, (q+d)/2, c`. For every deterministic weight design below, `E[S_total]=W*d`, `E[M_total]=W`, so the population ratio truth is exactly d. Each dataset records the actual numeric numerator and denominator separately. No unweighted PSU-rate average is used.

| Case | d | q | c | Required designs | Evaluations |
| --- | --- | --- | --- | --- | --- |
| Boundary | 1/20 | 3/20 | 1/10 | D0,D1,D2P,D2N,D2X | Direct forced + decision forced |
| Equal-distribution | 0 | 3/20 | 3/40 | D0,D1,D2P,D2N,D2X | Direct/decision, forced/natural |
| Positive interior | 1/200 | 1/10 | 1/10 | D0,D2P,D2N,D2X | Direct/decision, forced/natural |
| Negative interior | −1/20 | 3/20 | 3/40 | D0,D2P,D2N,D2X | Direct/decision, forced/natural |
| Harm | 1/10 | 1/5 | 3/40 | D0,D2P,D2N,D2X | Direct forced + decision forced |
| Sparse equal | 0 | 1/50 | 1/10 | D0,D2P,D2N,D2X | Direct/decision, forced/natural |
| Sparse boundary | 1/20 | 7/100 | 1/10 | D0,D2P,D2N,D2X | Direct forced + decision forced |
| Sparse positive interior | 1/200 | 1/40 | 1/10 | D0,D2P,D2N,D2X | Direct/decision, forced/natural |
| Sparse negative interior | −1/20 | 7/100 | 1/10 | D0,D2P,D2N,D2X | Direct/decision, forced/natural |

Both AU and SF instantiate every listed case/design/evaluation. This table summarizes the fully expanded JSON rows, not an instruction to select a subset. Accepted H2 §10.3 requires D1 for boundary/equal only and natural decision branches for alternatives. There is no natural-power claim at or above the margin. The AU boundary retains the original eight-pattern vector `[270,0,10,0,30,20,30,40]/400` exactly; it has the boundary pair probabilities above. SF receives its own truth-preserving boundary joint law. A separately enumerated **SF legacy harm .15 / D0** direct/forced-decision control retains that original vector unchanged: its SF truth is **3/20**, not 1/20. No route uses observed outcomes to choose a law.

Sparse means both discordance signs have at least .01 probability, with the precise probabilities fixed above. This choice avoids assuming .77 power on a law with a large analytically predictable zero-discordance mass. Under the fixed Dirichlet law, a PSU of size m has all-concordant probability `(9(1-q))_m/(9)_m`; multiply these factors over the prescribed independent PSUs. The smallest D0 q=.02 gives probability about 0.00000620 of all faces concordant. This is analytic law arithmetic, not a simulated refusal rate or coverage guarantee. A separate deterministic sparse array contains exactly one positive and one negative discordant singleton; it tests plumbing, not calibration.

| Design | Ordered PSU sizes and face weights | K / raw faces | W | Weighted n_eff | Role |
| --- | --- | --- | --- | --- | --- |
| D0 | 176×size1,44×size16; all weights1 | 220 / 880 | 880 | 400 | Gate, original fixed design |
| D1 | 220×size4; all weights1 | 220 / 880 | 880 | 8800/13 ≈676.923 | Gate, balanced |
| D2P | 352×size1 weight1,88×size16 weight2 | 440 / 1760 | 3168 | 28512/41 ≈695.415 | Gate, positive weight–size association |
| D2N | 352×size1 weight2,88×size16 weight1 | 440 / 1760 | 2112 | 6336/7 ≈905.143 | Gate, negative weight–size association |
| D2X | 352×size1 weight1,87×size16 weight1,1×size16 weight128 | 440 / 1760 | 3792 | 1797408/82399 ≈21.813 | Mandatory report-only numerical sensitivity |

For fixed sizes m_j and constant within-PSU face weights w_j, define `A=Σ w_j²[m_j+.1m_j(m_j−1)]`. Then `Var(delta_hat)=(q−d²)A/W²` exactly under this law, because W is fixed. Weighted `n_eff=W²/A`; weighted Kish face count and weighted design effect are also recorded. The original unweighted decision/MDE calculation is recorded separately: it is 400, 8800/13, 800, 800, 800 respectively. Adding independent background units never enlarges paired K or mated n_eff. These weights define the estimand; they are not an assertion that arbitrary unequal-probability sampling is repaired by uniform PSU resampling.

D2P with the original PSU count would have weighted n_eff about347.707, below the original .05 MDE planning requirement. Its independently sampled PSU count is doubled prospectively; D2N uses the same fixed composition to compare opposite weight–size associations. D2X's final PSU carries 128/237 of total weight and violates a no-dominating-PSU premise. Its numerical coverage/power are explicitly report-only before outcomes. Its completion, all-B accounting, immutable data and publication obligations still apply. A D2X numerical failure cannot be omitted or turned into a gate success.

The unchanged MDE formula at p_d=.15, target power=.80, alpha2=.05 needs about370 independent-equivalent observations at margin .05. D0's MDE is about.048025; D2P/D2N's original decision-route MDE is about.034003. For the positive interior d=.005, q=.10, D0's normal planning H2 power is about.88523 after the H1 union-bound adjustment on SF; the other gated weighted designs are stronger under this approximation. Equal-distribution D0 power is about.82565. These are planning approximations, not finite-sample bootstrap guarantees. They motivate the fixed inputs; failure of the actual gates disconfirms the plan and cannot trigger resizing.

## Gates and their Monte Carlo interpretation

Every stochastic row requests R=2000, B=10000 once. Missing intervals count as uncovered. Coverage includes equality; rejection uses the emitted finite binary64 upper bound strictly below binary64(.05). Completed means a typed result, including a refusal; it does not mean scorable or successful.

The original boundary/harm ceiling remains **≤120**, and equal-distribution power remains **≥1540** actual H2 decisions, forced/natural separately. These conjunctive project gates are preserved. There is no claim that their combined Monte Carlo false-failure probability is controlled at5% across the full grid.

New coverage gates use 118 named evaluation slots ×3 metrics =354 checks. A direct-natural result aliases direct-forced only after exact selected/reference and diagnostics invariance; it adds no independent trial. Forced decision coverage is counted separately. Natural decision coverage is reported over full R, plus a labelled conditional diagnostic; unchanged H1 selection does not justify a nominal conditional-coverage gate.

For `X~Binomial(2000,p)`, set `eta=.05/(2*354)=1/14160`. Let `lo` be the smallest integer with CDF(lo)≥eta and `hi` the smallest integer with CDF(hi)≥1−eta. Seal inclusive `lo≤count≤hi`:

| Metric | Nominal p | Inclusive count band |
| --- | --- | --- |
| Two-sided `L≤truth≤U` | .90 | 1747–1849 |
| Upper `truth≤U` | .95 | 1861–1935 |
| Lower `L≤truth` | .95 | 1861–1935 |

These bounds were derived with integer binomial sums, not simulated trials or a fitted MC error. Bonferroni gives at most.05 reference family error at exact nominal p, without assuming independence among metrics or routes. This is a specified calibration tolerance, not evidence the candidate achieves nominal p. Overcoverage also fails its upper bound.

For the48 new positive/negative-interior decision checks, use nominal planning target .80 and one lower-tail budget `.05/48=1/960`. The same exact binomial lower-quantile rule gives **count≥1544**. Analytic power above.80 motivates the design; this gate is not an assumed .77 floor transplanted to a weak truth. Equal and sparse-equal rows retain1540. All direct `U<.05` counts remain separately labelled diagnostics for power; they cannot replace actual decision outcomes stopped by H1, MDE, eligibility or frame handling.

Binomial MC arithmetic assumes independent outer replicates and a fixed decision function. The fixed inner seed makes the kernel deterministic given a paired dataset; B is not the number of independent outer trials. A hash collision check proves seed identity uniqueness, not PRNG independence. No source guarantees the nominal probabilities of this weighted binary ratio. Cameron–Miller (2015), VI.C.1, and MacKinnon–Nielsen–Webb (2023), §5.2, motivate whole-cluster studentization and explicitly caution about unequal sizes/heterogeneity. The supplied text hashes were checked; bounded passages actually read are recorded in JSON `source_evidence`. Their regression results are not imported as ratio guarantees.

## Deterministic arrays, draw lists and precedence

`deterministic_arrays` lists exact synthetic face tuples and PSU multiplicities. Expansion assigns monotonically numbered synthetic IDs, preserving order. `prescribed_draw_lists` is exact ordered run-length compression of10000 tuples, including every repeated sampled PSU position. IDENTITY means the exact tuple `[0,...,K−1]` repeated10000 times. Structural conformance injects these tuples at a test seam; it changes neither the statistical method nor the sealed RNG stream of stochastic rows. No such bootstrap evaluation was executed here.

The62 structural constructions are instantiated under both seals with explicit direct and decision expectations. They include K0/K1, common identical misses, all contrasts0/+1/−1, identical PSU ratios with unequal masses, exact reference variance9/3136, repeated positions, all six nonfailure t categories, finite/infinite rank ties at500/9500, mixed extreme weights2^1023 and2^−1074, common dyadic/decimal scales, finite bounds beyond[−1,1], endpoint underflow/overflow, margin equality, contract mutations, all certification-failure phases, interruptions and overlapping eligibility/MDE failures. No epsilon, winsorization, clipping, replacement or finite-only rank selection is allowed.

The fixed margin-spanning control is D0:176 concordant correct singletons; each of44 size16 PSUs contains11 both-correct,2 both-miss,1 selected-correct/reference-miss,2 selected-miss/reference-correct faces. Its selected/ref miss rates are1/5 and3/20, so its weighted empirical contrast is1/20 for both seals. The first5000 prescribed tuples draw210 copies of singleton0 and10 copies of largePSU176; the last5000 draw120 singleton0 and100 largePSU176 copies. Both have positive replicate SE, with contrasts respectively below/above.05; the selected finite t ranks have opposite signs, so analytically `L<.05<U` and no non-inferiority. No invented numerical endpoints or new bootstrap outcomes are reported.

The decision expectation explicitly distinguishes H1 impossibility: AU all-selected-miss cannot beat its forced all-miss SFace, whereas SF all-selected-correct cannot beat its forced all-correct AuraFace. K0 has no H1 paired data and is a logical decision report, with direct K0 tested separately. K1 remains reachable with the specified nonconstant faces. The global49/50 controls keep FPIR resolvable using1500 background units spread across exactly49/50 union PSUs, isolating the global threshold from paired K. Actual method reason precedence remains that of accepted §§5,8,11.

Recoverable replicate failures at tuples1,5000,10000 and all three together still classify all10000 original tuples. Observed refusal attests0 classified/10000 unattempted; quantile/endpoint failures attest10000 classified. An interruption is an incomplete computation with no delivered typed result, state, reason, interval or diagnostics; it never becomes numeric failure. Failure injections are structural conformance expectations, not stochastic successful completion.

## Seeds, records and output identity

`datasets` seals77 literal labels and their numeric uint128 masters. Registry11..87 is assigned in the literal dataset order, disjoint from v1 1..8 and cell9..10. Each master is the first16 bytes of SHA256(ASCII label), big-endian, with bit127 set. Replicate r=0000..1999 uses the same derivation on `label + '/r=' + four-digit-r`. All77 masters and154000 replicate integers were statically checked for uniqueness. Setting bit127 ensures numerical disjointness from the original uint32 masters and uint64 suite/replicate outputs. No RNG or new outcome was inspected. The inner kernel seed2429382368 is deliberately unchanged and is not an outer stream.

A native dataset is realized once per replicate and shared across its forced/natural/direct/decision evaluations. Each branch retains its own requested-R records; direct branches have null H1/reached flags as the accepted wire contract requires. Forced nondegenerate stochastic decisions must attempt forcing and pass H1/reach H2 on all2000 requests. A shortfall fails that obligation. Natural H1 non-rejection is a completed no-H2-rejection replicate, not a missing computation, and is retained in denominator2000.

For every row, reconcile requested=records+never_started and records=completed+contract_error+process_incomplete. Sum actual invoked/completed/finite/rejected states, reasons, nulls and all-B audit counts. Completed decisions whose candidate was not invoked have null draw counters per the accepted record contract, not fabricated unattempted kernel counts. Contract/process failures attest B/0/B. Preserve all category, histogram, phase and selected-status summaries required by accepted §10.5/11. Hash checks bind ordered selected/reference arrays and stream identities; no private mappings enter reports.

Each row has a literal new root beneath `benchmarks/results/firbench-1-prospective-v7/h2-case-grid-v1/`, including route/case/design/evaluation identity. Refuse an existing root before outcomes; never overwrite v6 or append a rescue run. Write `acceptance.json` and `records.jsonl` under that row root, with separate AU/SF manifests/seals in the same protocol envelope. The coordinator must bind the exact composed runner/fixture/source/config/manifest identities and final sibling method-spec registration before execution. That implementation/seal verification is separate from the now-resolved case-design inputs.

[GRPH-14], **Record provenance as a walkable lineage graph** (*Building Knowledge Graphs*, ch.8 + *Mental Models*, ch.8), is applied through the checked source/proposal hashes and per-row input bindings. [GRPH-32], **An edge exists only where data moves** (practice label `bootstrap`), is concrete here: the future adapter reads `joint_laws`, `designs`, `datasets` and literal row selectors; aggregation reads actual `H2CalibrationRecordV2` fields; gate evaluation reads sealed truth/count policies; adoption reads gates plus the remaining implementation and real-data holds. There is no outcome-to-design feedback edge.

## Execution cost and disconfirmers

This is an **unmeasured planning workload**, not a runtime quotation or approved budget. At most508000 stochastic candidate calls and254000 H1 calls are requested, plus248 structural row records. Counting all calls even if precedence avoids computation gives at most **2,864,487,300,000 sampled PSU positions** across candidate and H1 kernels. Exact arithmetic bit costs, generation, record I/O and VM overhead are additional. No timing probe, installation, MC or bootstrap was run. Seconds and peak RAM remain unknown; measured throughput cannot select a smaller or different experiment after outcomes.

The future execution is one VM process, one thread with library thread limits, and immutable requested R/B. Stream records; do not early-stop for success or a bad rate. Resource loss remains incomplete evidence, with never-started requests visible; no resume, replacements or retries within the sealed run.

The following observations disconfirm the corresponding claim: any gated count outside its inclusive bounds; any stochastic incomplete/error/never-started record; any forced H1/reached shortfall; any structural classification or invariant mismatch; any dropped B tuple or count mismatch; any changed selected/reference hash under forcing; any unsupported config/spec or parser/wire divergence; any seed, law, weight, dimension, order or output-root mismatch. Keep the failure and diagnose separately. D2X numeric failures remain visible as the prospectively designated sensitivity; its completion/structure are still required. Passing direct coverage alone does not establish actual decision power, and passing a new run never changes either old failure.

Canon Principle2, **Specify what would prove you wrong**, is implemented by those fixed disconfirmers. Principle11, **Unknown is a designed state**, applies to unavailable real GT/QC/observation/capture/budget and to missing future computation. They remain unknown/unqualified, without blocking the synthetic prospective design. Nothing here asserts implementation, full composed freeze, numerical acceptance, adoption, or real qualification.

Static validation checked every literal law/truth, all design arithmetic, the exact binomial gate endpoints, seed identity uniqueness, prescribed tuple dimensions/indices, all502 row identities and normative pointers, accepted proposal hashes, and unchanged unowned shared JSON values/key order against the parentless sandbox base. `git diff --check` passed. The two K0 decision entries request zero calibration replicates/draws plus one mandatory logical report each:246 structural calibration records and2 logical reports. Development-frame and veto controls use verified current enum/record shapes; no implementation or outcome test was run.
