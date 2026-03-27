# Chapter 37 — People & HR: drilldown summary

## Source entry point
- Chapter overview: https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/people-hr

## What this chapter is doing
Chapter 37 frames HR as an operations and knowledge problem before it frames it as a staffing problem. The chapter’s core claim is that HR teams lose time in three places: repeated information routing, repeated document/process work, and the silent loss of tacit knowledge when people leave. The chapter’s proposed answer is a two-plugin stack, a local configuration file, and four persistent agents that cover the employee lifecycle from policy lookup to offboarding.

The chapter is careful about scope. It assigns repeatable, document-heavy, policy-governed work to agents, but keeps judgment-heavy, high-risk, and dignity-sensitive decisions with human HR professionals. That boundary is repeated across the chapter and functions as its operating rule.

## Chapter structure at a glance
- L01: The Institutional Memory Problem
- L02: Your HR Operations Stack
- L03: Policy Lookup: Self-Service Policy Synthesis
- L04: The HR Knowledge Base Agent: 24/7 Employee Self-Service
- L05: Onboarding: The First 90 Days
- L06: Job Descriptions & Interview Preparation
- L07: Offer Letters & Employment Documents
- L08: Performance Reviews Without Bureaucracy
- L09: Compensation, Talent & Org Planning
- L10: Capturing Institutional Knowledge: Before It Walks Out the Door
- L11: Offboarding and Knowledge Transfer: The Four-Phase Process
- L12: Persistent Agents: Onboarding Orchestrator and Policy Maintenance
- L13: People Analytics & Agent Operations
- L14: Capstone: The Full Employee Lifecycle
- L15: Quick Reference & Central Insights
- Quiz

## Chapter thesis
The chapter’s practical thesis is simple:
1. make explicit HR knowledge easy to retrieve and explain,
2. turn recurring HR admin into fast, structured generation workflows,
3. capture tacit knowledge before departure turns it into loss,
4. reserve sensitive judgment for named humans.

That is the reason for the chapter’s sensitivity labeling model:
- **ROUTINE**: policy summaries, job descriptions, onboarding plans, general employee queries
- **CONFIDENTIAL**: offers, compensation, reviews, talent assessments, reference letters
- **SENSITIVE PERSONAL DATA**: medical, grievance, disciplinary, termination material; never auto-generated and always escalated

## Lesson-by-lesson drilldown

### L01 — The Institutional Memory Problem
Source: https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/people-hr/institutional-memory-problem

The opening lesson establishes the problem model for the chapter. It splits organisational knowledge into:
- **explicit knowledge**: documents, handbooks, policies, HRIS entries, wikis
- **tacit knowledge**: unwritten practice, relationships, escalation instincts, local norms

The chapter treats those as different failure modes. Explicit knowledge exists but is hard to find or decode. Tacit knowledge is not written down at all, so the organisation only notices it when the person holding it leaves.

This lesson also defines the three HR functions where agents help most:
- **information routing**: answering repeated questions that already have written answers
- **process execution**: producing recurring documents and structured workflows
- **institutional knowledge capture**: converting experience in people’s heads into usable records

The lesson also draws the non-negotiable boundary: agents can answer policy questions and structure documents, but not conduct terminations, mediate conflict, weigh grievance evidence, or handle medical and disciplinary matters.

### L02 — Your HR Operations Stack
Source: https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/people-hr/hr-operations-stack

This lesson turns the theory into an implementation model. The chapter relies on a two-plugin architecture:

#### Official plugin: `human-resources`
The overview page says this plugin provides 9 general HR skills, including policy lookup, onboarding, draft offers, interview prep, performance review support, compensation analysis, and related structured workflows.

#### Custom plugin: `hr-operations`
The overview says the custom plugin provides 5 more specialised skills plus 4 persistent agents. Its role is to handle organisation-specific knowledge work, ongoing maintenance, and lifecycle orchestration.

The lesson’s real point is separation of concerns. The official plugin handles reusable HR primitives. The custom plugin handles company-specific process glue, maintenance, and continuous monitoring.

The lesson also establishes `hr.local.md` as the configuration spine for tone, policy references, escalation contacts, jurisdictional rules, and organisation-specific defaults.

### L03 — Policy Lookup: Self-Service Policy Synthesis
Source: https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/people-hr/policy-lookup-self-service

This lesson takes the most common HR interrupt—employees asking for policy explanations—and breaks the work into a more useful output shape.

The chapter’s point is that employees do not want legal prose. They want:
- what the rule means,
- what steps they need to take,
- what exception or escalation path applies.

The `/policy-lookup` skill is described as translating policy text into plain-language guidance with citations back to the source. The output is meant to be accurate enough to trust and readable enough that employees stop routing every question through HR.

The lesson matters because it sets the design pattern for later HR automation: preserve the source of truth, rewrite for comprehension, and expose the escalation path where policy stops being enough.

### L04 — The HR Knowledge Base Agent: 24/7 Employee Self-Service
Source: https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/people-hr/hr-knowledge-base-agent

This lesson defines the chapter’s most important routing distinction:
- **Type 1 / policy queries**: answer directly, cite the source, include escalation contact
- **Type 2 / individual situations**: do not adjudicate; hand off to a named HR contact

That split is the main control mechanism for the whole chapter. Without it, a knowledge-base agent drifts into pseudo-HR judgment. With it, the system remains useful and safer.

The lesson’s practical setting is an employee asking after hours about absence reporting and sick leave. The agent’s job is not to “be HR.” Its job is to answer the policy-governed part quickly, consistently, and with a cited source.

The implication is operational: the organisation gets true self-service for routine questions while keeping private, exceptional, or judgment-heavy cases out of the automated lane.

### L05 — Onboarding: The First 90 Days
Source: https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/people-hr/onboarding-first-90-days

This lesson rejects onboarding-as-calendar-management. Its argument is that many onboarding failures happen because nobody defines what success should look like at 30, 60, and 90 days.

The lesson identifies three recurring failure modes:
- overloaded first days full of presentations and low-retention information
- delayed access, provisioning, and manager coordination
- weak milestone design, where the new hire does not know what “on track” means

The chapter’s answer is a milestone-based onboarding program with role-specific outcomes. The onboarding plan is supposed to include pre-boarding, first-week logistics, and a 30-60-90 structure that tells both manager and employee what progress should look like.

The chapter treats onboarding as a structured operating system, not a welcome ritual.

### L06 — Job Descriptions & Interview Preparation
Source: https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/people-hr/job-descriptions-interview-prep

This lesson takes apart a bad JD: inflated requirements, exclusionary language, no salary range, weak description of the actual work, and no sense of what success looks like.

The lesson’s improvement model is straightforward:
- lead with the real work,
- cut requirement inflation,
- remove coded language and vanity phrasing,
- include salary range where appropriate,
- give candidates a clear sense of the role and team.

It pairs that with structured interview preparation. The aim is to make hiring more legible and less improvisational, both for candidates and for interviewers.

This is one of the clearest examples in the chapter of agents making weak HR writing more usable without turning the process into a black box.

### L07 — Offer Letters & Employment Documents
Source: https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/people-hr/offer-letters-employment-docs

This lesson focuses on recurring employment documents that share a stable structure but vary in names, numbers, negotiated terms, and jurisdiction-specific details.

The lesson argues that these documents are high-frequency but low-novelty. Drafting them manually absorbs HR time while adding little strategic value. The `/draft-offer` workflow is positioned as a way to generate the first draft quickly while preserving review for legal and local compliance.

The chapter also stresses that these outputs are **CONFIDENTIAL**, not routine, and that local law can change. That means the time savings are real, but only inside a workflow that still validates templates, entitlements, and current legal requirements.

### L08 — Performance Reviews Without Bureaucracy
Source: https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/people-hr/performance-reviews

This lesson is built around a common management failure: honest observations that are too vague to become usable feedback.

The `/performance-review` skill is not described as a replacement for manager judgment. It is described as a structuring tool that turns rough notes into:
- specific feedback,
- evidence-backed examples,
- behavioural framing,
- development direction,
- a career-forward discussion.

The chapter’s point is that review systems often fail because they are forms without a thinking framework. The agent supplies the framework, but the manager still supplies the judgment, evidence, and final accountability.

### L09 — Compensation, Talent & Org Planning
Source: https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/people-hr/compensation-talent-org

This lesson links three workflows that are often handled separately but should not be:
- compensation benchmarking with `/comp-analysis`
- internal candidate assessment with `/match`
- team-structure modeling with `/org-planning`

The lesson centers on succession and internal mobility. Its main argument is that “gut feel” is not a succession plan. Internal candidates should be assessed across a defined set of dimensions rather than evaluated informally against an imagined external hire.

The overview page says `/match` evaluates internal candidates across six dimensions. The chapter contract highlights a further principle: motivation matters alongside capability in succession planning. That is a useful correction to the common mistake of treating technical readiness as the whole decision.

The lesson also treats compensation as part of the same system. A promotion decision that is not benchmarked and internally coherent can create downstream inequity and attrition.

### L10 — Capturing Institutional Knowledge: Before It Walks Out the Door
Source: https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/people-hr/institutional-knowledge-capture

This lesson brings the tacit-knowledge problem back into focus. It distinguishes between the knowledge that can be documented after the fact and the knowledge that only emerges through structured extraction from experienced people.

The chapter’s key warning is that knowledge loss is usually not sudden. It accumulates over years as informal decisions, relationship knowledge, escalation instincts, and unwritten workarounds stay inside one person’s head.

The lesson’s purpose is to make capture proactive rather than purely reactive. The `/knowledge` skill is positioned as a way to run structured interviews and produce knowledge articles before resignation turns the work into salvage.

This lesson is central because it connects HR to organisational memory, not just compliance and staffing.

### L11 — Offboarding and Knowledge Transfer: The Four-Phase Process
Source: https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/people-hr/offboarding-knowledge-transfer

This lesson argues that most offboarding processes are too narrow. Many companies treat offboarding as account closure and paperwork. The chapter says that is only one quarter of the job.

It defines four offboarding principles:
- protect the organisation
- preserve institutional knowledge
- create a positive employee departure experience
- support the remaining team

It then gives a four-phase timeline:
1. **departure confirmed**: acknowledge resignation, trigger departure records, schedule exit interview, start handover planning
2. **notice period / handover planning**: produce the handover plan early, not in the final week
3. **exit interview**: run it in week 3, with HR rather than the line manager, and focus on organisational learning
4. **last day checklist**: finish administrative closure once the substantive work is already done

This lesson is one of the stronger operational parts of the chapter because it turns departure into a managed transition rather than a compliance chore.

### L12 — Persistent Agents: Onboarding Orchestrator and Policy Maintenance
Source: https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/people-hr/persistent-agents-orchestrator-maintenance

This lesson introduces continuous monitoring rather than one-off command execution.

The Onboarding Orchestrator is presented as a checkpointing agent. It checks milestone status before problems become Day 1 failures. The example is straightforward: a laptop was never ordered because a request was misrouted, and nobody noticed because nobody was watching.

The Policy Maintenance Agent covers the other half of the chapter’s memory problem. It checks whether policy documents, cross-references, and statutory details remain current.

The lesson matters because it moves from “generate this output for me now” to “watch this process over time and escalate when drift appears.” That is the real transition from tool use to operations.

### L13 — People Analytics & Agent Operations
Source: https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/people-hr/people-analytics-agent-operations

This lesson converts the chapter’s separate workflows into operating signals.

The example dashboard includes:
- weekly knowledge-base volume and topic spikes,
- onboarding completion and exceptions,
- policy maintenance audit results,
- recruiting pipeline flow and bottlenecks.

The point is not just reporting. It is interpretation. A spike in policy questions is treated as evidence that a rollout was unclear. A repeated onboarding exception is treated as a process issue, not a one-off annoyance.

This lesson positions HR analytics as process health monitoring. The agents do the collection and summarisation work, while HR leadership reads the signal and decides what to change.

### L14 — Capstone: The Full Employee Lifecycle
Source: https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/people-hr/capstone-full-employee-lifecycle

The capstone asks the learner to run the full lifecycle for one employee persona, from hiring through onboarding, review, talent assessment, and eventual offboarding/knowledge transfer.

This is not just a recap exercise. It tests whether the learner understands sequencing, handoffs, configuration, and human boundaries across the whole system.

The capstone’s design reveals the chapter’s real claim: these tools are most useful when treated as one connected workflow rather than isolated commands.

### L15 — Quick Reference & Central Insights
Source: https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/people-hr/quick-reference-central-insights

This page acts as the chapter’s reference layer. It restates the central insight in one sentence:

> Explicit knowledge becomes findable without asking a person. Tacit knowledge gets captured before it walks out the door. HR professionals are freed for the 40% that only humans can do.

It then lists command references by plugin, function, sensitivity level, and lesson location. As a working document, this is the page to keep open while implementing the chapter’s stack.

### Quiz
Source: https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/people-hr/chapter-quiz

The quiz scope confirms the intended learning outcomes: institutional memory, the two-plugin architecture, policy synthesis, knowledge-base routing, 30-60-90 onboarding, inclusive JDs, employment documents, reviews, compensation and talent assessment, knowledge capture, offboarding, persistent agents, analytics, and full-lifecycle execution.

## Commands and agents the chapter appears to rely on

### Official `human-resources` plugin
From the overview and quick reference pages, the chapter explicitly names these official commands:
- `/policy-lookup`
- `/onboarding`
- `/draft-offer`
- `/interview-prep`
- `/performance-review`
- `/comp-analysis`

The overview says the official plugin contains 9 skills total, though the retrieved excerpts only expose part of the full list directly.

### Custom `hr-operations` plugin
The overview says the custom plugin contributes 5 skills and 4 persistent agents. The chapter text and references explicitly surface these custom capabilities:
- `/knowledge`
- `/offboard`
- `/match`
- `/org-planning`
- the HR Knowledge Base Agent
- the Onboarding Orchestrator
- the Policy Maintenance Agent
- the Offboarding Knowledge Agent

## The operational logic of the chapter
This chapter is strongest when read as a control system for people operations:
- search and explanation reduce repeated inbound questions,
- structured generation reduces admin writing time,
- persistent agents surface drift before it becomes a failure,
- knowledge capture protects the organisation against attrition,
- sensitivity labels keep the system from wandering into the wrong classes of work.

In that sense, the chapter is less about “HR chatbots” than about routing, structure, memory, and escalation.

## What is solid in the chapter
- The boundary between policy questions and individual-case judgment is clear.
- The separation between routine, confidential, and highly sensitive output classes is explicit.
- Onboarding and offboarding are treated as milestone systems rather than checklists.
- Knowledge capture is recognised as a first-class HR responsibility rather than an afterthought.
- The move from one-off commands to persistent agents is well chosen; it matches how HR failures usually happen: through drift, delay, and missed follow-up.

## Where the chapter needs caution
- Several pages include `[VERIFY]` placeholders, so some numeric and jurisdiction-specific claims are not fully finalised on the site.
- Employment documentation and right-to-work requirements are framed as jurisdiction-sensitive; a live implementation should not trust static templates without current review.
- The chapter’s case studies help make the workflows concrete, but they are still teaching scenarios. Real org complexity will be messier than the examples.
- The architecture is useful only if the knowledge sources are current. A stale knowledge base will automate wrong answers faster.

## Bottom line
Chapter 37 treats HR as a combination of retrieval, workflow design, document generation, institutional memory, and controlled escalation. Its strongest idea is not any one command. It is the system boundary: agents handle repeated, structured, policy-governed work; humans keep responsibility for judgment, dignity, conflict, and risk.

That makes the chapter more credible than a generic “AI for HR” pitch. It is trying to automate the admin load without pretending that the hard parts of HR are reducible to prompts.

## Page sources
- Overview: https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/people-hr
- L01: https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/people-hr/institutional-memory-problem
- L02: https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/people-hr/hr-operations-stack
- L03: https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/people-hr/policy-lookup-self-service
- L04: https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/people-hr/hr-knowledge-base-agent
- L05: https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/people-hr/onboarding-first-90-days
- L06: https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/people-hr/job-descriptions-interview-prep
- L07: https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/people-hr/offer-letters-employment-docs
- L08: https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/people-hr/performance-reviews
- L09: https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/people-hr/compensation-talent-org
- L10: https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/people-hr/institutional-knowledge-capture
- L11: https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/people-hr/offboarding-knowledge-transfer
- L12: https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/people-hr/persistent-agents-orchestrator-maintenance
- L13: https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/people-hr/people-analytics-agent-operations
- L14: https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/people-hr/capstone-full-employee-lifecycle
- L15: https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/people-hr/quick-reference-central-insights
- Quiz: https://agentfactory.panaversity.org/docs/Business-Domain-Agent-Workflows/people-hr/chapter-quiz
