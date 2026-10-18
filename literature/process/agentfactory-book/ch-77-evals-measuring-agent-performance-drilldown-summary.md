# Chapter 77: Evals - Measuring Agent Performance — drilldown summary

## Source record
- Source type: chapter landing page plus lesson sequence
- Title: Chapter 77: Evals - Measuring Agent Performance
- Venue: Agent Factory
- URL: https://agentfactory.panaversity.org/docs/Building-Agent-Factories/evals-agent-performance
- Scope used for this summary: chapter landing page, Lesson 0 through Lesson 10

## Chapter thesis
Chapter 77 argues that reliable agent development depends on disciplined evaluation of reasoning quality. The chapter distinguishes evals from deterministic testing, organizes evaluation design around ground truth and judge type, and teaches a repeatable loop: build a small dataset, grade outputs with explicit criteria, analyze where failures come from, fix the weakest component, protect against regression, and keep expanding the dataset from production failures.

## Chapter-level structure
The landing page frames the chapter as the counterpart to Chapter 76 on TDD. TDD checks code correctness with deterministic pass/fail outcomes. Evals measure probabilistic reasoning quality with scores. The running example is the Task API agent from Chapter 70, evaluated for routing, tool selection, output formatting, and error handling.

The chapter also follows the skill-first pattern. The reader starts by creating an `agent-evals` skill, then updates that skill as each lesson adds a new pattern. The chapter therefore teaches evaluation as a reusable operating method, not as a one-off tool tied to a single SDK.

A second structural point is portability. The landing page states that the chapter is framework-agnostic. OpenAI, Claude, Google ADK, LangChain, or any other stack can use the same evaluation logic because the core problem is not the SDK. It is how to define, measure, diagnose, and protect reasoning quality.

## Lesson-by-lesson drilldown

### Lesson 0: Build Your Evals Skill
The opening lesson has the reader create an `agent-evals` skill before studying the chapter concepts in detail. The lesson treats evaluation as a capability that should be documented, versioned, and reused. The reader creates a learning specification, defines success criteria, and starts a skill structure grounded in official documentation rather than memory.

The lesson's main claim is practical: evaluation discipline is easier to keep when it is encoded as a skill. Instead of relying on good intentions during a deadline, the reader builds a repeatable artifact that can be applied to later agent projects.

### Lesson 1: Evals Are Exams for Reasoning
This lesson draws the central distinction of the chapter. Traditional tests answer questions such as whether an endpoint returns valid JSON, whether authentication works, or whether a function handles null values. Evals answer a different class of questions: whether the agent understood the user's intent, chose the right action, responded helpfully, or reasoned well.

The lesson's decision rule is simple. If there is exactly one correct answer and code can verify it, use TDD. If acceptable outputs vary and require judgment, use evals. The chapter presents eval-driven development as a loop of building, examining outputs, scoring quality, and using the results to guide the next change.

### Lesson 2: The Two Evaluation Axes
This lesson organizes eval design around two questions: whether ground truth exists and whether code can verify success. Those questions create four quadrants.

Quadrants 1 and 2 use ground truth. Quadrant 1 covers objective checks that code can verify directly. Quadrant 2 covers cases with references where judgment is still required. Quadrants 3 and 4 operate without ground truth. Quadrant 3 uses explicit criteria that code can still check, while Quadrant 4 requires an LLM judge because success depends on semantic judgment.

The lesson's practical value is cost and signal selection. The reader is taught to classify an eval before building it, because the quadrant determines what kind of grader is possible, how expensive it will be, and how stable the measurement will be.

### Lesson 3: Designing Eval Datasets
This lesson rejects the instinct to begin with a huge test corpus. The chapter recommends starting with roughly 10 to 20 thoughtful examples because the initial bottleneck is not volume. It is learning why the agent fails.

The lesson divides the starter dataset into three categories: typical cases for common work, edge cases for ambiguous or boundary conditions, and error cases for failure handling. The point is coverage of behavior classes, not numerical scale. The chapter also advises using real or realistic cases from logs when possible, because synthetic examples often miss the messy structure of production inputs.

### Lesson 4: Building Graders with Binary Criteria
This lesson argues that direct 1-to-5 ratings are too unstable for systematic evaluation. LLMs can often recognize qualities such as helpfulness or clarity, but they are poorly calibrated at mapping that judgment onto a single number. A direct rating produces a number without clear diagnostic meaning.

The replacement pattern is decomposition. Instead of asking for one overall quality score, the evaluator defines a small set of binary criteria and scores each independently. The chapter recommends a short list of yes or no checks, sums them into a total score, and uses the result both for measurement and for debugging. A score of 3 out of 5 matters because the failed criteria show what needs to change.

### Lesson 5: LLM-as-Judge Graders
This lesson covers the cases where code cannot grade success and an LLM must act as the evaluator. The chapter presents LLM judges as useful but limited. They work better when the task is decomposed into clear binary decisions than when the model is asked to generate a single vague rating on a broad scale.

The lesson therefore continues the binary-criteria discipline from Lesson 4, but uses an LLM to answer each criterion where semantic judgment is required. The comparison the chapter emphasizes is calibration and actionability: binary judgments are more stable, easier to interpret, and easier to translate into concrete fixes than raw 1-to-5 scores.

### Lesson 6: Systematic Error Analysis
This lesson moves from detection to diagnosis. Once the agent is failing, the next task is not to patch the output at random. It is to trace failures back to the component or criterion that produces them most often.

The method is deliberately simple. The chapter uses a spreadsheet-style view or equivalent trace analysis to record cases, identify which component failed, count frequency, and prioritize fixes. Priority is not based on intuition alone. The lesson recommends a frequency-times-feasibility logic, so the reader fixes the problems that are both common and tractable before chasing isolated or expensive edge failures.

### Lesson 7: Component vs End-to-End Evals
This lesson explains the relation between two eval scopes. End-to-end evals tell you whether the overall agent works well enough. They are appropriate for ship decisions and for broad monitoring. Component evals tell you where the problem is. They are appropriate once the overall score shows weakness and error analysis suggests a specific failing part.

The chapter gives a concrete five-step flow: start with end-to-end measurement, use error analysis to identify the weakest component, build a component-level eval for that part, tune it, and then return to end-to-end evals to verify that the local fix improved the whole system. This keeps debugging tied to real user outcomes instead of drifting into local optimization that does not raise overall quality.

### Lesson 8: Regression Protection
This lesson treats evals as a release gate rather than as a periodic audit. Improvements in one area can silently damage another, especially when agent behavior changes without breaking code-level correctness. The chapter's example is straightforward: routing improves, but output formatting degrades, and ordinary tests do not catch the loss.

The lesson's workflow is eval on every change. Run the full suite before and after a modification, compare overall score and per-criterion deltas, and block or warn on regressions according to thresholds tied to the agent's stakes. The chapter also warns that overall improvement can conceal local damage, so per-criterion tracking matters as much as the headline pass rate.

### Lesson 9: The Complete Quality Loop
This lesson assembles the chapter into an operating cycle. The loop begins with a quick first version, then a small eval dataset, then an initial score. After that, the chapter repeats the same pattern: run evals, analyze failures, fix the weakest area, rerun the evals, and decide whether to ship or keep iterating.

The chapter illustrates this with a staged Task API improvement path, moving from an initial weak baseline to stronger routing and then to stronger output formatting. The governing idea is leverage. The fastest route to a better agent is usually to improve the worst-performing component, not to polish the best one.

The lesson also formalizes ship decisions. The chapter does not claim every agent needs the same threshold. High-stakes systems require higher pass rates and safer failure modes than internal tools or prototypes. Ship readiness therefore depends on the pass rate, the severity of remaining failures, the trend across iterations, and the quality of the non-agent alternative.

### Lesson 10: Finalize Your Evals Skill
The final lesson asks whether the `agent-evals` skill actually transfers beyond the Task API examples used in the chapter. A skill is only validated if it works in a different domain without rereading the lesson sequence.

The chapter tests portability by having the reader apply the same dataset design, grading, and documentation patterns to another agent class, such as customer support. The point of the lesson is not new theory. It is proof that the reader learned reusable evaluation patterns rather than memorizing chapter-specific examples.

## What the chapter says the reader owns at the end
By the end of the chapter, the reader is expected to own an `agent-evals` skill that can distinguish TDD from eval work, classify evaluation problems by quadrant, design a compact starter dataset, build binary graders, use LLM judges where needed, run error analysis, connect component and end-to-end measurement, protect against regressions, and apply the whole method to a new domain.

## Closing compression
The chapter's central claim is that agent quality improves when evaluation becomes a disciplined loop rather than a vague judgment. The lesson sequence starts with skill creation, then defines what evals are for, how to classify them, how to design small but useful datasets, how to grade outputs with explicit criteria, how to diagnose failures, how to protect against regressions, and how to turn all of that into a reusable method that transfers across agent projects.
