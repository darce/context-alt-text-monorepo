# Chapter 107: Testing TypeScript for AI Applications — Drilldown

Source chapter: [Testing TypeScript for AI Applications](https://agentfactory.panaversity.org/docs/TypeScript-Language-Realtime-Interaction/testing-typescript-ai)

## Chapter thesis

This chapter argues that TypeScript AI applications need a layered test strategy rather than a single testing tool. The sequence starts with Vitest fundamentals, moves into mocks for cost and determinism, then covers streaming-specific tests, runtime contract checks with Zod, selective integration testing against recorded or live responses, and compile-time type tests. The chapter's end state is a reusable `ts-testing` skill that checks behavior, response shape, integration boundaries, and type guarantees.

## What the chapter is trying to build

The overview frames the chapter as a practical testing chapter for UI and SDK code that talks to AI systems. Its stated goals are to write unit and integration tests with Vitest or Jest-style patterns, mock AI APIs and streaming responses, keep frontend and backend types aligned with contract tests, and use the TypeScript compiler itself as part of the safety net. The outcome is a reusable TypeScript testing setup for AI-facing code rather than a one-off suite for a single feature.

## Live navigation note

The chapter overview is published as Chapter 107 under Part 9, but the lesson pages still expose older Part 8 / Chapter 77 labels in their own navigation. The live authored sequence currently runs from the overview through six lesson pages and then links directly to Chapter 108. I did not find a separately exposed Chapter 107 quiz page in the live next-page flow.

## Chapter structure at a glance

1. Overview: testing goals and chapter scope
2. Vitest Fundamentals
3. Mocking AI APIs
4. Testing Streaming Responses
5. Contract Testing with Zod
6. Integration Testing Patterns
7. Type-Driven Development

## Drilldown by page

### 1) Overview

Source: [Chapter 107 overview](https://agentfactory.panaversity.org/docs/TypeScript-Language-Realtime-Interaction/testing-typescript-ai)

The overview defines the chapter as the place where the reader turns TypeScript testing into an AI-specific practice. The goals focus on four layers: ordinary unit and integration tests, mocks for AI APIs and streams, contract checks that keep types in sync across boundaries, and compiler-driven checks that catch type misuse before runtime. The lesson progression also matters. It shows that the chapter treats mocking, streaming, contracts, integration, and type checking as complementary rather than interchangeable techniques.

### 2) Vitest Fundamentals

Source: [Vitest Fundamentals](https://agentfactory.panaversity.org/docs/TypeScript-Language-Realtime-Interaction/testing-typescript-ai/vitest-fundamentals)

This lesson establishes Vitest as the base runner for the rest of the chapter. It recommends a minimal configuration with explicit imports, a Node environment, and file patterns such as `*.test.ts` or `*.spec.ts`. From there it teaches the core mechanics the rest of the chapter assumes: `describe` and `it` for structure, `expect` matchers for assertions, `toThrow` for error paths, lifecycle hooks for shared setup, and snapshots for shape-heavy outputs.

The lesson's real point is not that Vitest exists. It is that AI code needs the same testing discipline as any other TypeScript code, and the testing vocabulary has to be fluent before the chapter can move into AI-specific failure modes. The snapshot section is the first sign of that shift. It treats snapshots as suitable for complex object structures, parsed data, and formatted outputs, but rejects them for simple scalar checks, dynamic values, and behavior tests. That distinction matters later when the chapter starts testing streams and contracts.

The closing commands section turns Vitest into a daily tool: watch mode for rapid iteration, targeted test runs, snapshot updates, and coverage reporting. In other words, this lesson lays down the mechanics and the judgment needed for the rest of the chapter.

### 3) Mocking AI APIs

Source: [Mocking AI APIs](https://agentfactory.panaversity.org/docs/TypeScript-Language-Realtime-Interaction/testing-typescript-ai/mocking-ai-apis)

This lesson explains why AI clients are unusually expensive to test against live services. Responses are non-deterministic, latency is high, per-call cost accumulates, rate limits distort CI, and streaming adds time-dependent behavior. The answer is mocking, but the lesson is careful about what good mocking actually requires.

The first layer is ordinary `vi.fn()` usage: create a mock, inspect its call history, and control return values. The second layer is async mocking, where `mockResolvedValue`, `mockRejectedValue`, and the `Once` variants let the test describe retry and failure sequences. The third layer is module replacement with `vi.mock`, which the lesson uses for SDKs imported directly into the code under test. It explains that `vi.mock` is hoisted, intercepts the target import, and replaces the module's exports before the dependent module loads.

A more practical refinement appears in the mock factory pattern. Instead of hand-writing the whole SDK mock in every file, the lesson builds a reusable factory that returns typed mock constructors and handles nested SDK methods such as `chat.completions.create` and stream-related methods. This is paired with `vi.mocked`, which restores TypeScript awareness of mock methods and metadata after a module has been mocked.

The AI-specific section is the streaming mock section. Here the lesson shifts from promise-returning mocks to async generators that yield chunks over time. It shows how to test success paths, SDK streaming methods, and stream cancellation. The complete-example section then folds these pieces into a chat-service test file so the reader can see how ordinary mocking, module replacement, stream mocking, and assertion patterns fit together. The safety note is well aimed: a mock must match the real API structure, or the suite becomes a fiction.

### 4) Testing Streaming Responses

Source: [Testing Streaming Responses](https://agentfactory.panaversity.org/docs/TypeScript-Language-Realtime-Interaction/testing-typescript-ai/testing-streaming-responses)

This is the most operational lesson in the chapter. It treats streaming as a separate testing problem rather than a small variation on request-response APIs. The opening problem statement is straightforward: once tokens arrive incrementally, tests have to deal with timing, cancellation, ordering, partial failure, and producer-consumer coordination.

The first pattern is mocking async generators. The lesson uses `async function*` to create streams that yield chunks in a controlled order, with optional delays and injected failures. That makes it possible to test success, slow producers, and failure conditions without calling a real streaming API. It then adds a reusable stream factory so tests can generate many stream shapes without repeating boilerplate.

The next pattern is SSE testing. Since many AI APIs stream over Server-Sent Events, the lesson adds a parser-focused test layer that checks line parsing, `[DONE]` handling, invalid JSON tolerance, and conversion from text events into semantic chunks. This narrows the problem: one set of tests validates the transport shape, another validates the consumer logic.

The lesson then moves to cancellation with `AbortController`. It treats cancellation as routine behavior rather than an edge case. The tests assert that the consumer stops when the signal aborts and that cleanup still runs. After that, the chapter adds ordering checks, concurrent chunk-processing checks, and partial-response handling. The partial-response section is one of the load-bearing parts of the chapter: it requires consumers to surface accumulated content when a stream fails mid-flight instead of throwing away everything received so far.

The complete example consolidates these ideas into a stream consumer test file with success, error, cancellation, and edge-case branches. The quick reference distills the core techniques: async generators for stream mocks, delay control for timing-sensitive behavior, SSE stream creation, `AbortController`, index tracking for order, `try/catch` for partial responses, and `finally` for cleanup.

### 5) Contract Testing with Zod

Source: [Contract Testing with Zod](https://agentfactory.panaversity.org/docs/TypeScript-Language-Realtime-Interaction/testing-typescript-ai/contract-testing-zod)

This lesson makes the boundary between compile-time types and runtime data explicit. TypeScript types vanish after compilation, so they do nothing when the backend returns a renamed field or a changed response shape. Zod is introduced as the contract layer because a schema can both infer TypeScript types and validate live or recorded data at runtime.

The lesson starts with schema definition and `safeParse`, then moves quickly into fixtures recorded from real APIs. That part matters because contract tests are only as good as the data they validate. Stale fixtures validate an obsolete world. The lesson's answer is a fixture-recording pattern that periodically refreshes saved responses and then validates those files against current schemas.

Schema evolution gets its own section because a brittle contract suite is not useful either. The lesson shows three accommodation patterns: `.passthrough()` for unknown future fields, `optional()` or `nullable()` for backward compatibility, and default values for absent fields. The point is not to loosen everything. It is to loosen the right surfaces while still failing on real contract breaks.

The API-drift section turns that into a testing pattern. The frontend's expected schema is treated as an executable statement of what the code can handle. A multi-schema contract suite can then validate chat completions, streaming chunks, and error payloads together, making drift visible in CI instead of in production logs. The complete workflow section ties together schema definition, fixture refresh, validation, and automated update paths in CI.

### 6) Integration Testing Patterns

Source: [Integration Testing Patterns](https://agentfactory.panaversity.org/docs/TypeScript-Language-Realtime-Interaction/testing-typescript-ai/integration-testing-patterns)

This lesson rejects the idea that mocks are enough. Its opening claim is that mocks prove the code matches the developer's assumptions, while integration tests check whether those assumptions still fit the real system. For AI software, the lesson defines a spectrum rather than a binary: full mocks, recorded fixtures, seeded real API calls, and fully live API calls. Each has a distinct cost, speed, and confidence profile.

The lesson treats recorded fixtures as the default integration layer because they preserve real response shape without paying the cost of live calls in every run. Real API calls remain necessary for some jobs, especially validating that fixtures still match current provider behavior. To reduce variability, the chapter adds seeded requests. Seeds are described as reducing variation, not eliminating it, which is the right caution. The reader is pushed toward a deliberate seed strategy rather than a vague hope of reproducibility.

The environment section is practical. It separates test credentials from production credentials, sets test-specific overrides such as shorter timeouts and fewer retries, and uses Vitest setup files to enforce that tests run in a real test context. The rate-limit section adds a queueing wrapper so real API tests do not self-sabotage by exceeding provider limits.

The CI/CD section then arranges these ideas into test tiers: mocked unit tests for every commit, fixture-based integration tests for PRs, selective real API or smoke tests on main, and cost budgeting so the suite remains sustainable. The complete example combines fixtures, metadata, rate limiting, and cost tracking into a full integration test file. The chapter is clear here: integration testing for AI systems is as much about controlling cost and nondeterminism as it is about asserting outputs.

### 7) Type-Driven Development

Source: [Type-Driven Development](https://agentfactory.panaversity.org/docs/TypeScript-Language-Realtime-Interaction/testing-typescript-ai/type-driven-development)

The final lesson moves one layer earlier in the lifecycle. Runtime tests only tell you whether executed code behaved correctly. Type tests tell you whether invalid uses of the API can compile at all. The lesson treats the TypeScript compiler as an additional test framework.

The main tool is `@ts-expect-error`. The lesson uses it to assert that lines missing required fields, using wrong types, or bypassing narrowing should fail. If those lines stop failing, the directive itself becomes an error, which turns unintended loosening of types into a CI-visible problem. That pattern is extended to readonly constraints and invalid message shapes.

The narrowing section covers discriminated unions and exhaustive handling with `never`. This is the chapter's answer to AI clients that return multiple result shapes such as content chunks, tool calls, and completion markers. By testing exhaustiveness, the lesson forces the codebase to handle new variants when they are introduced instead of silently ignoring them.

The lesson then adds `tsd` for assertion-style type tests around exported APIs and generic functions. That is especially relevant for SDK surfaces where preserving inference across helper layers is part of the product quality. The CI section closes the loop by combining `vitest run`, `tsc --noEmit`, and `tsd` in one command chain. The ending message is clear: runtime tests and type tests cover different classes of failure, and AI applications need both.

## What the chapter adds up to

Taken together, the chapter builds a layered testing model for TypeScript AI software:

- Vitest for baseline runtime testing
- mocks for fast, deterministic unit tests
- async-generator and SSE tests for streaming behavior
- Zod schemas for runtime contracts across service boundaries
- integration tiers for fixture-backed and selective live validation
- compiler and `tsd` checks for type-level guarantees

The chapter's strongest contribution is that it does not treat any one of these as a silver bullet. It keeps the boundaries straight. Mocks are for speed and control. Contract tests are for boundary validation. Integration tests are for reality checks. Type tests are for compile-time misuse. When those layers are combined, the SDK or UI code has a better chance of surviving provider changes, stream failures, schema drift, and type regressions.

## Notable publication inconsistency

- Overview page: Chapter 107 under Part 9
- Lesson pages: older Chapter 77 / Part 8 labels still appear in the live navigation
- Live next-page flow: the final lesson links directly to Chapter 108, with no separately exposed Chapter 107 quiz page in the current authored sequence

## Source pages

- [Chapter 107 overview](https://agentfactory.panaversity.org/docs/TypeScript-Language-Realtime-Interaction/testing-typescript-ai)
- [Vitest Fundamentals](https://agentfactory.panaversity.org/docs/TypeScript-Language-Realtime-Interaction/testing-typescript-ai/vitest-fundamentals)
- [Mocking AI APIs](https://agentfactory.panaversity.org/docs/TypeScript-Language-Realtime-Interaction/testing-typescript-ai/mocking-ai-apis)
- [Testing Streaming Responses](https://agentfactory.panaversity.org/docs/TypeScript-Language-Realtime-Interaction/testing-typescript-ai/testing-streaming-responses)
- [Contract Testing with Zod](https://agentfactory.panaversity.org/docs/TypeScript-Language-Realtime-Interaction/testing-typescript-ai/contract-testing-zod)
- [Integration Testing Patterns](https://agentfactory.panaversity.org/docs/TypeScript-Language-Realtime-Interaction/testing-typescript-ai/integration-testing-patterns)
- [Type-Driven Development](https://agentfactory.panaversity.org/docs/TypeScript-Language-Realtime-Interaction/testing-typescript-ai/type-driven-development)

## Local drafting constraints used

- `agent-summary-template-from-bauer-ramazani.md`
- `ai-writing-tropes-squashed-augmented.md`
