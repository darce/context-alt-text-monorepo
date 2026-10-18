# Chapter 45 Drilldown: Reading Python

Original chapter entry: https://agentfactory.panaversity.org/docs/Programming-in-the-AI-Era/the-workbench/reading-python

## What this chapter is doing

Chapter 45 teaches the first verification skill for AI-assisted Python work: reading code before writing it. The chapter argues that the bottleneck has shifted. AI can generate code quickly, but the student still has to decide whether that code is correct. The method for doing that is PRIMM, narrowed in this chapter to the first three stages: predict, run, and investigate.

The chapter builds the skill in four moves:

1. predict the output of short typed Python blocks;
2. use trace tables once variables start changing;
3. review a larger SmartNotes example and locate both type bugs and logic bugs;
4. read pytest-style tests by recognizing `def` and `assert`.

The chapter is also the last purely reading-oriented stop before Chapter 46. By the end, the student is expected to read code, read tests, and verify simple AI-generated Python with a mix of human judgment and tool support.

## Chapter structure on the live site

The live Chapter 45 sequence currently exposes:

- Overview page
- Lesson 1: The PRIMM Method -- Predict, Run, Investigate
- Lesson 2: Trace Tables -- When Your Brain Takes Shortcuts
- Lesson 3: Your First Code Review -- Catching a Bug
- Lesson 4: Reading a Test -- Two New Words

After Lesson 4, the bottom `Next` navigation moves directly to **Chapter 46: Your First TDG Cycle**. The live chapter does not currently expose a separate Chapter 45 quiz page.

## Chapter thesis in one paragraph

The chapter's claim is that the beginner's first real job in AI-era programming is verification, not typing. PRIMM gives the student a repeatable way to read code actively rather than stare at it. Trace tables handle reassignment and state changes that exceed working memory. Code review adds a second layer by distinguishing type errors, which tools such as Pyright can catch, from logic errors, which still need human sense-making. The final lesson extends the same method to tests, preparing the student to write specifications in Chapter 46.

## Detailed drilldown

### Overview page: Chapter 45

Source: https://agentfactory.panaversity.org/docs/Programming-in-the-AI-Era/the-workbench/reading-python

The overview frames the chapter as the point where the workbench from Chapter 44 meets actual Python code. The student already has `uv`, `pyright`, `ruff`, `pytest`, and Git installed. Now the task is to read the language those tools process.

What the overview establishes:

- the chapter uses PRIMM as the reading method;
- the scope stays deliberately small: variables with type annotations, the four primitive types, arithmetic, string operations, booleans, and `print()`;
- Lesson 4 introduces only two extra words, `def` and `assert`, so the student can read tests before writing them;
- each lesson includes PRIMM-AI+ practice, so AI generation is paired with a forced prediction step.

The overview also gives the chapter's main educational claim: verification depends on reading. If the student cannot read the code, then type checking, testing, and later spec-first workflows have no stable foundation.

### Lesson 1: The PRIMM Method -- Predict, Run, Investigate

Source: https://agentfactory.panaversity.org/docs/Programming-in-the-AI-Era/the-workbench/reading-python/the-primm-method

This lesson defines the method that the rest of the chapter uses.

#### Main point

PRIMM is presented as a code-reading discipline that becomes more important when AI removes typing as the main bottleneck. The lesson states that writing used to be the slow part of programming, but in the AI era the limiting factor is deciding whether generated code is correct.

#### What the lesson teaches

The page explains all five PRIMM stages, but Chapter 45 uses only the first three:

- **Predict**: commit to an expected output before running the code.
- **Run**: execute the code and compare the result to the prediction.
- **Investigate**: explain why the prediction matched or failed.

The page treats prediction as the critical move. Without prediction, the student sees an answer and mistakes recognition for understanding.

#### The actual Python content

The examples stay close to the minimum needed for early reading practice:

- string concatenation;
- floor division with `//`;
- f-strings plus arithmetic;
- boolean logic with comparisons and `and`.

The student is told to ask Claude Code for tiny snippets, paste them into `main.py`, run `uv run python main.py`, and compare actual output with the prior prediction.

#### Load-bearing ideas

- **Reading is active work**. The page distinguishes reading from passive scanning.
- **Prediction exposes false confidence**. Wrong predictions are treated as diagnostic, not as failure.
- **The chapter reads Python before writing it**. That ordering is deliberate.
- **Verification Ladder, Rung 1** starts here: predict first, then check.

#### Why this page matters

This lesson gives the chapter its governing habit. Every later page depends on the student accepting that code comprehension is built through prediction, not through passive exposure.

### Lesson 2: Trace Tables -- When Your Brain Takes Shortcuts

Source: https://agentfactory.panaversity.org/docs/Programming-in-the-AI-Era/the-workbench/reading-python/trace-tables

Lesson 2 addresses the first point where raw mental simulation breaks down: reassignment.

#### Main point

Once variables change across multiple lines, working memory starts substituting stale values. The trace table is introduced as a mechanical fix, not a stylistic preference.

#### What the lesson teaches

A trace table records the state of each variable after each executed line. The rule is simple: when calculating a new row, use the values from the row above, not the variable's original value.

The lesson's opening example shows the common beginner failure:

```python
count: int = 10
bonus: int = 5
count = count + bonus
bonus = bonus * 2
total: int = count + bonus
print(total)
```

A quick mental skim often produces the wrong answer. The trace table makes the correct sequence visible and lands on `25`.

#### What the lesson wants the student to notice

- reassignment replaces the old value;
- strings built from earlier values are snapshots, not live links;
- once a variable appears on the left side of `=` again, the student should stop tracing from memory and draw the table.

The page also includes an AI-generated trace challenge so the learner cannot memorize the book's answers and has to apply the method on unfamiliar input.

#### Load-bearing ideas

- **Stale-value errors are predictable**. They come from memory limits, not from low ability.
- **Trace artifacts externalize state**. The grid turns hidden intermediate values into something the student can inspect.
- **Use the tool when code exceeds head-trace range**. The lesson gives a concrete threshold: more than three lines plus reassignment.

#### Why this page matters

This lesson upgrades PRIMM from a short-snippet method into something that can survive longer code. Without the trace table, the next lesson's code review exercise would collapse into guesswork.

### Lesson 3: Your First Code Review -- Catching a Bug

Source: https://agentfactory.panaversity.org/docs/Programming-in-the-AI-Era/the-workbench/reading-python/your-first-code-review

Lesson 3 shifts from reading code to reading code skeptically.

#### Main point

Code review changes the question from "what does this do" to "what does this do wrong." The lesson's SmartNotes example uses that shift to teach the difference between type bugs and logic bugs.

#### The first bug: type mismatch

The main example is a note statistics calculator in which `bonus_points` is written as a string:

```python
bonus_points: str = "10"
final_score: int = current_score + bonus_points
```

The trace table exposes the mismatch before execution. Then the lesson runs both tools:

- `uv run pyright main.py` flags the operator mismatch statically;
- `uv run python main.py` crashes at runtime with a `TypeError`.

The fix is mechanical: change `bonus_points` to `int = 10`.

#### The second bug: logic error

The page then gives a smaller example where the division order is reversed in an average calculation. Pyright reports no issue because the types are valid, yet the answer is obviously wrong for the domain.

That is the lesson's most important distinction:

- **type bugs** are structural mismatches that automated tools can often catch;
- **logic bugs** can pass automated checks and still be wrong.

#### What the lesson teaches beyond the examples

- PRIMM plus trace tables form the human side of code review.
- Pyright, Ruff, and pytest handle mechanical verification.
- Neither side is enough on its own.

The exercises keep that split visible by asking the student to classify each bug as a type bug or a logic bug and then state the fix.

#### Load-bearing ideas

- **Automated checks are necessary but incomplete**.
- **Human review is about intent, not just syntax**.
- **The reviewer's mindset is adversarial in the healthy sense**: assume there is a problem and locate it.
- **Verification Ladder, Rung 2** appears here through explicit use of type information.

#### Why this page matters

This is the chapter's first full professional-style lesson. It does not just teach syntax recognition. It teaches where tools stop and where human judgment starts.

### Lesson 4: Reading a Test -- Two New Words

Source: https://agentfactory.panaversity.org/docs/Programming-in-the-AI-Era/the-workbench/reading-python/reading-a-test

The last lesson prepares the student for writing tests in Chapter 46.

#### Main point

The student does not yet need a full theory of functions or pytest. They only need to recognize a test function and predict whether it passes or fails.

#### The two new words

The lesson reduces the new syntax to two items:

- **`def`** labels a test block.
- **`assert`** states what must be true.

Everything between those words uses earlier chapter material: strings, numbers, booleans, reassignment, and comparisons.

#### What the lesson teaches

The student saves a test in `test_practice.py` and runs:

```bash
uv run pytest test_practice.py -v
```

Then the student reads several tiny tests and predicts pass or fail before running them. The page's samples cover:

- string concatenation;
- floor division;
- f-string formatting;
- boolean logic.

The point is that test reading is just code reading with one extra wrapper.

#### Why the page matters for the next chapter

Lesson 4 explicitly connects `assert` to specification. The test is where "correct" gets written down. That is the bridge into TDG in Chapter 46, where the learner will write a test first and let AI generate the implementation.

The page also adds a small but important conceptual distinction in the PRIMM-AI+ section: a bad `assert` can be a **specification error**, not just a logic error. That matters because in a test-first workflow the test itself is the contract.

#### The chapter-end rubric

Unlike the earlier lessons, this page closes with a self-assessment rubric across five dimensions:

- prediction accuracy;
- trace quality;
- explanation quality;
- bug-finding quality;
- test-reading quality.

That rubric makes the chapter's skill model explicit. The goal is not raw exposure to Python syntax. The goal is calibrated reading skill.

## Cross-chapter reading

Chapter 45 is doing foundational work for three later workflows.

First, it grounds Chapter 46. By the end of Lesson 4, the student can read a test and understand what it asks for, which is the minimum needed for test-first generation.

Second, it gives concrete meaning to the PRIMM-AI+ language introduced earlier in the book. In this chapter, the framework stops being abstract and becomes a step-by-step way to verify real Python.

Third, it gives the student a model of verification that keeps showing up later:

- predict first;
- use tools, but do not confuse tool output with full understanding;
- inspect the logic, not just the types;
- treat the test as the specification boundary.

## The chapter's real contribution

This chapter is not a general Python primer. It is a controlled transition from tool setup to trustworthy AI-assisted programming. The student learns only a narrow subset of Python, but that is enough to build the habits that matter later: active reading, trace-based state tracking, type-aware review, and test interpretation.

That narrowness is one of the chapter's strengths. It keeps the student's attention on verification rather than on syntax volume.

## Source map

- Overview: https://agentfactory.panaversity.org/docs/Programming-in-the-AI-Era/the-workbench/reading-python
- Lesson 1: https://agentfactory.panaversity.org/docs/Programming-in-the-AI-Era/the-workbench/reading-python/the-primm-method
- Lesson 2: https://agentfactory.panaversity.org/docs/Programming-in-the-AI-Era/the-workbench/reading-python/trace-tables
- Lesson 3: https://agentfactory.panaversity.org/docs/Programming-in-the-AI-Era/the-workbench/reading-python/your-first-code-review
- Lesson 4: https://agentfactory.panaversity.org/docs/Programming-in-the-AI-Era/the-workbench/reading-python/reading-a-test
