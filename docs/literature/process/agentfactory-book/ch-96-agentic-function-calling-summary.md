# Chapter 96: Agentic Function Calling - Section-by-Section Summary

## Method
This summary follows an objective compression approach: it identifies the main claim of each published page, keeps the major supporting points, preserves the instructional sequence, and removes repetitive scaffolding. It restates the material in new wording and stays inside the chapter's teaching frame.

## Source path followed
1. Chapter 96 landing page: `.../agentic-function-calling`
2. Lesson 0: `.../agentic-function-calling/build-agentic-skill`
3. Lesson 1: `.../agentic-function-calling/what-is-agentic-tuning`
4. Lesson 2: `.../agentic-function-calling/tool-calling-patterns`
5. Lesson 3: `.../agentic-function-calling/structured-output-training`
6. Lesson 4: `.../agentic-function-calling/task-api-function-calling`
7. Lesson 5: `.../agentic-function-calling/lab-tool-tuning`
8. Lesson 6: `.../agentic-function-calling/multi-tool-orchestration`
9. Lesson 7: `.../agentic-function-calling/capstone-task-api-agent`

---

## Chapter overview

### Main idea
The chapter teaches how to turn a language model into a dependable agent backend that selects tools, emits valid structured arguments, and completes multi-step workflows instead of merely describing what it would do.

### What the chapter covers
The sequence begins by turning the subject into a reusable skill. It then defines agentic tuning as a specialization of fine-tuning for tool use, explains the exact response formats and schema patterns that tool-capable models must learn, shows how to train for strict JSON validity, builds a 500+ example Task API dataset, walks through a full training lab, extends the model to sequential and parallel multi-tool orchestration, and ends with a capstone that packages the result as a deployable Task API reasoning backend.

### Learning goals
By the end of the chapter, the reader should be able to define tool schemas, construct OpenAI-compatible tool-call messages, generate and validate function-calling datasets, tune for high JSON validity, test tool-selection and argument accuracy, train multi-tool chains, and integrate the resulting model with an agent framework.

### Organizing method
The chapter follows a skill-first pattern. The learner builds an `agentic-tuning` skill early, updates it after each lesson, and uses it at the capstone stage to verify that the final model, data, metrics, and integration patterns are reusable rather than one-off chapter artifacts.

---

# Lesson 0: Build Your Agentic Tuning Skill

## Main idea
The opening lesson asks the learner to build a reusable `agentic-tuning` skill before studying the mechanics of tool calling, so the chapter starts with a portable operating guide instead of scattered notes.

### Why the chapter starts with a skill
The lesson argues that function-calling formats, structured-output conventions, evaluation metrics, and SDK integration patterns change fast enough that relying on memory or general model knowledge is risky. A skill grounded in current documentation becomes the learner's working reference for the rest of the chapter.

### Workspace and learning spec
The learner clones a fresh `skills-lab` workspace, creates directories for the skill, the Task API specification, and the training data, then writes a `LEARNING-SPEC.md`. That spec defines the target system narrowly: a Task API backend that can replace an expensive frontier model for four tools while meeting thresholds for tool accuracy, JSON validity, argument correctness, SDK compatibility, and latency.

### Documentation harvest and first skill draft
The page then directs the learner to pull official function-calling and fine-tuning documentation. That research is folded into a `SKILL.md` that records tool-definition format, training-example structure, evaluation targets, the decision rule for fine-tuning versus prompt engineering, and common errors such as returning conversational text instead of `tool_calls`.

### Verification as a readiness check
The lesson closes by testing the skill on a concrete example. The learner asks an assistant to generate one training record for a low-priority task request and checks whether the output includes the system prompt, user message, null assistant content, and the expected tool call. The point is to confirm that the skill produces actionable guidance before the chapter moves on.

### Takeaway
Lesson 0 establishes the method for the entire chapter: encode the official patterns early, then refine that encoded knowledge as the lessons get more specific.

---

# Lesson 1: What is Agentic Tuning?

## Main idea
This lesson defines agentic tuning as the training discipline that turns a model from a conversational assistant into an executable agent backend.

### The agent-backend problem
The page begins with the core failure mode: a standard instruction-tuned model responds helpfully in prose but does not actually invoke a tool. For agents, that behavior is useless, because the framework needs parseable tool calls, not polite descriptions of intended actions.

### Three capabilities standard SFT does not supply
The lesson breaks agentic behavior into tool selection, argument extraction, and structured output formatting. A usable backend must choose the right function, map natural language into exact parameters, and emit a tool-call payload that the framework can parse without repair.

### Why standard fine-tuning misses the target
The chapter then explains that ordinary supervised fine-tuning teaches fluent assistant responses, not executable calls. Standard datasets omit tool schemas, reward conversational completion, and do not place training emphasis on the exact JSON-bearing tokens that agent pipelines depend on.

### What agentic data changes
Agentic data fixes that by inserting full tool definitions into the system prompt, using assistant turns with `content: null` and `tool_calls`, and treating correct tool name plus correct arguments as the actual target behavior. The lesson frames that as a change in task definition, not just a stricter formatting preference.

### Business case and decision rule
The page ends with the operational reason to do this work. It argues that custom agentic models make sense when the tool set is stable, call volume is high enough to justify training, privacy favors local inference, or latency targets rule out repeated remote API calls. It also states the reverse case: if tools change frequently, volume is low, or frontier-model reasoning still matters more than reliable tool execution, API function calling remains the better choice.

### Takeaway
Lesson 1 reframes the problem clearly: the goal is not a nicer assistant but a model that emits correct actions in machine-usable form.

---

# Lesson 2: Tool-Calling Patterns

## Main idea
This lesson teaches the exact schema and message patterns that a fine-tuned model must reproduce if it is going to participate reliably in agent workflows.

### Tool schemas as training contracts
The lesson starts with full JSON tool definitions for the Task API. It emphasizes that names, descriptions, argument properties, required fields, and enums are not documentation ornaments. They are part of the training contract that tells the model how to choose the tool and how to populate its arguments.

### The required response format
The page then defines the assistant-side payload: `content` must be null, `tool_calls` must be an array, `function.name` must match a declared tool exactly, and `function.arguments` must be a JSON string rather than a nested object. The lesson treats this distinction as a common break point for otherwise plausible outputs.

### Conversation flow beyond the single response
The chapter expands the lesson from one tool-call packet to the full message lifecycle: system message with tools, user request, assistant tool call, tool result message linked by `tool_call_id`, and optional assistant synthesis after execution. That broader flow matters because realistic training data has to teach the model how tools fit into a whole conversation, not just how one assistant turn looks.

### Tool-choice control and parallel calls
The page also explains `tool_choice` modes such as automatic choice, required tool use, no tool use, and forced selection of a specific function. It then adds parallel calls for independent operations, showing that the format supports multiple tool calls in one assistant turn when the request genuinely decomposes into separate actions.

### Schema design as accuracy work
The lesson closes with design guidance: descriptions should distinguish when to use a tool, enums should constrain outputs to exact allowed values, and `required` should include only fields that are truly mandatory. Better schemas produce cleaner training targets and fewer ambiguous outputs.

### Takeaway
Lesson 2 turns tool calling into something concrete: stable schemas, exact assistant payloads, correct message sequencing, and training examples built from those rules.

---

# Lesson 3: Structured Output Training

## Main idea
This lesson explains that reliable tool use depends on reliable structure, and that valid JSON must be treated as a core training outcome rather than an incidental formatting detail.

### Why JSON validity is a production requirement
The page starts by cataloging the usual structured-output failures: missing quotes, wrong quote style, trailing commas, broken escaping, truncated objects, and mixed text plus JSON. The lesson's point is direct: even a small failure rate becomes unacceptable once an agent serves real volume.

### Data-format discipline
The chapter then shows what the training data must get right: escaped strings inside `arguments`, exact type matching, and explicit null content for assistant tool-call turns. These are presented as non-negotiable formatting rules because the model learns whatever patterns the dataset repeats.

### AI-assisted generation with human-level validation gates
The lesson proposes a workflow in which AI helps generate diverse user messages and corresponding tool calls, but every output passes through a validation loop. The repeated sequence is template definition, generation, schema validation, error correction, and expansion until the dataset reaches sufficient size and variety.

### Validation scripts and metrics
A substantial part of the lesson is operational: write validators that check parseability, known tool names, required fields, enum values, and schema compliance. The reader is shown how to measure validity, detect bad lines before training, and rebalance tool distribution if one tool dominates the corpus.

### Training and inference choices that affect structure
The page also explains how low-temperature inference reduces malformed outputs, how correct chat formatting lets fine-tuning frameworks place loss on the right output regions, and how some frameworks encode tool calls with special markers under the hood. The instructional point is that structured reliability depends on both data and runtime settings.

### Dataset targets
The lesson ends with a concrete target shape: 500+ examples spread across create, update, complete, and list operations, plus multi-turn cases and edge cases. It also instructs the learner to add these distribution and validation rules back into the reusable skill.

### Takeaway
Lesson 3 treats structured output as a narrow engineering problem: exact data formatting, automated validation, balanced coverage, and deterministic inference settings.

---

# Lesson 4: Task API Function Calling

## Main idea
This lesson applies the earlier abstractions to one concrete domain by building a validated Task API training dataset large enough to support fine-tuning.

### Finalizing the tool surface
The page begins by defining complete schemas for `create_task`, `update_task`, `complete_task`, and `list_tasks`. These definitions include the intended use of each tool, optional versus required fields, enum-constrained priorities, and filter fields for list operations.

### System prompt template
The lesson then standardizes the system prompt that will appear in every training example. That prompt embeds the tool definitions and encodes practical behavior rules such as resolving natural-language dates into ISO form, inferring priority from wording, asking for clarification when a task identifier is missing, and switching back to natural language when no tool is needed.

### Scenario categories instead of random examples
The chapter organizes the dataset into deliberate categories: simple single-tool requests, phrasing variations, multi-turn conversations, and edge cases. That structure is meant to prevent a lopsided corpus in which the model sees mostly obvious create-task commands and too few updates, follow-ups, or tricky inputs.

### Systematic variation and generation
The page then shows how to generate examples programmatically by combining templates, task phrases, and argument mappings. The objective is not raw quantity alone. It is controlled coverage of the wording and state patterns that the production model will actually face.

### Validation and distribution check
After generation, the dataset is saved as JSONL and validated. The published walkthrough lands at 523 examples with a zero-error validation pass and an explicit tool distribution report, then feeds those results back into the `agentic-tuning` skill as concrete dataset targets.

### Safety and clarification cases
The lesson closes with a warning that training data shapes the model's behavioral defaults. If the examples always comply, the model learns to guess and act even when a request is ambiguous. The reader is told to include cases where the model asks which task the user means instead of fabricating a target.

### Takeaway
Lesson 4 turns generic function-calling theory into a domain dataset: full schemas, one reusable system prompt, scenario-driven variation, and a validated corpus ready for training.

---

# Lesson 5: Lab - Tool Tuning

## Main idea
This lesson converts the dataset into a trained model through a hands-on tuning workflow, while comparing a hosted OpenAI path with a local Unsloth path.

### Environment setup and path selection
The lab starts by showing two routes. Option A uses OpenAI's fine-tuning API for a fast hosted workflow. Option B uses Unsloth, LoRA adapters, and local GPU training for full control and lower long-run dependency on external APIs.

### Data preparation and splits
The learner first shuffles and splits the dataset into training and validation partitions. The OpenAI path uploads those files directly, while the local path reformats assistant tool calls into the representation expected by the local training stack.

### Hyperparameters for agentic work
The page then isolates the parameters that matter most for tool-calling models: lower learning rates than ordinary instruction tuning, small batches, several epochs, and warmup. The lesson's logic is that structured-output precision is easier to damage with aggressive training than plain conversational fluency is.

### Running and reading training
Both routes culminate in a real training job. The local example uses a quantized base model with LoRA adapters and tracks loss and validation loss over time. The learner is shown how to interpret useful patterns such as smooth decline, early plateau, divergence, and overfitting.

### Quick validation before formal evaluation
Before the next lesson's more formal metrics, the page asks for a fast smoke test: prompt the fine-tuned model with create, list, and complete requests and inspect whether the correct tools and arguments appear. This is a practical check that the model learned the basic format before spending time on broader evaluation.

### Troubleshooting and safety notes
The final sections diagnose common failures such as loss not decreasing, natural language leaking into tool-call turns, or malformed JSON at inference time. The lesson also notes that real user data raises privacy and memorization concerns, which is why the lab uses synthetic data.

### Takeaway
Lesson 5 gives the chapter its first trained artifact and shows that agentic tuning is mostly disciplined experimentation: data splits, controlled hyperparameters, close reading of training curves, and targeted debugging.

---

# Lesson 6: Multi-Tool Orchestration Training

## Main idea
This lesson extends the model from single calls to workflows by teaching it to chain dependent tools, launch independent calls in parallel, and synthesize the results back into one coherent response.

### Why single-tool accuracy is not enough
The lesson starts with the gap between doing one action correctly and completing a workflow. A model can be good at `create_task` in isolation and still fail when it needs to continue automatically, carry an ID forward, or decide that two operations should happen in parallel.

### The main orchestration patterns
The page identifies four recurring patterns: sequential chains, parallel calls, conditional flows, and loops. The point is that real workflows combine tool use with state handling and dependency reasoning, so the dataset has to expose those patterns explicitly.

### Sequential training examples
The chapter then shows how to generate chain examples in which the first tool's result becomes an argument source for the second tool. Correct orchestration is defined partly by ID consistency: the downstream call has to use the right value from the upstream result.

### Parallel and mixed examples
Independent operations are handled differently. The model must learn to issue multiple `tool_calls` in one assistant turn when no dependency blocks concurrency. The lesson then raises the difficulty further with mixed cases that require both reasoning over tool results and branching into additional calls.

### Distribution and evaluation for orchestration
The page gives recommended proportions for single-call, sequential, parallel, three-step, and mixed-pattern examples. It also defines orchestration-specific metrics such as chain completion, dependency accuracy, parallel recognition, over-serialization, and final synthesis quality.

### Generator-driven scale
The closing implementation examples use a generator to produce sequential and parallel data in volume. This keeps the orchestration corpus systematic rather than hand-authored and makes it easier to expand later when evaluation reveals a weak pattern.

### Takeaway
Lesson 6 broadens the target from correct single actions to correct workflow behavior, with dependency handling and parallelization treated as trainable capabilities.

---

# Lesson 7: Capstone - Build Task API Agentic Model

## Main idea
The capstone composes the chapter into one production-style deliverable: a fine-tuned Task API reasoning backend that meets explicit thresholds, plugs into an agent framework, and can be packaged as a reusable product component.

### Start from a spec, not from improvisation
The page opens with a formal specification: tool selection above 95 percent, argument extraction above 90 percent, JSON validity above 99 percent, multi-tool completion above 85 percent, and local latency below 500 ms. It also constrains the problem to a compact base model, 500+ examples, OpenAI-compatible `tool_calls`, and no external inference dependencies.

### Training stack and data preparation
The lesson then assembles the training run. It loads a small instruct model, applies LoRA adapters, formats the dataset into chat form, and splits the corpus into training and validation sets. The published walkthrough lands on 540 training examples and 60 validation examples after the split.

### Evaluation against the spec
A major phase of the capstone is explicit measurement. The published evaluation report passes the stated targets for tool selection, argument extraction, JSON validity, and multi-tool completion, and uses those results to decide whether the model is ready to move forward.

### Agent-framework integration
After evaluation, the capstone exposes the model behind an OpenAI-compatible local inference server and wires it into an agent built with tool definitions that mirror the Task API. End-to-end tests then verify that ordinary user requests cause the agent to call the expected tools and produce sensible final responses.

### Production checklist and packaging
The page closes with a production-readiness checklist that covers dataset size, balanced single versus multi-tool coverage, stable training behavior, passing metrics, SDK compatibility, and acceptable latency. It then shows two packaging directions: serving the model as an API or bundling it as a reusable skill package with declared capabilities and measured scores.

### Role of the finished skill
The capstone ends by reflecting on the completed `agentic-tuning` skill. At that point the skill contains data-generation patterns, tuned hyperparameters, evaluation criteria, and framework-integration patterns that can be reused for later tool-calling models.

### Takeaway
Lesson 7 turns the chapter's pieces into one deployable system and makes the chapter's broader claim concrete: agentic function calling becomes practical when data, structure, evaluation, and framework compatibility are treated as one engineering problem.
