# First principles

The lexicons hold rules. This document holds the mechanisms underneath them.

A claim earns a place in a lexicon when it is useful in its own domain. It earns a *tier* when a second source (from an economy the first author never saw) arrives at the same mechanism by a different road. Those independent arrivals are the corpus's most valuable output: a person or model answering a question defaults to the domain of the question, and the pop-charts rule never surfaces while you are debugging a race. The convergences are written down as principles, each with the arrivals that back it and the rule IDs to open next.

Read this file to understand how the corpus thinks. Cite a principle when a single-domain rule fires and you want its cross-domain corroboration: a session that reaches for [[PROD-09]](lexicons/business-marketing.md#prod-09) should also get [[A11Y-22]](lexicons/accessibility.md#a11y-22), because both require the artifact to satisfy a written contract.

Principles explain and navigate. Operational triggers, actions, tensions, and checks live on mechanism cards in the reasoning tree when a multi-rule decision needs more depth. Agents: use the compact [Agent application](#agent-application) protocol at the end of this file.

## Forces at a glance

The 20 mechanisms cluster into four forces without collapsing into four vague rules. These are navigation groups, not merge proposals. Each numbered principle stays separate because its trigger, causal mechanism, or prescribed action differs.

| Force | Principles | Question |
|---|---|---|
| [Contracts and boundaries](#contracts-and-boundaries) | 1, 5, 6, 10, 18 | What structure, interface, or default must be true before the surface can be trusted? |
| [Evidence and measurement](#evidence-and-measurement) | 2, 4, 9, 13, 15, 20 | What produced the claim, what would falsify it, and can the measured party shape the meter? |
| [Reversibility and exposure](#reversibility-and-exposure) | 3, 8, 14, 17 | What is expensive to undo, who controls it, and how much can one failure reach? |
| [Feedback and correction](#feedback-and-correction) | 7, 11, 12, 16, 19 | Where does error surface, where is it corrected, and can feedback arrive before the next commitment? |

---

## Contracts and boundaries

<a name="force-contracts-and-boundaries"></a>

Structure, interface, default, and machine-readable outcome must be true before the surface can be trusted. Spec before song; substance before style; chosen defaults; perceived boundary equals enforced boundary; machines consume contracts, not prose.

Entry points (first cited rule per principle):
[[PROD-09]](lexicons/business-marketing.md#prod-09) ·
[[COL-04]](lexicons/design-aesthetics.md#col-04) ·
[[LAY-10]](lexicons/design-aesthetics.md#lay-10) ·
[[PERC-03]](lexicons/interaction-ux.md#perc-03) ·
[[AGT-21]](lexicons/engineering.md#agt-21)

### 1. Author the contract before the components

Distribution almost never runs straight to the audience. It passes through a reader (playlist committee, store reviewer, compliance officer) who checks the artifact against a written spec and fades, demotes, or rejects whatever fails it. The spec exists before your work does, so the work is built to it first.

- The KLF wrote the channel contract before the song [[PROD-09]](lexicons/business-marketing.md#prod-09).
- WCAG makes "accessible" a falsifiable sentence page by page [[A11Y-22]](lexicons/accessibility.md#a11y-22).
- Do not risk customers by approving an unfinished release before QA has finished testing merely to meet an arbitrary date [[RLSE-02]](lexicons/engineering.md#rlse-02); *The Pragmatic Programmer: Your Journey to Mastery* assigns explicit parameter checks to the caller when the language checks preconditions before routine entry, because the routine never sees invalid arguments; without that language support, bracket the call with assertion checks [[AGT-08]](lexicons/engineering.md#agt-08).
- Anderson: write what must not happen and who may do what before choosing mechanisms [[SECD-01]](lexicons/security.md#secd-01).

Pop charts, app stores, procurement, release gates, and security policies run one mechanism: author the contract the gatekeeper reads; ship no claim that gatekeeper can falsify.

### 5. Rank the substance before you style it

Order the underlying thing first and the surface decisions fall out correctly, often passing their own checks for free. Reverse the order and you re-litigate every surface value and still fail the audit.

- Value before hue: hierarchy that survives greyscale is the real hierarchy [[COL-04]](lexicons/design-aesthetics.md#col-04), and a value-ranked palette can support contrast by design, but each actual text/background pair must still be measured against the applicable WCAG ratio [[A11Y-01]](lexicons/accessibility.md#a11y-01).
- Restate the solution brief as a measurable problem before designing a solution [[PROD-02]](lexicons/business-marketing.md#prod-02); layout starts from real content [[LAY-08]](lexicons/design-aesthetics.md#lay-08).
- The most accurate visual channel goes to the most important attribute before decoration [[VIZ-02]](lexicons/interaction-ux.md#viz-02); architecture is justified by quality-attribute risks, not feature decomposition [[ARCH-12]](lexicons/engineering.md#arch-12).
- Describe comprehension-essential visual content, avoid repeating information inferable from audio, and proceed from general information to details [[A11Y-43]](lexicons/accessibility.md#a11y-43); during automatic fitting, lock exact text, event-critical timing, or the presence of important descriptions [[A11Y-44]](lexicons/accessibility.md#a11y-44); budget-driven sentence order is editorial selection, not image privilege [[BOUND-05]](lexicons/depiction.md#bound-05).

Decide the structure before the decoration, and the decoration has nothing left to argue about.

### 6. An unchosen default is a defect the user feels before they can name it

Every value that ships should be one a human chose on purpose. A default that survives review reads as neglect, and neglect is legible even when the specific default is not.

- For an empty user-generated-content feature, include an image or illustration and a clear action, and hide supporting controls that do nothing until content exists [[LAY-10]](lexicons/design-aesthetics.md#lay-10); pure grey is an unchosen choice [[COL-05]](lexicons/design-aesthetics.md#col-05).
- Authoring tools must ship accessible-content support on by default [[A11Y-38]](lexicons/accessibility.md#a11y-38); fail-safe security defaults matter because most deployments keep the shipped default [[SECD-05]](lexicons/security.md#secd-05).
- Prefill known information only when the value has a high probability of making the form easier or quicker to complete; do not preselect an advertising-email checkbox [[FORM-04]](lexicons/interaction-ux.md#form-04). Match the codebase's existing convention over personal taste [[NAME-04]](lexicons/engineering.md#name-04).

Design and release engineering audit the same signal: the difference between a surface that was assembled and one that was chosen.

### 10. Perceived boundaries must match enforced boundaries

A grouping the surface implies but the system does not enforce is a lie the user believes. Gestalt, DOM, IA, authorization scopes, cluster membership, and automation envelopes fail the same way: the eye reads one boundary while the machine honours another.

- Check implied layout relations against real structure [[PERC-03]](lexicons/interaction-ux.md#perc-03); MECE labels fail when a thing has two homes [[NAV-05]](lexicons/interaction-ux.md#nav-05).
- Trust changes at every boundary [[SEC-01]](lexicons/security.md#sec-01); hidden automation or an autonomy overclaim can create over-trust and unrecoverable failure, so disclose its activity and document override [[HAI-05]](lexicons/interaction-ux.md#hai-05).
- Synthetic content that could pass as human must be labeled [[AIPX-13]](lexicons/business-marketing.md#aipx-13).
- Org and architecture: a software split must be a team split first [[TEAM-01]](lexicons/planning.md#team-01); a property left to "everyone will be careful" is not enforced [[ARCH-13]](lexicons/engineering.md#arch-13).
- IDOR without object auth [[WEB-08]](lexicons/security.md#web-08), multi-tenant rows without RLS [[PG-02]](lexicons/security.md#pg-02), complete mediation on each use [[SECD-03]](lexicons/security.md#secd-03), and click affordances that match reality [[INT-01]](lexicons/interaction-ux.md#int-01) are the same audit in different materials.

Draw the boundary the user perceives, then prove the system enforces exactly that one.

### 18. A machine consumes contracts, not prose

Whatever a program, pipeline, or reviewer must branch on has to arrive as a checkable structure: a status, a schema, a named artifact. Prose in that position is unparseable to the machine and unfalsifiable to the reader.

- Exit status is the outcome a caller branches on [[AGT-21]](lexicons/engineering.md#agt-21); stdout carries data, not banners [[AGT-15]](lexicons/engineering.md#agt-15).
- Machine-consumed generation is schema-constrained and validated before use [[FM-04]](lexicons/ml-systems.md#fm-04).

The moment a consumer must act on an outcome, the outcome stops being prose.

---

## Evidence and measurement

<a name="force-evidence-and-measurement"></a>

What produced the claim, what would falsify it, and whether the measured party can shape the meter. Disconfirmers before confidence; outcome over proxy; walkable provenance; evidence before the durable commit; unshaped sampling frames; reference conditions matched to the query.

Entry points:
[[STRAT-02]](lexicons/business-marketing.md#strat-02) ·
[[OPS-01]](lexicons/planning.md#ops-01) ·
[[GRPH-14]](lexicons/graph-theory.md#grph-14) ·
[[PROV-02]](lexicons/ml-systems.md#prov-02) ·
[[PERF-03]](lexicons/engineering.md#perf-03) ·
[[HITL-15]](lexicons/ml-systems.md#hitl-15)

### 2. Specify what would prove you wrong

A claim nobody has tried to break is a guess wearing a conclusion's clothes. Name the observation that would make you wrong, then go looking for it.

- Invert the thesis: define non-X and disconfirmers before the forward plan [[STRAT-02]](lexicons/business-marketing.md#strat-02); name the result that would kill the darling [[PROD-04]](lexicons/business-marketing.md#prod-04).
- Reproduce the failure before proposing a fix [[DBG-01]](lexicons/engineering.md#dbg-01); a cause is established when its absence makes the failure vanish [[DBG-11]](lexicons/engineering.md#dbg-11); do not trust a test never observed failing [[TEST-06]](lexicons/engineering.md#test-06).
- Write forecast resolution criteria in advance [[FORE-02]](lexicons/epistemics.md#fore-02); for a contested policy argument, *Superforecasting: The Art and Science of Prediction* asks each side to list in advance the signs that would nudge it toward the counterargument [[FORE-09]](lexicons/epistemics.md#fore-09); pre-mortems assume the plan has already failed [[NDM-02]](lexicons/epistemics.md#ndm-02); do not explain away early-warning cues one at a time; force an alternate diagnosis of the set [[NDM-05]](lexicons/epistemics.md#ndm-05).
- Threat models list how the policy dies before buying controls [[SECD-07]](lexicons/security.md#secd-07); a post-mortem that reverses process grade on outcome alone has replaced the disconfirmer test with resulting [[NDM-12]](lexicons/epistemics.md#ndm-12).
- Seal the non-inferiority margin, primary, and α allocation before the run [[EXP-12]](lexicons/epistemics.md#exp-12), [[EXP-10]](lexicons/epistemics.md#exp-10); post-data threshold selection is circular analysis [[EXP-22]](lexicons/epistemics.md#exp-22).

Replace "this looks right" with a stated way to find out it is not.

### 4. You get the number you pay for, not the outcome you want

Any proxy drifts from its target under pressure, and once the proxy becomes a target it gets gamed. Anchor on the outcome you actually want and instrument the node where that outcome is really counted.

- A metric pays for the behavior it rewards at 2am, not the behavior you meant [[OPS-01]](lexicons/planning.md#ops-01); ship what changes valuable behavior [[PROD-01]](lexicons/business-marketing.md#prod-01).
- Offline score up while acceptance flat is the proxy moving [[AIPX-02]](lexicons/business-marketing.md#aipx-02); coverage can be gamed, so measure the stability outcome the coverage target was meant to protect [[TEST-11]](lexicons/engineering.md#test-11).
- Cost-per-defect falls as quality worsens the fixed-cost accounting; defect-removal efficiency and delivered defects per size unit are the economic pair [[OPS-18]](lexicons/planning.md#ops-18) [[OPS-19]](lexicons/planning.md#ops-19) [[RLSE-14]](lexicons/engineering.md#rlse-14).
- A metric with no named decision and no anti-gaming check is collected for its own sake [[TEAM-12]](lexicons/planning.md#team-12).
- Page on degraded user experience, not a CPU threshold with benign explanations [[OBS-07]](lexicons/engineering.md#obs-07); measure the decision variable, not the convenient composite [[UXR-03]](lexicons/interaction-ux.md#uxr-03).
- Score resolved numeric probability forecasts with Brier scores; narrative confidence alone does not measure forecast accuracy [[FORE-03]](lexicons/epistemics.md#fore-03); simulate how the measured party will optimise the number before adopting it [[RSCH-07]](lexicons/epistemics.md#rsch-07).
- Tokens-per-second is not goodput at the latency target [[COST-15]](lexicons/ml-systems.md#cost-15).
- A clinical surrogate marker needs empirical linkage to patient benefit for the outcome, population and design; a plausible mechanism is not linkage [[MEAS-30]](lexicons/epistemics.md#meas-30).

The measured proxy and the real goal come apart exactly when the stakes rise.

### 9. A claim must walk back to what produced it

Every artifact is derived from inputs, and the derivation is the part that decays first. Attach the pointer at creation time so an audit follows pointers instead of reconstructing them. Principle 7 records knowledge so it survives its author; this one records derivation so a reader can verify it.

- Provenance as lineage: every artifact points at the inputs that produced it [[GRPH-14]](lexicons/graph-theory.md#grph-14); pin model and dataset revisions [[SEC-10]](lexicons/security.md#sec-10).
- Name the actor behind a reported claim when omitting the actor would conceal responsibility or evade needed attribution [[WRIT-26]](lexicons/writing.md#writ-26).
- A point probability with no decomposition has no walkable ancestors [[FORE-06]](lexicons/epistemics.md#fore-06).
- Look it up, don't guess [[AGT-02]](lexicons/engineering.md#agt-02); a model-invented package name is not a package until owner and history resolve [[SEC-09]](lexicons/security.md#sec-09).

Walk backward from the claim; if the walk breaks, the claim breaks with it.

### 13. Evidence precedes commitment

A model label, architecture decision, UX claim, purchase, and agent's "done" all become durable state the moment they are committed. Each needs inspectable evidence *before* that moment. This is Principle 2's disconfirmer and Principle 9's traceable ancestor on a clock.

- Suitability is earned before deployment: disaggregated analysis [[PROV-02]](lexicons/ml-systems.md#prov-02), intersectional tables [[FAIR-02]](lexicons/ml-systems.md#fair-02), baselines that make a metric mean anything [[EVAL-01]](lexicons/ml-systems.md#eval-01).
- Show the outcome before the costly commit [[INT-07]](lexicons/interaction-ux.md#int-07); accept training labels against embedded gold [[HITL-05]](lexicons/ml-systems.md#hitl-05).
- Outside view before narrative lock-in [[FORE-05]](lexicons/epistemics.md#fore-05); characterization tests before editing legacy contracts [[TEST-03]](lexicons/engineering.md#test-03).
- Costly action, not survey intent, is demand [[GTM-01]](lexicons/business-marketing.md#gtm-01).
- Most tested ideas are flat or negative, so a launch without controlled comparison commits against the prior [[EXP-01]](lexicons/epistemics.md#exp-01); confidence tracks story coherence, not evidence amount [[BIAS-01]](lexicons/epistemics.md#bias-01).

Each commitment is cheap to gate with evidence beforehand and expensive to reverse once it is durable state.

### 15. A measurement the measured party can shape is not a measurement

Where the measured system can decide which cases enter the sample, or how large the divisor grows, the metric reports the arrangement, not the world. The failure never looks like a failure: the number improves. Fix the sampling frame or the denominator *outside* the system under test.

- Coordinated omission: wait-then-send pauses when the system stalls and deletes the slow observations [[PERF-03]](lexicons/engineering.md#perf-03).
- For an unconstrained face-recognition claim, preserve non-frontal pose coverage that a frontal-biased collection detector would otherwise exclude [[MLDATA-09]](lexicons/ml-systems.md#mldata-09); in 1:N face identification, do not let detector false alarms add non-mated searches that dilute reported FPIR [[EVAL-19]](lexicons/ml-systems.md#eval-19).
- The watcher must sit outside the optimizer's reach [[OBS-09]](lexicons/engineering.md#obs-09); metrics on a rebalanced fantasy mix do not report the real one [[EVAL-03]](lexicons/ml-systems.md#eval-03).

Ask what the system under test could do to make this number better without doing anything better.

### 20. Match the reference to the conditions of the query

Every comparison has a query side and a reference side. The reference is almost always built first, under conditions convenient to collect. When the query arrives under different conditions, both sides can be honest and the metric can look fine — the silent failure lives in how the reference was constructed, not in a wrong quantity (Principle 4), a sample the measured party shaped (Principle 15), or evidence that arrived after a durable commit (Principle 13). Build or re-stratify the reference under the query's conditions before comparing; when you cannot, name the mismatch as a stratum rather than pool across it.

- Eyewitness lineup construction: for the tested human ski-mask condition, match candidates to that covering; the study used one mask type and does not establish transfer to other coverings or machine matchers [[HITL-15]](lexicons/ml-systems.md#hitl-15).
- Occluded face recognition: treat occlusion as spatial support and align corresponding parts before score [[EMB-11]](lexicons/ml-systems.md#emb-11), [[EMB-12]](lexicons/ml-systems.md#emb-12); gate real-occlusion claims on real-occlusion cells [[EVAL-28]](lexicons/ml-systems.md#eval-28).
- Training and serving construction: match training degradation to measured target statistics [[MLDATA-10]](lexicons/ml-systems.md#mldata-10); keep train and serve transforms identical [[SERVE-08]](lexicons/ml-systems.md#serve-08).
- Calibration and pair evaluation: fit thresholds on demographically matched non-mates [[CAL-04]](lexicons/ml-systems.md#cal-04); compare cohort false-negative rates within image-quality strata and report that false-positive differentials can persist in high-quality images [[CAL-01]](lexicons/ml-systems.md#cal-01); the measured slice is a query×enrolled cell [[EVAL-20]](lexicons/ml-systems.md#eval-20); choose models that win under production-like perturbation [[EVAL-06]](lexicons/ml-systems.md#eval-06).
- Statistical maps over time: collate both periods onto one stable set of spatial units before comparing, because redrawn boundaries change what is compared [[VIZ-28]](lexicons/interaction-ux.md#viz-28).

Before you trust the comparison, ask whether the reference was built under the conditions the query actually has. A filter that deletes the hard cells is the nearest shaped-sample neighbour and stays under Principle 15 — there the act is deletion by the pipeline owner, not mismatched reference construction.

---

## Reversibility and exposure

<a name="force-reversibility-and-exposure"></a>

What is expensive to undo, who controls it, and how much one failure can reach. Prefer the cheap reversible side; keep a second exit from hostile landlords; shrink grants; require two keys for high-impact acts.

Entry points:
[[CLM-02]](lexicons/business-marketing.md#clm-02) ·
[[BOOT-07]](lexicons/business-marketing.md#boot-07) ·
[[SECD-02]](lexicons/security.md#secd-02) ·
[[SECD-04]](lexicons/security.md#secd-04)

### 3. The safe side is cheap; the wrong side is not

When one option is reversible and the other is not, the reversible one is almost always underpriced at the moment you choose. The cautious version costs a softer verb or an hour now; crossing the line costs a rewrite, a recall, or a regulator later.

- Write the back-out steps, back up production state, and practice rollback before each release; restoring the backup loses post-deployment data, so for a destructive schema rollback, deploy a transitional application that works with both schemas and migrate only after that version no longer needs rollback [[RLSE-08]](lexicons/engineering.md#rlse-08); least privilege and human gates cost scope now, jailbroken broad scope costs everything it can reach [[SEC-04]](lexicons/security.md#sec-04), [[SEC-05]](lexicons/security.md#sec-05).
- Weak isolation and non-idempotent retries look free and bill later as integrity incidents [[DATA-17]](lexicons/engineering.md#data-17), [[DATA-13]](lexicons/engineering.md#data-13). High-stakes model output needs a human or external check [[AIPX-09]](lexicons/business-marketing.md#aipx-09).
- Freeze the shared trunk and train only an additive residual with an unadapted path kept live [[FM-09]](lexicons/ml-systems.md#fm-09); climb PEFT before full-weight change [[FM-07]](lexicons/ml-systems.md#fm-07), [[FM-05]](lexicons/ml-systems.md#fm-05).

Pay the small certain cost of the reversible side; treat "we can fix it after launch" as the expensive answer it usually is.

### 8. Assume a hostile landlord and keep a second exit

Any single point of external control eventually turns against you: platform, dependency, or model talked out of its instructions. Design as if the counterparty is adversarial, and keep the switch to an alternative cheap enough to actually throw.

- One ToS change can zero revenue overnight: multi-home masters and rails before you need to [[BOOT-07]](lexicons/business-marketing.md#boot-07); own rights, name, and a direct contact path first [[BOOT-01]](lexicons/business-marketing.md#boot-01).
- Rent distribution muscle under your own label rather than waiting on one platform's blessing [[GTM-04]](lexicons/business-marketing.md#gtm-04).
- Trust changes at every boundary: grant minimum scope [[SEC-01]](lexicons/security.md#sec-01), [[SEC-04]](lexicons/security.md#sec-04); wrap third parties behind adapters [[REF-15]](lexicons/engineering.md#ref-15).
- Name cut vertices and bridges: if this node dies, how many components remain? [[GRPH-05]](lexicons/graph-theory.md#grph-05).

No external party should get a hold on you that you cannot survive losing.

### 14. Grant the least privilege; minimize what a compromise reaches

Every component, credential, and role is a blast radius: whoever takes it inherits exactly what it could reach. The durable defense is not a taller wall but a smaller grant.

- Shrink the trusted computing base; grant least privilege by default [[SECD-02]](lexicons/security.md#secd-02).
- Bound agent tools so a jailbreak exercises little [[SEC-04]](lexicons/security.md#sec-04); run the app as a non-superuser [[PG-01]](lexicons/security.md#pg-01); split train / promote / serve rights [[SEC-16]](lexicons/security.md#sec-16).
- Avoid `GRANT … TO PUBLIC` and write-heavy ops roles beyond need [[PG-06]](lexicons/security.md#pg-06), [[PG-14]](lexicons/security.md#pg-14).

This is the inward twin of Principle 8: that principle keeps a second exit from external landlords; this one keeps every internal grant small. Assume the component will be compromised, and make sure that when it is, it holds almost nothing.

### 17. High-impact actions take two independent keys

Reversibility pricing (Principle 3) and small grants (Principle 14) still leave one gap: a single principal, honestly convinced or quietly compromised, can complete an action nobody else saw. Split the completion of any value-creating, value-destroying, or evidence-erasing action across two independent authorizers.

- Dual control for high impact: two independent authorizers or mechanism classes [[SECD-04]](lexicons/security.md#secd-04).
- A human approves before the agent side effect executes [[SEC-05]](lexicons/security.md#sec-05); high-stakes model output needs a check layer before accept [[AIPX-09]](lexicons/business-marketing.md#aipx-09).
- Expert adjudication stands between a low-agreement label and the training set [[HITL-07]](lexicons/ml-systems.md#hitl-07).

Some actions are too consequential for one key, however trusted its holder.

---

## Feedback and correction

<a name="force-feedback-and-correction"></a>

Where error surfaces, where it is corrected, and whether feedback can arrive before the next commitment. Externalize knowledge; design unknown as a first-class state; correct at the source; fail loudly and succeed quietly; bound step size by the loop that can catch it.

Entry points:
[[AGT-07]](lexicons/engineering.md#agt-07) ·
[[CAL-02]](lexicons/ml-systems.md#cal-02) ·
[[HAI-02]](lexicons/interaction-ux.md#hai-02) ·
[[AGT-15]](lexicons/engineering.md#agt-15) ·
[[REF-28]](lexicons/engineering.md#ref-28)

### 7. Write it where it outlives the person who knows it

Knowledge held only in a head, a session, or a founder dies at the next compaction or succession. Record it where the next reader will find it, before the person who knows it is gone.

- Persist plan, path verdicts, and model into notes at discovery [[AGT-07]](lexicons/engineering.md#agt-07); keep context, decision, and consequences in an ADR [[ARCH-07]](lexicons/engineering.md#arch-07).
- Correlation IDs turn post-mortems into greps [[OBS-03]](lexicons/engineering.md#obs-03); systemize taste into brand rules so the brand outlives the founder [[BRND-12]](lexicons/design-aesthetics.md#brnd-12).
- Orders need who/what/when/where/why [[OPS-13]](lexicons/planning.md#ops-13); handoffs carry intent, priorities, constraints, and forbidden moves [[NDM-07]](lexicons/epistemics.md#ndm-07).
- Single-head knowledge concentration is an operational hostage; require a backup path and a published store [[TEAM-17]](lexicons/planning.md#team-17).
- An approved engineering requirement and its basis go into the maintained formal record, not only a readable presentation copy [[WRIT-82]](lexicons/writing.md#writ-82).

A session, an author, and a founder all leave; only what they wrote down stays.

### 11. Unknown is a designed state

Forced certainty manufactures a false identity, a false merge, a misleading progress bar, and a silent failure. *Unknown*, *pending*, *disputed*, and *insufficient-evidence* must exist as first-class states, or the system fabricates an answer where it owed a question.

- Below-threshold action is a valid result [[CAL-02]](lexicons/ml-systems.md#cal-02); route low-agreement items to experts instead of forcing a machine call [[HITL-07]](lexicons/ml-systems.md#hitl-07).
- Refuse vague words that fake crisp odds [[FORE-01]](lexicons/epistemics.md#fore-01).
- Prefer silence to wrong advice [[AIPX-07]](lexicons/business-marketing.md#aipx-07); competence has a too-tough basket [[STRAT-03]](lexicons/business-marketing.md#strat-03).
- Partial knowledge that narrows a range is still measurement, not an excuse for fake certainty or fake ignorance [[MEAS-02]](lexicons/epistemics.md#meas-02).

When the evidence runs out, ship the designed unknown, not a confident wrong answer.

### 12. Correction must reach the source

Changing a label without changing the cluster, model input, rule, or state transition that produced it only hides the error until the next recomputation restores it. A correction is real only when it reaches the thing that was wrong.

- Write human corrections to the training store and retrain or adapt soon enough that the same model error is not presented again [[HAI-02]](lexicons/interaction-ux.md#hai-02); feed fresh labels into the next training run [[HITL-01]](lexicons/ml-systems.md#hitl-01).
- For live near-neighbor correction cascades, fold case-distinguishing features into one model or use a separate model for the new case; permit a temporary migration shim only with a hard sunset and dual-run metrics [[SERVE-04]](lexicons/ml-systems.md#serve-04); a wrong derived store is repaired by reprocessing the log, not hand-patching rows [[FLOW-06]](lexicons/engineering.md#flow-06).
- Mirror fields drift until they lie [[REF-09]](lexicons/engineering.md#ref-09); publish from the same transaction as the state change [[DOM-06]](lexicons/engineering.md#dom-06).

Edit the source, or you have edited nothing.

### 16. Fail loudly, succeed quietly

An outcome channel earns trust in both directions: failure must be impossible to miss, and success must be impossible to confuse with noise. Chatter on the success path buries the one line that matters; a swallowed failure converts an error into a silent lie.

- Diagnostics to stderr, silent success on stdout [[AGT-15]](lexicons/engineering.md#agt-15); fail noisily and early [[AGT-10]](lexicons/engineering.md#agt-10); *The Pragmatic Programmer: Your Journey to Mastery* says to terminate as soon as an impossible event makes further execution suspect [[RLSE-05]](lexicons/engineering.md#rlse-05).
- Verify end-to-end telemetry freshness with uniquely tagged synthetic events against a freshness target [[OBS-08]](lexicons/engineering.md#obs-08). ERROR that does not require action trains people to ignore ERROR [[OBS-04]](lexicons/engineering.md#obs-04).
- Empty catch blocks convert failures into silent lies; handle, translate, or rethrow [[REF-37]](lexicons/engineering.md#ref-37).
- Localize verify cues to the output at risk rather than a standing banner that habituates [[HAI-13]](lexicons/interaction-ux.md#hai-13), [[PERC-07]](lexicons/interaction-ux.md#perc-07).

A channel where success chatters or failure whispers is not reporting the system.

### 19. Step size is bounded by the feedback that can catch it

Principle 13 gates a single commitment on prior evidence. This one governs the increments after the gate: each step's size and exposure stay inside what a real feedback signal can catch before the next step commits.

- Plans whose forecasts outrun any near feedback channel lose to small replaceable steps [[REF-28]](lexicons/engineering.md#ref-28).
- Cheapest artifact that can falsify the riskiest assumption goes first [[PROD-03]](lexicons/business-marketing.md#prod-03).
- Shadow, then canary, then cutover [[AIPX-06]](lexicons/business-marketing.md#aipx-06); roll a service out gradually to controlled subsets, monitor and measure its effects, and roll it back if needed [[RLSE-07]](lexicons/engineering.md#rlse-07).

Never let the increment outgrow the loop that would catch it failing.

---

## When two rules point the other way

Not every cross-source pair agrees. Some rules pull in opposite directions, and the lexicons keep those pairs on purpose. Averaging two good opposed rules produces a rule worse than either parent. Resolution means finding the partition on which each rule is fully right.

- A **surface** partition separates where each rule applies: workbench reading order versus marketing shout; phased rollout versus launch stunt; recognition under time pressure versus scored probabilities when the validity-feedback gate fails.
- An **object** partition gives each rule its own asset: durable brand mark versus rotating campaign language; mission values versus empirical forecasts; YAGNI for single consumers versus structure that reduces real thinking cost.
- A **sequence** partition orders them in time: novelty may lead the first exposure while claim language stays on the safe side throughout.

A pair no partition can split is a genuine judgment call: it stays at tier J and gets decided in context, with the reasoning recorded in an architecture decision record [[ARCH-07]](lexicons/engineering.md#arch-07).

## When two rules watch the same failure

An amplification is the opposite of a tension: two sources watch one failure from different lanes, one naming the upstream cause and the other the downstream check. These stay wired rather than partitioned.

- Value-first palette [[COL-04]](lexicons/design-aesthetics.md#col-04) makes WCAG contrast [[A11Y-01]](lexicons/accessibility.md#a11y-01) pass by construction.
- Undesigned-state audit [[RLSE-04]](lexicons/engineering.md#rlse-04) and the accessibility state matrix [[A11Y-24]](lexicons/accessibility.md#a11y-24) read the same screen states from two threat models.
- Trust at every crossing [[SEC-01]](lexicons/security.md#sec-01) and similarity-chaining failure [[GRPH-18]](lexicons/graph-theory.md#grph-18) refuse one shortcut from two lanes.
- Articulation points [[GRPH-05]](lexicons/graph-theory.md#grph-05) detect the bridge; multi-home [[BOOT-07]](lexicons/business-marketing.md#boot-07) is the response before the landlord turns.

## How these earn their place

A convergence is the mechanism by which a claim earns a place in this file. A rule enters a lexicon with its source as provenance and its tier set by how hard the rule binds — **B**locker, **S**hould, **J**udgment — not by how much evidence stands behind it: as of 2026-08-15 the mean number of sources per rule is the same at all three tiers. What climbs is the *claim*, not the tier: when a second, unrelated source is found to have reached it independently, that arrival is recorded here. This file is not a summary of the lexicons: it is the record of those independent arrivals, and the index a reader uses to pull a rule's cross-domain siblings into a decision that only named one domain.

On 2026-10-03, the W13 writing-tropes ingest (`efafbf7a794c` → `ca0c65c8c078`) yielded `new_asserted_pairs=0`, `new_wired_pairs=0`, `new_prose_only_pairs=0`, and `new_wiring_rate=not applicable`.

---

## Agent application

<a name="agent-application"></a>

Compact protocol for tools and reviewers. Human orientation is above; do not treat this section as a second essay.

1. Route the artifact and keep only rules whose triggers are observed.
2. For each retained rule, find the numbered principles that cite it and load sibling rules from unrelated domains.
3. Ask whether a sibling exposes the same mechanism in a form the artifact's native vocabulary concealed. Count independent economies, not repeated rows from one author.
4. If two applicable rules oppose, partition by surface, object, or sequence. Do not average them. If they watch one failure at different stages, keep both as an amplification.
5. When several retained IDs share a mechanism, open matching cards in the reasoning tree. Cards deepen the decision; they do not replace rows.
6. State the action, evidence, disconfirmer, and next feedback boundary; cite the rule IDs. Stop when the decision is supported or explicitly deferred.

Forces are navigation groups only. Wrong proxy is not a shaped sample; least privilege is not dual control; falsification is not evidence timing; a commit gate is not step size. Open the principle that matches the failure you actually see.
