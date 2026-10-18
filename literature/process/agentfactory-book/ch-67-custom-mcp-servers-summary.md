# Chapter 67: Advanced MCP Server Development - Section-by-Section Summary

## Method
This summary follows an objective compression approach: it opens each page with the main claim, keeps the major supporting points, preserves the instructional sequence, and removes low-value repetition. It avoids commentary and keeps the wording distinct from the source.

## Source path followed
1. Chapter 67 landing page: `.../custom-mcp-servers`
2. Lesson 0: `.../custom-mcp-servers/build-your-mcp-server-skill`
3. Lesson 1: `.../custom-mcp-servers/context-object-lifespan`
4. Lesson 2: `.../custom-mcp-servers/sampling-servers-calling-llms`
5. Lesson 3: `.../custom-mcp-servers/progress-logging-notifications`
6. Lesson 4: `.../custom-mcp-servers/roots-file-permissions`
7. Lesson 5: `.../custom-mcp-servers/streamable-http-transport`
8. Lesson 6: `.../custom-mcp-servers/stateful-vs-stateless`
9. Lesson 7: `.../custom-mcp-servers/error-handling-recovery`
10. Lesson 8: `.../custom-mcp-servers/packaging-distribution`
11. Lesson 9: `.../custom-mcp-servers/capstone-production-server`
12. Assessment: `.../custom-mcp-servers/chapter-quiz`

---

## Chapter overview

### Main idea
The chapter argues that MCP becomes production-ready only when basic tools, resources, and prompts are extended with operational patterns: injected context, client-mediated sampling, real-time feedback, secure filesystem boundaries, network transport, scaling configuration, disciplined error handling, and installable packaging.

### What the chapter covers
The sequence begins by having the learner create an MCP server skill from official documentation. It then builds up the runtime model: Context for observability and lifecycle management, sampling for server-to-client model calls, notifications for long operations, roots for path security, StreamableHTTP for remote deployment, stateful versus stateless configuration for horizontal scale, structured recovery patterns for failures, and packaging rules for distribution. The capstone combines those pieces into a research assistant server.

### Learning goals
By the end of the chapter, the reader should be able to inject Context correctly, use `context.session.create_message()` for client-side inference, emit progress and log messages during long work, validate all file access against declared roots, deploy remote servers over HTTP with SSE-backed communication, choose between stateful and stateless modes based on feature needs, design retry-safe error responses, and package an MCP server as an installable Python project.

### How the chapter positions advanced MCP work
The chapter draws a line between hobby servers and production systems. Hobby servers expose a tool and return a result. Production servers must explain what they are doing, stay secure when touching files, survive failures, operate across a network, and remain installable and scalable in other environments.

---

# Lesson 0: Build Your MCP Server Skill

## Main idea
The setup page tells the learner to create a reusable MCP server skill from official documentation before writing code, so the rest of the chapter is grounded in a maintained reference asset rather than memory or guesswork.

### Get the lab environment
The learner downloads the skills lab repository, opens it in the terminal, and enters the Claude workflow. The page treats this lab as the workspace for building and testing the MCP skill.

### Create the MCP skill
The central prompt asks the skill creator to study official MCP documentation through Context7 and then build a server-building skill that can cover work from simple examples to professional systems. The page expects clarifying questions and documented references before any templates are generated.

### Purpose of the page
This lesson does not teach server internals directly. It creates the companion artifact that the learner will audit and improve as later lessons expose missing patterns.

### Takeaway
The chapter starts with tool-assisted documentation capture. The pattern is to externalize MCP knowledge into a reusable skill, then refine that skill as the production requirements become more precise.

---

# Lesson 1: Context Object & Server Lifespan

## Main idea
Lesson 1 argues that advanced MCP tools need infrastructure support that should not appear in their public schema. Context provides that support through dependency injection, giving tools logging, progress reporting, session access, and lifecycle-aware resource management.

### Dependency injection instead of explicit plumbing
The page explains that `Context` is not a normal user input. FastMCP injects it automatically into keyword-only parameters, which keeps tool schemas clean while still giving tool code access to runtime services. The client supplies business inputs; the framework supplies infrastructure.

### Logging and progress as observability primitives
The lesson presents `context.info()`, `context.warning()`, `context.error()`, and `context.report_progress()` as the basic way to make long-running operations visible. The pattern is to log before and after significant steps and to advance progress incrementally rather than treating completion as a single opaque event.

### Session as request-scoped state
Each tool invocation gets a session handle that can identify the request, expose connected-client capabilities, and support temporary request-local caching. The lesson stresses that this is request-scoped state, not a global shared store.

### Startup and shutdown handlers
The next layer is server lifecycle. `on_startup` initializes shared resources such as database connections or caches before tools are callable, and `on_shutdown` cleans them up when the server stops. The page treats this as the correct place for server-wide setup and teardown rather than ad hoc initialization inside tools.

### Putting the pieces together
The production example combines startup state, progress reporting, session access, optional sampling, caching, and structured logging in a single document-processing tool. The lesson's point is that Context is the hinge that lets those patterns coexist cleanly.

### Takeaway
Lesson 1 turns MCP from decorated functions into managed runtime components. Tools remain focused on domain work because Context absorbs the cross-cutting concerns that production systems need.

---

# Lesson 2: Sampling - Servers Calling LLMs

## Main idea
Lesson 2 argues that MCP servers should not own model credentials or inference billing when they only need reasoning. Sampling lets the server request inference from the connected client, which keeps the server provider-agnostic and pushes model choice, cost, and credentials to the client side.

### Why direct server-side model calls are the wrong default
The lesson contrasts a naive design, where the server embeds an Anthropic key and calls Claude directly, with a sampling-based design. The direct approach couples the server to one provider, adds operational complexity, and moves inference cost onto the server.

### The sampling mechanism
The server uses `ctx.session.create_message()` with `SamplingMessage` objects and a `system_prompt` to describe the reasoning task. It specifies intent and input, then waits for the client to route that request through its own model connection.

### Client-side callback responsibility
On the client, a sampling callback receives the request, chooses the model, performs the actual API call, and returns the structured result. This gives the client control over provider choice and error handling while keeping the server free of embedded credentials.

### Division of labor in hybrid systems
The page frames the pattern as a split architecture: deterministic work such as data fetching or transformation stays on the server, while interpretive or synthesis-heavy work is delegated to the client's model. That division reduces server complexity without eliminating AI-assisted behavior.

### Practical design concerns
The lesson also raises the missing pieces that make sampling usable in production: better prompts, explicit response validation, retry logic, and graceful fallback when sampling fails. Sampling is useful, but only if the surrounding error paths are designed deliberately.

### Takeaway
Lesson 2 defines sampling as cost and responsibility transfer. The server asks for reasoning, but the client owns the model relationship.

---

# Lesson 3: Progress & Logging Notifications

## Main idea
Lesson 3 argues that long-running MCP tools need continuous feedback or clients will appear frozen and users will abandon the operation. Notifications solve that by streaming progress and log events while work is still underway.

### Why notifications matter
The lesson starts from a simple UX failure: a thirty-second tool call with no visible movement looks broken. The absence of feedback invites cancellation, duplicate execution, and mistrust.

### Two notification channels
The page separates notifications into progress updates and logging messages. Progress conveys measurable advancement through a task, while logging conveys milestones, warnings, and status changes that may not map cleanly to a percentage.

### Server-side emission pattern
The server emits `context.info()` messages as work moves through stages and calls `report_progress(current, total)` as each measurable unit completes. The lesson treats this as a disciplined runtime contract rather than decoration.

### Client-side handling
On the client, logging and progress events are registered as handlers and can be turned into UI output, terminal updates, or other live displays. This reinforces that notification design is an end-to-end protocol, not just a server helper call.

### Designing notification strategy
The lesson also distinguishes between operations that need detailed progress, operations that only need milestone logs, and very short operations that need neither. The goal is not to emit messages constantly, but to match observability to runtime behavior.

### Takeaway
Lesson 3 makes feedback a protocol feature. A production tool does not merely finish; it reports what it is doing while the user is waiting.

---

# Lesson 4: Roots: File System Permissions

## Main idea
Lesson 4 argues that file-aware MCP servers need an explicit path-discovery and permission model. Roots provide that model by telling the client which directories are available and by requiring the server to validate every requested path against those boundaries.

### The path-discovery problem
If a user asks an MCP-connected client to work with a file, the client still needs some authorized way to discover where that file might be. Without roots, the model has no safe and structured map of the reachable filesystem.

### Declaring accessible roots
The server exposes allowed directories through `@mcp.list_roots()`, typically as named file URIs such as Documents or Downloads. This tells the client where it may search or propose file operations.

### Validating every requested path
Declaring roots is not enough. The server must still normalize paths and verify that every requested file remains within an allowed root. The lesson treats `is_path_allowed()` and similar checks as mandatory, not optional convenience code.

### Threat model and defensive checks
The page explicitly calls out path normalization, directory traversal, relative-path handling, and symlink escape attempts. The point is that file access is a security boundary, so every path must be checked as if the client input were untrusted.

### Testing the boundary
The lesson closes by pushing the learner toward integration tests that prove normal in-root access works and out-of-root access fails. Security is framed here as behavior that must be tested, not just intended.

### Takeaway
Lesson 4 makes roots a two-part system: the server advertises accessible directories, then enforces those boundaries on every file operation.

---

# Lesson 5: StreamableHTTP Transport: Remote MCP Over HTTP

## Main idea
Lesson 5 argues that remote MCP deployment is not solved by ordinary request-response HTTP alone. Production transport requires a way for the server to send messages back to the client during execution, which is why StreamableHTTP combines HTTP requests with SSE-backed streaming.

### Why stdio stops working remotely
The chapter starts from the limit of local transport. `stdio` works only when client and server share a machine, so it cannot support distributed clients talking to a remote server over the network.

### The asymmetry problem in HTTP
A plain HTTP request can carry a tool call to the server, but advanced MCP features need the server to push events back: progress updates, logs, and sampling callbacks. The lesson presents SSE as the mechanism that restores that missing reverse channel.

### Session-aware transport design
The page describes session IDs, SSE streams, and tool-specific communication channels as the way remote MCP maintains continuity across an interaction. This is the runtime substrate that makes advanced features work over the network.

### Real-time server-to-client events
With StreamableHTTP in place, the server can emit progress notifications and other messages as work proceeds, and those messages arrive without polling. The transport layer therefore becomes part of the feature set, not just a deployment detail.

### Operational concerns
The lesson also points to the distributed-systems work that appears once remote sessions exist: session cleanup, abandoned connections, collision avoidance, and timeout logic. The transport must be hardened, not just made functional.

### Takeaway
Lesson 5 reframes deployment as protocol design. Remote MCP needs a bidirectional communication pattern, and StreamableHTTP supplies that pattern through HTTP plus SSE.

---

# Lesson 6: Stateful vs Stateless Servers

## Main idea
Lesson 6 argues that horizontal scale introduces architectural constraints that break advanced MCP features unless the server's mode matches its feature set. The core decision is whether to preserve server-client session state or to disable those features and make each request fully independent.

### Why scaling breaks naive deployments
When requests are load-balanced across multiple instances, the server that receives a later request may not be the one that owns the client's SSE stream or session data. That causes progress, sampling, and other session-bound features to fail in ways that look random.

### What stateless mode changes
With `stateless_http=True`, the server drops SSE, session IDs, sampling, progress notifications, and subscriptions. The tradeoff is clear: any instance can answer any request, but the server gives up features that require ongoing server-to-client communication.

### What stateful mode preserves
Stateful configuration keeps the richer feature set, but it requires infrastructure that can consistently route a client's traffic to the right instance or otherwise preserve session affinity. This is operationally heavier but necessary when the feature contract depends on continuity.

### Decision framework
The page reduces the choice to a few questions: Do you need sampling? Do users need real-time progress? How high is the concurrency target? How much operational complexity can the deployment tolerate? The answer determines whether stateful behavior is required or whether stateless design is the safer fit.

### Practical implication
The lesson makes one thing explicit: scaling is not just about throughput. It is about whether the runtime model behind advanced MCP features can still function once requests are distributed across many servers.

### Takeaway
Lesson 6 turns mode selection into an architectural decision. Stateless design simplifies scaling, while stateful design preserves advanced MCP behavior at the cost of more operational discipline.

---

# Lesson 7: Error Handling & Recovery

## Main idea
Lesson 7 argues that production MCP servers must fail in ways the protocol can understand and operators can debug. That means structured JSON-RPC errors, specific exception handling, recovery strategies matched to error type, and retry-safe tool design.

### Speaking the protocol
The page begins with JSON-RPC error structure. Errors are not presented as arbitrary crashes or vague messages, but as structured responses with codes, messages, and explanatory data that clients can interpret.

### Specific exceptions before generic exceptions
The lesson models tool code with layered `try/except` handling that catches recoverable and known domain failures first, logs enough context to diagnose them, and avoids collapsing everything into one undifferentiated exception path.

### Transient versus permanent failures
A central distinction is whether an error is temporary and worth retrying, or permanent and better surfaced immediately. Timeouts, rate limits, and some server faults are treated as transient. Missing resources, unauthorized access, and malformed inputs are treated as permanent.

### Graceful degradation
The chapter also promotes partial success where appropriate. If some inputs fail but others can still produce useful output, the tool should continue, record what was skipped, and return the best available result instead of aborting the entire operation.

### Cleanup and retry safety
The lesson ties error handling to resource cleanup and idempotency. Retried operations should not duplicate destructive side effects, and failures should not leave the system in a corrupted intermediate state.

### Takeaway
Lesson 7 defines recovery as a design discipline. A production MCP server must classify errors, communicate them in protocol form, and preserve enough structure that retries and partial results remain safe.

---

# Lesson 8: Packaging & Distribution

## Main idea
Lesson 8 argues that an MCP server is not production-ready until other people can install and run it reliably. Packaging translates local code into a reusable Python component with explicit metadata, dependencies, entry points, and installation checks.

### From codebase to package
The lesson treats `pyproject.toml` as the central packaging contract. It declares project identity, Python version requirements, dependencies, and the script entry point that turns the package into a runnable command.

### Project layout and entry points
The page explains the expected package structure, including the package directory, server modules, README, and metadata file. It emphasizes that the installable command comes from `[project.scripts]`, not from manual shell instructions.

### Build and inspect
Using `uv build`, the developer produces a wheel that can be inspected and installed. The page frames this as verification that the package contains the right modules and that the build pipeline is configured correctly.

### Local installation and client verification
Packaging is not complete until the installed command works in practice. The chapter therefore checks whether the command is available locally and whether tools appear correctly in Claude Desktop after configuration.

### Packaging as part of the skill
As with the earlier setup page, the lesson also asks the learner to update the MCP skill with packaging patterns that may have been omitted at the beginning of the chapter.

### Takeaway
Lesson 8 closes the gap between a local experiment and a shareable component. Packaging is the step that makes an MCP server installable, testable, and transferable.

---

# Lesson 9: Capstone: Production MCP Server

## Main idea
The capstone argues that advanced MCP features only become useful when they are composed under a specification-first design. The project is a research assistant server that uses deterministic tools where possible, sampling where reasoning is required, roots for file security, progress and logs for observability, and structured recovery for failure handling.

### The project and its constraints
The server is designed for a consulting-style research workflow: list documents, search them deterministically, summarize a single document with sampling, and synthesize multiple documents into a broader answer. The constraints are explicit: stay within the research directory, keep users informed during long operations, survive failures, and remain deployable without hardcoded local assumptions.

### Specification before implementation
The lesson spends substantial space on the written specification. It defines intent, success criteria, tool contracts, non-goals, architectural decisions, and quality criteria. The point is to make multiple developers converge on the same system by agreeing on constraints and rationale before code is generated.

### Tool design by operation type
The capstone separates deterministic and reasoning-heavy work. Listing and search stay server-side because they are fast and predictable. Summarization and synthesis use sampling because they need model reasoning. This keeps model usage targeted rather than spreading it across every operation.

### Security and error strategy
File access is confined to a declared research root, and each path is validated before I/O. Sampling failures are retried with backoff, missing files can be skipped when partial work remains possible, and full failure is reserved for cases where no meaningful result can still be returned.

### Integrated architecture
The lesson then composes the whole system: a client invokes tools over JSON-RPC, the server validates roots, logs milestones, emits progress, calls sampling where needed, and returns structured output. The later prompts ask the learner to use AI to flesh out the implementation without losing the specification.

### Takeaway
The capstone makes the chapter's claim concrete. Production MCP work is not a pile of features. It is a constrained system whose features are selected, combined, and justified through specification-first design.

---

# Assessment: Chapter Quiz

## Main idea
The quiz checks whether the learner can reason about the chapter's production patterns rather than merely recall syntax. It covers Context, sampling, notifications, roots, transport, scaling, and packaging/error decisions.

### What the quiz measures
The question set spans applied and analytic understanding. It asks when Context should be used, how sampling should be wired, how path validation should be enforced, which errors are retryable, and how server mode affects feature availability.

### Emphasis of the assessment
The quiz is not limited to isolated API facts. It tests architectural judgment: when to use stateless mode, when to preserve streaming, how to validate filesystem access, and how to interpret recovery scenarios.

### Follow-up learning loop
The closing section asks the learner to review weak areas with AI assistance and use missed questions as prompts for clarification. That keeps the skill-building loop from Lesson 0 alive through the end of the chapter.

### Takeaway
The assessment confirms whether the reader can make design decisions about advanced MCP servers, not just reproduce code fragments.
