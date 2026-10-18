# Chapter 15 drilldown: Effective Context Engineering with General Agents

Source chapter: [Chapter 15: Effective Context Engineering with General Agents](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/context-engineering)

## Source record

- Chapter title: *Chapter 15: Effective Context Engineering with General Agents*
- Publisher/site: Agent Factory / Panaversity
- Last-updated stamp on overview page: Feb 10, 2026
- Scope covered here: overview, 10 lessons, exercises, and chapter quiz

## Chapter thesis

In *Chapter 15: Effective Context Engineering with General Agents*, the course argues that context quality is the main factor that separates a cheap, unreliable general-purpose agent from a dependable domain agent. The chapter develops that claim by showing how context fails, how to reduce waste in the context window, how to place information in the right mechanism, how to preserve state across resets and sessions, how to inject the right knowledge at the right moment, and how to keep multi-agent workflows from contaminating one another. The chapter closes by treating context engineering as a production discipline for building Digital FTEs that stay consistent across time, tasks, and sessions.

## What the chapter is doing overall

The chapter treats context as an engineering surface, not as a passive container. The recurring argument is that raw model quality is not enough because the same frontier models are widely available. What creates paid value is an agent that keeps track of the right constraints, sheds irrelevant material, persists decisions across resets, and applies domain knowledge without drifting.

The overview page frames the chapter around ten lessons. Those lessons move from diagnosis to architecture, then to operations, then to multi-session and multi-agent design. The exercises turn the ideas into a measurement problem, and the quiz checks whether the reader can choose the right intervention for a real context failure.

## Lesson-by-lesson drilldown

### 1) What Is Context Engineering?

This lesson defines context engineering as the discipline of choosing the smallest set of high-signal tokens that maximizes the odds of the desired outcome. It distinguishes prompt from context and argues that the prompt is only a tiny fraction of what the model processes. The lesson also introduces four failure modes of context rot: poisoning from outdated information, distraction from tangents, confusion between similar concepts, and clash between contradictory instructions.

Operationally, the lesson teaches the reader to inspect the session rather than trust intuition. It points to Claude Code's `/context` command, notes that much of the budget is already consumed before any user message, and presents autocompact as a partial but not sufficient answer.

Source: [What Is Context Engineering?](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/context-engineering/manufacturing-quality-problem)

### 2) Signal vs Noise: Auditing Your Context for Quality

This lesson asks a stricter question: how much of `CLAUDE.md` is actually earning its place in the context window? It introduces an instruction-limit argument, claiming that instruction-following degrades beyond a certain number of active rules, and then gives a four-question audit for every line of persistent context:

- Would the agent ask about this if it were missing?
- Could it infer this from existing materials?
- Does it change often?
- Is it already a standard convention the model knows?

The lesson then turns that audit into a filtering rule. Keep project-specific constraints, unusual style rules, review requirements, naming conventions, and non-obvious gotchas. Remove defaults, stale operational details, file-by-file descriptions, and anything already evident from the workspace. It also adds a placement rule: high-priority material belongs at the beginning or end of the window because the middle receives less attention.

Source: [Signal vs Noise: Auditing Your Context for Quality](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/context-engineering/signal-vs-noise)

### 3) Context Architecture

This lesson explains when to use `CLAUDE.md`, Skills, Subagents, and Hooks by tying each tool to a loading pattern.

- `CLAUDE.md` loads at session start and stays relevant only if its contents are needed for nearly every task.
- Skills advertise themselves cheaply at the start, then load their full contents only when invoked or judged relevant.
- Subagents work in isolated context and return summaries rather than their full working state.
- Hooks run outside the main session and therefore cost little or nothing in the main context budget unless they emit messages.

The point is architectural, not just tactical. Always-loaded material should be rare and stable. Domain procedures that matter only sometimes belong in Skills. Broad search, analysis, or parallel work should move to Subagents. Deterministic checks belong in Hooks. The lesson also names common mistakes, especially stuffing everything into `CLAUDE.md` and avoiding Subagents during research-heavy work.

Source: [Context Architecture](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/context-engineering/context-architecture)

### 4) The Tasks System: Persistent State for Context Management

This lesson addresses the problem of ephemeral planning. If the roadmap for a complicated job lives only inside the chat, a reset destroys the plan along with the noise. The Tasks system fixes that by moving task state onto the filesystem. In the chapter's framing, this makes aggressive clearing and compaction safe because the plan survives outside the conversation.

The lesson also treats task dependencies as a graph problem rather than a note-taking problem. Once work items and their dependencies live on disk, the agent can resume with less re-briefing and less fear of losing sequencing logic. The practical shift is simple: project state should live in persistent artifacts, not in a fragile conversational thread.

Source: [The Tasks System: Persistent State for Context Management](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/context-engineering/tasks-system)

### 5) The Two-Way Problem: Getting Tacit Knowledge In and Out

This lesson argues that high-value expertise often lives outside formal documentation. The agent can read documents, but documents usually miss the small judgments that experienced practitioners make automatically. The chapter calls this the first half of the two-way problem: getting tacit knowledge from the professional into artifacts that the agent can actually use.

The second half is less obvious and more demanding: getting the agent's reasoning back into a form that the professional can understand, review, defend, and maintain. The lesson's core warning is that many teams focus only on writing instructions for the model and neglect the harder job of making the resulting work legible to the human who remains accountable for it.

Source: [The Two-Way Problem: Getting Tacit Knowledge In and Out](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/context-engineering/tacit-knowledge)

### 6) Context Lifecycle: Knowing When to Reset vs Compress

This lesson moves from theory to operating thresholds. It proposes a zone model for context utilization:

- 0-50%: work freely
- 50-70%: monitor and prepare
- 70-85%: compact now
- 85-95%: emergency compaction
- 95%+: reset required

The lesson's argument is that context maintenance should happen before quality visibly collapses. A reset is appropriate when the task is complete or the session has accumulated too much contamination to salvage. Compaction is appropriate when continuity still matters and the reader can name exactly what must survive. The real method is diagnostic: inspect the current state, decide whether continuity is worth preserving, and preserve only the parts that still matter.

Source: [Context Lifecycle: Knowing When to Reset vs Compress](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/context-engineering/context-lifecycle)

### 7) Long-Horizon Work: Progress Files and Session Architecture

This lesson rejects the idea that one conversation should stretch across a multi-day project. Long jobs cross natural session boundaries, and resumed sessions accumulate old tangents. The proposed fix is a harness architecture built around a shared progress file.

The initializer agent creates the task structure, baseline decisions, and the initial progress artifact. Each later working session reads that file, chooses the next incomplete task, does the work, and writes back. The continuity mechanism is the file, not the lingering chat history. The practical gain is that each session can start clean while still inheriting the state that matters.

Source: [Long-Horizon Work: Progress Files and Session Architecture](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/context-engineering/progress-files)

### 8) Mid-Stream Memory: Injecting Context at Execution Time

This lesson focuses on timing. A memory injected at turn 1 may still be technically present at turn 20, but it may no longer receive useful attention or match the current micro-task. The chapter names the resulting failure workflow drift.

The answer is to move from one-time upfront memory loading toward execution-time injection. In the page's architecture, `PreToolUse` hooks can inject reminders or domain memories right before a specific action, when those facts are locally relevant. The lesson also stresses that memory quality matters: the memory store should contain reusable high-value knowledge, not a dump of everything the team has ever learned.

Source: [Mid-Stream Memory: Injecting Context at Execution Time](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/context-engineering/memory-injection)

### 9) Context Isolation: Why Clean Slates Beat Dirty States

This lesson explains why naive multi-agent pipelines often perform worse than a disciplined single-agent workflow. If each downstream agent inherits the entire upstream context, it also inherits exploratory dead ends, irrelevant reads, tool noise, and discarded reasoning. The final agent then works inside a polluted window where the real signal is buried.

The remedy is context isolation. Each subagent should start from a clean slate, receive only the input needed for its own job, and return a compact summary or artifact rather than its full working history. The lesson frames this as a coordination rule for multi-agent systems: pass outputs, not accumulated process.

Source: [Context Isolation: Why Clean Slates Beat Dirty States](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/context-engineering/context-isolation)

### 10) The Context Engineering Playbook: Decision Frameworks for Quality

The capstone lesson turns the earlier material into a decision tree. It asks the practitioner to diagnose the concrete failure mode first, then choose the matching intervention. If utilization has crossed the 70% threshold, compact or clear based on whether the current task still needs continuity. If work spans multiple agents, isolate contexts and communicate through summaries. If knowledge is needed at a specific step rather than globally, inject it at execution time. If the plan must survive resets, move it into persistent tasks or progress files.

This lesson also reconnects the chapter to the book's larger thesis. Commodity model access does not explain the difference between a low-value assistant and a high-value one. Reliability, consistency, reusable domain knowledge, and disciplined context management do.

Source: [The Context Engineering Playbook: Decision Frameworks for Quality](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/context-engineering/context-engineering-playbook)

## Exercises

The exercises turn the chapter into a controlled before-and-after study. The running case is a contract review agent that begins in a degraded state: it misses risks, contradicts itself, and forgets requirements. Each module applies one of the chapter's techniques, and the claim is that by the end the same agent is more consistent across sessions and less vulnerable to contamination.

The design of the exercise section matters because it treats context engineering as measurable system behavior rather than as taste or prompt folklore. The reader is expected to observe changes in output quality after changing context structure.

Source: [Context Engineering Exercises](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/context-engineering/context-exercises)

## Quiz

The quiz is framed as a diagnostic for practitioners who will design long-running agent systems. The emphasis is judgment. The reader is expected to identify tradeoffs, recognize failure modes, and choose the appropriate intervention rather than merely recall vocabulary.

Source: [Chapter 15 Quiz: Context Engineering](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/context-engineering/chapter-quiz)

## Compressed chapter synthesis

The chapter's logic can be compressed into five claims.

1. Agent quality degrades when the context window accumulates stale, irrelevant, contradictory, or poorly placed material.
2. Persistent context should be lean and selective, with each kind of information loaded through the cheapest mechanism that still preserves correctness.
3. Project state should live in files, tasks, and progress artifacts rather than inside a single long conversation.
4. Memory and expertise should enter the workflow at the moment they are needed, and the agent's output must remain understandable to the human owner of the work.
5. Multi-agent systems require isolation and summary-based handoff, otherwise they amplify noise instead of specialization.

Taken together, the chapter treats context engineering as the operating discipline that makes general models usable for domain work.

## Source pages used

- [Chapter 15 overview](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/context-engineering)
- [Lesson 1: What Is Context Engineering?](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/context-engineering/manufacturing-quality-problem)
- [Lesson 2: Signal vs Noise](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/context-engineering/signal-vs-noise)
- [Lesson 3: Context Architecture](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/context-engineering/context-architecture)
- [Lesson 4: The Tasks System](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/context-engineering/tasks-system)
- [Lesson 5: The Two-Way Problem](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/context-engineering/tacit-knowledge)
- [Lesson 6: Context Lifecycle](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/context-engineering/context-lifecycle)
- [Lesson 7: Long-Horizon Work](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/context-engineering/progress-files)
- [Lesson 8: Mid-Stream Memory](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/context-engineering/memory-injection)
- [Lesson 9: Context Isolation](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/context-engineering/context-isolation)
- [Lesson 10: The Context Engineering Playbook](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/context-engineering/context-engineering-playbook)
- [Exercises](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/context-engineering/context-exercises)
- [Quiz](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/context-engineering/chapter-quiz)
