# Chapter 32 Drilldown Summary: Banking-Specific AI

## Source record
- **Source type:** online book chapter
- **Author/venue:** Panaversity, *AI Agent Factory*
- **Title on linked landing page:** Chapter 32: Banking-Specific AI
- **Title on lesson sidebar pages:** Chapter 21: Banking-Specific AI
- **Date accessed:** 2026-03-26
- **Chapter URL:** https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/banking-domain-agents
- **Traversal method:** chapter landing page plus all lesson pages in chapter order through **Chapter 32: Banking-Specific AI Quiz**

## One-paragraph summary
In **Banking-Specific AI**, Panaversity argues that banking agents cannot be designed around one regulatory workflow at a time because the same balance-sheet item is governed simultaneously by accounting, solvency, and financial-crime obligations. The chapter builds that claim in sequence. It first defines banking through three regulatory pillars: IFRS 9, Basel III/IV, and AML/KYC. It then turns that structure into a pillar-aware plugin architecture with a router, 16 product skills, and direct commands for common workflows. The middle of the chapter builds each pillar in operational terms: staging and expected credit loss under IFRS 9, capital adequacy and liquidity metrics under Basel, and customer due diligence, transaction monitoring, and SAR controls under AML. The final lessons connect those pillars, move from single calculations to extended casework, add reconciliation across operational systems, and culminate in a capstone where the learner packages the chapter into reusable banking skills, scheduled workflows, and a board-facing risk report. The chapter closes by treating integrated routing, not isolated expertise, as the real deployment standard for banking agents.

## Main idea
The chapter argues that banking AI must be pillar-aware rather than task-specific, because useful banking output depends on integrating IFRS 9 provisioning, Basel capital and liquidity rules, AML controls, and reconciliation into one routed system.

## Chapter thesis and structure
The chapter is built as a domain architecture argument.

It begins from the claim that banking is not just highly regulated but multiply regulated. The same exposure is reviewed through three different supervisory lenses, each with its own models, thresholds, reports, and decision rights. That makes single-pillar agents structurally incomplete.

The chapter then turns that diagnosis into a system design. It defines the three pillars, maps them to a router and skill library, and then teaches the technical content inside each pillar so the learner can verify what those skills are doing.

The structure is cumulative:

1. define the three-pillar problem,
2. translate the pillars into a routed plugin architecture,
3. build IFRS 9 staging and ECL logic,
4. build Basel capital, RWA, leverage, and liquidity logic,
5. build AML onboarding, monitoring, and SAR logic,
6. show how events cascade across pillars,
7. pressure-test the material through applied exercises,
8. reconcile model outputs against operational systems,
9. package the knowledge into reusable skills and scheduled workflows.

## Prerequisites and deliverable system
The chapter requires Cowork, a connected working folder, and the Banking plugin installed from the Panaversity business plugin repository. The chapter-level work product is not a single spreadsheet or memo. It is a routed banking agent setup: a 17-skill architecture, a set of built or configured banking skills, worked ECL and capital calculations, AML investigation logic, reconciliation procedures, and a board-facing reporting package. The capstone also asks the learner to configure recurring operational tasks so the system behaves like an ongoing banking function rather than a one-off calculator.

## Lesson-by-lesson drilldown

### 1. The Three Regulatory Pillars of Modern Banking
The opening lesson defines the chapter's governing model: every bank asset is simultaneously subject to accounting, solvency, and financial-crime control. IFRS 9 asks what loss should already be provisioned. Basel asks how much capital must be held against unexpected loss. AML asks whether the activity itself is suspicious, illicit, or sanctions-related. The lesson's point is simple and structural. A loan is never just a credit-risk object. It is also a capital object and a financial-crime object. That is why one-pillar agents fail. They answer a valid question, but only a third of the real question.

### 2. The Banking Plugin Architecture: 17 Skills, Three Pillars
This lesson converts the three-pillar model into a routing system. The plugin contains one router and sixteen product skills across IFRS 9, Basel, AML, and reconciliation, plus four shortcut commands for the most common workflows. The router reads pillar signals in the prompt, decides whether the question is single-pillar or cross-pillar, loads the skill chain in dependency order, and validates terminology before returning output. The lesson's main contribution is architectural: the same router pattern used earlier for jurisdiction in Islamic finance is now re-used for pillars in banking. The system is designed so an IFRS 9 query stays narrow, but a provision question that also affects CET1 automatically chains into Basel logic instead of stopping after the accounting result.

### 3. IFRS 9 ECL: Staging and the ECL Formula
The third lesson begins the accounting pillar. It explains why IFRS 9 replaced the incurred-loss model and why forward-looking provisioning became mandatory after the financial crisis. The lesson then introduces the three-stage model. Stage 1 uses 12-month ECL for performing assets. Stage 2 uses lifetime ECL once there has been a significant increase in credit risk. Stage 3 uses lifetime ECL for credit-impaired assets and changes the interest-recognition basis from gross carrying amount to net carrying amount. The lesson stresses that stage classification is the decisive judgment in IFRS 9 because the move from Stage 1 to Stage 2 expands the measurement horizon and can multiply provisions several times over even before default occurs.

### 4. PD, LGD, and EAD: Building the ECL Components
Once the formula is introduced, the next lesson opens the components. It treats probability of default, loss given default, and exposure at default as models that must be built, justified, and checked rather than numbers that simply arrive from nowhere. PD matters across both IFRS 9 and Basel. LGD depends on recoveries, collateral, and workout assumptions. EAD must include drawdown behavior and credit conversion where relevant. The lesson's practical point is that professional trust in ECL output depends on understanding where these inputs came from and how sensitive they are to judgment. The `ifrs9-ecl` skill may calculate quickly, but the operator still has to verify whether the component logic is defensible.

### 5. Macroeconomic Scenarios and Post-Model Adjustments
This lesson completes the IFRS 9 pillar by adding the parts that most often separate a model output from the final reported number. IFRS 9 requires probability-weighted loss estimates across multiple scenarios rather than a single central case. The chapter highlights the non-linearity principle: expected credit loss is not the same thing as the loss in the expected scenario because deterioration can accelerate faster than the macro path itself. It then adds post-model adjustments for emerging risks or structural breaks that the core model does not capture. The result is a fuller view of provisioning practice. A compliant ECL process is not just a formula plus three inputs. It is staging, component modeling, scenario design, and management overlay.

### 6. Basel III/IV Capital Adequacy: CET1, Tier 1, Total Capital
The chapter then moves from expected loss to survivability. This lesson explains the Basel capital stack and the quality hierarchy inside regulatory capital. Common Equity Tier 1 is treated as the highest-loss-absorbing form of capital, with additional tiers lower in quality. The ratios all use risk-weighted assets as denominator, so the lesson begins to frame capital adequacy as both a numerator question and a denominator question. Its deeper point is that IFRS 9 and Basel are related but not interchangeable. Provisioning reduces reported earnings, while Basel determines how much capital the bank must still hold after those losses are recognized. The chapter therefore treats solvency as a separate discipline that must still consume accounting output.

### 7. Risk-Weighted Assets: SA and IRB Approaches
This lesson opens the Basel denominator. It explains that identical portfolios can produce different capital requirements depending on whether the bank uses the Standardised Approach or internal ratings-based models. That is why reported strength can differ across institutions even before the underlying risk changes. The lesson also introduces the Basel output floor, which limits how far model-based RWA can fall below standardised results. The point is not just technical calculation. It is regulatory skepticism. Banks are allowed some model discretion, but that discretion is bounded because overly optimistic internal models can understate capital needs. For the agent architecture, this means Basel output must always be tied to methodology and regulatory floor logic, not only to the raw portfolio data.

### 8. Leverage Ratio, LCR, and NSFR
The next Basel lesson addresses the areas where risk-weighting is not enough. The leverage ratio strips out risk weights and asks how much Tier 1 capital stands behind total exposure. LCR asks whether the bank can survive a 30-day liquidity stress using high-quality liquid assets. NSFR asks whether long-term funding is structurally stable over a one-year horizon. The lesson uses crisis logic to explain why these measures exist: a bank can look well capitalized in risk-weighted terms and still fail from excessive leverage or funding fragility. The chapter therefore broadens solvency into resilience. A banking agent that only knows CET1 and RWA still misses failure modes that regulators now treat as core.

### 9. AML/KYC: The Three Lines of Defence
The financial-crime pillar begins with governance and responsibility. This lesson defines customer due diligence, enhanced due diligence, politically exposed person treatment, beneficial ownership checks, and the three lines of defence model. The key point is that AML is not only a list of red flags. It is an operating structure that allocates responsibility across front-line business teams, compliance oversight, and internal audit. The lesson also draws an important legal boundary around SAR obligations and tipping-off risk. This is where the chapter makes clear that some banking outputs are high-stakes enough that the system design must protect against disclosure errors, weak escalation, and improper automation.

### 10. Transaction Monitoring, ML Evolution, and SAR Filing
After onboarding and governance, the chapter moves to transaction flow. This lesson explains why traditional rules-based monitoring produces massive false-positive burdens and why machine learning is being introduced to improve prioritization and pattern detection. But the chapter does not treat ML as autonomy. It is still embedded in a defined alert-to-SAR workflow, and the tipping-off prohibition remains a hard design constraint. The lesson therefore reframes transaction monitoring as a pipeline problem: detect, investigate, escalate, decide, file, and protect confidentiality throughout. Its practical message is that better detection is useful only if the surrounding control system is designed to preserve legal and operational boundaries.

### 11. Cross-Pillar Integration: When IFRS 9, Basel, and AML Collide
This is the chapter's integrating lesson. It shows how a single trigger such as fraud discovery, sanctions exposure, or borrower deterioration can force action across all three pillars at once. An AML event may trigger an IFRS 9 stage migration. A provision increase then reduces retained earnings and therefore CET1. The lesson treats the resulting chain not as a special case but as the real banking problem the chapter has been building toward. Banks do not report three disconnected answers to the board. They need one integrated answer that traces the event through accounting, capital, and financial-crime consequences. This lesson is the clearest justification for the router architecture taught earlier.

### 12. Exercises: IFRS 9 Deep Practice
The first deep-practice block turns the accounting pillar into applied judgment. The exercises use a UK mortgage portfolio and a GCC corporate setting to force stage decisions, parameter selection, and full ECL reasoning rather than mere formula substitution. The lesson stresses that classification and assumption choice remain human responsibilities even when a skill handles the arithmetic. The point of this section is not speed. It is to make the learner test whether they can defend a staging decision, explain why an exposure belongs in Stage 1, 2, or 3, and understand how those decisions reshape the provision.

### 13. Exercises: Basel and AML Deep Practice
The second exercise lesson does the same for solvency and financial crime. It places capital ratios, stress logic, AML investigation, and sanctions screening into extended cases. The practice design makes the learner work across prescribed regulatory scenarios and case-based suspicious-activity judgments, so the lessons stop feeling like isolated formulas. This section is doing two things at once: reinforcing the mechanics of Basel and AML, and training the user to hold calculation, regulation, and control logic in one frame.

### 14. Bank Reconciliation: Nostro, Suspense, and GL-to-Risk
The reconciliation lesson shifts from domain calculation to data integrity. It explains that bank controls also depend on agreeing records across systems: correspondent accounts, suspense accounts, general ledger records, and risk-system outputs. The most important exercise in chapter terms is the four-way IFRS 9 provision reconciliation, where the model result, ledger, risk system, and reporting source must all tie. This section matters because even correct analytical models can fail operationally if breaks, lags, mispostings, or unmatched items distort what reaches the books and returns. The chapter uses reconciliation to show that banking AI has to care about system flow as much as theoretical correctness.

### 15. Full Banking Agent: Skill Library Build and Capstone
The capstone packages the whole chapter into a reusable operational system. The learner is asked to build four core banking skills, configure scheduled tasks, execute a cross-pillar scenario, and produce a board risk report. This turns the chapter from a body of knowledge into a working banking function. The capstone's logic is that domain competence is not proven by isolated lesson answers. It is proven when the skills can be assembled into repeatable operational workflows, routed correctly, and used to generate management-grade outputs. By the end, the chapter is no longer about learning banking rules. It is about encoding them into a system that knows where its own boundaries are.

### 16. Chapter Quiz
The quiz closes the chapter by testing the full architecture rather than any single formula set. It covers the three regulatory pillars, pillar-aware routing, IFRS 9 staging and ECL, Basel capital and liquidity, AML controls, cross-pillar logic, and reconciliation. In effect, it restates the chapter contract: know the pillars, know how the router chooses and chains skills, know the main calculations inside each pillar, and know how to trace one event or one number across the bank's systems.

## Major supporting points

### Banking regulation is simultaneous, not modular
The chapter keeps returning to the fact that one asset can be governed by multiple frameworks at the same time, so single-domain answers are incomplete by design.

### Architecture matters as much as expertise
The router and skill-library lessons argue that correct banking output depends on how knowledge is partitioned and chained, not only on knowing the formulas.

### IFRS 9 is built around classification before calculation
Staging, SICR, and scenario logic determine the size and timing of provisions before the arithmetic is even run.

### Basel is broader than capital ratios alone
Capital quality, RWA methodology, leverage, and liquidity each address different failure modes, so solvency cannot be reduced to one ratio.

### AML is a control system, not just a detection problem
CDD, EDD, PEP handling, transaction monitoring, SAR workflow, and tipping-off constraints all define what the agent may support and what must remain under controlled escalation.

### Cross-pillar work is the real target state
The chapter's central operational claim is that integrated routing is what makes a banking agent useful to boards, regulators, and risk teams.

### Reconciliation is part of intelligence, not an afterthought
The chapter treats data breaks and system mismatches as first-order banking problems because analytical output is unusable if it does not land correctly in the operational record.

### The capstone defines deployment readiness
A working banking agent is not just a set of calculations. It is a configured skill library, recurring tasks, and a reporting output that can survive operational use.

## Major explanations

### Why a one-pillar banking agent fails
Because a provision answer without capital impact, or an AML answer without accounting consequences, leaves the real decision only partially answered.

### Why routing is necessary
Because the user may ask a banking question in business language, while the system still has to detect which regulatory pillar or combination of pillars is implicated and load the correct skills in order.

### Why stage migration matters so much under IFRS 9
Because moving from 12-month ECL to lifetime ECL often changes provisions dramatically even before a formal default occurs.

### Why Basel needs more than RWA-based ratios
Because crisis experience showed that banks can satisfy risk-weighted metrics and still fail through absolute leverage or funding stress.

### Why AML design has hard boundaries
Because SAR decisions, confidentiality, and tipping-off prohibitions create legal limits on what can be surfaced, to whom, and through which interface.

### Why cross-pillar integration changes management output
Because once the accounting, capital, and financial-crime effects of one event are chained together, the institution gets a decision-ready answer instead of three separate calculations.

### Why reconciliation belongs inside the chapter
Because banking numbers move through multiple systems, and any mismatch between model, ledger, risk engine, and report can make the final result unreliable even when each component looked plausible in isolation.

## What the chapter is really teaching
At the surface level, the chapter teaches banking regulation and the skill primitives needed to automate parts of it. At the structural level, it teaches a broader rule:

1. model the domain around simultaneous constraints,
2. route questions by regulatory meaning,
3. keep each pillar internally rigorous,
4. chain outputs when one pillar changes another,
5. protect hard legal and governance boundaries,
6. verify that outputs reconcile across systems,
7. package the result as reusable operational skills.

## Short conclusion
This chapter argues that banking AI becomes useful only when it stops pretending the bank is made of separate departments and starts treating it as one regulated system. The three-pillar model defines the problem. The router and skill library define the architecture. The IFRS 9, Basel, and AML lessons define the domain logic. Cross-pillar integration and reconciliation show how that logic behaves in the real institution. The capstone then turns all of it into a working banking agent with recurring tasks and a board-level deliverable.
