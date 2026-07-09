# Building Machine Learning Powered Applications (Ameisen) — distilled

> **Source**: Emmanuel Ameisen, *Building Machine Learning Powered Applications: Going from Idea to Product* (O’Reilly, 2020) · extracted from `../building-ml-powered-applications.txt` · distilled 2026-07-09 (spec v1)
> **Contributes**: The sharpest **idea→product decision-rule pipeline** for ML-powered applications in this directory: **when ML is not the answer**, **simplest-model-first ladder** (heuristic → simple supervised → complex generative), **product metrics vs model metrics**, **data flywheel** (weak labels, user override, active labeling), **error-analysis-driven iteration** (top-k, slices, feature importance), **deploy/monitor for drift**, and **human-in-the-loop** patterns (confidence gating, feedback, filtering models). Case study is an ML writing editor — directly analogous to an AI description / alt-text service. Named concepts: **strawman baseline**, **impact bottleneck**, **be the algorithm**, **weak labels**, **offline/model metrics**, **guardrail metrics**, **distribution shift / feature drift**, **data leakage**, **top-k method**, **filtering model**, **shadow mode**, **feedback loops**, **dual-use**, **model cards**, **calibration**.

## Chapter map

- ch-0 — ML process overview: four stages from idea to production
- ch-1 — From product goal to ML framing: when ML, which paradigm, data ladder
- ch-2 — Create a plan: product vs model metrics; freshness, speed; simple start
- ch-3 — First end-to-end pipeline: heuristic MVP; UX vs model bottleneck
- ch-4 — Acquire and iterate datasets: quality rubric; label yourself; flywheel seeds
- ch-5 — Train and evaluate: simple model; splits; beyond accuracy; error analysis
- ch-6 — Debug ML: wiring → capacity → generalization
- ch-7 — Classifiers → recommendations: precision-first guidance; feature UX
- ch-8 — Deploy considerations: bias, feedback loops, context, adversaries
- ch-9 — Deployment options: streaming vs batch vs on-device
- ch-10 — Safeguards: input/output checks; fallbacks; user feedback loops
- ch-11 — Monitor and update: drift, product metrics, shadow mode, A/B

---

## ch-0 — ML process overview: four stages from idea to production {#ch-0}

**Practical ML** = identify a product problem that benefits from ML *and* deliver a working solution. Training a model on a dataset is a small fraction of the work (~a tenth); product framing, data, iteration, validation, and robust deploy dominate.

Four successive stages (book structure):

1. **Identify the right ML approach** — success criteria, data availability, simplest framing that can ship.
2. **Build an initial prototype** — end-to-end *without* ML first; decide whether ML is needed; start gathering data.
3. **Iterate on models** — alternate error analysis and implementation; speed of this loop = ML development speed.
4. **Deploy and monitor** — deployment choice, safeguards, drift detection, update triggers.

**Case study shape:** ML-assisted writing (help users write better questions) — self-standing product, abundant text data, clear human-in-the-loop UX. Transfer to description/alt-text: same loop (heuristic quality checks → classifier/score → suggestions → deploy with fallbacks).

| Decision | Rule | Why |
|---|---|---|
| Project start | Optimize **iteration loop speed**, not first-model SOTA | Failures teach; slow loops kill products |
| Scope of “ML work” | Budget mostly for data, product metrics, error analysis, deploy | Model training alone does not ship value |

## ch-1 — From product goal to ML framing {#ch-1}

ML learns patterns from data (probabilistic); traditional code runs deterministic procedures. **Use ML when you cannot write a manageable set of deterministic rules** you could confidently maintain. Taxes, regulated calculations, pure policy engines → **not** ML. Cat-vs-dog from pixels → ML.

**Start from a concrete business problem**, not from “interesting models.” Be open to non-ML solutions. Evaluate approaches by **product fit**, not research novelty.

### Framing loop

1. **Frame product goal in an ML paradigm** — one product goal has many ML formulations of different difficulty.
2. **Evaluate feasibility** — prefer simplest framing; judge by data availability + known working models.

**Model taxonomy (supervised preferred when labels exist):**

| Paradigm | Product shape | Risk note |
|---|---|---|
| Classification / regression | Score, route, flag, rank | Easiest to validate |
| Knowledge extraction | Structure unstructured text/images | Good intermediate representation |
| Catalog organization | Search, recommend, similar-items | Often engagement-metric traps (ch-8) |
| Generative | Translate, rewrite end-to-end, caption | Highest data/latency/maintenance cost |

**Data availability ladder** (best → hardest): labeled → **weakly labeled** → unlabeled only → must acquire. Most real products start with weak labels. **Datasets are iterative** — imperfect data is fine for v1.

### Simplest-model-first ladder (named path)

For writing assistant (and description services):

| Level | Approach | Data need | When to use |
|---|---|---|---|
| **0 — Be the algorithm** | Manual edit + domain heuristics (style guides, readability rules) | None / tiny sample | Always start here |
| **1 — Heuristic baseline** | Rules on length, structure, tone features | Unlabeled corpus to validate rules | First shippable product |
| **2 — Simple supervised** | Classifier good/bad + inspect features as advice | Weak labels (votes, CTR, acceptance) | When heuristics plateau |
| **3 — End-to-end generative** | Seq2seq bad→good rewrite | Paired rewrites (expensive) | Only with data + ops budget |

**End-to-end generative is the last rung**, not the first: rare paired data, long-context limits (2020: weak beyond paragraph; re-check SOTA), slow autoregressive latency, hard to train/maintain.

**Be the algorithm** (Rogati / Munro / Ameisen): spend an hour solving the task manually before automating. Look at inputs/outputs; rank by frequency; often label top-100 covers ~80% of phrases (Jawbone meal-logging example).

**Strawman baseline** (Rogati): replace the model with the dumbest useful action (e.g. suggest user’s previous action). If product is dead at strawman performance, **do not invest in modeling**. Tweet/press-release the outcome before building — if only “cool model” survives a null result, wrong project.

**Impact bottleneck:** replace model with something simple and debug the whole pipeline. Frequently the issue is product UX, data plumbing, or wrong problem — not accuracy.

Scenario → lesson:
- Team spends months on seq2seq alt-text; no paired rewrite corpus; latency 2s+ → no ship → **lesson:** start classifier/score + heuristics; generative only after flywheel yields pairs.
- Chatbot demo wows; strawman “show FAQ top link” already satisfies 70% of tickets → **lesson:** ML not the answer for v1.

## ch-2 — Create a plan: metrics and simple start {#ch-2}

**Most projects fail by producing good models that don’t help the product**, not by modeling difficulty. Misalignment of **product metrics** and **model metrics** dooms projects from day one.

### Four performance categories

| Category | What it measures | Rule |
|---|---|---|
| **Business / product metrics** | User value: CTR, accept rate, task success, retention | **Only metrics that ultimately matter** |
| **Model / offline metrics** | Precision, recall, AUC, BLEU, etc. without users | Proxy; must **correlate** with product metrics |
| **Freshness** | How fast labels/world change | Sets retrain cadence + data-acquisition cost |
| **Speed** | End-to-end latency (preprocess + model + post) | Product shape (submit vs live-as-you-type) |

**Product metrics** are separate from model metrics. They may be multiple: one primary + **guardrail metrics** that must not degrade (e.g. raise CTR without shortening session length).

**Offline metrics** exist because you cannot measure usage before deploy. Choose modeling approaches so that a *sufficient* offline bar is achievable. Example: next-word prediction needs near-perfect word accuracy to help CTR; **category prediction of search intent** needs only one-of-N catalog accuracy — much easier product win.

**Product redesign to ease modeling** (observable levers):

- Omit suggestions below confidence threshold.
- Show top-k candidates, not only top-1.
- Label experimental state; collect explicit feedback.
- Prefer high-**precision** over high-recall for advice (wrong advice costs trust).

**Optimization metric ≠ product metric.** HTML-from-sketch optimized cross-entropy token match; product needed visual similarity (BLEU better proxy). Always ask: can a result score poorly on training loss but still delight users?

**Design for imperfect models.** If usefulness requires perfect accuracy (pill dosage from photo at medical risk), redesign product (human confirm, constrained set) or don’t ship.

**Freshness / distribution shift:** models need training data similar to production inputs. Rain→traffic model trained in dry season fails in winter rain. Translation of dead languages: low freshness; search/trends: high. Estimate retrain cost yearly/monthly. **Popularity can feed the flywheel** (rate buttons → new train set) only after product is useful.

**Speed:** submission UX can tolerate ~2s; live-as-you-type needs ≪1s. Complex models cost latency; plan the ladder against the product interaction mode.

### Always start simple

- Simplest model that could address requirements.
- End-to-end prototype including training **and** inference pipelines (shared preprocess).
- Judge by **product goal**, not only optimization loss.
- Small incremental improvements over “perfect model in one go.”

**Domain expertise:** learn from experts; then EDA + hand-label examples yourself to invent heuristics.

**Stand on shoulders:** reproduce open model+dataset first; transfer to domain data; abstract by **input/output types** (image→sequence: captioning architectures for GUI→code).

Scenario → lesson:
- Team optimizes BLEU/F1 for alt-text while product KPI is editor acceptance rate → ships model no one accepts → **lesson:** instrument accept/override first; offline metric must track acceptance.
- Live typing assistant forces 50ms budget; team trains 1B generative model → product unusable → **lesson:** match model class to latency contract.

## ch-3 — First end-to-end pipeline: heuristic MVP {#ch-3}

**First iteration is lackluster by design** — full pipeline so you can find the **impact bottleneck**. Start with **inference** pipeline + rules (no training yet).

**MVP rule:** simplify product surface and ML approach together. CLI or thin web form is enough.

**Test two axes independently:**

1. **User experience** — if the model were perfect, is presentation useful? (actionable suggestions vs dump of scores)
2. **Modeling results** — do heuristics/model correlate with quality?

If UX is poor, **improving the model is not helpful**. Product-side fix: actionable edits, highlight spans, single score + recommendations. Model-side fix: bias, slice failures, wrong labels.

Scenario → lesson:
- Prototype returns Flesch score + adverb counts; users cannot act → product dead despite “metrics” → **lesson:** ship advice format before deepening model.
- Research-paper accept model returns only P(accept) → users want *what to change* → extract features as guidance (ch-7).

## ch-4 — Acquire an initial dataset: iterate data as product {#ch-4}

In research, datasets are fixed benchmarks. **In product ML, the dataset is part of the product** — choose, update, augment as primary work. Most practitioners over-invest in models and under-invest in data; **bias yourself toward looking at data**.

**Start small:** subset that fits local memory; dozens of images for a side project. Scale after strategy is clear.

**Insights vs products:** insight = “fraud peaks Thursday from Seattle.” Product = feature from time+IP that *blocks* fraud on future logins. Need confidence patterns hold in future; quantify train vs production gap.

### Data quality rubric (summary)

| Lens | Questions |
|---|---|
| Format | Clear I/O? Reproducible preprocessing? Same steps in production? |
| Quality | Missing fields? Measurement error? Labels you agree with? |
| Quantity / distribution | Enough examples? Class balance? Absent classes? |

**Start with weak labels** (upvotes, skips, CTR) knowingly imperfect; decide after error analysis whether label carries enough signal.

### Robert Munro labeling economics (numbers to keep)

- ~**1,000** labeled examples of rarer class: enough signal to decide whether approach works.
- ~**10,000**: start trusting model confidence more.
- Last segment of the **performance-vs-data curve** estimates value of more labels — usually **labeling beats model fiddling**.

**Active data strategies:** uncertainty sampling; train **error model** (correct vs incorrect) on unlabeled pool; train **labeling model** (already labeled vs not) to find dissimilar examples. Always **random sample the test set** to avoid over-focusing on one failure mode (basketball articles).

**Validate with business metrics and drift** once deployed (see ch-11).

**Flywheel seed design (product decision):** instrument weak labels and overrides early (accept suggestion, edit after, publish, upvote). Without instrumentation, no flywheel.

### Data flywheel for an AI description service (mechanism map)

| Product event | Label type | Downstream use |
|---|---|---|
| Editor accepts suggested alt text | Strong positive weak label | Train accept classifier / ranker |
| Editor edits then saves | Pair (draft → final) | Eventual generative fine-tune data |
| Editor rejects / clears | Negative | Hard-negative mining |
| Published asset performance (if measurable) | Delayed product metric | Guardrail / refresh trigger |
| Human QA sample audit | Gold labels | Test set + slice benchmarks |

**Flywheel preconditions:** (1) product useful enough that events fire; (2) logging ties event to model version + features; (3) privacy/consent allows reuse; (4) feedback loops controlled (don’t only train on blander text that is easiest to accept).

Scenario → lesson:
- Nine support categories, one example each → generate templated data or expand collection before complex models.
- Stack Overflow score used as quality proxy; ignores author popularity → restrict community / split by author later (ch-5).
- Description service ships with no accept/edit logs → six months later cannot retrain on real use → **lesson:** logging schema is a v1 product requirement, not a v2 nice-to-have.

## ch-5 — Train and evaluate: simple models and error analysis {#ch-5}

### Simplest appropriate model

Do **not** grid-search every architecture. Prefer models that are:

1. **Quick to implement** (popular libraries, tutorials, team support)
2. **Understandable** (feature importances for iteration)
3. **Deployable** (latency, concurrency, train-time vs freshness)

Score candidates on those three axes for *your* domain; update the scorecard as tooling evolves.

Match model class to data patterns (scale-invariant trees, linear when linear, temporal models for series, CNNs for local patterns).

**Default first model for many tabular/text products:** random forest / gradient-boosted trees / logistic baseline — resilient, inspectable.

### Splits and data leakage

Hold-out **validation** (tune) + **test** (final, rarely touch). Typical 70/20/10 scales with data size.

**Data leakage** = train-time information unavailable in production → inflated metrics, production crash. Common forms:

| Leak | Mechanism | Fix |
|---|---|---|
| Temporal | Random split on forecasting | Split by time |
| Sample contamination | Same student/author/user in train and test | Group split |
| Snapshot leakage | Features include post-event state (bookings count after click) | Point-in-time correct features / versioned snapshots |

**Murphy’s law of ML:** the more pleasantly surprised you are by test metrics, the more likely a bug or leak.

### Beyond aggregate metrics

Aggregate accuracy/F1 is incomplete (class imbalance, slice failures). Use:

- **Confusion matrix** — empty columns = never-predicted class; critical rare events.
- **ROC + product threshold lines** — fix max FPR from ops capacity; optimize TPR under that constraint (writing advice: cap harmful recommendations, e.g. FPR ≤10%).
- **Calibration curve** — does 80% score mean ~80% positive? Needed if UI shows scores or confidence gates.
- **Dimensionality reduction colored by error** — clusters of failure.
- **Top-k method** — for each class: k best, k worst, k most uncertain (train + val). Uncertain train → conflicting labels; uncertain val → missing train coverage.
- **Feature importance / LIME / SHAP** — unexpected top features often = leakage (email topic codes).

**Iteration rule:** identify *specific* failure reasons; do not blind hyperparameter thrash.

Scenario → lesson:
- Alt-text model 92% aggregate accuracy; fails on dark-skinned faces / product photos with text → **lesson:** slice metrics before deploy (ch-8 inclusive performance).
- Top-k worst cases are “not a question” posts → add question-mark feature → precision rises.

## ch-6 — Debug ML: wiring → capacity → generalization {#ch-6}

ML can **execute without errors and still be wrong**. Debug order:

1. **Wiring** — few examples flow end-to-end; model can memorize them; visualize after load/clean/features/format/output; encode as tests.
2. **Capacity / optimization** — model fits training set; loss curves; wrong model class vs too simple.
3. **Generalization** — validation performance; fix leakage, overfitting (regularization, augmentation, dataset redesign), or reframe task if impossible.

**Tests vs production input checks** (ch-10): tests use known fixtures on code change; checks gate live control flow.

If task has no predictive signal (random→random), stop — return to ch-1 framing.

## ch-7 — Classifiers for recommendations: guidance UX {#ch-7}

**ML loop:** hypothesis → pipeline → error analysis → next hypothesis. Close the loop by turning classifiers into **actionable guidance**.

### Recommendation methods (accuracy ↔ latency trade-off)

| Method | Needs model at inference? | Strength | Weakness |
|---|---|---|---|
| Feature statistics vs class means | No | Fast, robust | Generic advice |
| Global feature importance prioritization | Optional offline | Focuses user on high-impact levers | Still aggregate |
| Calibrated model score | Yes (once) | Progress signal / trust | Needs calibration |
| Local explanations (LIME etc.) | Yes (~100s of evals) | Instance-specific | Latency (often ~2s) |

**Chris Harland (Textio) product rules for guidance:**

- **Precision ≫ recall** for advice — wrong advice is expensive; users generalize past advice to future inputs.
- Recommendations must be **consistent** as user edits (don’t flip “write 200 more words” after they write 150).
- Features must be **human-understandable** (“shorten these 3 sentences” not “reduce stop words 50%”).
- Guidance moves user through **feature space**; path may pass through worse intermediate points — design UX for that.
- Log predictions, features, **user overrides**; ultimate metric is delayed customer success.
- “Remove stop words 50%” underused → make actionable (highlight words).
- ~**1,000 domain documents** often enough to start; easy experiments; most product changes are null — ship small.

**Model selection for guidance product:** prefer slightly lower aggregate precision if **calibration + explainable features + speed** improve. Book case: dropped TF-IDF thousands of dims; 30 interpretable features; precision 0.60 vs 0.62 but far better calibration and UX → **ship v3**.

Scenario → lesson:
- Description service shows raw token importances (“increase ‘the’”) → users ignore → **lesson:** map model features to human edits (length, structure, missing who/what/where).
- LIME on every keystroke → 2s lag → force submit button or precompute feature-stat advice for live mode.

## ch-8 — Deploy considerations: ethics, bias, feedback loops {#ch-8}

Before deploy answer: how data collected; assumptions; representativeness; misuse; intended scope.

### Data ownership

Legal + moral: collection rights, informed permission, storage/access/deletion. **Limit data collected** → limit breach liability. GDPR-class rules are era-surface; mechanism is **minimize + document consent**.

### Bias

Assume datasets are biased. Sources: measurement error, representation (face datasets), access (English-heavy NLP). **Test set must encode product goals** (all genders for diagnosis). Removing a sensitive attribute is **not** enough (proxies: ZIP, income). Use explicit fairness constraints (e.g. **p% rule**) when required — keep the attribute for *measurement*.

### Feedback loops

User follows recommendation → more training mass for same recommendation → runaway (cat videos only). Clicks train clickbait. Power users dominate.

**Rules:**

- Prefer labels closer to true satisfaction (**watch time** over raw click) — still engagement can be unhealthy; question whether max engagement is the goal.
- Break loops with exploration, regularization toward diversity, holdout evaluation (ch-11 counterfactuals).
- For description services: optimizing “edit acceptance” alone may train bland/safe text; add quality guardrails and human review samples.

### Inclusive performance

Never ship on aggregate gain alone. New model 92% vs 90% but collapses on women 40+ → **block deploy**; rebalance data.

### Context / model cards

Tell users training domain and limits (“trained on Writing Stack Exchange; reflects that community”). Share confidence when possible.

### Adversaries and dual-use

Fraud: update models + features; rate-limit probing. Dual-use: voice clone, face ID → surveillance. No universal policy — if dual-use high, raise friction, limit release, document intended use (OpenAI GPT-2 delay as historical example; re-evaluate modern release norms).

Scenario → lesson:
- Recommend alt-text accepted most often → trains shortest generic captions → **lesson:** guardrail metrics for specificity; sample human review.
- Photo tagger fails on African American faces (2015) → **lesson:** representative test slices mandatory pre-ship.

## ch-9 — Deployment options {#ch-9}

Choose by **latency, hardware, network, privacy, cost, complexity**.

| Pattern | When | Trade-off |
|---|---|---|
| **Streaming API** | Need result at request time; features only now | Scales with QPS; ops automation |
| **Batch** | Features known ahead (lead scoring, morning digest) | Efficient; stale if too infrequent |
| **Hybrid** | Cache batch + on-demand miss | Complexity of two pipelines |
| **On-device** | Offline, privacy, server cost | Smaller models; accuracy cost; engineer quantize/prune |
| **Browser (e.g. TF.js)** | No install; client compute | Download size; bandwidth |
| **Federated** | Personalization without centralizing raw data | High complexity; rare for early products |

**Rule:** start streaming or simple batch for prototype; move client-side only when latency/privacy/cost prove it. If on-device inference time > server round-trip, prefer server (unless offline required).

## ch-10 — Safeguards and human-in-the-loop {#ch-10}

**Fault tolerance:** models *will* fail; engineer graceful failure (same as distributed systems).

### Control-flow safeguards

1. **Input checks** (live): required features present; types; ranges → else error or **heuristic fallback**.
2. **Output checks:** plausible range; actionable; non-destructive → else fallback.
3. **Model confidence gate:** if calibrated, hide low-confidence suggestions.
4. **Filtering model:** cheap binary classifier “will main model fail?” trained on main model’s errors — skip expensive inference; Google Smart Reply ~11% trigger rate → order-of-magnitude infra save. Need filter block rate > filter_time/main_time.

**Always keep the heuristic** — it is the production fallback.

Simpler backup models often err on **different** examples than complex ones → useful cascade.

### Performance engineering (decision-relevant)

- Horizontal scale; separate GPU inference from app tier if needed.
- Cache identical inputs (LRU); cache catalog embeddings for search.
- Version **model + dataset + app pipeline** on every prediction for reproducibility.
- DAGs (Airflow/Luigi) when retrain is production-critical — not for first prototype.

### Ask for feedback (HITL product design)

| Type | Example | Use |
|---|---|---|
| Explicit | “Was this useful?”; editable category (Mint) | Clean labels; trust |
| Implicit | Click, apply suggestion, publish, dwell | Weak labels at scale |
| Override | User edits model field | High-value train + monitoring signal |

Design UI so correction is natural, not a survey. Implicit signals aggregate-only (people misclick). Logging enables flywheel **and** feedback-loop risk — couple with ch-8.

**Stitch Fix pattern:** data scientists own full lifecycle; platform builds abstractions; present model as **feedback loop**, not read-only oracle; ownership drives simple robust models.

### Human-in-the-loop pattern catalog

| Pattern | Product behavior | When |
|---|---|---|
| **Confidence omit** | Hide suggestion if p < threshold | Calibrated classifier; low-stakes assist |
| **Confidence soften** | Strong UI if p>0.9; quiet if 0.5–0.9; omit if <0.5 (Rogati) | Graded trust UX |
| **Human override** | Editable field; model proposal default | Editors, alt-text, moderation assist |
| **Human confirm** | Block action until human OK | High-cost errors (legal, medical, brand) |
| **Filtering / trigger model** | Only run expensive model on suitable subset | Cost + quality gate |
| **Cascade** | Complex model → simple model → heuristic | Uncorrelated errors |
| **Explicit feedback** | Thumbs / “useful?” | Sparse but clean |
| **Implicit feedback** | Apply, publish, dwell, share | Scale; noisy |

**Rule:** pick the HITL pattern from **cost of wrong output**, not from model vanity. Description services for CMS editors → override + confidence omit. Fully automated publish to public site without review → higher bar + sampling QA.

Scenario → lesson:
- Description API returns garbage on empty/HTML-only input → model still scores → **lesson:** input validation before model.
- No override UI → cannot measure acceptance or retrain → **lesson:** ship edit/override day one.
- Team removes confidence threshold to “show more AI” → trust collapse from bad tips → **lesson:** empty is better than wrong for guidance.

## ch-11 — Monitor and update models {#ch-11}

Monitoring answers: when to refresh; when under attack; whether product still works.

### What to monitor

| Layer | Signals |
|---|---|
| Infra | Latency, error rate, resources |
| **Feature drift** | Mean/var of key features vs training baseline |
| Output distribution | Sudden shift in score/class mix |
| **Product metrics** | CTR, accept rate, overrides, retention |
| Abuse | Login/attempt spikes; anomaly models |

**Action on predictions biases observed labels** (blocked fraud never observed) → **counterfactual / random holdout** where ethically allowed; not for medical random-harm cases.

### CI/CD for ML

| Stage | Safety | Info |
|---|---|---|
| Offline test set | Highest | Lowest ecological validity |
| **Shadow mode** | High (users still on old model) | Production inputs; no user reaction to new model |
| Live A/B | Lowest | Full truth including behavior |

**A/B rules:** similar cohorts; precommit size/duration; no peeking (repeated significance error); check **guardrails** and **segments** (overall CTR up, segment collapse → don’t ship). Multiarmed bandits when many variants / continuous allocation.

**Refresh trigger:** retrain when monitored accuracy/product metric crosses threshold — not only calendar.

**Granular feedback UX** (word-level apply) multiplies labels vs single share button — design for flywheel.

Scenario → lesson:
- Model metrics green; accept rate sinks → **lesson:** product metrics are source of truth.
- Retrain weekly blindly without shadow → regressions ship → **lesson:** shadow then canary.

---

## Decision rules (summary)

| Trigger (observable) | Rule | Rationale | Src |
|---|---|---|---|
| Problem solvable with maintainable rules | **Do not use ML** | Uncertainty + cost without need | ch-1 |
| New ML feature idea | **Ship heuristic / strawman first** | Derisk product; find impact bottleneck | ch-1, ch-2, ch-3 |
| Strawman product already dead | **Kill or redesign product**, don’t train deeper | Model success ≠ product success | ch-1 |
| Multiple ML framings possible | **Pick simplest paradigm with available data** | Supervised class/score before generative | ch-1 |
| Offline metric improves, product metric flat | **Treat offline as proxy only; re-align** | Good models can fail products | ch-2 |
| Advice / guidance UX | **Optimize precision + calibrated score + human features** | Wrong advice destroys trust | ch-2, ch-7 |
| Latency contract (live vs submit) | **Match model class to budget** | Generative/LIME may force submit UX | ch-2, ch-7, ch-9 |
| First dataset | **Start small, weak labels OK, iterate data as product** | Data > model fiddling early | ch-4 |
| Pleasant surprise on test metrics | **Hunt leakage before celebrating** | Murphy’s law of ML | ch-5 |
| Aggregate metrics only | **Slice, confusion, top-k, importance** | Inclusive failures hide in averages | ch-5, ch-8 |
| Model errors inspected | **Next work from error analysis**, not random architecture search | Loop speed = progress | ch-5–ch-7 |
| Deploy candidate | **Input/output checks + heuristic fallback + confidence gate** | Models fail; fail closed to safe path | ch-10 |
| Production live | **Monitor product metrics + feature drift; shadow then A/B** | Offline insufficient | ch-11 |
| Engagement label (clicks) | **Prefer satisfaction-correlated labels; watch feedback loops** | Clickbait / monoculture | ch-8 |
| User can correct model | **Log overrides as gold weak labels** | HITL flywheel | ch-7, ch-10 |
| Live typing vs submit UX undecided | **Choose interaction before model family** | Latency budget selects architecture | ch-2, ch-9 |
| New model +2% offline, segment collapse | **Block ship on inclusive/guardrail fail** | Aggregate hides harm | ch-8, ch-11 |
| Expensive model on every request | **Trigger/filter before heavy inference** | Cost and quality | ch-10 |
| No model/dataset/app version on logs | **Version the full inference triple** | Cannot reproduce or debug prod | ch-10 |

---

## Anti-patterns

| Name | Detection cues | Why it fails |
|---|---|---|
| **ML-first solutionism** | “We need deep learning” before product metric | Wrong problem; delay |
| **End-to-end from day one** | Seq2seq before heuristic/classifier | Data and latency wall |
| **Metric laundering** | Report only train loss / accuracy | Product still fails |
| **Perfect-model product design** | UX assumes zero errors | Dangerous or useless in wild |
| **Black-box worship** | No feature importances, no top-k | Cannot iterate or detect leak |
| **Random split on grouped/temporal data** | Same user in train/test; future in train | Leakage; false confidence |
| **Aggregate-only ship gate** | +2% accuracy, no slices | Inclusive failure / PR disaster |
| **Click-maximization without guardrails** | CTR sole KPI | Feedback loops, clickbait |
| **No fallback path** | Model error → blank or crash | Brittle production |
| **Calendar retrain only** | Ignore drift dashboards | Silent staleness |
| **Peeking A/B** | Stop test at first significant blip | False winners |
| **Survey-only feedback** | No in-flow override | Starves flywheel |
| **Remove sensitive attr = fair** | Drop gender, keep ZIP | Proxy bias remains |
| **Silent dual-use** | Ship general face/voice model with no policy | Abuse externalities |

---

## Applicability & exemptions

### Where the book is strongest (this monorepo)

- **AI description / alt-text / writing assistance** — nearly the case study; hierarchical ladder, precision guidance, accept/override flywheel map 1:1.
- Any **B2B SaaS ML feature** with human review: moderation assist, support routing, search ranking with editors.
- Teams that over-index on model architecture and under-instrument product metrics.

### Era correction (2020 → 2026)

| 2020 surface | Transferable mechanism | Modern note |
|---|---|---|
| Seq2seq slow / weak long context | Generative last; latency & data cost first | LLMs easier to prototype; **still** start with eval, product metric, fallbacks — cost/latency/safety remain |
| LIME default local explainer | Instance-level sensitivity for advice | SHAP, integrated gradients, LLM rationales — same product rule: explanations must be actionable |
| TF.js / TF Lite examples | Client-side when privacy/offline dominates | Stack choices change; decision factors don’t |
| GDPR as new constraint | Minimize data + consent | Broader global privacy regimes; same ownership checklist |
| “1k–10k labels” heuristics | Label ROI curve | Foundation models may shift sample efficiency — **re-estimate curve**, don’t drop error analysis |
| OpenAI GPT-2 release delay anecdote | Dual-use review before broad release | Policy landscape moved; keep dual-use *process*, not the anecdote as law |

### Contra / align other sources in this directory

- ↔ align *lean-ux*: MVP, experiment, measure — Ameisen is the ML-specialized version of build-measure-learn.
- ↔ contra *technological-republic* conviction-over-metrics pure: Ameisen demands product metrics and user feedback as sovereign for *ML feature* success (conviction still chooses the problem).
- ↔ partial align *poor-charlies-almanack*: inversion (assume failure modes), avoid psychology of “surprised by great metrics.”
- ↔ contra hype “AI-first everything”: explicit **when not ML** rules.

### Exemptions

- **Regulated autonomous decisions** (credit, medical, criminal): book’s “show confidence / omit” patterns help but are not compliance; need legal review and often human mandatory approval.
- **Pure research / benchmark chasing:** fixed datasets; ignore “iterate data as product.”
- **One-shot offline analytics** (single report): no deploy/monitor chapter weight.
- **Hard real-time safety systems:** random holdout counterfactuals may be unethical; use other eval.
- **Tiny teams with zero ops:** shadow mode + bandits optional; still keep heuristic fallback + product metric.

---

## Candidate lexicon rows

| Trigger phrase | Rule name — one-line rationale | Activating question | Tier | Phase | Src |
|---|---|---|---|---|---|
| “we need a model for this” before rules tried | **Heuristic before ML** — ship deterministic baseline first | Can a maintainable rule or strawman deliver value? | blocker | product | src: building-ml-powered-applications ch-1 |
| generative rewrite as v1 plan | **Simplest-model ladder** — classifier/score before seq2seq | What is the weakest model that could improve the product metric? | should | product | src: building-ml-powered-applications ch-1 |
| F1 up, acceptance flat | **Product metric sovereignty** — offline is only a proxy | Which user behavior proves this model helped? | blocker | product | src: building-ml-powered-applications ch-2 |
| advice feature with high recall low precision | **Precision-first guidance** — wrong advice costs more than silence | What happens to trust if we are wrong once? | should | product | src: building-ml-powered-applications ch-7 |
| no accept/edit instrumentation | **Instrument the flywheel** — weak labels from product use | Where does the next training label come from in production? | blocker | product | src: building-ml-powered-applications ch-4 |
| only aggregate accuracy at ship review | **Slice before ship** — inclusive and mode-of-failure checks | On which user/content slice would we be embarrassed? | blocker | product | src: building-ml-powered-applications ch-5 |
| next sprint is “try another architecture” | **Error-analysis drives work** — top-k and slices assign tasks | What concrete failure mode are we fixing? | should | product | src: building-ml-powered-applications ch-5 |
| model path with no fallback | **Heuristic fallback required** — models fail closed to safe path | What do we show when confidence is low or input is garbage? | blocker | ops | src: building-ml-powered-applications ch-10 |
| live model, no drift/product dashboard | **Monitor product + feature drift** — refresh on signal not vibes | How would we know within a week that quality died? | should | ops | src: building-ml-powered-applications ch-11 |
| new model replaces old on 100% traffic | **Shadow then canary** — prove production parity before full cutover | Have we compared on live traffic without burning users? | should | ops | src: building-ml-powered-applications ch-11 |
| optimize clicks for recommendations | **Anti-feedback-loop labels** — prefer satisfaction-correlated outcomes | Are we training a monoculture or clickbait? | judgment | strategy | src: building-ml-powered-applications ch-8 |
| perfect accuracy assumed in UX copy | **Design for imperfect models** — confidence gates and human override | What is the worst wrong output a user might see? | blocker | product | src: building-ml-powered-applications ch-2 |

---

*End distilled · slug `building-ml-powered-applications` · decision-rule pipeline feed for business/marketing lexicon*
