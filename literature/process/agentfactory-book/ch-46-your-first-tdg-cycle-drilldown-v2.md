# Chapter 46 Drilldown: Your First TDG Cycle

Original chapter entry: https://agentfactory.panaversity.org/docs/Programming-in-the-AI-Era/the-workbench/your-first-tdg-cycle

## What this chapter is doing

Chapter 46 introduces **Test-Driven Generation (TDG)** as the first full Python expression of the book's earlier **Spec-Driven Development (SDD)** method. The chapter's core claim is simple: the human writes a compact specification in Python, AI writes the implementation, and tools plus human reading verify the result.

The chapter teaches one loop and repeats it until it feels normal:

1. Specify a stub and tests.
2. Check types with `pyright`.
3. Ask AI to implement.
4. Verify with `pytest`.
5. Read the generated code with PRIMM.

The teaching move here matters. The chapter is not mainly about Python syntax. It is about changing the student's role from manual implementation to specification and verification.

## Chapter structure on the live site

The live Chapter 46 sequence currently exposes:

- Overview page
- Lesson 1: From Reading to Specifying
- Lesson 2: Your First Failing Test
- Lesson 3: AI Generates, You Verify
- Lesson 4: When AI Gets It Wrong

After Lesson 4, the bottom `Next` navigation currently jumps to **Phase 2 — Specify with Types**, not to a separately exposed Chapter 46 quiz page. In other words, the live authored sequence for this chapter appears to end with Lesson 4 and its chapter-end rubric.

## Chapter thesis in one paragraph

The chapter argues that beginner-friendly AI programming should start with **small, typed, testable specifications**, not with free-form prompting and not with hand-written implementations. A stub plus two tests is enough to define intent. AI can then write code against that intent. The safety comes from two layers: automated verification (`pyright` and `pytest`) and human inspection of the generated logic. The chapter's deeper point is that green tests are necessary but not sufficient; the human still has to read the code.

## Detailed drilldown

### Overview page: Chapter 46

Source: https://agentfactory.panaversity.org/docs/Programming-in-the-AI-Era/the-workbench/your-first-tdg-cycle

The overview page frames the chapter as the bridge from **reading Python** in Chapter 45 to **specifying Python** for AI generation.

What it introduces:

- **TDG as Python-native SDD**: Chapter 16 taught specification-first work in English. Chapter 46 shifts the specification into Python itself through type annotations and tests.
- **The five-step loop**:
  - specify
  - check types
  - generate
  - verify
  - read
- **Three new vocabulary items**:
  - `return`
  - `-> float`
  - `...`
- **The operational distinction between TDD and TDG**: both start with tests, but in TDG the AI writes the implementation and the human verifies.
- **Tool-agnostic framing**: the examples use Claude Code, but the chapter says the workflow applies to any coding assistant.

The overview also establishes a recurring educational pattern for the chapter: each lesson has a PRIMM-AI+ practice block, so code generation never replaces code reading.

### Lesson 1: From Reading to Specifying -- What Is TDG?

Source: https://agentfactory.panaversity.org/docs/Programming-in-the-AI-Era/the-workbench/your-first-tdg-cycle/from-reading-to-specifying

This lesson is the conceptual pivot.

#### Main point

The student already knows more than they think. If they can read a stub and two assertions, they can understand the whole TDG loop.

#### What the lesson actually teaches

It rewrites the old SDD workflow into a Python form:

- English requirement becomes a **function signature plus tests**
- AI still generates
- verification becomes partly automatic through `pytest` and `pyright`

The worked example is intentionally tiny:

```python
def double(n: int) -> int: ...
```

with two tests. The point is not the function. The point is that five lines of specification can drive correct generation.

#### Load-bearing ideas

- **A stub is a specification artifact**, not a half-written implementation.
- **Tests are more precise than prose**. The chapter contrasts English ambiguity with a concrete assertion like `assert celsius_to_fahrenheit(0.0) == 32.0`.
- **Reading stays central even after tests pass**. The student is told to predict outputs for unseen inputs and confirm the logic mentally.

#### Important claims the lesson makes

The lesson explicitly says:

- TDG is SDD translated into Python.
- Small, diverse tests are better than bloated test suites for guiding AI.
- The student's value is in the specification and verification, not in typing the middle layer.

#### Why this page matters

Without Lesson 1, the rest of the chapter could look like syntax training. This page makes clear that the real subject is a workflow for trustworthy AI-assisted programming.

### Lesson 2: Your First Failing Test

Source: https://agentfactory.panaversity.org/docs/Programming-in-the-AI-Era/the-workbench/your-first-tdg-cycle/your-first-failing-test

This lesson finally lets the student write, but only the **specification layer**.

#### Main point

The right first success is not a green test. It is a **valid red state**:
- pyright passes
- pytest fails

That means the specification is sound and the implementation is still absent.

#### New syntax introduced

1. **`return`**
   - returns a value to the caller
   - different from `print()`
   - tests can assert on returned values, not printed output

2. **`-> float`**
   - states the function's return type
   - gives both the type checker and the reader a contract

3. **`...`**
   - marks an intentionally empty stub
   - lets `pyright` accept the function as a stub without demanding a real body

#### One of the best distinctions in the chapter

The lesson contrasts `...` with `pass`:

- `...` makes the function a stub that `pyright` accepts
- `pass` makes it a real function body with no return, which creates a type mismatch for non-`None` return types

That is not decorative syntax. It is what keeps Step 2 clean.

#### The actual exercise

The student writes:

```python
def celsius_to_fahrenheit(celsius: float) -> float: ...
```

and then writes two tests:
- freezing point
- boiling point

The expected result:

- `uv run pyright` returns clean
- `uv run pytest` fails because the function currently returns `None`

#### Why the red state matters

The lesson insists that this is not an error condition. It is the intended handoff point between human specification and AI generation.

That is one of the chapter's strongest habits:
- shape verified first
- behavior verified second
- implementation deferred until the spec is stable

### Lesson 3: AI Generates, You Verify

Source: https://agentfactory.panaversity.org/docs/Programming-in-the-AI-Era/the-workbench/your-first-tdg-cycle/ai-generates-you-verify

This lesson covers the first full green cycle.

#### Main point

The first green bar is useful, but the chapter refuses to treat it as enough. The lesson is about generation **and** post-generation scrutiny.

#### Prompt pattern taught

The student is told to use a narrow, test-anchored prompt:

> Implement the celsius_to_fahrenheit function ... so that all tests ... pass. Do not modify the tests.

The phrase **"Do not modify the tests"** is treated as essential because the tests are the specification.

#### Operational habit introduced

The lesson tells the student to **commit the tests first** so any AI modification of the specification can be caught in `git diff`.

That is a strong professional move. It treats the tests as the protected source of truth.

#### What the lesson demonstrates

AI generates:

```python
return celsius * 9 / 5 + 32
```

Then the student:
- reruns `pyright`
- reruns `pytest`
- reads the generated line
- predicts new values such as `37.0` and `-40.0`
- traces the computation

#### The most important conceptual section: the trust gap

This lesson is where the chapter becomes more than beginner tutoring.

It says:

- passing tests only prove the cases you wrote
- a function can pass a narrow test set and still be wrong
- human reading closes the gap between “tests pass” and “logic is trustworthy”

That is the chapter's adult insight. Verification is layered:
- tests check selected behavior
- PRIMM reading checks general logic

#### Independent practice

The student then performs another TDG cycle on `fahrenheit_to_celsius`, which turns the lesson from demonstration into repetition.

### Lesson 4: When AI Gets It Wrong

Source: https://agentfactory.panaversity.org/docs/Programming-in-the-AI-Era/the-workbench/your-first-tdg-cycle/when-ai-gets-it-wrong

This is the chapter's most important page.

#### Main point

TDG is not sold as “AI gets it right first try.” It is sold as a loop where **failures are legible and recoverable**.

#### The chosen example

The function is `reading_time_minutes(word_count, words_per_minute) -> float`.

The specification includes:
- one exact-division case
- one fractional-result case

AI's first attempt uses:

```python
return word_count // words_per_minute
```

The first test passes. The second fails.

That is a good teaching example because it exposes a common AI failure mode:
- the code is plausible
- part of the test suite passes
- one operator is wrong
- the bug is visible only if the tests are diverse enough

#### What the lesson teaches the student to do with failure

1. Read the failing assertion carefully
2. Compare expected vs actual
3. Classify the failure
4. Identify the specific operator or logic error
5. Re-prompt with an explicit diagnosis

The repair prompt is not vague. It names:
- the failing test
- the wrong value
- the root cause
- the requested fix

That is the chapter's model of disciplined iteration.

#### The deeper lesson

AI failure is not outside the workflow. It is one of the workflow's normal states.

The chapter reframes iteration as:

`Specify → Generate → Verify → if fail, read → re-prompt → verify`

That framing is crucial. It stops the student from interpreting a red test as “the method failed.” The method is doing its job.

#### Chapter-end material on this page

Lesson 4 also carries the chapter's wrap-up apparatus:

- self-assessment rubric
- common mistakes table
- final takeaways
- transition to the next phase

That suggests the live site currently treats Lesson 4 as the chapter terminus.

## What Chapter 46 adds to the book's larger method

This chapter is not just “first Python testing.” It locks in several durable rules for the rest of Part 4.

### 1. The specification belongs to the human

The human owns:
- function shape
- types
- expected behavior
- test cases

AI is allowed to implement against the specification, not redefine it.

### 2. Type checking and behavioral checking are separate gates

The chapter is careful about this split:

- `pyright` checks the contract shape
- `pytest` checks the runtime behavior

That makes debugging cleaner because the student can isolate what kind of failure they are seeing.

### 3. Red is a valid stage

A failing test suite before generation is a milestone, not a setback.

### 4. Green is not final trust

Passing tests are necessary. They do not remove the obligation to read the code.

### 5. Re-prompting should be diagnostic, not emotional

The best re-prompt is not “it failed, fix it.”
It is:
- which test failed
- what value was returned
- what should have been returned
- what operator or logic caused the mismatch

## Reusable chapter pattern

The chapter implies a reusable pattern for any small function:

1. Write a stub with a return type.
2. Write two non-redundant tests.
3. Run `pyright`.
4. Run `pytest` and confirm RED.
5. Prompt AI to implement without touching tests.
6. Run `pytest` again.
7. Read the generated implementation.
8. Predict one or two new inputs.
9. If the tests fail, classify and re-prompt.

That is the smallest useful TDG cycle the book has shown so far.

## Commands and artifacts the chapter standardizes

### Commands

```bash
uv run pyright
uv run pytest -v
git add tests/test_temperature.py && git commit -m "test: add celsius_to_fahrenheit specification"
```

### Artifacts

- function stub
- test file
- AI implementation
- pytest failure output
- diagnostic re-prompt
- PRIMM trace or output prediction

## Common mistakes the chapter explicitly warns about

From the chapter-end material:

- using `print()` instead of `return`
- using `pass` instead of `...`
- using `//` where `/` is required
- trusting GREEN without reading the implementation

Those are not random beginner errors. They match the chapter's governing concern: preserving a clean spec → generate → verify loop.

## What a good student should leave this chapter able to do

By the end of the chapter, a student should be able to:

- explain TDG in relation to SDD and TDD
- write a typed stub
- write two tests that define behavior
- produce a correct RED state
- prompt AI against the tests
- protect the tests from AI edits
- read generated code rather than just run it
- diagnose a failed generation
- write a specific correction prompt

That is a real threshold. It turns the student from passive AI user into a basic AI code verifier.

## Bottom line

Chapter 46 is the first chapter in Part 4 where the student performs the whole AI programming loop on actual Python code. Its contribution is not syntax coverage. Its contribution is **discipline**:

- write the contract first
- protect the tests
- verify with tools
- read the generated logic
- treat failures as normal inputs to the loop

That is the foundation the later Python chapters will build on.

## Source links

- Chapter overview  
  https://agentfactory.panaversity.org/docs/Programming-in-the-AI-Era/the-workbench/your-first-tdg-cycle

- Lesson 1: From Reading to Specifying -- What Is TDG?  
  https://agentfactory.panaversity.org/docs/Programming-in-the-AI-Era/the-workbench/your-first-tdg-cycle/from-reading-to-specifying

- Lesson 2: Your First Failing Test  
  https://agentfactory.panaversity.org/docs/Programming-in-the-AI-Era/the-workbench/your-first-tdg-cycle/your-first-failing-test

- Lesson 3: AI Generates, You Verify  
  https://agentfactory.panaversity.org/docs/Programming-in-the-AI-Era/the-workbench/your-first-tdg-cycle/ai-generates-you-verify

- Lesson 4: When AI Gets It Wrong  
  https://agentfactory.panaversity.org/docs/Programming-in-the-AI-Era/the-workbench/your-first-tdg-cycle/when-ai-gets-it-wrong

- Navigation target after Lesson 4 on the live site  
  https://agentfactory.panaversity.org/docs/Programming-in-the-AI-Era/specify-with-types
