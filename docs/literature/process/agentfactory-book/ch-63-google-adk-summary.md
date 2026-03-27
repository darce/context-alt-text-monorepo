# Chapter 63: Building Custom Agents with Google ADK — Section-by-Section Summary

## Method
This summary follows an objective compression approach: it opens each page with the main claim, keeps the major supporting points, preserves the instructional sequence, and removes low-value repetition. It avoids commentary and keeps the wording distinct from the source.

## Source path followed
1. Chapter 63 landing page: `.../google-adk-reliable-agents`
2. Lesson 0: `.../google-adk-reliable-agents/build-your-google-adk-skill`
3. Lesson 1: `.../google-adk-reliable-agents/your-first-adk-agent`
4. Lesson 2: `.../google-adk-reliable-agents/custom-function-tools`
5. Lesson 3: `.../google-adk-reliable-agents/session-state-memory`
6. Lesson 4: `.../google-adk-reliable-agents/coordinator-patterns`
7. Lesson 5: `.../google-adk-reliable-agents/callbacks-guardrails`
8. Lesson 6: `.../google-adk-reliable-agents/multi-agent-orchestration`
9. Lesson 7: `.../google-adk-reliable-agents/workflow-agents`
10. Lesson 8: `.../google-adk-reliable-agents/capstone-news-podcast`

---

## Chapter overview

### Main idea
The chapter argues that Google ADK is a production-oriented framework for Gemini-based agents that emphasizes declarative design, typed tools, structured orchestration, and stronger operational controls than the simpler handoff-centered style introduced in the OpenAI SDK chapter.

### What the chapter covers
The chapter uses one running example across the whole sequence: an AI News Podcast Agent. The system starts as a simple search agent, then gains custom tools, memory, silent background coordination, callback-based controls, specialist delegation, deterministic workflow agents, and a full capstone architecture that produces reports and audio artifacts.

### Learning goals
By the end of the chapter, the reader should be able to define ADK agents declaratively, wrap Python functions as tools, manage state through ToolContext and SessionService, enforce policies with callbacks, compose specialists with AgentTool, choose workflow agents when order and repeatability matter, and assemble those pieces into a deployable multi-agent product.

### How ADK is positioned
The chapter contrasts ADK with the OpenAI SDK along several axes. It presents ADK as stronger on explicit orchestration, callback hooks, managed deployment options, and native multimodal alignment with Gemini and Google Cloud. It presents the OpenAI SDK as simpler and more flexible, but less structured for deterministic multi-agent pipelines.

---

# Lesson 0: Build Your Google ADK Skill

## Main idea
The opening setup page tells the learner to create an ADK skill from official documentation before beginning the code lessons, so the chapter starts with a reusable knowledge asset rather than improvised assumptions.

### Get the lab environment
The learner downloads the skills lab repository, extracts it, opens it in the terminal, and enters the Claude environment. The page frames this as the base workspace for skill creation.

### Create the ADK skill
The central action is a prompt that asks the skill creator to build a Google ADK skill from official documentation through Context7. The page expects the skill builder to gather references first, ask clarifying questions, and then generate templates and guidance without relying on unstated prior knowledge.

### Purpose of the page
This lesson does not teach ADK concepts directly. It establishes a companion skill that the reader can test and refine as the chapter progresses.

### Takeaway
The setup page defines the pattern for the rest of the chapter: rely on documented behavior, store the result as a reusable skill, and improve it as understanding becomes more concrete.

---

# Lesson 1: Your First ADK Agent

## Main idea
Lesson 1 introduces ADK through a simple Gemini-powered news agent and argues that the framework's defining move is declarative agent definition rather than imperative orchestration.

### Installation and project setup
The lesson begins with installation of `google-adk`, project scaffolding through `adk create`, and environment setup through a `.env` file. It presents two authentication paths: a free Google AI key for local learning and Vertex AI configuration for Google Cloud deployments.

### Verification before development
Before the first agent is written, the lesson inserts a short verification step that checks whether the API key is present and whether a Google client can initialize correctly. The point is to catch environment problems before the agent code becomes harder to debug.

### The first agent
The initial agent is a small research assistant that uses `gemini-2.5-flash` with the built-in `google_search` tool. The lesson uses this example to show that agent name, model, instructions, and tools are declared together in one definition rather than assembled later at runtime.

### Declarative design versus imperative orchestration
The lesson contrasts ADK with the earlier OpenAI SDK approach. In ADK, agent definition is self-contained and execution is handled through `adk run` or `adk web`. In the OpenAI pattern, the developer defines the agent and then explicitly runs it through code. The lesson treats ADK's separation of definition from execution as the basis for reuse, clearer operations, and easier production deployment.

### Tool integration
Built-in tools are introduced as capabilities added directly to the agent definition. The lesson highlights search, code execution, and safe file access as examples of how agent behavior can be extended without changing the structural pattern.

### Common setup failures
The final sections focus on operational problems rather than new concepts: missing packages, misplaced environment files, incorrect imports, web server connectivity issues, and slow responses. The lesson closes by directing the learner back to the ADK skill they created earlier so they can test whether it captures the actual agent definition pattern.

### Takeaway
Lesson 1 establishes the chapter's base model: define the agent declaratively, attach tools at definition time, and run it through ADK's execution environment instead of a hand-written orchestration loop.

---

# Lesson 2: Custom Function Tools

## Main idea
Lesson 2 argues that ADK becomes genuinely useful when the developer can turn ordinary Python functions into domain-specific tools through type hints and docstrings.

### The function-to-tool pattern
The core claim is simple: if a function has clear parameter types, a typed return value, and a useful docstring, ADK can treat it as a tool. The chapter uses this to move from the built-in search tool to custom capabilities such as financial enrichment.

### Financial data example
The lesson builds a yfinance-based tool that accepts stock tickers and returns formatted market data. The example is not presented as a finance lesson. Its purpose is to show that external API access, structured outputs, and graceful failure can be packaged into an agent-visible capability without special ADK ceremony.

### Tool composition patterns
The lesson then broadens from one tool to patterns of collaboration between tools. One pattern chains a search step with an enrichment step. Another separates collection from analysis. A third pairs discovery with validation so the agent can filter low-quality or disallowed results before continuing.

### Design rules for tools
Several recurring rules are emphasized. Tools should be narrow in scope, typed explicitly, and documented well enough that the agent can infer when to call them. They should return useful structured values rather than opaque blobs, and they should handle failure internally rather than crashing the whole run.

### Common pitfalls
The lesson spends substantial space on mistakes that weaken tool reliability: missing type hints, exception-heavy code, vague return types, and overloaded functions that mix too many jobs. In each case, the source argues that tool clarity is part of agent reliability because the model needs a stable schema and predictable behavior.

### Supported typing model
The chapter notes that ADK can work with primitive types, common collections, and optionals. That detail supports the broader point that typed Python is the interface contract between the developer and the agent runtime.

### Takeaway
Lesson 2 turns ADK from a framework with a built-in search tool into a framework for exposing domain logic. The main lesson is not yfinance itself, but the discipline of writing small, typed, well-described functions that an agent can call safely.

---

# Lesson 3: Session State & Memory

## Main idea
Lesson 3 argues that useful agents must remember prior work, and it explains ADK's memory model by separating state access from state storage.

### Why session state matters
The lesson starts from a continuity problem: a research agent that learns something on Monday should still be able to use that result on Tuesday. Without persistence, the agent cannot recall prior questions, honor user preferences, or avoid repeating work.

### ToolContext: state access inside execution
ToolContext is introduced as the mechanism tools use to read and modify state during a session. The lesson shows how tools can inspect prior history, read preferences such as source quality, detect duplicate research, and append new findings for later steps in the same conversation.

### SessionService: where memory lives
The next distinction is architectural. ToolContext exposes the state, but SessionService determines where that state is stored. The lesson first introduces `InMemorySessionService` for local work, where state survives within one Python process and disappears on restart.

### Persistent backends
The lesson then moves to production-oriented persistence, where session documents survive process restarts, deployments, and long time gaps. Firestore and Vertex-oriented storage are presented as the kinds of backends that preserve conversation history and tool state beyond a single local run.

### Memory patterns
The page organizes memory use into several patterns. One stores user preferences so later tools can filter results automatically. Another records conversation history so the agent can avoid redundant work and keep track of accumulated insights. A third treats state as project progress, allowing a long-running research effort to continue across multiple sessions until all topics are complete.

### Operational distinction
The lesson's main conceptual split is practical: ToolContext is the API the tool touches, while SessionService is the backend that decides whether that state is transient or durable.

### Takeaway
Lesson 3 reframes memory as infrastructure rather than magic. Agents remember because tools read and write structured state, and because a session backend persists that state at the appropriate level for development or production.

---

# Lesson 4: Coordinator Patterns

## Main idea
Lesson 4 argues that production agents should separate user-facing interaction from heavy internal work, and it introduces the coordinator-dispatcher pattern as the way to do that.

### The problem with raw streaming output
The lesson begins with the failure mode of naive transparency: if the user sees every search result, every enrichment step, and every formatting action, the interaction becomes noisy and hard to use. The source treats this as a UX and system-design problem rather than a cosmetic one.

### Two-message architecture
The proposed fix is a strict interaction pattern. The agent acknowledges the request immediately, performs the substantive work silently, saves its result to persistent storage, and then returns a completion message with the output location. The lesson presents this as the right default for background-style agent work.

### File persistence as a tool
To make the pattern concrete, the lesson builds a markdown-saving tool. The implementation emphasizes safe filename normalization, predictable location, UTF-8 encoding, clear success or error messages, and no path traversal. The tool is important because the coordinator pattern depends on persistent artifacts rather than transient chat output.

### Coordinator instructions
The coordinator agent is then defined with explicit behavior constraints: acknowledge first, execute the middle phase silently, and only surface the final completion status when the report has been saved. The source treats the instruction block as a control surface for shaping the agent's interaction contract.

### Structured report schema
The lesson also defines the shape of the saved report. The markdown template organizes the output into an executive summary, top headlines, market context, and key metrics. The purpose is to reduce ambiguity about what the coordinator should produce and to make the saved file reusable.

### Why the pattern matters
The source gives four reasons for the pattern: better user experience, persistence across sessions, better scaling for multi-step work, and a durable audit trail in the form of saved artifacts.

### Takeaway
Lesson 4 shifts the chapter from single-turn chat behavior to production workflow design. The agent is no longer just answering. It is coordinating a job, storing the result, and reporting completion with a clean interaction boundary.

---

# Lesson 5: Callbacks & Guardrails

## Main idea
Lesson 5 presents callbacks as the mechanism that lets developers enforce policy and reshape execution without rewriting the agent's core logic.

### The callback model
The lesson begins by locating callbacks inside the ADK lifecycle. It lists six hook points across agent, model, and tool execution, then narrows attention to the two most operationally useful ones for this chapter: `before_tool_callback` and `after_tool_callback`.

### Return behavior as control logic
A key distinction is that returning `None` usually allows normal execution to continue, while returning a value can block or replace the default behavior. The lesson treats this return contract as the practical lever that turns a callback into a guardrail.

### Before-tool callbacks for policy enforcement
The first major pattern filters search behavior by domain. The callback inspects the tool name and arguments, blocks requests that target prohibited sites, and returns a structured error instead of letting the tool run. The lesson uses this to show how an agent can be prevented from searching unwanted sources while still continuing its overall task.

### After-tool callbacks for transparency and response shaping
The second major pattern enriches tool output after execution. Search results are parsed to extract domains, and that sourcing information is written into process state so later steps can expose what sources were used. The lesson frames this as a way to add transparency without burdening the main tool implementation.

### Combining callbacks
The page then combines policy enforcement and transparency into one agent configuration. The point is that callbacks can layer: one callback constrains what the agent is allowed to do, while another makes the resulting execution more inspectable.

### Additional operational uses
Beyond filtering and logging, the lesson shows callbacks being used for caching. This expands the concept from safety to efficiency: a callback can intercept repeated tool calls and return stored results instead of repeating the external operation.

### Takeaway
Lesson 5 makes the chapter's reliability story more explicit. Instructions influence behavior, but callbacks let the developer impose rules, inject metadata, and short-circuit operations at precise points in execution.

---

# Lesson 6: Multi-Agent Orchestration

## Main idea
Lesson 6 argues that reliable multi-agent systems need a coordinator-specialist structure in which one agent remains in control while invoking narrower agents for specialized work.

### Coordinator versus specialist roles
The lesson defines specialist agents as narrow components with focused instructions, a limited toolset, and structured outputs. The coordinator receives the user's request, decides when to invoke specialists, combines their outputs, and handles failures without giving up control.

### ADK's orchestration model
The crucial ADK mechanism is `AgentTool(agent=specialist)`. The coordinator wraps the specialist as a callable tool and receives its output as part of its own reasoning process. The lesson contrasts this with the OpenAI SDK handoff model, where control moves away from the coordinator and becomes harder to recompose across three or more agents.

### Structured output through schemas
Pydantic models are introduced as the contract that keeps multi-agent exchange predictable. By defining report schemas and validating coordinator output against them, the system can preserve structure across specialist calls and make the final result type-safe to consume.

### Building the first coordinated system
The source walks through a small podcast-oriented system: a podcaster specialist is defined first, then wrapped as an agent tool, and then invoked by a coordinator that researches news, enriches stories, and delegates podcast generation.

### Resilience and graceful degradation
The lesson does not assume all specialists will succeed. It explicitly shows a pattern where missing financial data, missing search results, or failed podcast generation do not collapse the whole workflow. Instead, the coordinator returns the best result it can, fills unavailable fields with placeholders, and records what failed.

### Full example
The later sections combine schemas, a specialist agent, and a coordinator into a complete working example. The point is to show that multi-agent composition in ADK is still structured code, not an informal conversation among loosely defined bots.

### Takeaway
Lesson 6 defines orchestration as controlled delegation. The coordinator remains the system boundary, specialists stay narrow, and typed outputs keep the overall workflow coherent even when one component fails.

---

# Lesson 7: Workflow Agents — Deterministic Pipelines

## Main idea
Lesson 7 argues that some production tasks should not rely on free-form LLM routing at all. When execution order, repeatability, and testing matter, ADK workflow agents provide a deterministic alternative.

### The problem with pure routing
The lesson starts by showing how the same routed multi-agent request can follow different paths on different runs. Research may repeat, steps may occur out of order, and debugging becomes difficult because the sequence is no longer stable.

### Flexibility versus predictability
The source frames the decision as a trade-off. LLM routing is more adaptive for novel situations, but workflow agents are easier to test, faster to reason about, and more predictable for standardized processes.

### SequentialAgent
The first workflow type guarantees ordered execution. One agent completes before the next begins. The lesson shows this as the right fit for pipelines where research must happen before writing, or enrichment must happen before report generation. It also introduces shared context so structured data can pass from one stage to the next.

### ParallelAgent
The second workflow type runs multiple independent analyses at the same time. The example combines fact-checking, sentiment analysis, and metadata extraction as concurrent tasks that all operate on the same input and return a grouped result more quickly than a sequential chain would.

### LoopAgent
The third workflow type handles iterative refinement. A generator can produce a draft, inspect or receive feedback, then refine again until an explicit exit condition is met or a maximum iteration count stops the loop. The lesson treats this as the structured version of controlled improvement rather than unconstrained repetition.

### Composite workflow patterns
The later sections show that these workflow types can be nested. A sequential pipeline can contain a parallel analysis phase, and parallel branches can each contain their own bounded loops. The point is to build deterministic substructures instead of relying on open-ended model judgment at every step.

### Testing implications
The lesson ties workflow design directly to verification. Because the path is fixed, developers can assert the number of iterations, inspect execution events, and reason about pipeline behavior in a way that is much harder under free LLM routing.

### Takeaway
Lesson 7 narrows the chapter's orchestration choices. Use routed agents where adaptability matters, but use workflow agents when the job has a known structure and reliability depends on guaranteed order or bounded iteration.

---

# Lesson 8: Capstone — AI News Podcast Agent

## Main idea
The capstone assembles the chapter's separate mechanisms into a single product-style system that researches AI topics, enriches them with market context, generates a report, and produces podcast audio.

### System architecture
The architecture is centered on a root coordinator that routes work to specialized news, financial, reporting, and podcast components. The lesson treats these as named roles inside one system rather than as isolated code exercises. The coordinator is responsible for orchestration, process logging, error handling, and final result assembly.

### Specification-first design
Before implementation, the source requires a written specification. It defines intent, success criteria, constraints, component composition, output artifacts, and non-goals. The contract includes report generation, audio output, audit logging, partial-failure tolerance, source restrictions, timing limits, and a no-hallucination expectation for factual claims.

### Project structure and shared models
The implementation begins with a concrete project layout that separates coordinator logic, specialist agents, shared tools, callbacks, environment configuration, and output directories. Pydantic schemas define the shapes of sources, news reports, financial context, and audio metadata so the system can pass structured objects across stages.

### Specialist implementations
The capstone then fills in the specialists. The news component returns structured research with sources and key insights. The financial component adds adoption and market context. The report generator converts structured inputs into markdown files. The podcast component converts the report into audio-oriented output through script generation and text-to-speech.

### Guardrails and logging
Callbacks reappear here as production controls. Search results are filtered toward trusted technical sources, and tool activity is logged for later inspection. Logging utilities create an audit trail alongside the user-visible outputs.

### End-to-end orchestration
The coordinator ties everything together through an end-to-end request path. A topic enters the system, specialists run in sequence, artifacts are saved to dedicated directories, and the final result includes status plus output locations. The capstone treats this as a complete service candidate rather than a lesson-sized toy.

### Testing and verification
The system is then validated through manual execution and a verification checklist that checks for created directories, generated reports, audio files, and logs. This keeps the capstone aligned with the chapter's larger theme that production agents must be inspectable as systems, not only as conversations.

### Production hardening and productization
The final sections move beyond the classroom build. They describe the next hardening layer in terms of retries, timeouts, circuit breakers, monitoring, data-quality controls, and compliance requirements. The lesson also points toward customer-facing APIs, subscriptions, and asynchronous delivery, making the capstone a template for commercialization as well as orchestration practice.

### Takeaway
Lesson 8 turns the chapter's individual patterns into one coherent architecture. The capstone's purpose is to show that declarative agents, typed tools, memory, callbacks, specialist delegation, and deterministic workflows are not separate topics. They are the parts of one production system.

---

## Chapter-end takeaway
Chapter 63 builds a progression from single-agent declaration to product-shaped orchestration. It starts by teaching how ADK defines agents and tools, then adds memory, control hooks, delegation, deterministic workflows, and a full specification-led capstone. The chapter's recurring claim is that reliable agents come from explicit structure: typed interfaces, durable state, bounded coordination patterns, and artifacts that can be tested, logged, and shipped.
