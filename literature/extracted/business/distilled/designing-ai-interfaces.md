# Designing AI Interfaces (Macfadyen 2026) — distilled

> **Source**: Louise Macfadyen, *Designing AI Interfaces: Design Principles for Creative and Autonomous AI* (O’Reilly, 2026) · extracted from `../designing-ai-interfaces.txt` · distilled 2026-07-09 (spec v1)
> **Coverage note**: Early-release extract contains only final-book **ch-4 Computation** and **ch-5 Output** (file labels ch01/ch02). Unavailable: Overview, Onboarding, Input, Recall, Feedback. Distillate covers available material fully; do not invent rules from missing chapters.
> **Contributes**: The sharpest **AI-product UX decision-rule pipeline** in this directory for **trust calibration**, **uncertainty display**, **human-in-the-loop control points**, **error-recovery UX**, **expectation-setting for probabilistic output**, and **when NOT to expose model internals**. Named concepts: **computation pipeline** (process → route → generate), **agentic computation**, **detectable vs undetectable errors**, **output is not the answer**, **clear / verifiable / grounded / actionable / adjustable**, **AI overreliance**, **HITL**, **grounding**, **forward actions**, **canvas**, **prompt augmentation**, **multi-turn continuity**, **watermarking**, **red teaming**, **system cards**, **staple scripts**. Directly feeds UX decisions for AI alt-text / description products (probabilistic captions, confidence misuse, edit-vs-regenerate, disclosure, soft failures).

## Chapter map

- ch-4 — Computation: processing, routing, generation; agentic plans; errors; latency; context windows
- ch-5 — Output: clarity, verifiability, grounding, actionability, adjustability; multi-turn; watermarking; harmful outputs
- ch-1–3, ch-6–7 — *unavailable in this extract* (Overview, Onboarding, Input, Recall, Feedback)

---

## ch-4 — Computation: designing the processing and generation phase {#ch-4}

Apollo 11 **1202 alarm** = low-priority overload triage that *looked* like crash because resource allocation was invisible. **Lesson for AI UX:** invisible middle-layer work (inference) produces user-facing confusion even when the system is behaving as designed.

**Design goal of computation literacy:** designers who understand tokenization, routing, and generation can (a) talk to engineers, (b) anticipate failure modes, (c) surface the *right* amount of process—not every internal dial.

### Key terms (keep author’s names)

| Term | Working definition | UX implication |
|---|---|---|
| **Tokenization** | Split input into model units (subwords, formatting-sensitive) | Formatting/case/spaces change outputs; “same” prompt ≠ same tokens |
| **Context window** | Hard max tokens per request | Long history degrades relevance; users assume “more context = smarter” |
| **Latent space** | Compressed meaning coordinates | Similarity ≠ pixel/identity match; descriptions can be “close but wrong” |
| **Inference** | Run trained model on new input | Latency + nondeterminism live here |
| **Routing** | Choose model/tool/path per request | Same UI action may take different time/quality paths |
| **RAG** | Retrieve external knowledge before generate | Citable vs purely generative path—different trust UX |
| **Agentic workflows** | Plan → execute → monitor multi-step | Need plan legibility + step intervention |
| **Model switching** | Specialized models/configs by task | Progress copy should not imply single “brain” if multi-model |

### Computation pipeline (three stages)

1. **Input processing and preparation** — tokenize, embed, **context assembly** (history, prefs, retrieved docs, environment).
2. **Routing** — parser vs summarizer vs slide model; training knowledge vs external retrieval.
3. **Generation and inference** — produce tokens/images/video under chosen path.

| Observable situation | Rule | Why |
|---|---|---|
| User believes prompt is passed “as typed” | Design as if **preprocessing always rewrites** the request | Tokenization + assembly reshape meaning before generation |
| Multimodal or multi-tool request | Expect **longer latency + more complex soft failures** | Orchestration (film-production scale) |
| Similar prompts → different answers | Treat as **normal sampling**, not bug by default | Autoregressive path has no predetermined endpoint |
| Fluent, confident, wrong content | Label as **hallucination risk**, not “system error” | Model optimizes plausibility of next token, not truth |

**Generation mechanics that drive UX:**

- **Text (LLM):** one token at a time from probability distribution; can ramble, loop, contradict, **hallucinate** while sounding authoritative. Evolving: **chain-of-thought** forces intermediate breakdown—still not a master plan.
- **Images (diffusion):** noise → stepwise denoise; timing often more estimable than free-form LLM generation.
- **Multimodal:** higher latency, more failure modes, higher upside when orchestration works.

### Agentic computation {#ch-4-agentic}

Traditional automation (IFTTT, Salesforce Flow): user authors logic; UI is sequence + status + nudge.

**Agentic AI** = project-manager mental model: user states *goal*; system decomposes, sequences tools/time, tracks unknowns, decides when to act vs ask. Shift: **from executing to orchestrating**.

Agent loop (interface must support each):

1. Interpret high-level goal  
2. Decompose into interdependent tasks  
3. Sequence across tools/time  
4. Track completions, decisions, unknowns  
5. Adjust; fallback; ask when stuck  

**MCP (Model Context Protocol):** shared structure for tool availability, metadata, continuity across steps (Anthropic-originated; foundational for multi-tool agents). UX parallel: traditional API call is discrete; agent request is a **tree of contingent actions**.

| Decision | Rule | Why |
|---|---|---|
| Plan visibility | **Surface a draft plan early**, even incomplete (“Step 1… Step 2…”) | Align expectations before full execution (Tip) |
| Structure ownership | Even when AI builds the workflow, **keep structure as affordance** (list, map, stages) | Benefits of traditional workflow UI remain |
| Intervention | Allow **step-level review** (inspect input/output of a step; edit; re-run downstream) | Users need mid-flight control, not only final reject |
| Watch preference | Research: some watch process, some ignore until done → **expand/collapse** process detail | One density fits nobody |
| Retries / loops | **Make retries visible** (“Tried A, then alternate phrasing”) | Invisible retry looks like confusion |
| Pauses | **Acknowledge processing phases** (“Waiting for real-time data…”) | Blank = assumed hang |

↔ contra lean-ux ch-12: Lean UX optimizes for smallest *learning* ship; agentic UI often needs *more* process visibility at first ship so autonomy is steerable—MVP can be plan+checkpoint without full agent.

### Errors: detectable vs undetectable {#ch-4-errors}

| Type | System knows? | Example | UX burden |
|---|---|---|---|
| **Detectable (system errors)** | Yes | Timeout, 5xx, rate limit | Classic messages, retry, degrade |
| **Undetectable (reasoning errors)** | No | “Tokyo pop. 50M”; fake citations | User must become **error detector** |

**Critical design shift:** most dangerous AI failures arrive with perfect grammar and algorithmic confidence. No backend flag. **You are not only handling errors—you are training users to detect them.**

#### Adapted HCI error tenets (Cooper / classic → AI)

1. **Make error understandable**  
2. **Make recoverable**  
3. **Prevent foreseeable**  
4. **Degrade gracefully**  
5. **Surface system status**

**AI adaptations:**

| Tenet | AI-specific rule |
|---|---|
| Understandable | Fluent wrong ≠ success. Avoid blame copy (“We couldn’t understand you”) → collaborative (“Let’s try a different approach”). Place messages near the failure locus. |
| Recoverable | “Try again” can yield *totally different* output. Offer **Regenerate same / Edit & retry / Start fresh**. Prefer **revise output** over full re-prompt. Guided chips: “Make shorter,” “More detail,” “Focus tone.” |
| Prevent | Inputs can be valid but ineffective → **examples, starters, structure hints**. Surface capability limits early (no live data, domain gaps) as *help get better results*, not scolding. |
| Degrade | Soft failure: trail-off / off-topic mid-stream → **preserve good prefix** (“Keep editing from here”). Hold prompt + prior messages + partial output. |
| Status | Model may not know failure → **verification cues**: “Double-check important details,” “Generated—accuracy not guaranteed,” training-data cutoff, **source attribution**. Localize limits (this user / this instance), not always global banners. |

**Tone rule:** calm, clear, matter-of-fact for important failures; humor is optional and often wrong.

Scenario → lesson:
- User accepts alt-text that invents a person/object not in image; no error state → **lesson:** undetectable errors need **verify/edit affordances by default**, not error banners.
- Agent retries summarizer three times silently → user thinks product is broken → **lesson:** surface resilience path.

### Context windows and conversational memory {#ch-4-context}

**Self-attention** weights tokens across the window; more context can help *or* dilute (“lost in the middle”). Hard limits (examples in book: Claude ~200k tokens; Gemini experiments at ~1M). Long inputs: expensive, slower, less reliable.

| User belief | Design rule |
|---|---|
| “More background always better” | **Not guaranteed**—warn and offer prune / new thread |
| Tokens are meaningless jargon | Goal is **not** force users to think in tokens; soft cues OK |

Patterns:

- Soft **token / length indicator** or “Input too long—try shortening”  
- **Warn before hard fail**; options: prune earlier messages, start new thread  
- Educate gently over time; smarter defaults for what to keep

### Latency: don’t just minimize—design waiting {#ch-4-latency}

Perceived wait ≠ clock time (grocery/airport baggage analogies). Nielsen thresholds (still taught):

| Threshold | User perception | Feedback need |
|---|---|---|
| **0.1 s** | Instant | None |
| **1 s** | Noticeable, flow mostly intact | Optional |
| **10 s** | Attention limit | Progress / estimates essential |

AI wait is **thinking uncertainty**, not just load. Users are patient *if kept in the loop*.

**Three priorities by task (spend design effort where it fits):**

| Priority | When | Latency UX |
|---|---|---|
| **Make it fast** | Real-time control, transactions | Near-zero delay, optimistic UI |
| **Engaging** | Art, chat, entertainment | Tolerable delay if progress feels meaningful |
| **Clear** | Search, payments, learning | Clarity > flair |

**Visual toolkit (use selectively—“not every AI needs to show its homework”):**

| Technique | Use when | Risk |
|---|---|---|
| Immediate ack (“Thinking…”) | Any non-instant | Ack then silence → worse frustration |
| Spinner | Short unknown | Bad for long creative waits |
| Progress bar | Estimable duration | Stalled/fake bar worse than none |
| Skeleton screens | Predictable layout | Misleading if structure unknown |
| Async / non-blocking | Multi-task apps | Needs completion notification |
| Progressive disclosure | Search / research | Partial value early |
| **Token streaming** | Chat / long text gen | Best perceived-latency lever for LLMs |
| Articulated wait reasons | Multi-step / agent | Explains “why longer” |

**Segment by user need:**

| Task class | Latency design |
|---|---|
| **Information retrieval** | Progressive results, no blank, autosuggest; multi-second latency fragments mental context |
| **Real-time control** | Instant visual feedback; skeleton of likely outcome; prioritize “connected” cues (cursors) if content lags |
| **Transactional** | Immediate confirmation; staged steps if long (“1 of 3: verifying…”); optimistic UI carefully |
| **Conversational agents** | **~2–3 s** natural; typing indicators; partial stream; confirmation echoes (“Okay, looking that up”) |
| **Creative generation** | Higher patience; prefer progress over spinner; sequential process messages OK if accurate-ish |
| **Autonomous / agentic** | Publish expected wait; **pacing check-ins every x seconds** or permission gates; incremental deliverables (flights then hotels); optional “run without oversight + notify” |

Counterintuitive research note: some AI delays **increase reflection** and sense of control when expectations are set—waiting can be a partner cue, not only a cost.

### When NOT to expose model internals (computation side)

| Do surface | Do **not** dump by default |
|---|---|
| Draft plan steps, current phase, retry path | Raw token IDs, embedding dims, full routing graph |
| Why wait is long (retrieval, multi-model) | GPU scheduling / vendor infra noise |
| Soft uncertainty + verify CTA | Fake **self-reported confidence %** as truth meter |
| Collapse/expand for power users | Always-on chain-of-thought theater for every generation |

**Rule:** expose **coordination and risk**, not **occult mechanics**. 1202-style alarms without interpretation recreate Apollo panic.

---

## ch-5 — Output: delivery and presentation {#ch-5}

**CDSS history (MYCIN et al.):** fluent recommendations mis-calibrated trust—some doctors ignored, some over-relied. **Interface = risk surface.** Fluency without transparency/guardrails is a liability.

**Core thesis: the output is not the answer.** It is a designed artifact shaped by defaults, framing, and expectations. Generation is pattern completion, not verification. Missing pieces (sources, alternatives, assumptions, bias) are **byproducts**, not bugs.

### Output pipeline (technical sub-phases)

1. **Internal generation**  
2. **Post-processing** — detokenize, format, **guardrails**  
3. **Delivery/presentation** — chat bubble, stream, document, image asset  

After generation, **responsibility shifts to the interface**.

### Five design principles of outputs {#ch-5-principles}

| Principle | Definition | Product test |
|---|---|---|
| **Clear** | Instantly understandable, scannable | Can user act without re-reading thrice? |
| **Verifiable** | Evidence-backed / checkable | Can user independently validate? |
| **Grounded** | Context-aware (who/where/when/mode) | Does UI state the *lens* of the answer? |
| **Actionable** | Onward-task oriented | Are **forward actions** first-class? |
| **Adjustable** | User-editable / steerable | Can they refine without full restart? |

### Designing for clarity {#ch-5-clarity}

Models do not naturally write user-centric structure. **Content design is a product requirement**, not decoration (NN/g: users skip unclear text whether human or LLM authored).

Levers:

- **Formatting rules / output templates** in system instruction (title → intro → key concepts → steps → notes → sources)  
- **Tone specs** (friendly-formal, clarity over creativity)  
- **Trade-off heuristic:** prioritize readability/scannability over exhaustive completeness  
- **Missing-data default:** output explicit “this isn’t available” / “No data provided” instead of inventing  

**Over-styling risk (2024 study cited):** rigid templates can raise hallucinations on messy inputs and make content feel mechanical → **balance structure with flexibility**. Leaner style specs also cost less compute.

Cross-format: images/video also need hierarchy, pacing, story—raw model output is a **starting point**.

Scenario → lesson:
- Naive “how to set up X” paragraph vs structured steps + notes + sources → same model, different usability → **lesson:** post-generation structure (or constrained generation) is product UX work.

### Designing for verifiability & trust calibration {#ch-5-verify}

**Schwartz / ChatGPT fake case law (2023):** fluent citations that never existed; court sanctions. Deterministic software mental model fails.

**AI overreliance** (Microsoft AETHER / 60+ studies):

| Mechanism | Effect |
|---|---|
| Skill atrophy | Dependence weakens human skill (GPS / writing) |
| Automation bias | Favor AI over own expertise even when shaky |
| Confirmation bias | Trust AI that agrees with user |
| Ordering effects | Early good experiences create lasting over-trust |
| Detailed explanations | Can **paradoxically increase** overreliance |

Human–AI teams can underperform human or AI alone when overreliant. Helpful patterns: **cognitive forcing functions**, transparent capability bounds, progressive mental models, real-time decision-quality feedback. Goal: **appropriate reliance**, not blind trust.

#### Confidence indicators — mostly a trap

| Myth | Reality |
|---|---|
| Model “knows” confidence like a spellchecker % | Next-token probability ≠ correctness; latent, uninspectable |
| One % works for all questions | Volcano forecast ≠ essay quality ≠ “is sky blue?” |
| Show % → calibrated trust | Often **false precision** |

**Rule:** ask first *Can the user independently validate this?*  

- If **no** → route to verification (citations, evidence, human handoff) **or** hedge authority (“seems…”, “hard to verify”)  
- Best current AI fit: tasks user can **quickly verify**, or **subjective** tasks (rewrite, brainstorm) where usefulness > factuality  
- Objective / high-stakes action → **secondary human verification layer is mandatory** (Warning callout in book)

**Perplexity-style pattern:** sources attached to claims; sources also support **branching journeys** (cite, deep-read), not only “check.”

### Human-in-the-loop (HITL) {#ch-5-hitl}

**HITL** = people stay involved; not pure automation.

| Pattern | Shape | When |
|---|---|---|
| AI + human edge review | Model routes bulk; humans train on edges | Support tickets, moderation |
| Constrained generation | Model picks from **pre-approved library** | High-risk (e.g. mental-health phrases) |
| Escalation | AI routine; human for exceptions | Quality + volume |

Research (Lai et al. 2023): well-designed HITL often **beats full automation** in creativity, ethics, edge cases.

| Control point | UX affordance |
|---|---|
| Before commit | Review draft; draft vs send/publish |
| On edge case | Explicit escalate / “needs human” |
| Continuous | Feedback that trains (thumbs, edits as labels) |
| Domain risk | Block free generation; use approved phrases only |

### Designing for grounding {#ch-5-grounding}

**Grounding** ≠ only checkability (**verifiability**). Grounding = declare the **lens**: jurisdiction, timeframe, version, entities, mode.

Vegas wedding / ChatGPT jurisdiction error: correct CA law applied as if NV → grounding failure.

Surface when relevant:

| Signal | Example |
|---|---|
| Model name/version | GPT-4o vs o3 — tone/scope differ |
| Agent/tool responsible | Multi-agent: which component answered |
| Geo/locale | Jurisdiction, units, legal region |
| Task/mode | Creative vs analytical; draft vs polish |
| Session assumption | “Because you’re working on Q2 planning…” |

**Why we suggested this** pattern: inline / hover / info icon with data consulted, prefs, history influence, model/agent—**optional depth without cluttering main path**.

### AI disclosure {#ch-5-disclosure}

| Source | Requirement shape |
|---|---|
| California SB-1001 (bots, commercial/political) | Identify non-human when influencing purchase/vote |
| EU AI Act (2024) | Transparency for interaction / synthetic content; skip only if obvious |
| FTC guidance | Non-disclosure can be deceptive advertising |
| Google PAIR | Safeguards for vulnerable groups who may misread AI as human |

**Design rule:** disclose early; frame as **understanding aid**, not scare warning. “This summary is AI-generated” (AllTrails-style).

### Designing for actionability {#ch-5-action}

Output value often lives in **forward actions** (save, buy, export, cite, navigate, book…). Design secondary verbs from **downstream intent**, not only the Q&A.

Familiar web norms still apply: act from here; modify before act; multiple paths; clear consequences; returnability.

| AI-specific | Rule |
|---|---|
| Imprecision | Prefer **review before execute** (draft vs send) |
| Multi-option | Show **choices** (Gmail smart-reply panel) |
| Domain switch | Notify leaving product; preserve draft/state |
| Maps/lists | Layer list + detail + directions + external site |

### Canvas pattern {#ch-5-canvas}

**Canvas** = editable, spatial, persistent, multi-modal workspace—not linear chat only.

Traits: composable edit; spatial layout; persistent state; multi-modal blocks.

| Moves | Product effect |
|---|---|
| Chat → canvas | Exploration → human-guided artifact (share, store, collab) |
| Version picker (Claude-style) | Clear which iteration is active; favorites/projects |
| Node graph (Runway-style) | Breadcrumb undo/redo for generative co-creation |

State management is mandatory once artifacts outlive a single message.

### Designing for adjustability {#ch-5-adjust}

Users prefer **refine over restart** (preserve what’s working; continuity; context window carries prior intent).

Patterns:

- **Versions** of same input  
- **Temperature**-like creativity controls (user-facing “conservative/creative”—parameter is next-token sampling, not true creativity)  
- **Prompt augmentation**: select text → “Elaborate” appends directive → regenerate **section**, not whole doc  
- Iterative chips (Elaborate repeatedly) for paced expansion  
- Inline AI menus on selection (Notion-style)

**Discoverability rule:** users must know selection + refine tools exist.

### Multi-turn outputs {#ch-5-multiturn}

Agent as collaborator over sessions/threads/workflows: pause, resume, branch, abandon without penalty.

Scaffold:

- Turn markers / separators  
- Inline edits with change annotations  
- Side panel / timeline of task structure  
- Named threads returnable later  

**Permission:** if system will change existing content, obtain permission (one turn or multi). User must see relationship between current output and prior state.

Goal: auditable, interruptible, steerable—without becoming full IDE by accident.

### Watermarking, detection, provenance {#ch-5-watermark}

**Misuse spectrum:** unaware non-disclosure → deliberate deception. Dual-use of fluent genAI.

Risks: scale of synthetic media, academic integrity, professional liability docs, creative rights, fake personas.

| Medium | Technique notes |
|---|---|
| Text | Statistical generation bias; hard (low redundancy); fragile to edit |
| Image | Visible deterrent logos; invisible pixel/LSB; **C2PA** manifests (ChatGPT/DALL·E) |
| Video | Temporal + compression complexity; China: prominent synthetic marks for deepfakes |

**Detection limits:** OpenAI 2023 classifier ~26% true positive AI text, 9% false positive human; biased against non-native English; easily circumvented; false positives on Declaration of Independence / classic literature. **Do not ship detection as sole compliance UI.**

Forward path: transparency at generation + social norms + education + multi-layer forensics—not perfect classifier theater.

### Managing problematic outputs {#ch-5-safety}

Layered defense: data → training (**RLHF**, **Constitutional AI**) → **red teaming** (human + automated attack prompts) → filters → **system/safety cards** (intended use, known failures, “not for medical/legal decisions”).

**Interface role when model refuses or errs:**

| Situation | UX rule |
|---|---|
| Refusal | Conversational, not punitive; short reason; invite continue on safe path (Sparrow-style) |
| Unknown content space | Design against **staple scripts** from real logs/personas—not idealized perfect answers |
| Variability | Script confident, hedged, list, paragraph, wrong, refuse—UI must survive all |
| Soft wrong | Design repair, not only empty state |

**Staple scripts tip set:** grounded examples from logs; mix tones/certainty; always include sideways cases for fallback/trust cues.

### When NOT to expose model internals (output side)

| Expose | Withhold / avoid |
|---|---|
| Sources, jurisdiction, mode, model version | Raw logits, full system prompt dumps to end users |
| “Why we suggested this” on demand | Always-on explanation walls that **increase overreliance** |
| Hedge + verify for factual claims | Uncalibrated confidence percentages |
| AI disclosure | Deep “how transformers work” education mid-task |
| Diffs / versions on multi-turn edit | Internal agent graph for casual users |

**Meta-rule from summary:** show enough reasoning to support trust, **not so much as to overwhelm**. Signal fixed vs flexible. Output is proposal; **what happens next** is the product.

---

## Decision rules (summary)

| Trigger (observable business/product situation) | Rule | Rationale | Src |
|---|---|---|---|
| Shipping any generative caption/summary UI | Treat **output as designed artifact**, not “the answer”; add structure, hedges, next actions | Fluency ≠ correctness; CDSS risk surface | ch-5 |
| User will act on objective claim (legal, medical, finance, identity in image) | Require **secondary human verification** or block authoritative presentation | Undetectable errors + overreliance | ch-5 |
| Product asks “show model confidence %” | Prefer **verifiability paths** (sources, edit, human) over self-reported confidence | Token probability ≠ truth; false precision | ch-5 |
| Hallucination-class risk in domain | Default **edit-in-place + double-check cues**, not error banner only | System may not flag wrongness | ch-4 |
| Generation fails softly (partial, off-topic) | **Preserve prefix**; offer continue/edit; keep prompt history | Soft failures ≠ hard crashes | ch-4 |
| User retries after bad output | Offer **Regenerate / Edit & retry / Start fresh** + guided refine chips | Nondeterministic retry; refine > restart | ch-4, ch-5 |
| Multi-step agent feature | Surface **early draft plan** + step inspect/edit + visible retries | Agentic opacity destroys trust | ch-4 |
| Wait > ~1–3 s for chat; longer for creative | Stream partial results; ack immediately; articulate wait reason | Patience depends on loop-in | ch-4 |
| Transactional or real-time control | Optimize **true speed + optimistic confirm**; never theater progress | Wrong priority class erodes confidence | ch-4 |
| Long conversation / large paste | Warn before context limits; offer prune/new thread | Overlong context degrades quality | ch-4 |
| Commercial/political bot or synthetic summary | **Disclose AI** early, as understanding aid | Law + trust (SB-1001, EU AI Act, FTC) | ch-5 |
| Locale/jurisdiction-sensitive advice | Surface **grounding** (region, source set, mode) | Wrong lens = confident wrong action | ch-5 |
| User needs to keep refining artifact | Move to **canvas + versions**; section-level regenerate | Chat buries state; restart loses context | ch-5 |
| High-risk generative domain | Constrain to **HITL / approved libraries**; red-team before launch | Full free-gen amplifies harm | ch-5 |
| Explanations always-on to “fix trust” | Prefer **progressive / on-demand** explanation; test for overreliance | Detailed explanations can increase blind trust | ch-5 |
| Designer mocks only ideal answers | Build **staple scripts** including wrong/refuse/hedge | Real outputs vary; UI must hold | ch-5 |
| Request to show full model internals for “transparency” | Surface **risk, plan, sources, limits**—not occult mechanics | 1202 problem: visibility without interpretation | ch-4, ch-5 |

---

## Anti-patterns

| Name | Detection cues | Fix direction |
|---|---|---|
| **Fluent-failure blind spot** | No verify/edit path; success UI on every completion | Treat completion ≠ correctness |
| **Confidence theater** | Big % badges from model self-report | Sources, human review, hedges |
| **Blank think** | Spinner, no phase, no stream | Ack + progress + stream |
| **Invisible agent** | Multi-minute work, no plan, silent retries | Draft plan, step status, expand/collapse |
| **Blame the user** | “We couldn’t understand your input” on ambiguous gen tasks | Collaborative reframe + examples |
| **Full restart only** | Delete & retype as sole recovery | Section edit, chips, versions |
| **Over-templated voice** | Mechanical sameness; user distrust; more invention on gaps | Allow flexible structure; explicit missing-data |
| **Explanation dump** | Walls of why that raise rubber-stamping | Forcing functions + on-demand why |
| **Undisclosed AI** | Human-mimic chat without label | Early disclosure |
| **Ungrounded authority** | Advice without locale/source/mode | Grounding chips / jurisdiction pickers |
| **Classifier compliance** | Ship AI-detector as sole authenticity gate | Provenance at gen + norms + multi-layer |
| **Always show homework** | Token graphs / raw CoT for every user | Selective transparency by task risk |

---

## Applicability & exemptions

**Applies strongly when:**

- Product generates **probabilistic** text/media users may treat as fact (captions, summaries, recs, support)  
- **Alt-text / image description** services: soft errors, identity/object invent, accept-rate metrics, editor-in-loop  
- Agentic multi-tool workflows (research → draft → publish)  
- Consumer or professional tools where overreliance has cost  

**Apply with caution / era-bound surfaces:**

| Bound surface | Transferable mechanism | Modern note |
|---|---|---|
| Specific token limits (200k / 1M) | Hard windows + quality decay | Recheck model limits; rule is UX for limits, not the numbers |
| MCP as Anthropic-specific | Shared multi-tool context protocol | Industry evolving; pattern = continuity metadata, not brand |
| Nielsen 0.1/1/10 s (1990s roots) | Perceived-latency bands | Still useful bands; AI adds *thinking* uncertainty layer |
| OpenAI classifier 26% figure (2023) | Detection is weak/biased | Don’t treat as fixed forever; still: don’t sole-source on detectors |
| Named products (Perplexity, Claude canvas, Notion, Cline) | Patterns (inline sources, versions, checkpoints) | Copy pattern, not vendor UI |
| Early-release missing ch-1–3,6–7 | Incomplete onboarding/input/memory/feedback rules | Re-distill when chapters ship |

**Does NOT apply / exemptions:**

- Fully **deterministic** calculators/policy engines with no generative step (still use classic error UX)  
- Offline pure research demos with no user action risk (still good ethics; less product urgency)  
- When regulation mandates specific disclosure/watermark formats—**law overrides pattern book**  
- Internal tooling where all users are model experts and want raw internals (invert progressive disclosure)  

**Contra notes within directory:**

- ↔ **building-ml-powered-applications**: Ameisen’s confidence gating / filtering models = good *product* controls; Macfadyen warns against **displaying** raw model confidence as user truth—gate behind the scenes, show verify/edit.  
- ↔ **lean-ux**: outcome experiments still rule roadmap; this book constrains *how* AI surfaces may present results without poisoning metrics via overtrust.  
- ↔ **technological-republic**: state/power scale; this book is interaction-scale—use for product UX, not geopolitics.

**Transfer to AI description / alt-text product (operator checklist):**

1. Never present caption as verified fact without review path.  
2. Prefer **accept / edit / regenerate** triad; store human edits as flywheel labels.  
3. Soft-fail partial descriptions; don’t wipe on timeout.  
4. Disclose AI-generated; ground on image context (page, locale, decorative vs informative).  
5. No confidence % on captions; optional “needs review” from *product* rules (length, objects, policy).  
6. Batch agentic description: show queue plan + per-asset checkpoint.  
7. Latency: stream or progressive fields; don’t block whole library UI.  
8. High-stakes images (people, medical, legal evidence): HITL required before publish.

---

## Candidate lexicon rows

| Trigger phrase | Rule | Activating question | Tier | Phase | Src |
|---|---|---|---|---|---|
| generative output looks complete | **Output is not the answer** — design for interpretation, edit, and next action, not consumption alone | Will the user treat this as verified truth? | blocker | product | src: designing-ai-interfaces ch-5 |
| objective claim drives real action | **Secondary human verification** — high-stakes objective outputs need a human or external check layer | Can a wrong accept cause irreversible harm? | blocker | product | src: designing-ai-interfaces ch-5 |
| request for model confidence badge | **No confidence theater** — prefer sources, hedges, and independent validation over self-reported % | Can the user validate without trusting a score? | should | product | src: designing-ai-interfaces ch-5 |
| AI fluent but possibly wrong | **User as error detector** — afford double-check, edit, and source paths when system cannot self-flag | Is failure detectable by the system, or only by the user? | blocker | product | src: designing-ai-interfaces ch-4 |
| multi-step autonomous workflow | **Early draft plan + step control** — show scaffold and allow intervene before/during execution | Can the user stop, edit, or redirect mid-flight? | should | product | src: designing-ai-interfaces ch-4 |
| wait exceeds conversational beat | **Designed waiting** — ack, stream, and reason the wait; match technique to task class | Which priority applies: fast, engaging, or clear? | should | product | src: designing-ai-interfaces ch-4 |
| recovery from bad generation | **Refine over restart** — regenerate, edit-retry, chips, and section rewrite before full reset | Does retry preserve what already works? | should | product | src: designing-ai-interfaces ch-4 |
| advice depends on place/time/mode | **Ground the lens** — surface jurisdiction, model/tool, mode, and session assumptions | What context did the model assume? | should | product | src: designing-ai-interfaces ch-5 |
| humanlike AI in commercial UI | **Disclose AI early** — label synthetic/agent nature as understanding aid | Could a user reasonably think this is a human? | blocker | gtm | src: designing-ai-interfaces ch-5 |
| always-on long explanations | **Progressive transparency** — on-demand why; avoid explanation that increases rubber-stamping | Does more why improve judgment or overtrust? | judgment | product | src: designing-ai-interfaces ch-5 |
| artifact needs reuse/collab | **Canvas and versions** — persistent editable state over chat-only burial | Will this output live beyond one message? | should | product | src: designing-ai-interfaces ch-5 |
| “show the model’s guts” for trust | **Risk not occult** — expose plan, limits, sources; hide raw internals by default | Does this surface aid action or just spectacle? | judgment | product | src: designing-ai-interfaces ch-4 |

---

*End of distillate. Chapter anchors ch-4 and ch-5 are API—do not renumber. Expand when early-release chapters 1–3, 6–7 ship.*
