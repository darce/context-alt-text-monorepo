# Chapter 68: Agent Skills & MCP Code Execution — Drilldown

Source chapter: <https://agentfactory.panaversity.org/docs/Building-Agent-Factories/agent-skills-mcp-code-execution>

## What this chapter is doing

This chapter moves from two earlier building blocks to a higher-value pattern:

1. **MCP-wrapping skills** that add judgment on top of raw tools.
2. **Script-execution skills** that generate code, run it, inspect results, and iterate.
3. **Workflow orchestration** that composes both into a fault-tolerant, shippable system.

The chapter's claim is simple: a useful execution skill is not just "a tool" and not just "a prompt." It is a reusable operating pattern with explicit triggers, constraints, recovery rules, convergence criteria, and packaging for real users.

## Chapter thesis

The central move is the shift from **advisory skills** to **execution skills**.

- An advisory skill recommends.
- An execution skill manages a loop: understand the task, act, inspect the result, recover from failure, and stop only when the specification is met or a clear boundary is reached.

That distinction drives the whole chapter. Persona, questions, and principles are no longer there to make answers sound smart. They are there to govern autonomous behavior.

---

## Chapter overview

The overview page frames the chapter in five stages:

- lessons 1–2: advanced skill design and composition
- lessons 3–4: MCP-wrapping skills
- lessons 5–6: script execution skills
- lesson 7: full workflow orchestration
- lesson 8: a capstone positioned as a sellable Digital FTE asset

It also states concrete success criteria: explain the intelligence layer in MCP-wrapping skills, achieve meaningful token reduction through filtering, build a script-writing/executing skill, handle syntax/runtime/timeout failures, and complete a full execution-pattern capstone.

**Source:**
- Chapter overview: <https://agentfactory.panaversity.org/docs/Building-Agent-Factories/agent-skills-mcp-code-execution>

---

## Lesson 1 — Advanced Skill Patterns

Source: <https://agentfactory.panaversity.org/docs/Building-Agent-Factories/agent-skills-mcp-code-execution/advanced-skill-patterns>

### Core point

The lesson establishes the design difference between a skill that gives advice and a skill that runs a workflow.

An advisory persona looks like "you are an expert in X." An execution persona looks more like "you are an orchestrator: when situation X appears, do A, then B, then validate C, then either iterate or stop." That is a stronger design because it encodes a control loop instead of a knowledge label.

### What changes in design

The lesson pushes three design upgrades:

#### 1. Persona becomes a workflow declaration

The skill persona should describe sequence and behavior, not just expertise.

A strong execution persona includes:
- when the skill should activate
- the actions it performs
- the validation step
- the rule for completion versus retry

#### 2. Questions become decision logic

The lesson distinguishes three useful kinds of questions:
- **context analysis questions**: what kind of problem is this, what are the constraints, what counts as success
- **convergence questions**: has the spec been satisfied, what is missing, is another iteration justified
- **safety questions**: what must not happen, what resource or permission boundaries apply

The chapter is right to push against vague questions like "is this important?" Those are not operational. They do not constrain action.

#### 3. Principles become runtime guardrails

The lesson treats principles as directives with three parts:
- constraint
- reason
- practical application

It highlights three principle categories:
- convergence principles to stop runaway loops
- efficiency principles to keep context and work bounded
- safety principles to block harmful or reckless execution

### Why this lesson matters

This lesson is the chapter's conceptual hinge. If a reader misses it, the rest can look like mechanical tutorial material. In fact, the later lessons are just implementations of this control-pattern idea.

---

## Lesson 2 — Skill Composition & Multi-Skill Workflows

Source: <https://agentfactory.panaversity.org/docs/Building-Agent-Factories/agent-skills-mcp-code-execution/skill-composition>

### Core point

Skills do not formally depend on each other in a rigid package-manager sense. Claude is the orchestrator. It reads available skill descriptions, matches them to the task, calls them in sequence, and passes outputs forward as context.

That means the **skill description is effectively the contract**.

### The practical rule

If the description is vague, overly narrow, or overlapping with another skill, orchestration becomes unreliable. If the description clearly states:
- capability
- trigger conditions
- expected output shape

then skills compose much more cleanly.

### Composition patterns covered

The lesson identifies three useful patterns:

#### 1. Output → Input flow
One skill produces data in a format the next skill expects.

#### 2. Shared domain knowledge
Multiple skills use the same schema or reference material. The course prefers self-contained skills, even if that means duplication.

#### 3. Progressive refinement
One skill drafts, another refines, another verifies. The chain is conceptual rather than hard-coded.

### The key design tradeoff

The lesson compares duplicated resources versus central references:
- duplication improves portability and self-containment
- central references reduce maintenance but create deployment coupling

That is a real engineering tradeoff, and the chapter handles it well.

### What to keep from this lesson

Treat each skill as a small product with a precise surface area. Composition works when interfaces are legible, not when one giant skill tries to do everything.

---

## Lesson 3 — Anatomy of MCP-Wrapping Skills

Source: <https://agentfactory.panaversity.org/docs/Building-Agent-Factories/agent-skills-mcp-code-execution/mcp-wrapping-anatomy>

### Core point

An MCP server is a raw capability. A wrapping skill adds the intelligence layer.

The lesson argues that raw MCP is "powerful but purposeless" on its own. The wrapper decides:
- when to call the MCP tool
- what the user really needs
- how to filter the result
- how to recover if the call fails

That is the correct abstraction. The value is not the call itself. The value is the policy around the call.

### Reference examples used

The lesson deconstructs reference skills such as `fetching-library-docs` and `browsing-with-playwright` to show the same structure repeated in different domains.

### Three insights the lesson extracts

#### 1. MCP wrapping is decision-making
The wrapper is not a thin alias. It is the logic that turns a tool into a task-specific capability.

#### 2. Token efficiency is intentional
The page repeatedly emphasizes filtering as a first-class design concern. It cites **60–90% token reduction** as the target range for well-designed filtering, depending on content type.

#### 3. Error recovery makes the wrapper production-ready
A useful wrapper has recovery plans for empty results, ambiguity, rate limits, timeouts, and fallback paths.

### What this lesson really teaches

The skill is the policy object. MCP is the transport. That distinction is easy to miss, but it is the lesson's most important idea.

---

## Lesson 4 — Build Your MCP-Wrapping Skill

Source: <https://agentfactory.panaversity.org/docs/Building-Agent-Factories/agent-skills-mcp-code-execution/build-mcp-wrapping-skill>

### Core point

This lesson turns the wrapper pattern into a build process. It refuses the usual tutorial sequence of "start coding now" and instead starts with a specification.

The lesson's target is a skill that:
- wraps an MCP server from the previous chapter
- reduces token use by **30% or more**
- handles failure with fallback behavior
- works across multiple scenarios within a real domain

### Workflow taught here

The lesson proceeds through:
- specification first
- persona and question design
- collaborative implementation with AI
- implementation and testing
- consumer-facing documentation

### Why that ordering matters

The lesson is making a spec-driven point, not just a tooling point. If the wrapper's contract, trigger logic, and filtering policy are vague, the code will look complete while the behavior stays unreliable.

### What to take away

The deliverable is not just a working wrapper. It is a reusable wrapper with measurable filtering behavior, failure handling, and usage documentation.

---

## Lesson 5 — Script Execution Fundamentals

Source: <https://agentfactory.panaversity.org/docs/Building-Agent-Factories/agent-skills-mcp-code-execution/script-execution-fundamentals>

### Core point

MCP is limited to the tools that exist. Script execution generalizes the model: when no tool exists, the skill writes code, runs it, inspects the outcome, and iterates.

The lesson presents the chapter's second major pattern:

**write → execute → analyze → fix → refine**

### The loop

The course treats this loop as the basis of autonomous code execution. It starts from a specification, generates code, executes it, reads the result, diagnoses failures, and revises the code until a stop condition is reached.

### Error taxonomy

The lesson explicitly separates three error classes:
- **syntax errors**: code does not parse
- **runtime errors**: code parses but fails during execution
- **logic errors**: code runs but gives the wrong answer

That taxonomy matters because each class implies a different recovery strategy.

### Safety boundaries

The lesson also adds a missing piece that many "agentic coding" tutorials skip: execution safety.

It calls out boundaries around:
- filesystem access
- API and database access
- rate limits and quotas
- memory, time, and iteration limits

It also makes the right design claim: these constraints are not a nuisance. They are what make an execution skill reliable.

### Convergence

The stop rule is explicit. The skill should stop when:
- the specification is satisfied, or
- the maximum iteration/resource boundary is reached

That is stronger than vague notions like "keep trying until it works." The chapter is correct to reject open-ended retry logic.

---

## Lesson 6 — Build Script-Execution Skill

Source: <https://agentfactory.panaversity.org/docs/Building-Agent-Factories/agent-skills-mcp-code-execution/build-script-execution-skill>

### Core point

This lesson turns the loop from Lesson 5 into a concrete skill. Again, the build starts with a problem specification rather than with implementation.

### The sequence

The lesson walks through:
- writing the specification
- designing the skill persona and decision questions
- generating an initial implementation with AI collaboration
- testing on real inputs
- recovering from failures
- iterating until convergence
- adding timeout and resource protection
- testing against edge cases
- documenting the finished skill

### Edge-case emphasis

The lesson includes four test classes worth preserving:
- clean data / happy path
- malformed data
- empty or non-recoverable input
- timeout scenarios

That is the right bias. A script-execution skill proves itself under broken conditions, not under perfect input.

### Success conditions named by the lesson

The page's success checklist is practical:
- spec is clear enough that AI does not need clarification
- clean-path execution works
- error recovery works
- convergence is detected
- edge cases are tested
- iteration limits hold
- the skill is documented for reuse

### Best reading of the lesson

This is less a coding lesson than a reliability lesson. The "script" is incidental. The real artifact is a bounded self-correcting process.

---

## Lesson 7 — Full Workflow Orchestration

Source: <https://agentfactory.panaversity.org/docs/Building-Agent-Factories/agent-skills-mcp-code-execution/workflow-orchestration>

### Core point

The chapter now composes the two earlier patterns into a larger system.

The lesson frames workflows as **directed acyclic graphs (DAGs)** in which:
- each step depends on previous steps
- outputs must match downstream input contracts
- each step can fail in predictable ways
- recovery and terminal states must be designed, not improvised

### What the orchestrator is responsible for

The orchestration layer must:
- define step order
- validate handoffs between skills
- perform retries and backoff when warranted
- choose fallbacks where possible
- escalate when recovery is exhausted
- maintain workflow state
- decide whether the workflow converged

### Data contracts

One of the lesson's strongest practical points is that composition requires explicit data contracts. If Skill A returns a payload that Skill B cannot consume, the orchestrator must transform or terminate. It cannot just "hope" the handoff works.

### Recovery hierarchy

The lesson lays out a sensible hierarchy:
- retry if the error is transient
- apply fallback if a backup path exists
- degrade gracefully when partial output is acceptable
- escalate when the failed step is essential

### Why this matters

This is the point where the chapter stops being about isolated skills and becomes about production engineering. The shift from "run two skills" to "manage a workflow as a system" is the real step-change.

---

## Lesson 8 — Capstone: Shippable Agent Skill

Source: <https://agentfactory.panaversity.org/docs/Building-Agent-Factories/agent-skills-mcp-code-execution/capstone-shippable-skill>

### Core point

The capstone insists that learning a pattern is not enough. The student has to turn the pattern into a product.

The capstone asks the reader to choose a domain, write a specification, compose skill components, implement and test them, package the result, and then position it commercially.

### Capstone phases

The page breaks the build into six phases:

#### 1. Domain specification
Choose the problem and define the specification before implementation.

#### 2. Skill composition
Map components, data contracts, and recovery paths.

#### 3. Specification → implementation
Create the skill and document implementation choices.

#### 4. Acceptance testing and validation
Run a full test suite and record gaps between the spec and the implementation.

#### 5. Production packaging
Create customer documentation, versioning, and installation instructions.

#### 6. Digital FTE positioning
Identify the buyer, articulate business value, choose a monetization model, and define go-to-market.

### What the capstone is really asserting

The page makes a strong commercial claim: the durable value is not just code generation. It is the ability to write a clean spec, compose reusable intelligence, validate behavior, and package the result as something another party would actually adopt and pay for.

That claim is more ambitious than the rest of the chapter, but it is internally consistent with the curriculum's product orientation.

---

## How the chapter fits together

This chapter has a clean progression:

1. define what makes an execution skill different
2. show how independent skills compose
3. explain why MCP wrappers are intelligence layers rather than thin tool calls
4. build one wrapper from a spec
5. introduce general script execution for arbitrary computation
6. build one script-execution skill from a spec
7. orchestrate multiple skills with contracts and recovery logic
8. package the result as a deployable product

That sequence is strong because each stage solves a limitation from the previous one:
- basic skill design is too passive
- single skills are too narrow
- raw MCP is too dumb
- wrappers alone are too limited when no tool exists
- script execution alone is too isolated
- orchestration alone is not yet a product

---

## The most important ideas in Chapter 68

### 1. The wrapper is where the value sits
MCP by itself is just capability exposure. The wrapper decides when, why, and how to use it.

### 2. Spec-first still matters in agentic systems
The chapter repeatedly comes back to specification before implementation. That is one of its better instincts.

### 3. Error handling is not a side concern
The curriculum treats retries, fallbacks, and convergence rules as core design material rather than cleanup. That is correct.

### 4. Composition requires contracts
The workflow lesson does not treat multi-skill chaining as magic. It treats it as interface design plus recovery policy.

### 5. Packaging is part of the engineering problem
The capstone's commercial framing may be more aggressive than some readers want, but the packaging point is sound: a reusable skill needs documentation, versioning, installation instructions, and a defined user.

---

## Limitations and caveats in the chapter

A few points should be read critically:

- The chapter often uses polished examples rather than messy real operational constraints. In practice, permissions, observability, rollback, audit logging, and secret handling become central much earlier than the chapter suggests.
- The line between "skill" and "workflow engine" gets blurry by Lesson 7. Some of these patterns may be better implemented in explicit orchestration code than embedded entirely inside a skill layer.
- The capstone's Digital FTE framing is commercially bold, but the chapter does not fully address pricing pressure, support load, or governance requirements for production deployment.

Those are not fatal issues, but they matter.

---

## Practical takeaway

If you strip away the branding, Chapter 68 teaches a useful engineering pattern:

- start from a specification
- define the intelligence layer around tools
- give execution skills explicit stop rules and safety boundaries
- compose them through data contracts
- design recovery rather than improvising it
- package the result so someone else can operate it

That is the chapter's actual contribution.

---

## Live navigation note

The current live chapter navigation exposes the overview and eight lesson pages, but the chapter does **not** currently expose a separate Chapter 68 quiz page in the live next-page path. The capstone page links directly to Chapter 69.

Sources for that endpoint behavior:
- Capstone page: <https://agentfactory.panaversity.org/docs/Building-Agent-Factories/agent-skills-mcp-code-execution/capstone-shippable-skill>
- Next chapter target: <https://agentfactory.panaversity.org/docs/Building-Agent-Factories/multi-agent-reliability>

