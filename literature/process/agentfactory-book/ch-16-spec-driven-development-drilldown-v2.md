# Chapter 16 drilldown: Spec-Driven Development with Claude Code

This document rebuilds Chapter 16 from the live Panaversity pages and condenses the chapter into a working reference. It follows the authored chapter flow: overview, nine lessons, exercises, and quiz.

Writing constraint used for this draft: `ai-writing-tropes-squashed-augmented.md`.

## What Chapter 16 argues

Chapter 16 presents Spec-Driven Development, or SDD, as a response to the failure pattern of vibe coding on substantial work. The chapter's claim is simple: once work grows past a small prototype, conversational iteration stops being a reliable control mechanism. A written specification becomes the stable artifact that carries requirements, constraints, architecture, and validation criteria across sessions and across agents.

The chapter ties SDD directly to the previous chapter on context engineering. Its core position is that the main failures of vibe coding are failures of context persistence, constraint clarity, and pattern recall. A specification fixes those failures by front-loading the information Claude needs before implementation begins.

Source: [Chapter 16 overview](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/spec-driven-development)

## Chapter structure

The overview page frames SDD as a methodology rather than a single framework. It names the chapter's native Claude Code building blocks as `CLAUDE.md` memory, subagents, tasks, and hooks, and positions the chapter as a workflow for turning those primitives into production-grade work.

The lesson sequence is coherent:

1. why vibe coding breaks down
2. the three levels of SDD
3. the project constitution
4. the four-phase workflow
5. parallel research with subagents
6. writing effective specifications
7. refinement by interview
8. task-based implementation
9. the decision framework
10. practical exercises and quiz

Source: [Chapter 16 overview](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/spec-driven-development)

## Overview page

The overview page defines SDD as a shift in primary artifact. Code is no longer the first durable output. The specification is. The page also contrasts quick prototype work with production work. For prototypes, conversational generation may be enough. For production systems, the chapter argues that a missing spec usually leads to wrong assumptions, dropped constraints, and code that fits neither team patterns nor architectural intent.

The page also places SDD in a broader tools landscape. It mentions Kiro, GitHub Spec-Kit, Tessl, and CC-SDD, then narrows the teaching approach to native Claude Code capabilities. That choice matters because the chapter is not teaching a branded external framework. It is teaching a discipline that can be implemented with Claude Code alone.

Source: [Chapter 16 overview](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/spec-driven-development)

## Lesson 1: Why specs beat vibe coding

This lesson identifies three recurrent failure modes.

Context loss comes first. Each new request pulls the model's attention toward the newest clarification. Earlier decisions remain in context technically, but they lose weight. The result is revision that silently undoes prior choices.

Assumption drift comes next. When the prompt leaves gaps, the model fills them with plausible defaults: audience, format, structure, depth, and tone. Those defaults may be reasonable in isolation and still be wrong for the actual task.

Pattern violations form the third failure mode. Even if the generated text or code addresses the requested topic, it may miss the team's actual standards: report structure, code architecture, testing rules, citation style, or validation expectations.

The lesson's stronger point is that these failures compound. Context loss leads to re-explanation fatigue. Re-explanation fatigue opens space for unstated defaults. Those defaults then collide with project-specific standards. At that stage, the user is not refining output. The user is managing drift.

The lesson also links these failures back to Chapter 15. Context loss is treated as a persistence problem. Assumption drift is a missing-constraints problem. Pattern violations are a missing-architecture-in-working-memory problem. The specification is presented as the repair: a persistent, high-signal context artifact that states what exists, what to build, what not to build, and how success will be validated.

Source: [Why Specs Beat Vibe Coding](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/spec-driven-development/why-specs-beat-vibe-coding)

## Lesson 2: The three levels of SDD

This lesson distinguishes three operating modes.

Spec-First is the default mode for most people. The spec guides implementation, then becomes disposable or archival. The chapter treats this as the right choice for one-off tasks, prototypes, small personal work, and fixes that are unlikely to need long-lived documentation.

Spec-Anchored keeps both spec and implementation as maintained artifacts. The chapter presents this as the team standard. The spec becomes onboarding material, an architectural decision record, and the first place to update when requirements change. The cost is obvious and real: double maintenance. The benefit is that intent remains legible months later.

Spec-as-Source is described as experimental. In this model, the spec is the only maintained artifact and code is regenerated on demand. The chapter points to Tessl-style work here. The appeal is that intent stays primary and hand-edited code disappears as a source of drift. The trade-off is that this model depends on generation reliability, test strength, and tooling maturity that most teams do not yet have.

The lesson handles the trade-offs well. It does not pretend there is a single right level. It argues instead that teams should pick the maintenance burden that matches the life of the work.

Source: [The Three Levels of SDD](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/spec-driven-development/three-levels-of-sdd)

## Lesson 3: The project constitution

The constitution is one of the chapter's most useful distinctions. A spec tells Claude what a feature should do. The constitution tells Claude how the project always operates.

The lesson describes two layers of constitution. A project-level `./CLAUDE.md` lives inside the repository and travels with the codebase. A global `~/.claude/CLAUDE.md` lives at the user level and applies across projects. Claude reads global rules first, then project rules, with project rules refining or overriding global defaults when needed.

The chapter is explicit about what belongs here: architecture principles, technology constraints, code quality standards, security requirements, and workflow rules. The examples are concrete: repository-only database access, strict typing, no raw SQL except migrations, TDD as the first commit, audit logging for state changes, and a standard commit message format.

The constitution matters most when many subagents work in parallel. Because each subagent starts with fresh context, cross-agent consistency cannot depend on conversational overlap. It has to come from shared governance loaded at session start. This lesson therefore turns `CLAUDE.md` from a convenience file into the chapter's main governance mechanism.

Source: [The Project Constitution](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/spec-driven-development/the-project-constitution)

## Lesson 4: The four-phase workflow

This lesson lays out the chapter's main operating sequence:

- Phase 1: research with parallel subagents
- Phase 2: convergence into a written specification
- Phase 3: refinement by interview to expose ambiguity
- Phase 4: implementation through task delegation and atomic commits

The contrast with vibe coding is strong and useful. In vibe coding, review happens during generation, persistence is weak, corrections happen in the code or prose directly, and context accumulates in a single thread. In SDD, review happens at phase gates, the spec survives session boundaries, correction happens by editing the spec, and implementation can run in fresh contexts per task.

That shift is the chapter's real proposal. SDD is not just "write a spec first." It is "move correction upstream, isolate implementation contexts, and keep one durable artifact that can outlive the conversation."

Source: [The Four-Phase Workflow](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/spec-driven-development/four-phase-workflow)

## Lesson 5: Phase 1, parallel research with subagents

This lesson turns research into a parallel workload. The trigger prompt is simple: "Spin up multiple subagents for your research task." The chapter says Claude will split the work into several isolated research agents, each focused on a separate slice of the problem.

The decomposition rules are the key part. Good research threads are independent, focused, bounded, and complementary. The lesson gives a concrete migration example that spans CRDTs, WebSocket protocols, IndexedDB persistence, and architectural integration. That example is useful because it shows what parallel research is actually for: multi-domain problems where one linear pass would be slow and error-prone.

The chapter also avoids a common mistake: it does not stop at collection. It assigns the human or main agent the synthesis job. When research returns, someone still has to detect patterns, conflicts, and implications. That synthesis step decides what becomes part of the spec, what becomes a trade-off, and what still needs more investigation.

Source: [Phase 1: Parallel Research with Subagents](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/spec-driven-development/parallel-research)

## Lesson 6: Phase 2, writing effective specifications

This lesson gives the chapter's most operational template.

The spec structure has four parts:

1. reference architecture analysis
2. current architecture analysis
3. implementation plan in atomic checklist form
4. explicit constraints and measurable success criteria

The design choice here is sharp. The spec is not a brainstorming note. It is an execution document. The implementation plan must decompose into atomic tasks that a subagent can complete cleanly. The chapter's rule of thumb is strong: if you cannot explain a task to a junior developer in one sentence, it is not atomic enough.

The lesson then names three qualities that make specs effective. First, constraints must be explicit, especially exclusions. Second, success criteria must be measurable rather than rhetorical. Third, the checklist format must support later task extraction.

The anti-pattern section is the best part of the lesson. It rejects three common errors: specifying how instead of what, omitting constraints, and using vague success criteria. The text argues that behavior-level descriptions preserve room for Claude to choose good implementations, while constraints and measurable outputs protect against drift.

Source: [Phase 2: Writing Effective Specifications](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/spec-driven-development/writing-effective-specs)

## Lesson 7: Phase 3, refinement via interview

This lesson introduces a pre-implementation interview mode. The trigger prompt is direct: "Here's my spec. Use the ask_user_question tool to surface any ambiguities before we implement."

The lesson classifies interview questions into five ambiguity categories: data decisions, conflict resolution, pattern selection, failure recovery, and boundary conditions. That taxonomy is useful because it turns vague "what did we miss?" anxiety into a finite review pass.

The checklist is pragmatic. It asks whether migration strategy, tie-breaking rules, timeout behavior, quotas, rate limits, and other decisions are already specified. The point is not to fill every checkbox for every project. The point is to force the team to decide which ambiguity classes matter here.

The stop condition is clear. Interviewing should end when questions become repetitive, new questions are trivial, and the spec can be read without needing to guess at architecture or behavior. That is one of the better parts of the chapter because it protects against endless clarification loops. The lesson also makes a subtler point: irritation at the questions can be diagnostic. Often it signals an unmade decision rather than an unnecessary question.

Source: [Phase 3: Refinement via Interview](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/spec-driven-development/refinement-via-interview)

## Lesson 8: Phase 4, task-based implementation

This lesson converts the refined spec into a managed implementation stream. The prompt pattern is explicit: implement the spec, use the task tool, assign each task to a subagent, and commit after each task.

The chapter describes a clean execution model. Claude extracts tasks from the checklist, identifies dependencies, and delegates each task to a fresh subagent. The fresh-context property matters because errors remain local. If one subagent makes a wrong assumption, the contamination does not bleed into the rest of the run.

The built-in task system is described as a four-tool loop: create tasks, update task state, list tasks, and retrieve task details. The lesson combines that with atomic commits so rollback boundaries stay small.

A second safeguard appears here as well: backpressure. The chapter recommends pre-commit hooks such as typecheck, lint, and test execution so that high-speed delegation does not simply create broken commits faster.

The chapter's real-world example is the alexop.dev redesign. The reported numbers are modest but concrete: 14 tasks, 14 commits, 45 minutes, 71 percent context usage, and no rollbacks. That example is offered as evidence that the discipline can stay fast while remaining auditable.

Source: [Phase 4: Task-Based Implementation](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/spec-driven-development/task-based-implementation)

## Lesson 9: The decision framework

This lesson does necessary damage control. SDD is presented as a power tool, not as default ceremony for everything.

The chapter says SDD excels when complexity exceeds working memory: large refactors, unclear requirements, new libraries, team coordination, and legacy modernization. In those cases, the spec acts as external memory and as a contract between implementers.

It also states where SDD is overkill: single-file bug fixes, obvious features, exploratory prototyping, and production incidents. This restraint keeps the chapter credible. It acknowledges that documentation overhead can waste time when the problem is small or urgent.

The quick heuristic is blunt and probably useful in practice: if the work affects more than five files, has unclear requirements, or requires learning new technology, use SDD. If it is a single-file bug fix, skip it. Everything in between gets a lightweight spec first.

That lightweight spec is intentionally small: one-line task description, constraints, and success criteria. The chapter claims those two sections deliver most of the value with a fraction of the overhead. That is probably the most portable rule in the chapter.

Source: [The Decision Framework](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/spec-driven-development/decision-framework)

## Practical SDD exercises

The exercises page is not filler. It is structured as a training ladder.

Module 1 contrasts vibe prompts with proper specs and asks the learner to observe the gap in outcomes.

Module 2 focuses on research design and source quality. The aim is not just to collect facts, but to learn how to frame multi-angle investigations that produce usable context.

Module 3 asks the learner to convert messy human input into structured specs. The examples use contradictory homeowner notes, fundraiser planning, and mixed-source onboarding material.

Module 4 isolates constraints and success criteria. One exercise hands the learner under-constrained specs and asks them to break them. Another asks the learner to convert vague success language into measurable criteria.

Module 5 trains the interview habit by pushing draft specs through ambiguity discovery.

Module 6 trains task decomposition, dependency mapping, and delegation planning.

Module 7 runs the full SDD cycle end to end on realistic projects such as a community newsletter or office move plan.

Module 8 moves into capstones. The learner must design the whole workflow without starter prompts. That choice fits the chapter's thesis. SDD is a method, not a fill-in-the-blanks form.

Source: [Practical SDD Exercises](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/spec-driven-development/sdd-exercises)

## Quiz page

The quiz page is thin, but it confirms the chapter scope. It states that the assessment covers vibe coding failure modes, the three SDD levels, the project constitution, the four-phase workflow, and the decision framework. That matches the chapter's actual center of gravity.

Source: [Chapter 16 quiz](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/spec-driven-development/chapter-quiz)

## What the chapter adds up to

The chapter's strongest contribution is not the four-phase diagram by itself. It is the combination of three ideas:

- a constitution that loads standards before work starts
- a spec that persists across sessions and captures decisions
- task delegation that isolates contexts and keeps rollback boundaries small

That combination gives Claude Code a shape closer to managed team execution than to an extended chat.

The chapter is weaker where it leans on renamed common practice. Some of what it calls SDD will be familiar to experienced engineers as ordinary planning, architecture notes, acceptance criteria, and task decomposition. The new part is not that these artifacts exist. The new part is that agentic coding makes their absence expensive much earlier in the process.

That is the chapter's real claim, and it is the part worth keeping.

## Source index

Live chapter pages:

- [Chapter 16 overview](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/spec-driven-development)
- [Why Specs Beat Vibe Coding](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/spec-driven-development/why-specs-beat-vibe-coding)
- [The Three Levels of SDD](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/spec-driven-development/three-levels-of-sdd)
- [The Project Constitution](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/spec-driven-development/the-project-constitution)
- [The Four-Phase Workflow](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/spec-driven-development/four-phase-workflow)
- [Phase 1: Parallel Research with Subagents](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/spec-driven-development/parallel-research)
- [Phase 2: Writing Effective Specifications](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/spec-driven-development/writing-effective-specs)
- [Phase 3: Refinement via Interview](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/spec-driven-development/refinement-via-interview)
- [Phase 4: Task-Based Implementation](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/spec-driven-development/task-based-implementation)
- [The Decision Framework](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/spec-driven-development/decision-framework)
- [Practical SDD Exercises](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/spec-driven-development/sdd-exercises)
- [Chapter 16 quiz](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/spec-driven-development/chapter-quiz)

Local source used as a standing writing constraint:

- `ai-writing-tropes-squashed-augmented.md`
