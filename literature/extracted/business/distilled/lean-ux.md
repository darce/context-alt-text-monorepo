# Lean UX (3rd ed., Gothelf/Seiden) — distilled

> **Source**: Jeff Gothelf & Josh Seiden, *Lean UX: Designing Great Products with Agile Teams*, 3rd ed. (O’Reilly) · extracted from `../lean-ux.txt` · distilled 2026-07-09 (spec v1)
> **Contributes**: The sharpest **hypothesis-driven product discovery** pipeline in this directory: **outcomes over outputs**, **assumption → hypothesis → MVP → experiment** grammar (templates kept verbatim), **Hypothesis Prioritization Canvas** (when to test / build / throw away), **MVP taxonomy** (landing page, feature fake, Wizard of Oz, prototype ladder, no-code), **Truth Curve** investment rule, **collaborative design** (Design Studio, fat-marker first, no hero design), and **evidence thresholds** for kill / pivot / persevere. Named concepts: **Lean UX Canvas**, **outcome**, **impact**, **proto-persona**, **shared understanding**, **MVP**, **Truth Curve**, **HPC**, **build-measure-learn**, **permission to fail**, **continuous discovery**, **UX debt**.

## Chapter map

- ch-1 — Why Lean UX now: continuous software, learn while shipping
- ch-2 — Principles: team, culture, process
- ch-3 — Outcomes over outputs: definition of done = behavior change
- ch-4 — Lean UX Canvas: assumptions are the new requirements
- ch-5 — Box 1: Business problem statements (templates)
- ch-6 — Box 2: Business outcomes; Pirate Metrics / Metrics Mountain
- ch-7 — Box 3: Proto-personas; early kill gates
- ch-8 — Box 4: User outcomes and benefits (empathy before features)
- ch-9 — Box 5: Solutions under constraint; Design Studio
- ch-10 — Box 6: Hypotheses + Hypothesis Prioritization Canvas
- ch-11 — Box 7: Most important thing to learn first
- ch-12 — Box 8: MVP taxonomy, Truth Curve, experiment design
- ch-13 — Cases: when “loved” features get deprioritized; validation ladder
- ch-14 — Collaborative design rules; Design Sprints; design systems
- ch-15 — Continuous research; evidence quality by artifact; A/B
- ch-16–17 — Agile integration + org shifts (outcomes roadmaps, kill features)
- pipeline — Assumption→hypothesis→MVP→evidence→persevere/pivot/kill

---

## ch-1 — Why Lean UX now {#ch-1}

Physical-product design required **big design up front (BDUF)** because manufacturing was expensive. Software distribution is continuous (Amazon as extreme: code live every second). Competitors with short cycle times force **discover while delivering**.

**Lean UX** (definition): a design approach that brings the true nature of a product to light faster, in a collaborative, cross-functional, and user-centered way. Three layers: process change, culture of humility (initial solutions are wrong), organizational transparency.

Foundations: **UX / design thinking** (human needs) + **Agile values** (individuals, working software, customer collab, respond to change) + **Lean Startup** (**build-measure-learn**, MVPs to test market assumptions).

| Decision | Rule | Why |
|---|---|---|
| Framing of each design | Treat design as a **hypothesis**, not a requirement | Predictability of human behavior is low |
| Size of first ship | Smallest thing that creates **learning**, not “phase 1 feature set” | Wrong large batches = expensive waste |

## ch-2 — Principles {#ch-2}

Lean UX is principles, not a rigid rulebook—adapt process, keep principles.

### Team organization

| Principle | Decision rule |
|---|---|
| **Cross-functional** | Staff design, eng, PM, content, marketing, QA from day one through end—no sequential handoff silos |
| **Small, dedicated, colocated** | Core team ≤ **10**; one project; shared space (physical or high-bandwidth virtual). Colocation = shared understanding + unplanned conversation |
| **Self-sufficient and empowered** | Team can ship and contact customers without external permission gates |
| **Problem-focused** | Assign a **problem/outcome**, not a feature list. “Done” = problem solved, not feature shipped |

### Culture

| Principle | Decision rule |
|---|---|
| **Moving from doubt to certainty** | Start every initiative as **assumptions**; validate systematically (**enthusiastic skepticism**) |
| **Outcomes, not output** | Measure progress as **measurable change in human behavior that creates value**—not features shipped |
| **Removing waste** | Anything that doesn’t improve outcomes is waste. Ultimate waste: **stuff people don’t want** |
| **Shared understanding** | Currency of Lean UX—reduces docs, ego fights, secondhand reports |
| **No rock stars / gurus / ninjas** | Star culture breaks cohesion; team owns design |
| **Permission to fail** | Safe technical + cultural space to experiment; without it, no creativity |

**Ceramics-class lesson (Sivers):** quantity/iteration group produced higher quality than perfection-of-one group. Optimize **iteration volume with learning**, not one “perfect” ship.

### Process

| Principle | Decision rule |
|---|---|
| Don’t do the same thing faster | 8 weeks of research ≠ 2-week “sprint research.” Reconceptualize methods for the medium |
| Beware of phases | Research/design/dev/test “phases” = finished process steps, not finished work. Do all continuously |
| Iteration ≠ incremental slicing | Incremental = ship pieces of a plan. **Iterative** = rework until outcome is met |
| Small batches | Only the design needed to move forward; no inventory of untested designs |
| Continuous discovery | Regular qualitative + quantitative customer contact with whole team |
| Get out of the building (Blank) | Truth is not in the conference room |
| Externalize work | Walls/whiteboards/shared boards so quiet people contribute equally |
| Make over analysis | First concrete version beats half-day debate without market data |
| Get out of the deliverables business | Market reaction to product > beauty of artifacts |

## ch-3 — Outcomes over outputs {#ch-3}

**Output** = stuff you make (features, pages, docs, wireframes).  
**Outcome** = “a **change in human behavior that creates value**.”  
**Impact** = high-level business targets (revenue, profit, loyalty, strategic reach).

Outcomes sit between outputs and impact: many outputs can pursue one outcome; many outcomes combine into impact. Outcomes have a **point of view**—user value ≠ org value ≠ societal cost. Align them deliberately (Facebook timeline/ads example: multi-party value; ignore externalities at ethical risk).

**Finish line shifts:** Acceptance criteria / “definition of done” that only check *output* are incomplete. Done requires **validation**: put it in the world, observe behavior, **iterate until the outcome is achieved** (build-measure-learn / inspect-adapt). One-and-done shipping is incompatible with outcome management.

| Observable situation | Rule |
|---|---|
| Stakeholder brings a long feature list | Reframe: impact → intermediate outcomes → prioritize features that create those outcomes |
| Feature shipped but metric flat | Keep working the feature (or replace it)—shipping ≠ success |
| Team argues aesthetics mid-discovery | Defer polish; ask which **behavior** must change |

Scenario → lesson: Agency filters client’s ambitious event-marketplace requirements by outcome “event hosts meet qualified planners and create collaborative bids” → anything that doesn’t create that meeting/bid behavior is deprioritized.

## ch-4 — Lean UX Canvas {#ch-4}

**Assumptions are the new requirements.** Requirements often mean “shut up” (Patton). Software + human behavior are complex; declaring certainty is usually a lie. Humility about guesses **creates room for discovery**.

**Lean UX Canvas** consolidates assumption declaration + test path into one facilitation surface (NOW current condition → LATER target condition). Eight boxes:

1. Business problem  
2. Business outcomes  
3. Users (proto-personas)  
4. User outcomes & benefits  
5. Solutions  
6. Hypotheses  
7. What’s the most important thing to learn first?  
8. MVPs and experiments  

**When to use:** kickoff of features, major initiatives, new products—any work with important unknowns. Works for early-stage *and* sustaining innovation. Whole team + stakeholders (esp. Boxes 1–2). Half-day minimum; multi-session for big work. Avoid analysis paralysis: park unknowns, move to learning.

**Facilitation default:** Liberating Structures **1-2-4-All** (solo → pairs → subgroup → all) for inclusive participation across power gradients.

Canvas is optional as a *form*; boxes are not optional as *conversations*.

## ch-5 — Box 1: Business problem {#ch-5}

Teams must be given **problems to solve**, not solutions to build.

A business problem statement must:

1. Give a specific challenge (not a feature list)  
2. Anchor in customer-centric success  
3. Specify scope constraints  
4. Provide clear success measures (impacts or outcomes)  
5. **Not** define a solution  

### Templates (verbatim)

**Existing product:**

> [Our service/product] was designed to achieve [these business/customer goals and deliver this value]. We have observed [in these ways] that the product/service isn’t meeting these goals, which is causing [this adverse effect/problem] to our business.  
> How might we improve service/product so that our customers are more successful as determined by [these measurable changes in their behavior]?

**New initiative:**

> The current state of [the domain we are working in] has focused mainly on [these customer segments, these pain points, these workflows, etc.].  
> What existing products/services fail to address is [this gap or change in the marketplace].  
> Our product/service will address this gap by [this product strategy or approach].  
> Our initial focus will be [this audience segment].  
> We’ll know we are successful when we see [these measurable behaviors in our target audience].

| Antipattern | Fix |
|---|---|
| Solution smuggled into “how might we” (“implement a mobile app…”) | Keep solutions for Box 5 |
| Problem leveled above team’s jurisdiction | Resize so team can actually solve it |
| Vague success (“intuitive UI,” “great UX”) | Quantified behavior change |
| Missing metrics/evidence | Specific observations + targets |

## ch-6 — Box 2: Business outcomes {#ch-6}

Impact metrics (revenue, NPS, churn) live on executive dashboards. Feature teams need **leading indicators**: *What will people do differently if our solutions work?* Every brainstorm item should start with a **verb** (do more of / less of / start doing).

**Pirate Metrics (AARRR):** Acquisition → Activation → Retention → Revenue → Referral. Use as journey slices to pick which stage the problem hits.

**Metrics Mountain** (Patton/Gothelf): mountain not funnel—not everyone reaches the top. Map plateaus + % success thresholds per step (e.g. 75% discover feature, 50% of those try, 25% weekly use, 10% pay).

**Outcome-to-impact mapping:** strategy → impact metrics → leading customer behaviors → lower leading behaviors → **dot-vote top ~10** outcomes; set baseline + goal per outcome; assign to team.

| Not an outcome | Why |
|---|---|
| “% of shelf that is our brand” | Product strategy decision, not customer behavior |
| “% of tasks automated” | System property; outcome is *time staff spend on repetitive tasks* |

## ch-7 — Box 3: Users / proto-personas {#ch-7}

**Proto-personas** = team’s best-guess personas, sketched in hours, revised continuously after research—not months-long sacred research deliverables.

Template zones: sketch + name/role | demographics/psychographics that **predict behavior** | goals, needs, obstacles (features are not needs).

**Early validation triad** (kill gates *before* code):

1. **Does the customer exist?** (Can you recruit them?)  
2. **Do they have the needs/obstacles you assume?**  
3. **Would they value *your* solution enough to switch?** (Persona + pain ≠ willingness to leave email/Excel)

Scenario → lesson: Angel-investor tooling—persona exists, pain exists, but ~**95%** invest 1–2×/year and stick with email/Excel → market too small; stop before shipping. Three-gate fail is a **feature-kill / product-kill** signal at Box 3.

## ch-8 — Box 4: User outcomes and benefits {#ch-8}

Separate points of view:

| Actor | Example (expense software) |
|---|---|
| Business | Acquire/retain customers, grow subscription revenue |
| Customer (buyer org) | Accounting efficiency, fewer non-reimbursable payments, lower ops cost |
| User (employee) | Get reimbursed fast; minimize input friction |

Include **emotional** outcomes (look good to boss; feel confident reimbursement works). Emotional goals are hard to quantify but drive experience quality and eventually metrics.

Prompts: What is the user trying to accomplish? How should they feel during/after? How does this approach a life goal? Why seek *this* product? What observable behavior shows success?

**Antipattern:** writing features as benefits (“calendar integration”). Prefer latent need: “Never be late to another meeting.”

## ch-9 — Box 5: Solutions {#ch-9}

Solutions come **after** problem, outcomes, personas, user benefits—constraints enable creativity. Still not detailed UI; specific enough to form hypotheses.

**Affinity mapping prompt:** *What solutions can we design and build that will serve our personas and create their desired outcomes?*

### Design Studio (collaborative design ritual)

- Team **5–8** (split if larger); **≥3 hours**  
- Flow: problem/constraints (15m) → individual six-ups (10m) → present+critique (3m/person) → pair refine (10m) → team converge (45m)  
- Critique art: **questions > opinions** (“How does this address the persona’s problem?” not “I don’t like that”)  
- Resist false consensus via abstraction—force specific decisions; use a **parking lot** for cut ideas  
- Output: low-fi sketches → feed Box 6; post on wall; archive photos  

Even participation is mandatory; silent dropouts create later resistance to chosen directions.

## ch-10 — Box 6: Hypotheses {#ch-10}

### Hypothesis template (verbatim)

> We believe we will achieve [this business outcome]  
> If [these personas]  
> Attain [this benefit/user outcome]  
> With [this feature or solution]

A **compelling hypothesis**: clear user + obvious benefit + behavior change that solves Box 1 problem. If you can’t write one for a Box 5 idea, that idea does not graduate.

**Vs Agile user story** (“As a… I want… so that…”): stories often collapse to feature delivery and system acceptance. Hypotheses define success as **behavior change**. Features/stories still track work; always wire them to outcomes.

### Hypothesis Prioritization Canvas (HPC)

2×2: **x = risk**, **y = perceived value** (assumption that UX+business impact is high). Risk is multi-type (tech, brand, design capability)—don’t normalize to one risk type.

| Quadrant | Action |
|---|---|
| **Q1 high value, high risk** | **Test** → Boxes 7–8 |
| **Q2 high value, low risk** | **Build** now; measure live against hypothesis outcomes; revisit if miss |
| **Q3 low value, low risk** | Usually **don’t build**; exception = table-stakes ops (payment rails)—build basics only |
| **Q4 high risk, low value** | **Throw away**—no test, no build |

**When to kill features (pre-build):** Q4 always; Q3 unless mandatory infrastructure; multi-feature hypotheses that can’t be isolated (split until testable); ideas that fail the compelling-hypothesis check.

## ch-11 — Box 7: Learn first {#ch-11}

Two key Lean UX questions:

1. **What’s the most important thing we need to learn first about this hypothesis?**  
2. (Box 8) **What’s the least amount of work we need to do to learn the next most important thing?**

Early life-cycle: prioritize **value risks**—need? seek? try? use? find value? If “no,” skip design/build risks. Mature hypotheses: tech, usability, scale.

No consensus? **Decide and experiment** (usually PM call)—don’t park forever. Unchosen risks return to backlog if current path falsified.

## ch-12 — Box 8: MVPs and experiments {#ch-12}

**MVP** here ≠ “phase 1 ugly release.” MVP = **smallest, fastest way to learn something**. May create value *and* learning, but primary job is learning. Need not be code.

### Value-MVP guidelines

- Get to the **core value proposition**; skip nav/login polish  
- Clear **call to action** (intent or pay)  
- **Measure behavior**, not opinions  
- Talk to converters *and* non-converters  
- Ruthless prioritization: if experiment falsifies hypothesis, **you’re wrong**—don’t cling  
- Stay agile in the medium  
- Reuse existing rails (email, SMS, Shopify, no-code, forums)

### Implementation-MVP guidelines

- Functional enough for realistic use  
- Integrate analytics context  
- Visually consistent to reduce novelty bias  

### Global MVP rules

- Prefer single-factor learning when possible  
- Instrument before launch  
- **Start small**; expect throwaway  
- Code optional  

### Truth Curve (Constable, adapted)

Investment in MVP fidelity must be **proportional to market evidence** for the idea. Low evidence → low investment. High evidence → higher fidelity justified because next questions are harder. Anything beyond “smallest thing to learn next” is waste.

### MVP taxonomy

| Type | What it tests | Notes |
|---|---|---|
| **Landing page test** | Demand / value prop / conversion language | Positive easy; negative ambiguous (story may be wrong). Crowdfunding pages are landing-page MVPs |
| **Feature fake / button to nowhere** | Interest in expensive feature | Show “coming soon”; use sparingly; compensate if trust hit (Flickr screensaver, MapMyRun photo upload) |
| **Wizard of Oz** | Process/mechanics with human backend | Looks real; humans run ops (Echo query tests; Taproot pro-bono matching via static pages + Trello DB) |
| **Paper prototype** | Concept, structure, flow | Hours; high throwaway; limited usability fidelity |
| **Low-fi clickable wireframes** | Hierarchy, IA, path length, findability | Not brand/polish |
| **Mid/high-fi interactive** | Workflow, UI, branding | Maintenance cost; often not real data |
| **No-code MVP** | Functional value without custom eng | Airtable/Zapier/Webflow; hard brand; expensive to scale |
| **Coded / live-data prototype** | Highest realism; A/B-capable | Risk of over-perfecting code |

Prototype only **core workflows** tied to biggest hypothesis risks. Demo widely (team, stakeholders, customers).

## ch-13 — Cases: evidence in practice {#ch-13}

**Enterprise map feature:** Beautiful map loved by customers *and* stakeholders for v2 enhancement. Canvas Box 4 forced re-read of research: users wanted **proactive attention highlights**, not prettier maps. Pivot priorities; pilot improved; broad release ~**6 months sooner**.

**Validately validation ladder** (time → social → money):

1. Will they give **30 minutes** to discuss the problem?  
2. Will they **introduce** you inside their org (risk reputation)?  
3. Will they **pay now** for a product not yet built (cancel if undelivered)?

Two-day InVision prototype used as sales tool after dozens of interviews.

**Kaplan university partnership:** Box 7 risk = university interest before product exists → conversations → 2 major partners in 90 days. Later pivots: live realtime → async (time zones); pricing/fee experiments in **1-week sprints**; outcome north stars (login within 48h, **80%** completion, **NPS 50**). No-code/SaaS stitch to escape corporate tech lag.

## ch-14 — Collaborative design rules {#ch-14}

UX is the sum of *all* product decisions (pricing, packaging, support…)—created by a team. Lean UX is **cocreation facilitated by designers**, not design-by-committee and not **hero design** (drop-in genius, leave).

Rules:

1. Designer **facilitates** + still crafts; whole team contributes  
2. Prefer **fat-marker** sketches; never group-edit pixels  
3. Low fidelity preserves **pivotability**  
4. Conversation is primary communication (Agile Manifesto alignment); parallel eng work from shared understanding  
5. **Design Sprint** (Knapp): great for kickoff / big new bet; does *not* replace continuous MVP/hypothesis loop or full roadmap  
6. **Design systems** enable speed/consistency *after* concept; **don’t skip fat markers**—hi-fi components bias feedback to fonts/colors  
7. Distributed: level the playing field (shared digital boards, not one person on phone while room whiteboards); invest social time  
8. **Retrospectives + team working agreements** improve collaboration  
9. **Psychological safety** (Weinberg): shared belief no punishment for mistakes/questions/new ideas—required for experiment culture  

## ch-15 — Feedback, research, evidence quality {#ch-15}

Research is **continuous** (every sprint cadence) and **collaborative** (team in field; researchers guide, don’t monopolize). Don’t outsource discovery.

**Three users every Thursday** (three / twelve / one): Mon recruit → Tue–Wed prep MVP → Thu test ≤1h ×3 users, whole team notes → Fri plan. Test-what-you-got; fidelity sets expected feedback type.

| Artifact | Valid evidence for | Not for |
|---|---|---|
| Sketches | Concept value, conversation | Step usability, copy precision |
| Static wireframes | Hierarchy, IA, taxonomy | Brand, full interaction |
| Hi-fi static mock | Brand, visual hierarchy, CTAs | Natural click paths |
| Clickable mock | Workflow simulation | Full data/edge cases |
| Coded prototype | Highest-authority simulation | — (costly) |

**Sense-making:** same-day team read-out; sticky theme; patterns > single opinions; **parking lot** outliers; cross-channel verify (support tickets, analytics).

**Longitudinal:** same baseline questions weekly reveal slow attitude shifts (e.g. SMS acceptability 2008→2011).

**Always-on channels:** support top-10 monthly; on-site feedback; search logs; analytics funnels; **A/B** with small changes + large enough cohorts—attribute only when instrumented.

**Feature kill in continuous discovery:** “If you’re doing discovery right, you’re changing and potentially **killing a lot of ideas**… sometimes that means we kill features before we ship them.” Discovery that only validates the backlog is cargo-cult.

## ch-16–17 — Agile integration & org shifts {#ch-16}

Agile without discovery = software factory. Progress on outcome roadmaps = **how well customer behavior improved**; failed ideas die; learning feeds next backlog.

Org shifts (decision-relevant):

| Shift | Rule |
|---|---|
| Humility | Strong vision + willingness to reverse on market evidence |
| Competencies over roles | Secondary skills welcome; silos kill collab |
| Two-pizza teams | ≤ size that eats two pizzas; large problems → multi-team, shared outcome |
| Outcomes not feature roadmaps | Leadership sets metrics; team chooses features |
| Beware **Agilefall** / BDUF-in-sprints | Upfront design phase + locked handoff destroys Lean UX |
| Speed first, aesthetics second (Fried) | Least artifact that communicates; polish late |
| **UX debt** | Track like tech debt; journey-map current vs ideal; backlog paydown |
| Docs | Lead with conversation, trail with required compliance docs |
| Agency | Prefer time-materials or **outcome-based** contracts over deliverable SOWs |

---

## Pipeline grammar (end-to-end) {#pipeline}

The book’s commercial decision loop, compressed:

```
assumptions (every canvas box)
    → business problem + outcomes + personas + user benefits + solutions
        → hypothesis (verbatim template)
            → prioritize (HPC quadrants)
                → learn-first risk (Box 7)
                    → MVP / experiment (Box 8; Truth Curve)
                        → evidence
                            → persevere | pivot | kill
```

**Persevere** when: behavior moves toward the outcome stated in the hypothesis (qual patterns + instrumented metrics agree); Q2 builds hit live success criteria; validation ladder advances (time → social → money).

**Pivot** when: problem/persona still real but solution path fails (Kaplan live→async; enterprise map→proactive alerts; community product needing differentiation after prototype week). Keep the outcome; change the solution hypothesis.

**Kill** when: HPC Q4; fails compelling-hypothesis write-up; proto-persona triple-gate fail; value questions answer “no”; experiment falsifies and no adjacent hypothesis remains worth the next smallest test; discovery shows people won’t leave the incumbent.

**Evidence quality ladder (use the lightest that answers the risk):**

| Risk class | Prefer | Escalate when |
|---|---|---|
| Demand / value prop | Landing page, interview, CTA | Need price/commitment signal |
| Feature interest | Feature fake | Build cost still high after positive clicks |
| Service mechanics | Wizard of Oz / no-code | Manual ops can’t teach the workflow |
| Usability / workflow | Clickable prototype | Need real data or A/B confidence |
| Live impact | A/B + analytics | Sample/confound issues → more qualitative |

**Two questions, every cycle:** (1) Most important thing to learn first? (2) Least work to learn it?

---

## Decision rules (summary)

| Trigger (observable business/product situation) | Rule | Rationale | Src |
|---|---|---|---|
| Stakeholder delivers feature list / “requirements” without success metrics | Reframe to impact → outcomes; treat list as assumptions; run canvas Boxes 1–2 before build | Features don’t guarantee value; behavior change does | ch-3, ch-4, ch-5 |
| Team measures progress as velocity / stories shipped | Switch KPI to defined outcomes; shipping is table stakes | Output ≠ outcome | ch-2, ch-3, ch-10 |
| Idea is high perceived value and high risk (HPC Q1) | Design experiment (Boxes 7–8) before production build | Risk of wrong big bet | ch-10, ch-12 |
| Idea is high value, low risk (Q2) | Build, ship, **measure**; revisit if outcomes miss | Don’t over-test the obvious; still verify live | ch-10 |
| Idea is high risk, low value (Q4) or fails compelling hypothesis | Kill—no test inventory, no build | Ruthless prioritization | ch-10 |
| Early hypothesis; unknown demand | Ask value questions first (need/seek/try/use/value) before UX/tech polish | Invalid value → all other work waste | ch-11 |
| Low market evidence for idea | Stay low on **Truth Curve**—cheapest MVP | Investment ∝ evidence | ch-12 |
| Expensive feature unproven | Prefer landing page, feature fake, or Wizard of Oz over full build | Learn demand/mechanics cheaply | ch-12 |
| Proto-persona fails recruit, need, or switch-cost gate | Stop or rewrite audience before solutions | Three-gate kill at Box 3 | ch-7 |
| Experiment falsifies hypothesis | Drop or pivot idea; designer preference is not evidence | “If results disagree, you’re wrong” | ch-12 |
| Design critique becomes opinion warfare | Enforce question-based critique; designer facilitates | Protect psychological safety + signal | ch-9, ch-14 |
| Team skips research to “stay agile” | Build continuous discovery into cadence (e.g. weekly 3 users) | Agile without learning = factory | ch-15, ch-16 |
| Feature shipped, outcome flat | Iterate or replace feature; don’t mark done | Validation required beyond acceptance tests | ch-3 |
| Hi-fi comps shown too early | Force fat-marker / low-fi first | Hi-fi biases feedback to cosmetics | ch-14 |
| Multi-feature hypothesis | Split to one feature per testable hypothesis | Confounded tests teach nothing | ch-10 |
| Cross-team UX regressions accumulate | Log **UX debt**; dual journey maps; prioritize paydown | Continuous improvement includes UI | ch-17 |

---

## Anti-patterns

| Name | Detection cues | Counter |
|---|---|---|
| **Requirements as silence** | “Just build the PRD”; questions treated as insubordination | Canvas; assumptions language |
| **Output theater** | Demos celebrate screens; no behavior metrics | Outcome baselines/goals |
| **Hero design** | Single designer unveils polished work; team learns nothing | Collaborative design; facilitation |
| **Agilefall / BDUF-in-Agile** | Design phase → handoff → “predictable” sprint factory | Concurrent discovery + delivery |
| **Phase theater** | “Research phase,” “hardening phase” | Continuous all practices |
| **Persona idolatry** | Untouchable research personas never updated | Living proto-personas |
| **Feature-as-benefit** | Box 4 filled with “integrations” and “dashboards” | Latent needs / emotional jobs |
| **Solution-smuggled problem** | “How might we build an app that…” | Strip solutions from Box 1 |
| **Opinion over pattern** | Roadmap changed by one loud user | Theme patterns; multi-channel verify |
| **Truth Curve inversion** | High-fidelity build with zero demand evidence | Landing page / fake door first |
| **Discovery as backlog blessing** | Research only confirms planned features | Expect kills; celebrate invalidation |
| **Rock-star culture** | Ninjas/gurus; private design | Shared ownership |
| **Deliverables business** | Success = deck/spec acceptance | Market reaction |
| **Unsafe experiments** | Failure punished; no feature flags | Permission to fail + technical safety |

---

## Applicability & exemptions

**Applies strongly when:** digital/software products with continuous delivery potential; uncertainty about users, value, or solution shape; cross-functional product teams; greenfield *or* sustaining innovation with unknowns.

**Weaken / adapt when:**

| Context | Guidance |
|---|---|
| True manufacturing / regulated physical product with high change cost | Keep heavier upfront validation; still use outcome framing—cycle times differ |
| Hard compliance documentation regimes | “Lead with conversation, trail with documentation”—don’t block learning on docs; capture decisions after validation |
| Design systems / platform teams | Limited live experimentation; lean into collaborative design with internal users; adoption > vanity metrics |
| Agencies on fixed-deliverable SOWs | Lean UX conflicts with deliverable billing; prefer T&M or outcome contracts; embed client in sessions |
| Zero customer access (legal/security) | Proxy users + instrumented dogfood; escalate access as blocker—don’t fake continuous discovery |
| Purely deterministic/regulatory engines | Hypothesis craft still helps scope; experimental UX may be constrained |

**Era notes:** 3rd ed. already absorbs remote/COVID colocation nuance and modern no-code/tooling. Amazon “every second” is aspirational extreme—transfer the *mechanism* (short learn cycles as competition), not the ops number. Pirate Metrics and weekly lab cadences are templates; match cohort reality (B2B recruit slower → adjust sample, keep continuous rhythm).

**↔ contra other sources in this directory:** vs pure growth-hack ship-speed playbooks—Lean UX refuses velocity without outcome validation. vs deliverable-heavy design craft cultures—polish is late-stage. Complements ML-product ladders (`building-ml-powered-applications`) on simplest-test-first; Lean UX is broader product discovery, not model-specific.

---

## Candidate lexicon rows

| Trigger phrase | Rule | Activating question | Tier | Phase | Src |
|---|---|---|---|---|---|
| feature request without outcome metric | **Outcome over output** — ship only what changes valuable behavior | What human behavior must change, by how much? | blocker | product | src: lean-ux ch-3 |
| long PRD / solution brief arrives first | **Problem before solution** — rewrite as business problem template | What adverse effect and measurable behavior define success? | blocker | strategy | src: lean-ux ch-5 |
| backlog of untested ideas | **HPC triage** — test Q1, build Q2, trash Q4 | High value *and* high risk, or just loud? | should | product | src: lean-ux ch-10 |
| expensive feature debate | **MVP learning first** — landing page / fake door / WoZ before build | What’s the least work to learn the riskiest unknown? | should | product | src: lean-ux ch-12 |
| “we know our users” with no recent contact | **Proto-persona + three gates** — exist, need, switch value | Can we recruit them, confirm pain, and beat the incumbent? | blocker | product | src: lean-ux ch-7 |
| experiment fails but team loves design | **Falsification wins** — kill or pivot; taste isn’t evidence | What result would make us wrong—and did we see it? | blocker | product | src: lean-ux ch-12 |
| low evidence, high-fidelity project plan | **Truth Curve** — investment ∝ market evidence | What evidence justifies this fidelity? | should | product | src: lean-ux ch-12 |
| design review as opinion pile-on | **Question critique** — facilitate; no hero unveil | What persona problem does this solve? | should | ops | src: lean-ux ch-9 |
| sprint demo only shows stories completed | **Discovery-in-cadence** — continuous research; kill pre-ship | What did customers do that changed our plan? | should | product | src: lean-ux ch-15 |
| roadmap is a feature timeline | **Outcome roadmap** — leadership sets metrics; team chooses features | Why this work—and how will we know we did a good job? | blocker | strategy | src: lean-ux ch-17 |
| cross-functional handoffs and phase gates | **Shared understanding over docs** — collocate/ co-create early | Who is missing from the problem framing room? | should | ops | src: lean-ux ch-2 |
| UI quality never revisited after v1 | **UX debt** — track and pay down like tech debt | Where does current journey diverge from ideal? | judgment | product | src: lean-ux ch-17 |
