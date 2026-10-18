# Chapter 65 drilldown: Anthropic Claude Agent SDK

Source chapter: https://agentfactory.panaversity.org/docs/Building-Agent-Factories/anthropic-agents-kit-development

This file rebuilds the live Chapter 65 sequence from the overview, all exposed lesson pages, the capstone, and the quiz. It follows the summary discipline from `agent-summary-template-from-bauer-ramazani.md`: open with the chapter's thesis, keep the major supporting points, and cut the ornamental detail. It also follows the anti-trope constraints from `ai-writing-tropes-squashed-augmented.md`: no inflated claims, no filler transitions, no decorative structure, and no vague attributions.

## Chapter thesis

Chapter 65 presents Claude Agent SDK as an agent runtime, not just a model API. The chapter's central distinction is that with the lower-level Claude API, the developer implements the tool loop, error handling, state management, stop conditions, and guardrails; with Claude Agent SDK, Claude runs that loop and the developer focuses on specification, tool scope, validation, and deployment policy.

The overview also positions this chapter as the end of the framework survey that began with OpenAI Agents SDK and Google ADK. Its argument is that framework choice should follow operational requirements, especially runtime autonomy, permissions, recoverability, session persistence, and production controls.

## What the live chapter covers

The live chapter path exposes these pages:

1. Build Your Claude Agent SDK Skill
2. What is the Claude Agent SDK?
3. Your First Agent with query()
4. Built-in Tools Deep Dive
5. Permission Modes and Runtime Security
6. Agent Skills in Code
7. Custom Slash Commands
8. Session Management
9. File Checkpointing: Recovering from Agent Mistakes
10. Subagents for Parallel Work
11. Lifecycle Hooks: Controlling Agent Execution
12. Custom MCP Tools
13. ClaudeSDKClient and Streaming
14. Cost Tracking and Billing
15. Production Patterns: Hosting, Sandbox, and Compaction
16. TaskManager: Complete Digital FTE Capstone
17. Chapter Quiz: Claude Agent SDK Mastery

## Drilldown by page

### 0) Build Your Claude Agent SDK Skill

The chapter opens with a setup workshop rather than theory. The reader is told to download the `claude-code-skills-lab`, launch Claude, and use an existing skill-creator workflow to generate a new skill for Claude Agent SDK from official documentation. This page frames the rest of the chapter as both conceptual study and skill refinement: the reader should finish the lesson sequence with a better skill than the one created at the start.

Source: https://agentfactory.panaversity.org/docs/Building-Agent-Factories/anthropic-agents-kit-development/build-your-claude-agent-skill

### 1) What is the Claude Agent SDK?

This lesson supplies the chapter's main conceptual split. In the Client SDK or raw API model, the developer owns the loop: send prompt, receive tool call, execute tool, send result back, repeat. In the Agent SDK model, Claude owns the loop: the developer specifies the task and the runtime manages tool use, iteration, and completion. That shift matters because it removes a large surface area of plumbing bugs and moves attention toward task definition, permissions, and evaluation.

The page then compares Claude Agent SDK with Claude's Client SDK, OpenAI Agents SDK, and Google ADK. The differentiators it names include filesystem-based skills, file checkpointing, runtime permission callbacks, custom slash commands, persistent sessions, native MCP integration, and a multi-turn client for ongoing conversations. The lesson's claim is narrow and operational: the SDK is better suited to long-running autonomous agents because it packages the execution layer that other approaches leave to the developer.

Sources:
- https://agentfactory.panaversity.org/docs/Building-Agent-Factories/anthropic-agents-kit-development/what-is-claude-agent-sdk
- https://agentfactory.panaversity.org/docs/Building-Agent-Factories/anthropic-agents-kit-development

### 2) Your First Agent with `query()`

The first coding lesson reduces agent startup to the `query()` pattern. The chapter treats an agent as an async stream of messages rather than a single request-response pair. The developer passes a prompt and a `ClaudeAgentOptions` object, then iterates over emitted messages as the agent reasons, uses tools, and finishes.

The example uses a small task, tool restrictions such as `allowedTools: ["Bash", "Glob"]`, and a permission mode. The lesson is less about syntax than about mental model: an autonomous agent is a stateful execution stream with intermediate events, not just a completion endpoint.

Source: https://agentfactory.panaversity.org/docs/Building-Agent-Factories/anthropic-agents-kit-development/first-agent-query

### 3) Built-in Tools Deep Dive

This page argues that Claude SDK's autonomy is only useful when tool scope is deliberate. It lists nine built-in tools: `Read`, `Write`, `Edit`, `Bash`, `Glob`, `Grep`, `WebSearch`, `WebFetch`, and `Task`. The lesson distinguishes read-only tools from mutation and execution tools, then pushes a minimum-permissions design rule: give the agent only the tools required for the job.

The page also turns tool selection into a design exercise. A read-only code analyzer should get `Read`, `Glob`, and `Grep`; a development agent adds `Write`, `Edit`, and possibly `Bash`; a research agent should be confined to web tools; a parallel review agent can use `Task` to spawn narrower subagents rather than broadening one agent's permissions. The operational point is that capability design and safety design are the same activity.

Source: https://agentfactory.panaversity.org/docs/Building-Agent-Factories/anthropic-agents-kit-development/built-in-tools

### 4) Permission Modes and Runtime Security

This lesson gives the security model. The chapter defines four permission modes: `default`, `acceptEdits`, `bypassPermissions`, and `plan`. `default` prompts for each tool call, `acceptEdits` auto-approves file changes but still prompts for riskier operations, `bypassPermissions` removes prompts for approved tools, and `plan` lets the agent reason without executing tools.

The page then introduces `canUseTool()` as the finer-grained control layer. Permission mode sets the baseline posture; `canUseTool()` can inspect the requested tool, its inputs, and the current context, then allow, deny, or modify the action. The examples show protected paths, time-based rules, input rewriting, and error responses that force the agent to adapt when a tool call is denied. The chapter's security argument is that production autonomy is viable only when static tool allowlists are paired with context-sensitive runtime policy.

Source: https://agentfactory.panaversity.org/docs/Building-Agent-Factories/anthropic-agents-kit-development/permission-modes-security

### 5) Agent Skills in Code

The skill lesson moves organizational knowledge out of giant prompts and into filesystem-managed `SKILL.md` documents. The page argues that prompts become brittle when they carry all domain knowledge directly. Claude Agent SDK instead loads reusable intelligence from skill files discovered through `setting_sources`.

The chapter distinguishes between `"user"` and `"project"` skill sources. User skills live in `~/.claude/skills/` and apply across projects; project skills live in `./.claude/skills/`; both can be loaded together, with project definitions taking precedence. The operational point is that teams can version, share, and override agent knowledge without rewriting base prompts for every use case.

Source: https://agentfactory.panaversity.org/docs/Building-Agent-Factories/anthropic-agents-kit-development/agent-skills-code

### 6) Custom Slash Commands

This page separates commands from skills. Skills encode reusable expertise; slash commands encode reusable task entry points. A command file in `.claude/commands/` gives the agent an intent pattern, allowed tools, and task-specific instructions that activate when the prompt begins with a matching command such as `/code-review` or `/deploy`.

The lesson emphasizes YAML frontmatter because that is where command-scoped tool access is defined. The examples show read-only analysis commands, refactoring commands that can run tests, and deployment-verification commands that can inspect but not change a system. Arguments such as file paths and severity flags specialize the command at runtime. The page's design claim is that commands are a workflow interface, not just a convenience alias.

Source: https://agentfactory.panaversity.org/docs/Building-Agent-Factories/anthropic-agents-kit-development/custom-slash-commands

### 7) Session Management

The session lesson makes persistence explicit. A session begins when an agent starts and can be resumed later by storing the emitted `session_id` and passing it back through the `resume` option. The page says that this preserves prior files analyzed, conclusions reached, decisions made, and constraints discovered.

The distinctive addition is session forking. Instead of forcing one continuation path, the SDK lets the developer branch from a checkpoint and explore alternatives in parallel. The example uses query optimization approaches as separate forks. In chapter logic, sessions are the memory substrate for long-running agents and forks are the exploration substrate for decision points that do not have one obvious answer.

Source: https://agentfactory.panaversity.org/docs/Building-Agent-Factories/anthropic-agents-kit-development/session-management

### 8) File Checkpointing: Recovering from Agent Mistakes

This lesson adds recoverability to autonomy. The SDK can snapshot file state at execution checkpoints and later rewind to a specific checkpoint if the agent takes a bad path. The chapter uses refactoring as the core example: without checkpoints, a broken sequence of edits becomes a manual cleanup problem; with checkpoints, the agent can revert to an earlier state and try again.

The page says checkpointing is off by default and must be enabled with `enable_file_checkpointing=True`. It also says `extra_args={"replay-user-messages": None}` is needed if the developer wants checkpoint UUIDs surfaced in messages for later rewind. The practical lesson is simple: an agent that can edit code in production needs a built-in escape hatch, not just a promise to be careful.

Source: https://agentfactory.panaversity.org/docs/Building-Agent-Factories/anthropic-agents-kit-development/file-checkpointing

### 9) Subagents for Parallel Work

The subagent lesson shifts from single-agent execution to orchestration. The motivating example is code review that spans security, performance, testing, and documentation. Instead of letting one large agent handle all concerns sequentially, the chapter defines specialist subagents with narrower prompts, narrower tool access, and even different models.

The example assigns Sonnet to a security reviewer and Haiku to more routine analyzers, while also giving each subagent only the tools it needs. The parent agent then synthesizes their outputs. The lesson's argument is that orchestration is not just about speed. It is also about isolation, cost control, and separation of reasoning responsibilities.

Source: https://agentfactory.panaversity.org/docs/Building-Agent-Factories/anthropic-agents-kit-development/subagents-parallel-work

### 10) Lifecycle Hooks: Controlling Agent Execution

This page introduces hooks as intervention points around the agent lifecycle. The chapter frames them as the place where production control actually happens: before tool execution, after completion, when prompts arrive, and when compaction is about to run.

The examples focus on `PreToolUse`. A hook can inspect inputs, decide whether to allow or deny an action, log the reason, or even modify the requested input before execution. The page uses dangerous Bash patterns as the main case. The broader idea is that hook logic turns policy into executable enforcement rather than relying on prompt wording alone.

Source: https://agentfactory.panaversity.org/docs/Building-Agent-Factories/anthropic-agents-kit-development/lifecycle-hooks

### 11) Custom MCP Tools

After built-in tools and skills, the chapter moves to domain extension. MCP tools are the path from generic agent capability to business-specific capability. The page treats `Read`, `Bash`, and `WebSearch` as universal primitives, then argues that real products need custom tools that understand a company's APIs, workflows, or domain objects.

The GitHub example shows the expected pattern: validate inputs, call the external service, normalize errors, and return a clean text payload the agent can work with. The lesson is not just about connecting to APIs. It is about shaping a narrow, reliable interface between the agent and domain systems.

Source: https://agentfactory.panaversity.org/docs/Building-Agent-Factories/anthropic-agents-kit-development/custom-mcp-tools

### 12) ClaudeSDKClient and Streaming

The `query()` pattern is presented as the one-shot interface. `ClaudeSDKClient` is presented as the interface for ongoing collaboration. The chapter contrasts disconnected queries with a persistent session in which turn two can refer to turn one and turn three can build on the result of turn two.

The lesson uses a conversation loop to show why this matters: iterative refinement, progressive constraint addition, and correction after failed approaches all depend on continuity. In the chapter's architecture, `query()` is enough for bounded tasks, while `ClaudeSDKClient` is the right abstraction for collaborative or extended workflows.

Source: https://agentfactory.panaversity.org/docs/Building-Agent-Factories/anthropic-agents-kit-development/sdk-client-streaming

### 13) Cost Tracking and Billing

This lesson turns token accounting into product math. The page says the relevant metric is not abstract usage but `total_cost_usd` for a completed execution. It also shows how to capture per-message token counts and final totals so the developer can see which workflows are cheap, which are expensive, and what a pricing model has to absorb.

The chapter uses this to connect engineering and monetization. If a workflow costs a known amount per execution, then per-customer billing, subscription pricing, and profitability analysis become tractable. The lesson is narrow, but it is one of the stronger product-oriented parts of the chapter because it treats cost observability as part of the runtime contract.

Source: https://agentfactory.panaversity.org/docs/Building-Agent-Factories/anthropic-agents-kit-development/cost-tracking-billing

### 14) Production Patterns: Hosting, Sandbox, and Compaction

This is the deployment lesson. The page defines three hosting patterns: ephemeral agents, long-running agents, and hybrid agents. Ephemeral agents are suited to stateless, one-off tasks with clean isolation and bounded cost. Long-running agents keep context across days or months. Hybrid agents mix both by running independent tasks ephemerally while checkpointing durable context back to a persistent orchestrator.

The security portion adds sandbox controls. The examples show sandboxed Bash execution, auto-approval only when sandboxed, and network restrictions such as local binding controls. The lesson then turns to context compaction. Through `PreCompact` hooks and a threshold setting, long-running agents can archive or summarize older history while preserving the knowledge that still matters. The chapter treats compaction as a production necessity, not an optional optimization.

Source: https://agentfactory.panaversity.org/docs/Building-Agent-Factories/anthropic-agents-kit-development/production-patterns

### 15) TaskManager: Complete Digital FTE Capstone

The capstone consolidates the chapter into a spec-driven product sketch called TaskManager. The system intent is clear: an autonomous agent manages team task workflows, integrates with development tools and Slack, keeps persistent state, prioritizes work based on dependencies and deadlines, and operates under explicit safety guardrails.

The page ties each product requirement to a specific SDK feature. Session resume supports persistent tasks, `canUseTool` supports role-based permissions, file checkpointing makes deletion reversible, slash commands provide task operations such as `/assign` and `/report`, subagents parallelize analysis, skills encode team conventions, and context compaction keeps long-running operation sustainable. The capstone also names non-goals, cost bounds, approval gates, and audit logging, which makes it a proper system specification rather than a feature list.

Source: https://agentfactory.panaversity.org/docs/Building-Agent-Factories/anthropic-agents-kit-development/taskmanager-capstone

### 16) Chapter Quiz: Claude Agent SDK Mastery

The quiz closes the chapter with twenty questions across a Bloom-style progression from recall to evaluation. The questions are grounded in the chapter's distinct features, including `rewindFiles()`, `canUseTool()`, skill loading from `.claude/skills/`, and slash commands from `.claude/commands/`.

The page also gives score bands with recommendations. High scores are framed as readiness for production Digital FTE work, while lower bands direct the reader back toward the foundational lessons. As a chapter device, the quiz does two things: it checks recall of the named SDK features and it checks whether the reader can choose the right deployment and control pattern for a real scenario.

Source: https://agentfactory.panaversity.org/docs/Building-Agent-Factories/anthropic-agents-kit-development/chapter-quiz

## What Chapter 65 adds to the broader curriculum

Chapter 65 completes the book's comparison of three agent frameworks, but it does not present them as stylistic alternatives. It argues that Anthropic's Claude Agent SDK is strongest where the product needs a real runtime for autonomous execution: scoped tools, runtime permissions, file recovery, persistent sessions, orchestration, hooks, MCP extension, cost tracking, and production memory control.

The deeper pattern across the chapter is this:

- specification first
- permissions first
- recoverability before autonomy
- persistence only when the workflow needs memory
- orchestration by role, not by prompt size
- pricing and deployment treated as first-class design constraints

## Source index

- Chapter overview: https://agentfactory.panaversity.org/docs/Building-Agent-Factories/anthropic-agents-kit-development
- Lesson 0: https://agentfactory.panaversity.org/docs/Building-Agent-Factories/anthropic-agents-kit-development/build-your-claude-agent-skill
- Lesson 1: https://agentfactory.panaversity.org/docs/Building-Agent-Factories/anthropic-agents-kit-development/what-is-claude-agent-sdk
- Lesson 2: https://agentfactory.panaversity.org/docs/Building-Agent-Factories/anthropic-agents-kit-development/first-agent-query
- Lesson 3: https://agentfactory.panaversity.org/docs/Building-Agent-Factories/anthropic-agents-kit-development/built-in-tools
- Lesson 4: https://agentfactory.panaversity.org/docs/Building-Agent-Factories/anthropic-agents-kit-development/permission-modes-security
- Lesson 5: https://agentfactory.panaversity.org/docs/Building-Agent-Factories/anthropic-agents-kit-development/agent-skills-code
- Lesson 6: https://agentfactory.panaversity.org/docs/Building-Agent-Factories/anthropic-agents-kit-development/custom-slash-commands
- Lesson 7: https://agentfactory.panaversity.org/docs/Building-Agent-Factories/anthropic-agents-kit-development/session-management
- Lesson 8: https://agentfactory.panaversity.org/docs/Building-Agent-Factories/anthropic-agents-kit-development/file-checkpointing
- Lesson 9: https://agentfactory.panaversity.org/docs/Building-Agent-Factories/anthropic-agents-kit-development/subagents-parallel-work
- Lesson 10: https://agentfactory.panaversity.org/docs/Building-Agent-Factories/anthropic-agents-kit-development/lifecycle-hooks
- Lesson 11: https://agentfactory.panaversity.org/docs/Building-Agent-Factories/anthropic-agents-kit-development/custom-mcp-tools
- Lesson 12: https://agentfactory.panaversity.org/docs/Building-Agent-Factories/anthropic-agents-kit-development/sdk-client-streaming
- Lesson 13: https://agentfactory.panaversity.org/docs/Building-Agent-Factories/anthropic-agents-kit-development/cost-tracking-billing
- Lesson 14: https://agentfactory.panaversity.org/docs/Building-Agent-Factories/anthropic-agents-kit-development/production-patterns
- Capstone: https://agentfactory.panaversity.org/docs/Building-Agent-Factories/anthropic-agents-kit-development/taskmanager-capstone
- Quiz: https://agentfactory.panaversity.org/docs/Building-Agent-Factories/anthropic-agents-kit-development/chapter-quiz
