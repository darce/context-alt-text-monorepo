# Chapter 104: Async Patterns & Streaming — drilldown summary

## Source record
- Source type: chapter landing page plus lesson sequence
- Title: Chapter 104: Async Patterns & Streaming
- Venue: Agent Factory
- URL: https://agentfactory.panaversity.org/docs/TypeScript-Language-Realtime-Interaction/async-patterns-streaming
- Scope used for this summary: chapter landing page plus the seven exposed lesson pages from `Promises and async/await` through `Concurrent Requests and Rate Limiting`

## Chapter thesis
Chapter 104 argues that production AI interfaces depend on disciplined control of asynchronous behavior. The chapter starts with Promise and `async`/`await` foundations, then builds outward into failure handling, cancellation, streaming protocols, transport design, resilience patterns, and bounded parallelism. Its practical claim is that responsive chat, voice, and tool-using systems are not made reliable by model quality alone. They require explicit handling of waiting, partial failure, interrupted work, streaming transport semantics, and throughput limits.

## Chapter-level structure
The landing page frames the chapter as a reusable `async-streaming` skill rather than a one-off tutorial. The stated goals are robust Promise use, streaming via SSE and streamable HTTP, cancellation with `AbortController`, retries and timeouts, and packaging those patterns into reusable utilities for later chapters.

The chapter is organized as a progression from local control to system control. It first explains how TypeScript async code works at the function level. It then shows how errors propagate, how cancellation and timeouts should be modeled, how streaming data arrives and must be parsed, why MCP moved from SSE toward streamable HTTP, how transient and sustained failures differ, and how to process many requests without blowing through quotas or memory.

One source inconsistency matters enough to preserve. The chapter landing page is labeled as Chapter 104 under Part 9, but the lesson pages still expose an older numbering scheme that labels the same material as Chapter 74 under Part 8. The content is clearly the same unit, but the site metadata has not been normalized.

## Lesson-by-lesson drilldown

### Lesson 1: Promises and async/await
The first lesson establishes the mental model. TypeScript async programming is presented as conceptually close to Python `asyncio`, but simpler at the runtime boundary because Node.js and browsers already provide the event loop. The lesson's main point is that `async` functions always return Promises and `await` pauses the current async function without blocking the whole program.

The lesson uses Promise states, sequential waiting, and Python-to-TypeScript comparisons to make the model concrete. Its practical payoff is not abstract language knowledge. It is the ability to structure AI API calls, chat turns, and streaming reads without freezing the interface or confusing the control flow.

### Lesson 2: Error Handling for Async Operations
This lesson argues that async reliability depends on explicit failure semantics. It emphasizes that `fetch` does not throw for HTTP error status codes, so callers must check `response.ok` and raise errors themselves if they want failures to enter `catch` blocks.

A second key point is TypeScript's stricter error model. Caught values are `unknown`, not automatically `Error`, because JavaScript can throw anything. The lesson therefore teaches type narrowing with `instanceof Error` before reading properties such as `message`. It also distinguishes local handling, propagation with rethrow, and unhandled rejection risk.

The lesson then extends beyond single-call failures. For multi-model or multi-request workflows, `Promise.all` is treated as too brittle when partial output is still useful. The chapter recommends `Promise.allSettled` for partial-success scenarios so the application can preserve completed work while reporting failures explicitly.

### Lesson 3: AbortController and Timeouts
This lesson treats cancellation as a first-class operational requirement. In AI interfaces, users navigate away, press stop, or change intent mid-generation. If in-flight requests are allowed to continue, the application wastes tokens, ties up resources, and risks updating UI state that no longer exists.

The core pattern is `AbortController` for user-driven cancellation and `AbortSignal.timeout()` for bounded latency. The chapter explicitly distinguishes `AbortError` from `TimeoutError`, because those two outcomes should usually produce different user messaging and different recovery behavior.

The lesson also covers composition. When an application needs both user cancellation and timeout behavior, it combines signals with `AbortSignal.any(...)`. The production framing matters: the goal is not merely to stop work, but to preserve partial output when appropriate, clean up readers and UI state, and align cancellation with browser lifecycle events or CLI interrupts such as `SIGINT`.

### Lesson 4: Server-Sent Events (SSE) Deep Dive
This lesson explains why AI interfaces feel responsive when they stream. SSE is presented as the protocol behind token-by-token or chunk-by-chunk delivery in many model APIs. The lesson's main claim is that streaming requires more than reading bytes. It requires understanding event framing, provider-specific payload shapes, end-of-stream markers, and incremental extraction of useful content from each chunk.

The chapter walks through the OpenAI-style format of repeated `data:` lines ending in `[DONE]`, then generalizes the pattern into reusable parsing logic. That shift from provider-specific parsing to extractor-based design is the lesson's real engineering move. It lets the same streaming machinery support multiple providers with different event payloads.

The lesson also covers reconnection and recovery. SSE's built-in `id` field and `Last-Event-ID` header are presented as the protocol's mechanism for resuming interrupted streams when the server supports it. The chapter notes that some major providers do not support resumable SSE in practice, but the recovery pattern remains important because it teaches how streaming clients should think about continuity, backoff, and replay.

### Lesson 5: Streamable HTTP: The MCP Standard
This lesson shifts from generic streaming to protocol evolution. It explains that MCP originally used SSE transport, but moved in March 2025 to Streamable HTTP because pure SSE became too limiting as MCP adoption expanded.

The chapter gives three reasons for the change. First, SSE is unidirectional, while MCP increasingly needs richer bidirectional exchanges. Second, long-lived SSE connections behave poorly across corporate proxies, load balancers, firewalls, and similar infrastructure. Third, simple operations should not require a permanently open stream when a standard HTTP request-response exchange is enough.

The lesson then introduces the operating model of Streamable HTTP. A client uses ordinary HTTP requests for non-streaming cases, upgrades to streaming behavior when needed, and carries forward state through the `Mcp-Session-Id` header. The practical recommendation is conservative: use Streamable HTTP for new MCP work, but preserve SSE fallback for compatibility with older servers and mixed environments.

### Lesson 6: Retry Logic and Circuit Breakers
This lesson argues that production AI systems need two different resilience patterns because not all failures mean the same thing. Retries handle transient problems such as rate limits, short outages, and network blips. Circuit breakers handle sustained degradation by failing fast once repeated attempts become wasteful.

The retry pattern is framed around exponential backoff rather than immediate repetition. The chapter treats this as a resource and etiquette issue as much as a correctness issue: immediate retries make overload and rate limits worse. Smarter retry logic therefore checks whether an error is retryable, bounds the number of attempts, and spaces them out progressively.

The circuit breaker section introduces the standard closed, open, and half-open states. Its job is to stop pointless retries when the dependency is persistently unhealthy, then allow a cautious recovery probe later. The lesson's most important implementation rule is layering: the circuit breaker should wrap retry logic, so the application first decides whether the dependency should be called at all, and only then decides how to retry transient failures inside the allowed window.

### Lesson 7: Concurrent Requests and Rate Limiting
The final exposed lesson addresses scale. AI applications frequently need to process many requests at once, such as batch document analysis, eval runs, or multi-item enrichment jobs. The chapter rejects both extremes: unbounded concurrency overwhelms APIs and memory, while serial processing wastes time and degrades user experience.

The lesson organizes the concurrency toolbox by intent. `Promise.all` is for cases where everything must succeed. `Promise.allSettled` is for partial completion. `Promise.race` is for first-completion or timeout patterns. A concurrency pool is the pattern for keeping a fixed number of operations active at a time while starting new work as old work finishes.

Rate limiting is then treated as a separate concern from concurrency. Even a well-bounded concurrency pool can violate provider quotas if requests are launched too quickly. The lesson's rate limiter therefore enforces minimum spacing between requests. The combined design goal is clear: keep throughput high, respect API quotas, avoid memory blowups, and return the fullest useful result set rather than collapsing the whole batch on individual failures.

## What the chapter says the reader owns at the end
By the end of the chapter, the reader is expected to own an `async-streaming` skill that can model Promise-based control flow, handle async failures safely, distinguish partial from total failure, cancel in-flight work, enforce timeouts, parse SSE streams, understand MCP's shift to Streamable HTTP, add retry and circuit-breaker resilience, and process batches under explicit concurrency and rate limits.

## Closing compression
The chapter's central claim is that asynchronous programming for AI systems is operational engineering, not just syntax. The lesson sequence starts with Promise fundamentals, then adds error discipline, cancellation, streaming transport knowledge, MCP transport evolution, resilience patterns, and bounded concurrency. The result is a reusable method for building AI interfaces that remain responsive under slow networks, partial failure, interrupted sessions, infrastructure constraints, and high request volume.
