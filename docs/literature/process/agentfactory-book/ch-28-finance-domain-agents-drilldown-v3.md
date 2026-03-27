# Chapter 28 drilldown: Finance Domain Agents

## Scope

This file rebuilds the live chapter from the chapter overview, eleven lesson pages, and the quiz page. The chapter teaches a three-layer finance-agent stack:

1. Claude in Excel as an embedded assistant for work inside one workbook.
2. Cowork finance plugins as agents that run multi-step workflows across tools.
3. Enterprise extensions written as `SKILL.md` files that encode a firm's own judgment, thresholds, templates, and control rules.

Primary chapter source: [Chapter 28: Finance Domain Agents](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/finance-domain-agents)

## Note on the live site

The overview page renders this material as Chapter 28, but several lesson pages still expose older Chapter 17 labels in the sidebar and breadcrumb text. The content sequence is still coherent; the numbering is not fully cleaned up in the current publication.

Sources: [Overview](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/finance-domain-agents), [Lesson 2 example of old numbering](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/finance-domain-agents/understanding-workbooks-you-didnt-build)

## Chapter thesis

The chapter argues that finance is a natural first domain for production agents because Excel already sits at the center of professional judgment. The teaching sequence begins with workbook-level intelligence, moves to cross-application orchestration, and ends with firm-specific extensions. The chapter treats those as related layers of one system rather than separate products.

Source: [Overview](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/finance-domain-agents)

## What the chapter is trying to teach

The overview frames five outcomes. You should be able to understand inherited models, test scenarios, diagnose spreadsheet errors, and build model structures inside Excel. You should also be able to install and use two finance plugin families: the corporate finance plugin for close and accounting work, and the investment-oriented plugin suite for valuation, research, deal work, and wealth workflows. Past that, the chapter wants you to see that the same connector layer can support both a workbook assistant and a multi-app agent, and that the real enterprise moat comes from extracting your institution's own financial judgment into extensions.

Source: [Overview](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/finance-domain-agents)

## Lesson 1: The Assistant and the Agent

The first lesson draws a hard architectural line. Claude in Excel is an assistant embedded inside one application. It reads the open workbook, traces dependencies, tests scenarios, debugs errors, and can invoke built-in financial skills. Cowork with Excel is different in scope: it treats Excel as one step in a larger workflow and can carry context into PowerPoint and other tools.

A second distinction matters: both environments use the same connector layer. The difference is not connector access but operating scope. In the Excel add-in, connectors serve analysis inside one workbook. In Cowork, the same connectors serve multi-app workflows.

The lesson also splits Claude in Excel into two layers. Layer 1 is general workbook intelligence that works on any spreadsheet. Layer 2 is a set of pre-built finance skills, including three-statement modelling, comps, DCF, earnings work, diligence packs, and presentation support. The practical guidance covers installation, supported platforms, and a security warning: untrusted spreadsheets can contain prompt-injection attempts in cells, formulas, comments, or hidden sheets.

Source: [The Assistant and the Agent](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/finance-domain-agents/the-assistant-and-the-agent)

## Lesson 2: Understanding Workbooks You Didn't Build

This lesson focuses on inherited-model comprehension. The core move is dependency tracing with cell-level citations. Claude in Excel can explain how an output cell is built, trace the chain back through formulas and input cells, and point you to the exact tabs and cell references so you can verify the explanation.

The lesson's operational claim is modest but useful: the assistant accelerates comprehension, but it does not remove the need to check cited cells before you present anything upward. The workflow is trace first, then verify. The worked example ties that discipline to a familiar finance setting: an FP&A analyst inherits a five-tab model before a board call, traces a revenue variance to a unit-volume assumption, then asks which assumptions to change for a recovery scenario.

This is a good example of how the chapter treats iteration. One prompt uncovers the structure. The follow-up prompt turns that structure into a scenario question. The tool is fastest when the user keeps narrowing the question against cited cells.

Source: [Understanding Workbooks You Didn't Build](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/finance-domain-agents/understanding-workbooks-you-didnt-build)

## Lesson 3: Scenarios, Errors, and Model Building

Lesson 3 completes the chapter's workbook-intelligence layer. It covers three tasks.

First, scenario testing. The lesson recommends a precise prompt style: specify the exact cells to change, apply the scenario, inspect the downstream outputs, then undo with `Ctrl+Z` to return to base case. The chapter's point is that this gives you a third option between destructive overwriting and the slower work of building a separate scenario manager.

Second, formula debugging. Claude traces from a visible symptom such as `#REF!`, `#VALUE!`, `#DIV/0!`, `#N/A`, or a circular reference back to the underlying cause. The page treats this as source tracing rather than magical error repair: the assistant explains the break and the likely fix, but the user still confirms the chain.

Third, model-structure drafting. Claude can scaffold tabs, row labels, linked statements, and formula architecture from a plain-language description. The chapter is careful on one point: this removes structural setup work, not analytical judgment. The model still depends on sound assumptions and professional review.

Source: [Scenarios, Errors, and Model Building](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/finance-domain-agents/scenarios-errors-and-model-building)

## Lesson 4: From Assistant to Agent: Cowork Finance Plugins

Lesson 4 is the first real shift in scope. The subject is not the Excel add-in but Cowork as an orchestration layer. The lesson uses the corporate-finance plugin in `knowledge-work-plugins/finance` as the example. It is aimed at controllers, accounting managers, FP&A teams, and internal-audit users.

The page also introduces the chapter's command-versus-skill distinction. Commands are explicit slash-invoked workflows. Skills are passive `SKILL.md` instructions that fire when context matches. That split matters because finance work usually mixes a few named workflows with many smaller judgment rules that should run without a separate command.

The plugin exposes five named commands:

- `/reconciliation` for GL-to-source reconciliation workpapers
- `/journal-entry` for debit-credit entries with rationale and support
- `/variance-analysis` for price-volume-mix analysis with narrative
- `/income-statement` for management P&L output with variance flags
- `/sox-testing` for SOX 404 testing workpapers

The lesson also explains category placeholders such as `~~erp` and `~~data warehouse`. Workflow knowledge stays in the skill files while actual connector mapping lives in `.mcp.json`. The architecture keeps domain logic with knowledge workers and system connection details with IT.

Source: [From Assistant to Agent: Cowork Finance Plugins](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/finance-domain-agents/from-assistant-to-agent)

## Lesson 5: Financial Analysis: The Core Plugin

Lesson 5 changes audience. The corporate-finance plugin is for operational finance. The `anthropics/financial-services-plugins` core plugin is for investment professionals: analysts, bankers, portfolio managers, and researchers. The page stresses one architectural rule: all connectors live in the core plugin, so install order is core first and add-ons second.

The core plugin provides eight commands:

- `/comps`
- `/dcf`
- `/lbo`
- `/3-statements`
- `/competitive-analysis`
- `/debug-model`
- `/check-deck`
- `/ppt-template`

The summary around those commands is straightforward. `/comps`, `/dcf`, `/lbo`, and `/3-statements` generate models and valuation workbooks. `/competitive-analysis` handles market context. `/debug-model` and `/check-deck` validate model and deck integrity. `/ppt-template` registers firm presentation standards. Passive skills then apply conventions around those workflows even when the user does not invoke a command directly.

The lesson's worked example with `/comps` also shows the intended pattern: the command pulls market and model data through configured connectors, builds a structured workbook, and leaves the analyst to judge peer quality, assumptions, and final interpretation.

Source: [Financial Analysis: The Core Plugin](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/finance-domain-agents/financial-analysis-the-core-plugin)

## Lesson 6: Domain Plugins: From Deals to Portfolios

This lesson moves from the shared core to role-specific add-ons. The four built-in add-ons are investment banking, equity research, private equity, and wealth management. Each inherits the core plugin's connectors and modelling commands, then adds workflows and document types tied to that function's own conventions.

The overview table is one of the more useful parts of the lesson. It maps role to plugin and then to named commands. Examples include:

- Investment banking: `/teaser`, `/cim`, `/buyer-list`, `/one-pager`
- Equity research: `/earnings`, `/initiate`, `/thesis`, `/morning-note`
- Private equity: `/source`, `/ic-memo`, `/returns`, `/dd-checklist`
- Wealth management: `/client-review`, `/financial-plan`, `/rebalance`, `/tlh`

The investment-banking page detail makes the pattern concrete. The plugin follows the actual sequence of an M&A process: one-pager, teaser, CIM, buyer list, process letter, merger model, deal tracker. The lesson also mentions partner-built plugins from LSEG and S&P Global, which extend the ecosystem with proprietary data sources.

The last section is the chapter's most explicit boundary statement. Four limits apply across the suite: the plugins do not provide investment advice, their numbers must be verified, they do not validate assumptions for you, and they do not replace audit or professional sign-off.

Source: [Domain Plugins: From Deals to Portfolios](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/finance-domain-agents/domain-plugins-from-deals-to-portfolios)

## Lesson 7: Cross-App Orchestration

This lesson is the clearest statement of the chapter's assistant-versus-agent distinction. A workflow that starts in Excel and ends in PowerPoint without manual transfer is the point where the system stops being a workbook assistant and starts behaving like an agent.

The example is an earnings workflow. Cowork runs `/earnings`, updates the Excel model, calculates beats and misses against consensus, then uses that context to build a client-ready deck in the firm's template. The lesson argues that the real gain is not speed alone. It is structural consistency: the figures in the slides stay tied to the model that produced them.

That is a stronger claim than time saving. It is a claim about reducing transcription risk and preserving context across tools. The lesson also hints at a design discipline for agentic workflows: think about data carriage, transformations, reruns, and rollback instead of thinking only about application switching.

Source: [Cross-App Orchestration](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/finance-domain-agents/cross-app-orchestration)

## Lesson 8: Extracting Finance Domain Knowledge

Lesson 8 applies Chapter 27's knowledge-extraction method to a CFO context. The basic argument is that generic close automation fails at the level of judgment. A standard plugin can compute variances, but it cannot know that a dormant travel account with activity may be a fraud signal, that a Q4 COGS variance is seasonally expected, or that a deferred-revenue drop at this firm leads revenue misses by one quarter.

The page uses that gap to restate the purpose of enterprise skills. The target is not more generic analysis. The target is a first-draft `SKILL.md` that captures the CFO's actual materiality logic, seasonal adjustments, red-flag conditions, and board-format expectations.

This is also where the chapter becomes practical about interview quality. The goal is not to collect generic management clichés. The goal is to push from vague comments to specific rules, thresholds, and actions that can survive translation into explicit instructions.

Source: [Extracting Finance Domain Knowledge](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/finance-domain-agents/extracting-finance-domain-knowledge)

## Lesson 9: Enterprise Extensions: Risk and Compliance

Lesson 9 covers four extensions where firm-specific judgment materially changes outputs: credit risk, regulatory reporting, IPS compliance, and portfolio attribution/risk decomposition. The shared pattern is the one from Chapter 27: state what the generic plugin lacks, identify the institution's own rules, then encode them in `SKILL.md`.

The credit-risk example is the most detailed. The generic system can calculate common metrics, but it does not know your sector leverage thresholds, your ratio package, your management-quality signals, or your non-negotiable escalation rules. The lesson gives concrete examples of what should be written down: leverage thresholds by sector, the five ratios required on the first page of a credit file, qualitative management signals, and unconditional escalation triggers.

The broader point is that risk and compliance work cannot stop at technically correct calculation. It must reflect the institution's own control logic and review triggers.

Source: [Enterprise Extensions: Risk and Compliance](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/finance-domain-agents/enterprise-extensions-risk-and-compliance)

## Lesson 10: Enterprise Extensions: Operations and Strategy

Lesson 10 widens the extension set to treasury and cash management, tax provision and compliance, FP&A and budget ownership, M&A integration, ESG reporting, fund administration and NAV, and insurance workflows. The chapter frames all of them the same way: generic finance logic is real but incomplete because it does not know the institution's policy, structure, data conventions, or sign-off rules.

The treasury section is a good example. A generic plugin cannot know which banks hold which accounts, how sweeps work, what minimum balances are required by currency, or which hedging instruments and tenors are allowed by policy. The tax-provision section makes the same point in a more technical setting: a generic plugin cannot infer jurisdiction mix, permanent versus temporary differences, deferred-tax methodology, or uncertain-tax-position treatment.

This is the chapter's strongest case for extensions as knowledge capture rather than mere customization. The firm is not changing labels. It is encoding policy.

Source: [Enterprise Extensions: Operations and Strategy](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/finance-domain-agents/enterprise-extensions-operations-and-strategy)

## Lesson 11: Your Extension Roadmap and Chapter Summary

The final lesson turns the extension list into a sequencing problem. The framework uses four criteria: frequency of use, current pain level, data availability, and expertise availability. Score candidates on those dimensions, then override the arithmetic when regulatory exposure is present.

The chapter is explicit on that override: compliance-sensitive extensions move forward even when their raw score would not place them first, because the cost of failure is risk rather than inconvenience. The lesson also suggests a first-quarter portfolio of three extension types: one high-volume workflow, one high-risk compliance workflow, and one area where tacit knowledge is most likely to leave the institution.

This closing page then reassembles the chapter's three layers into one architecture: Excel for deep model work, Cowork for cross-tool orchestration, and enterprise `SKILL.md` extensions for institution-specific judgment.

Source: [Your Extension Roadmap and Chapter Summary](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/finance-domain-agents/your-extension-roadmap)

## Quiz page

The quiz page does not expose the question set in the fetched HTML. It does confirm the chapter's intended span: embedded assistant work in Excel, Cowork as an orchestrating agent, and enterprise extensions that encode institution-specific knowledge.

Source: [Chapter 28: Finance Domain Agents Quiz](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/finance-domain-agents/chapter-quiz)

## Compressed synthesis

The chapter's architecture is simple once stripped of the lesson packaging.

Excel work stays close to the workbook. That includes model comprehension, scenario testing, error tracing, and model scaffolding. When the workflow crosses tool boundaries, Cowork and plugins take over. When the workflow depends on a firm's own thresholds, policy rules, control triggers, formats, or judgment, the system needs enterprise extensions written as explicit instructions.

That makes the chapter less about finance theory than about operating boundaries. The assistant is for reasoning inside one artifact. The agent is for carrying work across artifacts. The extension layer is where the institution's own way of doing finance becomes durable enough to automate.

## Source list

- [Overview](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/finance-domain-agents)
- [Lesson 1: The Assistant and the Agent](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/finance-domain-agents/the-assistant-and-the-agent)
- [Lesson 2: Understanding Workbooks You Didn't Build](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/finance-domain-agents/understanding-workbooks-you-didnt-build)
- [Lesson 3: Scenarios, Errors, and Model Building](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/finance-domain-agents/scenarios-errors-and-model-building)
- [Lesson 4: From Assistant to Agent: Cowork Finance Plugins](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/finance-domain-agents/from-assistant-to-agent)
- [Lesson 5: Financial Analysis: The Core Plugin](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/finance-domain-agents/financial-analysis-the-core-plugin)
- [Lesson 6: Domain Plugins: From Deals to Portfolios](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/finance-domain-agents/domain-plugins-from-deals-to-portfolios)
- [Lesson 7: Cross-App Orchestration](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/finance-domain-agents/cross-app-orchestration)
- [Lesson 8: Extracting Finance Domain Knowledge](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/finance-domain-agents/extracting-finance-domain-knowledge)
- [Lesson 9: Enterprise Extensions: Risk and Compliance](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/finance-domain-agents/enterprise-extensions-risk-and-compliance)
- [Lesson 10: Enterprise Extensions: Operations and Strategy](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/finance-domain-agents/enterprise-extensions-operations-and-strategy)
- [Lesson 11: Your Extension Roadmap and Chapter Summary](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/finance-domain-agents/your-extension-roadmap)
- [Quiz](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/finance-domain-agents/chapter-quiz)
