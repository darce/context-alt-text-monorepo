# Chapter 76 drilldown: TDD for Agents

Source chapter: https://agentfactory.panaversity.org/docs/Building-Agent-Factories/tdd-for-agents

## What this chapter is doing

Chapter 76 draws a hard line between two kinds of testing for agent systems.

TDD in this chapter covers deterministic code behavior: API endpoints, database operations, tool functions, mocked LLM interactions, and full agent pipelines whose external model calls are replaced with controlled responses. Evals are left for the next chapter because they answer a different question: whether the model reasons well, not whether the code path is correct.

The chapter’s practical outcome is a reusable `agent-tdd` skill plus a production test suite for the Task API. The target is explicit across the overview and capstone pages: 80% or higher coverage, zero live LLM API calls during tests, sub-10-second feedback, and CI enforcement on every pull request.

## Chapter thesis

The chapter argues that agent applications should be tested like software first and like model behavior second. That means fast, mocked, deterministic tests should cover the code you own, while probabilistic quality checks should be separated into evals. The split matters because expensive, slow, real-call test suites do not run often enough to protect production code.

## What you build across the chapter

By the end of the chapter, the learner is expected to have:

- an `agent-tdd` skill built from official pytest-asyncio and respx documentation
- async test infrastructure for Python agent projects
- endpoint tests for a FastAPI Task API
- model tests for SQLModel operations
- LLM mocks for OpenAI and Anthropic style calls
- isolated tests for tool logic
- multi-step integration tests for agent pipelines
- coverage and CI rules that block unsafe merges

## Drilldown by page

### Overview page

The overview frames the chapter as quality assurance for agent code rather than model-quality measurement. It lists the learning path from manual skill creation through philosophy, async test setup, endpoint testing, database testing, LLM mocking, tool testing, integration tests, and a final capstone. It also names the core stack: pytest-asyncio, httpx, respx, and pytest-cov.

### Lesson 0: Build Your Testing Skill

This page uses the same skill-first pattern as earlier chapters. The learner is told to fetch the Claude Code Skills Lab, invoke the skill creator, and build a new `agent-tdd` skill grounded in official pytest-asyncio and respx documentation. The purpose is structural: the chapter is not only teaching testing patterns, it is teaching the learner to own those patterns as a reusable asset stored under `.claude/skills/agent-tdd/`.

The rest of the chapter is then framed as a loop for improving that skill. Each lesson ends with a check against the current skill output, then a prompt to patch missing patterns back into it.

### Lesson 1: TDD Philosophy for Agent Development

This lesson establishes the boundary between TDD and evals. TDD is for deterministic behavior: whether an endpoint rejects a bad token, whether a record is written correctly, whether a tool returns the right shape, whether mocked agent flow logic takes the correct branch. Evals are for things like helpfulness, ambiguity handling, safety, topicality, and factual quality.

The chapter’s economic argument also starts here. The lesson models a monthly cost for live-call testing and then ties cost to behavior: expensive tests run rarely, while zero-cost mocked tests can run after every change. The point is not just savings. It is frequency. Fast tests become part of ordinary development; slow paid tests drift toward occasional ceremony.

Operationally, this lesson gives the chapter its central testing rule: mock model responses for code-correctness tests, reserve real model calls for evaluation of reasoning quality.

### Lesson 2: pytest Fundamentals for Async Code

This lesson sets up the async test foundation. Since agent code typically uses `async def` for HTTP calls, database work, and SDK operations, the test harness has to understand coroutines and event loops. The learner installs pytest, pytest-asyncio, httpx, respx, and pytest-cov, then configures pytest-asyncio to run async tests reliably.

The page pays special attention to event loop scope. Function-scoped loops maximize isolation. Session-scoped loops matter when expensive async fixtures need to outlive a single test, such as shared database connections. The chapter leans toward function-level isolation by default, but it explains the session-scoped pattern so the learner can trade setup cost against isolation deliberately.

It also introduces async fixtures and the common failure modes around missing `await`, missing markers, and mismatched fixture scope.

### Lesson 3: Testing FastAPI Endpoints

This lesson moves from generic async testing into app-level HTTP testing. The recommended pattern is `httpx.AsyncClient` plus `ASGITransport`, which sends requests directly into the FastAPI app without starting a real server. That keeps tests fast and removes network noise.

The other major pattern is dependency overrides. The learner replaces dependencies such as `get_session` and `get_current_user` with test versions inside fixtures, then clears those overrides after the test run. That makes it possible to test authentication, authorization, validation, CRUD endpoints, and error responses in a controlled environment.

The page also pushes toward a complete `conftest.py` setup rather than ad hoc per-test wiring. That is consistent with the rest of the chapter: reusable infrastructure first, individual tests second.

### Lesson 4: Testing SQLModel Operations

Here the test target narrows to the data layer. Endpoint tests cover the full request path, but model tests go directly at persistence logic so failures are easier to localize. The lesson uses in-memory SQLite for speed and isolation, then explains the trap that appears if each connection gets a separate empty in-memory database.

The fix is `StaticPool`, which keeps the same connection alive across operations. The lesson pairs that with async session fixtures, table setup and teardown, and direct tests for record creation, relationships, cascade deletes, and constraint failures.

It also warns that SQLite is not PostgreSQL. A passing SQLite test is still useful, but it does not erase backend differences. The chapter treats that as a known limit rather than pretending the databases behave identically.

### Lesson 5: Mocking LLM Calls

This lesson is the hinge for the whole chapter. The testing strategy only works if model calls can be replaced cleanly. The page teaches respx as a transport-layer mock for httpx-based clients, which matters because modern OpenAI and Anthropic SDKs commonly sit on top of httpx.

The lesson covers three mock styles: decorator, context manager, and shared fixture. It then moves into response-shape realism: basic completions, richer full responses, tool call payloads, multiple tool calls, and API failure cases such as rate limits. The goal is not superficial stubbing. The mock has to look close enough to the real provider response that the application code exercises the same parser and control flow it would use in production.

This is where the chapter turns “zero LLM API calls” from a slogan into a repeatable mechanism.

### Lesson 6: Testing Agent Tools

The main claim here is that agent tools should not be treated as mysterious agent internals. A tool is regular Python with framework metadata attached. The decorator tells the SDK how to expose the function, but the function body is still testable directly.

That leads to a clean split in test design:

- test the business logic directly as Python
- test edge cases with normal unit-test techniques such as parameterization
- leave framework composition concerns for higher-level tests

This lesson matters because it cuts down debugging ambiguity. If a tool is isolated and correct on its own, later failures in a full agent run are less likely to be blamed on the wrong layer.

### Lesson 7: Integration Test Patterns

After the isolated layers come together, the chapter shows how to test full agent flows. These tests combine mocked model responses, database state changes, and multi-step conversation flow. The key respx technique is `side_effect` with ordered responses, so one mocked LLM call can return a tool invocation and the next can return the final answer.

The lesson also covers error paths. A `side_effect` can raise exceptions or simulate malformed and rate-limited responses, which lets the learner test timeouts, retries, and graceful failure handling without using the live provider.

The core discipline here is state verification. The test should not stop at checking the final text response. It should confirm that the database or other system state changed as expected after the agent acted.

### Lesson 8: Capstone — Full Test Suite for Task API

The capstone shifts from individual patterns to system design. The learner is asked to write a `TEST_SPEC.md` first, define success criteria, organize tests by category, and only then implement the suite. The capstone is explicit about its targets: coverage above 80 percent, runtime under 10 seconds, zero live LLM calls, stable test behavior, and CI execution on every pull request.

This page adds the production scaffolding around the earlier lessons:

- test factories for consistent object creation
- coverage configuration in `pyproject.toml`
- GitHub Actions workflow setup
- branch protection so failing tests block merges
- a complete `tests/` directory structure

This is where the chapter becomes more than a test tutorial. It becomes a release-gating pattern for agent-backed applications.

### Chapter quiz

The quiz reinforces the actual boundaries the chapter wants the reader to remember: authentication logic is TDD territory, not eval territory; async testing relies on pytest-asyncio and the right event-loop setup; respx is the mechanism for zero-cost mocked model calls; and integration tests should verify both output and downstream state.

## The chapter’s working method

Across all pages, the chapter repeats one operating pattern:

1. build the reusable skill first
2. learn one new testing pattern
3. test whether the skill already knows it
4. patch the missing pattern into the skill
5. compose the patterns into a full production suite

That structure is consistent with the course’s wider claim that durable agent development is partly about owning reusable skills, not only about solving one project once.

## Reusable patterns extracted from the chapter

### 1. Separate code correctness from model quality

Use TDD for deterministic code paths and evals for probabilistic judgment tasks. Mixing them makes test suites slower, more expensive, and harder to reason about.

### 2. Keep model calls out of ordinary tests

Mock provider responses at the transport layer so the application sees realistic payloads but no real network call happens.

### 3. Test each layer on its own terms

- FastAPI endpoints through `AsyncClient` and `ASGITransport`
- SQLModel logic through direct session tests
- tool functions as normal Python
- full pipelines through sequential mock responses and state verification

### 4. Use fixtures as infrastructure, not convenience glue

The chapter treats fixtures as the backbone of the suite: event loops, async clients, database sessions, dependency overrides, mock providers, and cleanup all belong there.

### 5. Treat the capstone as release engineering

Coverage thresholds, CI runs, and protected branches turn tests into enforcement. Without that last step, the chapter’s earlier patterns remain optional.

## What a learner should retain after Chapter 76

A strong reading of this chapter leaves the learner with a concrete testing posture for agent systems:

- most of the codebase should be tested deterministically
- most tests should run without paid model calls
- provider mocks should preserve realistic payload shape
- isolated unit tests and integration tests serve different jobs
- CI and branch rules are part of testing, not an afterthought
- evals still matter, but they belong in a separate layer with separate goals

## Source links

- Chapter overview: https://agentfactory.panaversity.org/docs/Building-Agent-Factories/tdd-for-agents
- Lesson 0: https://agentfactory.panaversity.org/docs/Building-Agent-Factories/tdd-for-agents/build-your-testing-skill
- Lesson 1: https://agentfactory.panaversity.org/docs/Building-Agent-Factories/tdd-for-agents/tdd-philosophy-for-agents
- Lesson 2: https://agentfactory.panaversity.org/docs/Building-Agent-Factories/tdd-for-agents/pytest-async-fundamentals
- Lesson 3: https://agentfactory.panaversity.org/docs/Building-Agent-Factories/tdd-for-agents/testing-fastapi-endpoints
- Lesson 4: https://agentfactory.panaversity.org/docs/Building-Agent-Factories/tdd-for-agents/testing-sqlmodel-operations
- Lesson 5: https://agentfactory.panaversity.org/docs/Building-Agent-Factories/tdd-for-agents/mocking-llm-calls
- Lesson 6: https://agentfactory.panaversity.org/docs/Building-Agent-Factories/tdd-for-agents/testing-agent-tools
- Lesson 7: https://agentfactory.panaversity.org/docs/Building-Agent-Factories/tdd-for-agents/integration-test-patterns
- Lesson 8: https://agentfactory.panaversity.org/docs/Building-Agent-Factories/tdd-for-agents/capstone-task-api-test-suite
- Quiz: https://agentfactory.panaversity.org/docs/Building-Agent-Factories/tdd-for-agents/quiz
