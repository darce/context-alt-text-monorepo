# Chapter 31 Drilldown: Islamic Finance Domain Agents

## Scope and source note

This file rebuilds the chapter from the live Panaversity pages for the Islamic finance chapter, then compresses the chapter into a lesson-by-lesson summary.

Two publication mismatches are live on the site and matter:

- The overview page still renders this material as **Chapter 20**, while the lesson pages and sidebar render it as **Chapter 31**.
- The overview page's lesson flow omits **Trade & Partnership Finance: Salam, Istisna'a, Mudaraba, Musharaka**, even though the lesson exists in the live sidebar and page sequence.
- The overview says the chapter includes **14 practice exercises**, but the final capstone page is labeled **Exercise 15**.

## Source pages

### Overview
- [Islamic Finance Domain Agents overview](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/islamic-finance-domain-agents)

### Lessons
1. [Why Islamic Finance Needs Jurisdiction-Aware Agents](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/islamic-finance-domain-agents/why-islamic-finance-needs-jurisdiction-agents)
2. [The Global Standards Map: Three Regimes, One Transaction](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/islamic-finance-domain-agents/global-standards-map)
3. [The Plugin Architecture: Router, Product Skills, Jurisdiction Overlays](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/islamic-finance-domain-agents/plugin-architecture)
4. [Murabaha: Cost-Plus Financing Across Jurisdictions](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/islamic-finance-domain-agents/murabaha)
5. [Ijarah and IMB: Four-Jurisdiction Lease Accounting](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/islamic-finance-domain-agents/ijarah-imb)
6. [Sukuk: Global Islamic Capital Markets](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/islamic-finance-domain-agents/sukuk)
7. [Takaful and IFRS 17: Islamic Insurance](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/islamic-finance-domain-agents/takaful-ifrs17)
8. [Trade & Partnership Finance: Salam, Istisna'a, Mudaraba, Musharaka](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/islamic-finance-domain-agents/trade-partnership-finance)
9. [Malaysia Sukuk: The World's Largest Market](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/islamic-finance-domain-agents/malaysia-sukuk)
10. [Saudi Arabia: Vision 2030, ZATCA Zakat, and Al Rajhi](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/islamic-finance-domain-agents/saudi-arabia)
11. [UK Islamic Banking: IFRS, PRA/FCA, and HMRC](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/islamic-finance-domain-agents/uk-islamic-banking)
12. [Nigeria Sovereign Sukuk: African Infrastructure Finance](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/islamic-finance-domain-agents/nigeria-sovereign-sukuk)
13. [Global Zakat Accounting](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/islamic-finance-domain-agents/global-zakat)
14. [Shariah Portfolio Screening: Global Standards](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/islamic-finance-domain-agents/shariah-screening)
15. [AAOIFI vs IFRS: Full Financial Statements](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/islamic-finance-domain-agents/aaoifi-vs-ifrs-capstone)
16. [Cross-Border Islamic Banking Group: Consolidation](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/islamic-finance-domain-agents/cross-border-consolidation)
17. [Islamic Fintech: Accounting for New Structures](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/islamic-finance-domain-agents/islamic-fintech)
18. [Full Islamic Finance Agent: SKILL.md Library Build](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/islamic-finance-domain-agents/full-skill-library-capstone)
19. [Chapter 31 quiz](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/islamic-finance-domain-agents/chapter-quiz)

## Chapter thesis

The chapter's claim is simple: Islamic finance breaks the one-jurisdiction assumption used by ordinary finance agents. The same commercial transaction can be arithmetically identical yet still require different income labels, balance-sheet captions, disclosures, and escalation rules across Bahrain, Malaysia, Saudi Arabia, the UK, Pakistan, and other markets. The chapter answers that problem with a layered architecture: route first by jurisdiction and product, apply shared accounting mechanics second, then apply jurisdiction-specific overlays last.

A second claim runs through the chapter. The agent is allowed to execute accounting treatment, generate entries, assemble statements, and flag compliance risks. It is not allowed to make Shariah judgments that belong to a Shariah Supervisory Board. That division is treated as a design constraint, not as a footnote.

## What the chapter adds to the earlier finance chapters

The previous finance chapters trained agents inside a single regime. This one trains an agent to switch regimes without smearing one jurisdiction's assumptions onto another. The transferable pattern is broader than Islamic finance. The chapter explicitly presents the router -> product skill -> jurisdiction overlay stack as a general solution for any domain where the same business event produces different compliant outputs by country or regulator.

## The chapter's operating model

### 1. Three accounting regimes

The chapter reduces a messy twenty-jurisdiction map into three practical buckets:

- **AAOIFI primary**: jurisdictions where AAOIFI accounting standards control the presentation.
- **IFRS or IFRS-equivalent with Islamic guidance**: jurisdictions where IFRS mechanics dominate, but Islamic terminology, disclosures, or local overlays still matter.
- **Local standards**: jurisdictions that blend local accounting requirements with Islamic finance treatment.

That compression matters because it turns the agent's first problem into classification. Before any entry, schedule, or statement, the agent has to answer: which regime am I in?

### 2. Three-layer skill architecture

The technical answer is a three-layer stack:

1. **Base finance plugin** for generic accounting commands.
2. **Product skills** for the shared mechanics of murabaha, ijarah, sukuk, takaful, zakat, screening, and related products.
3. **Jurisdiction overlays** for the labels, presentation, regulatory references, disclosures, and prohibitions that vary by market.

The chapter repeats one ordering rule: product rules first, overlay rules second. Arithmetic lives in the product skill. Compliance wording and presentation live in the overlay.

### 3. Boundary rule

The agent can classify, compute, draft, reconcile, screen, and schedule. It must escalate when the task turns into a Shariah ruling, a board judgment, or a borderline interpretation that the standards do not settle.

## Lesson-by-lesson drilldown

### Lesson 1: Why Islamic Finance Needs Jurisdiction-Aware Agents

This lesson states the problem in the cleanest possible form. A murabaha with the same economics can be labeled and presented differently in Bahrain, Malaysia, and the UK, so a generic finance agent that defaults to one framework will be wrong almost everywhere else.

It also fixes the doctrinal base for the rest of the chapter. Islamic finance rests on prohibitions on riba, gharar, and maysir, along with asset-backing, risk-sharing, and ethical screening. The lesson treats those as design constraints that explain why the products exist and why their accounting cannot be treated as cosmetic relabeling.

### Lesson 2: The Global Standards Map: Three Regimes, One Transaction

This page converts the problem into a routing table. It maps twenty jurisdictions to their primary standards, AAOIFI's role, regulators, and distinctive features, then collapses the map into the three regimes used by the rest of the chapter.

The practical point is sharper than the taxonomy. The agent must declare the governing regime before doing any work. The chapter keeps returning to the same failure mode: the numbers may match while the compliance output does not.

### Lesson 3: The Plugin Architecture: Router, Product Skills, Jurisdiction Overlays

Here the book turns the standards map into agent behavior. The router identifies jurisdiction and product, loads the product skill for the accounting mechanics, then loads the jurisdiction overlay that changes captions, classifications, and disclosures.

This is the chapter's main reusable pattern. A multi-jurisdiction domain does not need one giant monolith. It needs a stable core for the mechanics and narrow overlays for the local rules.

### Lesson 4: Murabaha: Cost-Plus Financing Across Jurisdictions

Murabaha is presented as the chapter's first real test case because it dominates Islamic banking activity in many markets. The lesson insists that murabaha is a sale, not a loan, and treats title transfer, disclosed markup, and valid contract formation as structural requirements rather than ceremonial details.

The lesson's accounting point is that murabaha often produces the same arithmetic across regimes while still requiring different labels, classifications, and statement presentation. That makes it the clearest example of why overlays are compliance logic rather than wording polish.

### Lesson 5: Ijarah and IMB: Four-Jurisdiction Lease Accounting

This lesson introduces a more serious divergence. In murabaha, the tension often sits in terminology and presentation. In ijarah and IMB, AAOIFI and IFRS can produce materially different balance-sheet outcomes.

The key source of divergence is ownership. AAOIFI and IFRS agree on pure operating leases more often than they do on lease-to-own structures. Once ownership transfer and finance-lease style economics appear, the regime differences start to matter for assets, liabilities, and regulatory ratios.

### Lesson 6: Sukuk: Global Islamic Capital Markets

The chapter shifts from bank-customer financing to globally traded instruments. Sukuk are framed as ownership certificates tied to underlying assets or ventures, not simple debt instruments.

The lesson centers on two accounting questions. On the issuer side, the hard problem is derecognition of the underlying assets and the liability-versus-equity analysis. On the investor side, the hard problem is classification, especially the SPPI test under IFRS-style regimes. The page also flags the industry's attention to AAOIFI Draft Standard 62 and the controversy around purchase undertakings, because both cut straight into the question of whether many sukuk structures are really asset-based or truly asset-backed.

### Lesson 7: Takaful and IFRS 17: Islamic Insurance

Takaful changes the shape of the accounting question. The central issue is not just measurement. It is identity: who actually bears the insurance risk?

The lesson distinguishes the participants' risk fund from the operator and walks through wakala, mudaraba, and hybrid operating models. The accounting consequence is that the operator manages the structure and earns fees or profit shares, but does not automatically occupy the same position as a conventional insurer.

### Lesson 8: Trade & Partnership Finance: Salam, Istisna'a, Mudaraba, Musharaka

This lesson fills out the product library beyond the chapter's headline products. Salam and istisna'a cover advance purchase and construction-style structures. Mudaraba and musharaka cover profit-sharing and joint-venture logic.

The value of this page is architectural. It shows that the product layer cannot stop at the most common retail products. A usable Islamic finance agent needs explicit mechanics for trading, manufacturing, partnership, and investment structures that behave differently from both conventional loans and one another.

### Lesson 9: Malaysia Sukuk: The World's Largest Market

Malaysia is used as the main case for an IFRS-equivalent jurisdiction that still has a dense Islamic capital-markets infrastructure of its own. The lesson uses Malaysia to anchor the chapter's claim that a jurisdiction can be IFRS-led and still require a strong local overlay.

The operational point is that scale changes the importance of the overlay. If one country accounts for a large share of global sukuk issuance, the local regulatory and disclosure details are not edge cases. They are core production rules for any serious agent.

### Lesson 10: Saudi Arabia: Vision 2030, ZATCA Zakat, and Al Rajhi

Saudi Arabia is the chapter's most useful corrective to superficial assumptions. The page states directly that Saudi Islamic banks apply IFRS as adopted in the Kingdom, not AAOIFI financial accounting standards as their primary basis.

The distinctive Saudi feature is zakat. The chapter gives ZATCA's equity-based formula and contrasts it with AAOIFI or Hanafi asset-based approaches. It also uses Al Rajhi as the benchmark for Saudi IFRS Islamic banking presentation and emphasizes a strict wording rule: do not use interest terminology in Saudi Islamic banking output.

### Lesson 11: UK Islamic Banking: IFRS, PRA/FCA, and HMRC

The UK lesson shows how Islamic finance operates in a Western market with standard IFRS regulation, prudential supervision, tax-equivalence rules, and listed sukuk activity. The page's lesson is that Islamic finance in the UK is not a doctrinal exception bolted onto the side of conventional regulation. It is an IFRS-governed market with specific product structures, labels, and tax treatment.

For the agent, that means the overlay has to carry PRA, FCA, and HMRC context while keeping the accounting mechanics in the underlying product skills.

### Lesson 12: Nigeria Sovereign Sukuk: African Infrastructure Finance

Nigeria introduces a frontier-market case and uses sovereign sukuk to make a careful accounting point. Changing the financing structure does not automatically rewrite the accounting treatment for every participant in the broader transaction chain.

That matters for agents because Islamic finance terms can tempt a model to over-apply product logic. The page pushes the opposite discipline: only change the accounting where the standard, structure, or party role actually changes it.

### Lesson 13: Global Zakat Accounting

This lesson brings back the cross-jurisdiction problem in a form that is religiously universal but technically unstable. Zakat is the same obligation across the domain, yet the calculation base and resulting liability differ sharply by jurisdiction.

The page contrasts the Saudi ZATCA equity-based approach with other models and treats jurisdiction overlays as necessary even for obligations that every Islamic institution recognizes. The lesson is narrow in content and broad in implication: universality of purpose does not imply uniformity of accounting treatment.

### Lesson 14: Shariah Portfolio Screening: Global Standards

This page is the chapter's screening and purification module. It compares four major screening approaches, starting with shared sector exclusions and then moving to the places where methodologies split: debt thresholds, denominators, cash screens, and non-permissible income handling.

The most important lesson is that the same issuer can be compliant under one methodology and non-compliant under another. The agent can compute the ratios, find the divergence, and calculate purification. It cannot decide the governing methodology on its own when the fund's Shariah policy or SSB judgment is unsettled.

### Lesson 15: AAOIFI vs IFRS: Full Financial Statements

This is the accounting capstone before consolidation. The exercise asks for complete statements for the same bank under two different frameworks, plus a reconciliation of the differences and a review of the audit risk that follows from that gap.

The lesson matters because it forces the chapter's moving parts into one deliverable. Product logic, labels, classification, disclosures, and regime-level presentation differences all have to survive contact with a full set of statements.

### Lesson 16: Cross-Border Islamic Banking Group: Consolidation

Once the chapter reaches group reporting, the previous differences stop being abstract. A Bahrain parent with subsidiaries in UAE, Malaysia, Pakistan, and elsewhere cannot avoid clashes between AAOIFI-primary entities, IFRS entities, and hybrid local overlays.

The lesson turns the earlier pages into consolidation work. The agent must preserve local correctness and still produce a coherent group result. This is where the router-and-overlay design stops being a teaching convenience and becomes necessary infrastructure.

### Lesson 17: Islamic Fintech: Accounting for New Structures

The final thematic lesson moves from established products to cases where the products or delivery channels are ahead of the standards. The page cites digital murabaha, Shariah-compliant robo-advisers, peer-to-peer Islamic lending, and green impact sukuk distributed through apps.

The lesson's point is not that standards disappear. It is that the agent must reason from existing principles and product mechanics while knowing when a new structure exceeds what the installed skill library can settle without escalation.

### Lesson 18: Full Islamic Finance Agent: SKILL.md Library Build

The chapter closes by turning the curriculum into a concrete skill library. The page lays out three layers: one global router, twelve product skills, and thirteen jurisdiction overlays.

The capstone work is operational. Audit every skill, verify the governing standard and the never-rules, add escalation triggers, build the router, identify gaps in the installed library, create a new jurisdiction overlay, test it against product queries, and wire scheduled tasks for daily, monthly, quarterly, and annual workflows. The chapter's architectural claim is strongest here: Islamic finance competence becomes a managed library, not a pile of prompts.

### Quiz page

The quiz confirms the chapter's actual center of gravity. It tests the router-product-overlay design, AAOIFI-versus-IFRS divergence, product mechanics, jurisdiction routing, zakat methods, screening, consolidation, and the line between automated execution and SSB judgment.

## The main practical takeaways

### 1. Jurisdiction is the first branch

The agent must determine jurisdiction before it produces entries, schedules, statements, or disclosures. The chapter treats this as a hard gate.

### 2. Product mechanics and compliance wording belong in different layers

The arithmetic and accounting mechanics sit in product skills. Labels, balance-sheet captions, note disclosures, and regulator-specific constraints sit in overlays.

### 3. Similar economics do not imply interchangeable output

The chapter returns to the same warning across murabaha, ijarah, sukuk, zakat, and screening. Matching numbers are not enough. Labels, classification, presentation, and escalation rules are part of the compliant output.

### 4. Islamic finance is a good teaching case for any multi-jurisdiction agent

The router -> product -> overlay pattern generalizes. Tax, legal, healthcare, and other regulated fields face the same structural problem when one commercial event has different compliant outputs across jurisdictions.

### 5. The Shariah Supervisory Board boundary has to be explicit in the skills

The agent can execute and prepare. It cannot authoritatively resolve every Shariah question. The chapter keeps that boundary visible because the whole system becomes unsafe if the model starts improvising religious judgments as though they were ordinary accounting choices.

## Bottom line

This chapter is less about Islamic finance as a niche specialty than about how to build agents for domains where legal, accounting, and doctrinal variation all matter at once. Islamic finance provides the hardest clean example in the book because the products are distinct, the regimes are explicit, and the outputs diverge in ways that are easy to miss if the model sees only the arithmetic. The chapter's answer is disciplined decomposition: route the query, apply the product mechanics, overlay the jurisdiction, and escalate the judgments that do not belong to the model.
