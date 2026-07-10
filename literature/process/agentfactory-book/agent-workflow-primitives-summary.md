# Summary — Part 2: Agent Workflow Primitives

> Source chapter: [Part 2: Agent Workflow Primitives](https://agentfactory.panaversity.org/docs/Agent-Workflow-Primitives)

## Executive summary

Part 2 is the practical transition from *understanding* general agents to *building with them*. It frames agent work as a progressive skills lab: first control files safely, then add computation, then persistent storage, then deployment, then version control, and finally combine the stack into a working AI Employee. The section’s through-line is not tool memorization; it is learning to decompose real work into agent-solvable tasks, verify results, and preserve outputs so they can be reused later.

## What this part is trying to teach

The chapter presents a consistent operating model for agent work:

1. Describe the need clearly, focusing on the outcome rather than micromanaging steps.
2. Verify that the agent understood the task correctly.
3. Execute in small, reversible steps.
4. Persist the result so the work can be reused.

That pattern is presented as the “General Agent workflow,” and the rest of Part 2 teaches it across increasingly demanding environments.

## The progressive arc

Part 2 is organized as a staircase of capabilities:

- **Files first**: use the agent for survey, cleanup, search, backup, and bulk operations.
- **Then computation**: move from Bash-only workflows to small Python tools when deterministic math and structured parsing are needed.
- **Then storage**: escalate again from scripts to SQL when requirements become relational, persistent, concurrent, or query-heavy.
- **Then operations**: learn how to run agents on real Linux systems instead of a laptop session.
- **Then safety and collaboration**: use Git and GitHub deliberately rather than relying on invisible safety done by the tool.
- **Finally a capstone**: assemble the whole stack into a profession-specific AI Employee.

## Two interfaces, one agent

The part explicitly distinguishes between two modes of interacting with the same general agent:

- **Code / Claude Code** for precise operational work: file processing, data analysis, scripting, and version control.
- **Cowork / Claude Desktop** for iterative work: research synthesis, planning, and document generation.

The point is not that one interface is “better,” but that each is fit for a different kind of work. By the end of the part, the learner is expected to switch between them fluently.

## Mindset the chapter wants to build

The section emphasizes that the hardest skill is not command syntax. It is judgment:

- when to trust the agent,
- when to demand a preview,
- when to test on one item first,
- when to back up,
- when to escalate to a stronger tool,
- and when not to automate further.

This is a serious strength of the material. It treats workflow design, reversibility, and observability as first-class concerns rather than footnotes.

## Chapter-by-chapter breakdown

> **Note on numbering:** the Part 2 landing page currently lists its child chapters as **Chapter 8–13**, but the linked destination pages are titled **Chapter 19–24**. The URLs below reflect the live destination pages.

### 1) File Processing Workflows
**Page:** [Chapter 19: File Processing Workflows](https://agentfactory.panaversity.org/docs/Agent-Workflow-Primitives/file-processing)

This chapter uses file work as the training ground for disciplined agent operation. Its practical framework is:

**Survey → Backup → Design Rules → Test → Execute → Verify → Document**

That is a sound escalation from exploration to irreversible action. The emphasis is safety-first file handling, organization rules, batch renaming/moves, recovery, and search.

### 2) Computation & Data Extraction
**Page:** [Chapter 20: Computation & Data Extraction Workflow](https://agentfactory.panaversity.org/docs/Agent-Workflow-Primitives/computation-data-extraction)

This chapter identifies a real limit of Bash: deterministic decimal math and more robust data parsing. The solution is not “become a Python programmer,” but “have the agent build small Unix-style Python tools” that read from stdin, write to stdout, and compose with shell pipelines.

Representative tools the chapter proposes include:

- `sum.py`
- `sum-expenses.py`
- `extract-column.py`
- `filter.py`
- `stats.py`
- `tax-prep`

The key continuity claim is strong: the language changes, but the workflow does not.

### 3) Structured Data & Persistent Storage
**Page:** [Chapter 21: Structured Data & Persistent Storage](https://agentfactory.panaversity.org/docs/Agent-Workflow-Primitives/structured-data-persistent-storage)

This is the next escalation step. The chapter argues that Python scripts become a dead end once the problem shifts from one-off calculation to evolving questions, multiple users, shared state, relationships, and concurrency. Its core model is:

- **Bash** for movement/orchestration,
- **Python** for deterministic parsing/computation,
- **SQL** for persistence, relationships, and flexible querying,
- **Hybrid verification** only when the risk profile justifies it.

That escalation logic is one of the most important ideas in the whole part.

### 4) Linux Operations for Agent Deployment
**Page:** [Chapter 22: Linux Operations for Agent Deployment](https://agentfactory.panaversity.org/docs/Agent-Workflow-Primitives/linux-mastery)

This chapter moves the work from “runs on my laptop” to “runs as a product.” The target state is a production service that:

- starts on boot,
- restarts on failure,
- logs activity,
- runs under a dedicated non-root user,
- and is secured through SSH keys.

That is the correct operational baseline for any agent expected to do useful unattended work.

### 5) Version Control & Safe Experimentation
**Page:** [Chapter 23: Version Control & Safe Experimentation](https://agentfactory.panaversity.org/docs/Agent-Workflow-Primitives/version-control)

The chapter’s thesis is that Claude Code already uses Git as a hidden safety mechanism, but learners need to understand that safety model explicitly. It covers Git/GitHub setup, local history, cloud backup, and safer experimentation.

This chapter is especially important because it converts “the agent protects me” into “I know how to direct the protection.”

### 6) Build Your AI Employee
**Page:** [Chapter 24: Project – Build Your AI Employee](https://agentfactory.panaversity.org/docs/Agent-Workflow-Primitives/build-first-ai-employee)

The capstone asks the learner to build a real AI Employee for their own profession using NanoClaw. It is organized into three achievement tiers:

- **Bronze**: identity, skill, connection, proof
- **Silver**: proactive behavior, boundaries, memory, value demonstration
- **Gold**: stronger architecture and memory isolation

This is where the previous chapters stop being abstractions and become a deliverable system.

## What is strongest about this part

- It teaches **tool escalation** instead of tool tribalism.
- It treats **verification and reversibility** as default operating rules.
- It recognizes that **deployment and version control** are part of the workflow, not separate disciplines.
- It ends with a **real synthesis project**, which is the correct way to teach this material.

## What to watch critically

- The section uses **product-specific naming** (Claude Code, Claude Desktop, NanoClaw), so some readers may confuse principles with vendor tooling. The durable part is the workflow pattern, not the brand names.
- The **chapter numbering discrepancy** between the Part 2 landing page and the destination pages should be cleaned up; it makes the structure look less stable than it probably is.
- The framework is strongest when treated as **an escalation ladder**, not as “always use more tooling.” Sometimes the right move is to stop at Bash or a small script.

## Referenced setup tools and pages mentioned in Part 2

- [Git Bash](https://gitforwindows.org)
- [Python](https://www.python.org)
- [Git for Windows download](https://git-scm.com/download/win)
- [NanoClaw](https://github.com)

## Sources

### Primary source
- [Part 2: Agent Workflow Primitives](https://agentfactory.panaversity.org/docs/Agent-Workflow-Primitives)

### Linked chapter sources
- [Chapter 19: File Processing Workflows](https://agentfactory.panaversity.org/docs/Agent-Workflow-Primitives/file-processing)
- [Chapter 20: Computation & Data Extraction Workflow](https://agentfactory.panaversity.org/docs/Agent-Workflow-Primitives/computation-data-extraction)
- [Chapter 21: Structured Data & Persistent Storage](https://agentfactory.panaversity.org/docs/Agent-Workflow-Primitives/structured-data-persistent-storage)
- [Chapter 22: Linux Operations for Agent Deployment](https://agentfactory.panaversity.org/docs/Agent-Workflow-Primitives/linux-mastery)
- [Chapter 23: Version Control & Safe Experimentation](https://agentfactory.panaversity.org/docs/Agent-Workflow-Primitives/version-control)
- [Chapter 24: Project – Build Your AI Employee](https://agentfactory.panaversity.org/docs/Agent-Workflow-Primitives/build-first-ai-employee)
