# Chapter 26 Drilldown — The Enterprise Agent Blueprint

Source chapter: [Enterprise Agent Blueprint](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/enterprise-agent-blueprint)

## Note on live numbering

The live site is internally inconsistent. The overview page at the chapter URL renders this material as **Chapter 15**, while the lesson pages and sidebar render the same material as **Chapter 26**. This drilldown follows the current lesson-page numbering and labels it as Chapter 26, while noting the mismatch.

## One-paragraph summary

This chapter defines the enterprise plugin as an inspectable, governable package rather than a black box. It breaks the system into three layers: the **intelligence layer** written by the knowledge worker in `SKILL.md`, the **integration layer** handled through manifests, connectors, commands, agents, hooks, and settings, and the **governance layer** configured at the organisation level. The chapter’s main argument is that enterprise deployment depends less on raw model capability than on ownership clarity, transparent architecture, policy hierarchy, and a controlled path from shadow-mode validation to trusted production use.

## Chapter thesis

The chapter answers a practical enterprise question: what exactly is a Cowork plugin, who owns each part, and what makes it deployable in regulated settings?

Its answer has four parts:

1. A plugin is a **package format** that bundles plain-text and JSON components.
2. A knowledge-work plugin uses that format to turn a general model into a **domain specialist**.
3. Enterprise deployment requires **inspectability**, not just capability.
4. Durable operation depends on **clear separation of responsibility** among the knowledge worker, IT/plugin developers, and the administrator.

---

## Chapter structure

- [Overview](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/enterprise-agent-blueprint)
- [L01 — What a Plugin Actually Is](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/enterprise-agent-blueprint/what-a-plugin-actually-is)
- [L02 — The Intelligence Layer: SKILL.md](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/enterprise-agent-blueprint/the-intelligence-layer-skill-md)
- [L03 — The Plugin Infrastructure](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/enterprise-agent-blueprint/configuration-and-integration-layers)
- [L04 — The Three-Level Context System](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/enterprise-agent-blueprint/three-level-context-system)
- [L05 — The PQP Framework in Practice](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/enterprise-agent-blueprint/agent-skills-pattern-in-practice)
- [L06 — The MCP Connector Ecosystem](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/enterprise-agent-blueprint/mcp-connector-ecosystem)
- [L07 — The Governance Layer](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/enterprise-agent-blueprint/governance-layer)
- [L08 — The Division of Responsibility](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/enterprise-agent-blueprint/division-of-responsibility)
- [L09 — The Cowork Plugin Marketplace](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/enterprise-agent-blueprint/cowork-plugin-marketplace)
- [L10 — Chapter Summary](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/enterprise-agent-blueprint/chapter-summary)
- [Quiz](https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/enterprise-agent-blueprint/chapter-quiz)

---

## Drilldown by page

### Overview

The overview frames the plugin as a bundled architecture containing `SKILL.md` files, MCP connector declarations, slash commands, agents, hooks, and a manifest. It also introduces the chapter’s five deployment questions: what the package contains, how PQP works, how the context hierarchy resolves conflicts, how shadow mode leads to autonomy, and what makes expertise publishable. The lesson flow is architectural rather than procedural: define the package, inspect the intelligence layer, map the infrastructure, resolve policy precedence, validate the skill-writing method, map connector coverage, establish governance, assign ownership, then examine marketplace distribution.

### L01 — What a Plugin Actually Is

This lesson separates three ideas that are easy to blur together:

- **Plugin format**: a self-contained directory of components that Claude/Cowork can discover and load.
- **Knowledge-work plugin**: a plugin that uses that format to encode domain expertise and connect to enterprise systems.
- **Enterprise readiness model**: a separate evaluation lens concerned with identity, instructions, connections, governance, and performance record.

The lesson’s most useful move is the ownership split inside the package. The knowledge worker owns the `SKILL.md` files because they carry domain expertise. IT or plugin developers own manifests, connector declarations, commands, agents, hooks, and operational settings. That split is treated as a governance feature, not bureaucracy.

The lesson also argues that a deployable plugin must be **inspectable by role**. Identity is visible in `plugin.json`, behavioural logic in `SKILL.md`, connectivity in `.mcp.json`, and operational history in logs and admin controls. The chapter treats this inspectability as the key property that allows enterprise use in regulated environments.

### L02 — The Intelligence Layer: SKILL.md

This lesson says the `SKILL.md` is not a config file and not a technical artifact in the ordinary sense. It is a structured Markdown document with YAML frontmatter and plain-English body content, written by the domain expert rather than by a developer.

The chapter’s body methodology is the **Persona–Questions–Principles (PQP) Framework**:

- **Persona** defines professional identity, authority, tone, relationship to the user, and what the agent will not claim to be.
- **Questions** defines scope in two directions: what the agent handles and what it redirects.
- **Principles** defines operating logic for hard cases, including constraints, escalation thresholds, and domain quality standards.

The strongest point here is that **identity handles ambiguity better than a finite rule list**. A carefully written persona gives the agent a professional stance it can fall back on when the exact case was not anticipated. The Questions section then fences the scope so the agent does not hallucinate across adjacent domains. The Principles section turns vague aspirations like “be accurate” into domain-specific checks, thresholds, and stop conditions.

### L03 — The Plugin Infrastructure

This lesson supplies the directory map and narrows the infrastructure to the three files the knowledge worker most needs to understand:

- `.claude-plugin/plugin.json`
- `.mcp.json`
- `settings.json`

The manifest is intentionally minimal: `name`, `description`, `version`, and `author`. That minimalism matters because it prevents people from confusing plugin identity with plugin behaviour. The behavioural logic belongs in `SKILL.md`, while connectivity belongs in `.mcp.json`.

The connector declaration file describes which MCP servers the plugin can use to reach external systems. The knowledge worker is not expected to implement those servers, but does need enough infrastructure literacy to understand whether the plugin can reach a system at all, whether access is read-only or read/write, and whether a failure is content-related or integration-related.

`settings.json` is presented as the file that configures default runtime behaviour, especially the entry agent for the plugin’s main conversation path.

The broader lesson: the knowledge worker does not need to become an engineer, but does need enough architectural fluency to diagnose the right layer when something fails.

### L04 — The Three-Level Context System

This lesson introduces the policy hierarchy that explains why an agent may ignore a perfectly clear instruction in `SKILL.md`.

The three levels are:

1. **Platform context** — set by Anthropic/platform-level runtime constraints.
2. **Organisation context** — set by the Cowork administrator for the whole organisation.
3. **Plugin context** — set by the knowledge worker inside the plugin.

The key operational point is that higher levels can **silently override** lower ones. That means an instruction can fail without any syntactic error in the `SKILL.md`. The correct diagnostic order mirrors the hierarchy:

1. Check platform-level limits.
2. Check organisation-level policies and admin controls.
3. Check the plugin-level instruction last.

This is a useful corrective because most knowledge workers will start by rewriting the skill. The chapter argues that this is often the wrong first move.

### L05 — The PQP Framework in Practice

This lesson moves from abstract structure to a worked example. It presents a full financial-research `SKILL.md` body and explains how each section behaves under pressure.

The chapter’s standard of “production-ready” comes through clearly here. A strong Persona does not flatter the agent or advertise it. It sets a credible professional stance, including how the agent treats uncertainty and what authority it refuses to claim. A strong Questions section names in-scope work and also names adjacent areas that must be redirected. A strong Principles section does not stop at values. It encodes concrete domain checks, threshold conditions, source requirements, and escalation triggers.

The governing distinction is between **generic prose** and **functional prose**. “Be accurate” is generic. “Cite consensus source, flag stale revisions, do not extrapolate beyond the data” is functional. The lesson’s purpose is to teach the reader how to recognise that difference in their own drafts.

### L06 — The MCP Connector Ecosystem

This lesson treats connectors as a reference landscape rather than a memorisation exercise. It maps the official ecosystem as of early 2026 and groups connectors by business function.

The core enterprise connector set covers categories such as:

- CRM and sales
- Communication
- Document and knowledge systems
- Data and analytics

The point is not that the official marketplace covers every enterprise system. The point is that the plugin model already has enough connector surface area to make many business-domain agents useful, and that uncovered systems are expected to be handled through custom connector work.

This lesson also tightens the separation between the knowledge worker’s job and IT’s job. The knowledge worker specifies the systems and workflows they need. IT or developers implement, configure, and secure the actual connector path.

### L07 — The Governance Layer

This lesson rejects the common idea that governance merely slows deployment. In this model, governance is what makes deployment possible.

It identifies four governance components:

1. **Permissions and access control**
2. **Audit trails**
3. **Shadow mode**
4. **Human-in-the-loop gates**

Permissions come from the organisation’s existing identity and role system, not from the `SKILL.md`. Audit trails make the plugin defensible by recording user, timestamp, data access, and output history. Shadow mode is the chapter’s bridge from promise to trust: the agent runs in a monitored, reviewed state before autonomous use is allowed.

The shadow-mode protocol is concrete: at least **30 days** of operation and at least **95% accuracy** across a representative sample judged against a domain-specific rubric. The lesson treats this as a professional standard, not a suggestion.

Human-in-the-loop gates are framed narrowly and correctly. They are not there because the model “might make mistakes” in a generic sense. They exist where a workflow requires human accountability, judgment, or sign-off.

### L08 — The Division of Responsibility

This lesson turns the architecture into an ownership map. A plugin has three owners:

- **Knowledge worker** — owns the intelligence layer (`SKILL.md`)
- **IT / plugin developers** — own the integration layer (connectors, commands, agents, manifest, related infrastructure)
- **Administrator** — owns the governance layer (access, logging, shadow mode controls, approval routing)

The lesson’s value is diagnostic clarity. If the wrong jurisdictional standard is encoded in the Principles section, that is a knowledge-worker problem. If a connector returns stale or broken data, that is an IT/plugin problem. If junior staff can access a workflow that should be restricted, that is an administrator problem.

This sounds simple, but the chapter’s point is that without an explicit ownership model, enterprise agents do not fail loudly. They drift.

### L09 — The Cowork Plugin Marketplace

This lesson explains how expertise can become a product without pretending that general templates can replace institutional specificity.

The marketplace distributes two broad kinds of offerings:

- **Vertical skill packs** — domain-specific `SKILL.md` templates that encode general best practice
- **Connector packages** — reusable integration bundles that simplify access to common systems

A vertical skill pack provides architecture and professional structure, not the subscriber’s proprietary standards, routing rules, or jurisdictional specifics. The subscriber still has to adapt the pack with local knowledge. The lesson is explicit about that boundary.

The economic thesis is that good skill architecture has publishable value because it compresses months of structural thinking into a reusable starting point. What remains non-transferable is the organisation’s private standards and operating context.

### L10 — Chapter Summary

The summary page ties the architecture together in the order the chapter built it. The package definition leads to the intelligence layer; the intelligence layer raises the infrastructure question; infrastructure raises the policy-precedence question; precedence leads to governance; governance creates the need for an explicit ownership model; the ownership model then makes marketplace distribution intelligible.

That sequencing matters. The chapter is not a grab-bag of plugin concepts. It is an argument about how enterprise deployment becomes manageable once each layer is visible and assigned.

### Quiz

The quiz page positions the assessment around plugin architecture, PQP, governance, ownership, and marketplace concepts. It functions less as memorisation and more as a check that the reader can now describe the plugin as a governed system rather than as an opaque AI feature.

---

## Core concepts extracted from the chapter

### 1) The plugin is not the model

The chapter treats the plugin as the operational wrapper that makes a model usable inside a business domain. The model may supply general reasoning ability, but the plugin supplies identity, scope, constraints, data reach, and organisational legitimacy.

### 2) `SKILL.md` is the centre of domain transfer

The knowledge worker’s main contribution is not prompt tweaking in the loose sense. It is authorship of a structured professional document that captures domain stance, scope, and operating logic.

### 3) Policy hierarchy outranks skill text

When behaviour conflicts with the skill, do not assume the skill is wrong first. Higher-level policies can suppress lower-level instructions.

### 4) Governance is a deployment prerequisite

Permissions, logging, review periods, and escalation paths are treated as architectural requirements for trust.

### 5) Ownership clarity is part of reliability

The system is designed to be diagnosable because each layer belongs to someone who can change it.

### 6) Publishable expertise is general structure, not private policy

The marketplace can distribute reusable domain architecture, but subscribers must still inject their own institutional specifics.

---

## What this chapter is really doing

At bottom, this chapter turns “enterprise agent” from a marketing phrase into a systems concept. It does that by replacing vague enthusiasm with a package model, a writing method, a policy hierarchy, a governance standard, and an ownership map.

That is why the chapter matters. Without these pieces, “agent deployment” stays hand-wavy. With them, it becomes a design problem that can be inspected, tested, governed, and assigned.

---

## Source links by page

- Overview: <https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/enterprise-agent-blueprint>
- L01: <https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/enterprise-agent-blueprint/what-a-plugin-actually-is>
- L02: <https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/enterprise-agent-blueprint/the-intelligence-layer-skill-md>
- L03: <https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/enterprise-agent-blueprint/configuration-and-integration-layers>
- L04: <https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/enterprise-agent-blueprint/three-level-context-system>
- L05: <https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/enterprise-agent-blueprint/agent-skills-pattern-in-practice>
- L06: <https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/enterprise-agent-blueprint/mcp-connector-ecosystem>
- L07: <https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/enterprise-agent-blueprint/governance-layer>
- L08: <https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/enterprise-agent-blueprint/division-of-responsibility>
- L09: <https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/enterprise-agent-blueprint/cowork-plugin-marketplace>
- L10: <https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/enterprise-agent-blueprint/chapter-summary>
- Quiz: <https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/enterprise-agent-blueprint/chapter-quiz>
