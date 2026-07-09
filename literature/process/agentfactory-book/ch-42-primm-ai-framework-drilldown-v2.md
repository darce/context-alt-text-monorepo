# Chapter 42: The PRIMM-AI+ Framework — drilldown

Source note: the live overview page still labels this material as Chapter 30, while the lesson pages and quiz label it as Chapter 42. This file preserves that mismatch rather than smoothing it over.

## Source pages

- Overview: https://agentfactory.panaversity.org/docs/Programming-in-the-AI-Era/the-workbench/the-primm-ai-framework
- Lesson 1, The PRIMM Framework: https://agentfactory.panaversity.org/docs/Programming-in-the-AI-Era/the-workbench/the-primm-ai-framework/the-primm-framework
- Lesson 2, PRIMM-AI+: AI as Your Learning Partner: https://agentfactory.panaversity.org/docs/Programming-in-the-AI-Era/the-workbench/the-primm-ai-framework/primm-ai-plus-ai-as-your-learning-partner
- Lesson 3, The PRIMM-AI+ Toolkit: https://agentfactory.panaversity.org/docs/Programming-in-the-AI-Era/the-workbench/the-primm-ai-framework/the-primm-ai-plus-toolkit
- Lesson 4, The Complete Teaching and Learning System: https://agentfactory.panaversity.org/docs/Programming-in-the-AI-Era/the-workbench/the-primm-ai-framework/the-complete-teaching-system
- Quiz: https://agentfactory.panaversity.org/docs/Programming-in-the-AI-Era/the-workbench/the-primm-ai-framework/chapter-42-quiz

## Chapter thesis

This chapter defines the learning operating system for the whole programming section of the book. Its central claim is that in an AI-heavy programming workflow, the scarce skill is no longer code production but code comprehension. PRIMM-AI+ is the method the book uses to protect and train that skill. The learner studies code before writing code, predicts behavior before running programs, verifies explanations instead of trusting them, and uses AI as a bounded partner rather than a substitute for thinking.

The chapter also positions PRIMM-AI+ as more than a study trick. It is presented as the fixed lesson architecture that later chapters will reuse. From Chapter 45 onward, the reader is expected to encounter the same rhythm repeatedly: predict, run, investigate, modify, and only then make something new.

## What the overview page adds

The overview page frames the chapter as a response to a comprehension crisis. AI can generate working code almost instantly, but that speed is useless if the learner cannot read, judge, adapt, or verify what was produced. The page gives the full five-stage loop, names the added safeguards, and makes one structural point very clearly: the method stays constant across later programming chapters, even as the syntax and difficulty change.

It also introduces the enhanced parts of the system: AI-free checkpoints, mastery gates, confidence scoring, and a verification ladder. Those additions turn PRIMM into PRIMM-AI+, a version adapted to the conditions of 2026 rather than 2017.

## Lesson 1: The PRIMM Framework

Lesson 1 explains the base method without the later AI-specific controls. PRIMM comes from computing-education research by Sue Sentance and Jane Waite, with validation across 493 students in 13 schools. The lesson grounds the method in a simple inversion: most programming courses start by asking novices to write code, while PRIMM starts by asking them to read and reason about finished code first.

The five stages are the spine of the chapter:

- Predict: read code and commit to a specific prediction before execution
- Run: execute the code and compare reality to the prediction
- Investigate: trace variables, test edge cases, and explain how the program works
- Modify: change an existing program in targeted ways
- Make: write a new program from a written specification

The lesson insists that four of the five stages are comprehension-building stages. Only the final stage asks for original construction. That ordering is the whole point. Writing is treated as the consequence of understanding, not as the route that somehow produces understanding later.

The worked example is a short greeting program. The program itself is trivial; the lesson uses it to show the mental work attached to each stage. Prediction is useful because it forces commitment. Running is useful because it exposes the gap between the learner's mental model and the actual behavior. Investigation matters because a correct prediction is still weaker than a line-by-line explanation of how the code produced that result. Modification matters because it pushes the learner to locate causal structure inside the program. Make matters because it asks the learner to build from a spec after those earlier steps have supplied the needed mental model.

The lesson's practical message is blunt: if AI writes code that you cannot explain, you are not really programming. You are copying. PRIMM exists to break that pattern.

## Lesson 2: PRIMM-AI+, AI as your learning partner

Lesson 2 keeps the five-stage sequence but inserts permissions, prohibitions, and gates around AI usage. Its main question is simple: if PRIMM was designed for classrooms with human teachers, how should it work when the learner's day-to-day partner is an AI coding assistant?

The answer is stage-specific control. Each stage has three columns underneath it, in effect: what the learner must do, what AI is allowed to do, and what AI must not do. The lesson treats these boundaries as necessary because AI's default helpfulness can destroy the exact struggle the stage is meant to create.

Two mechanisms carry most of the lesson:

### 1. AI-free checkpoints

Some parts of the cycle must happen without AI.

- Predict is always AI-free.
- Make begins AI-free because the learner must write the specification and first attempt alone.
- Investigate and Modify can involve AI, but only after the learner has produced an initial explanation or attempt.

The chapter treats these checkpoints as diagnostic, not punitive. Their purpose is to reveal whether the learner actually understands the code or merely recognizes an explanation when AI supplies one.

### 2. Mastery gates

The chapter also adds explicit gating rules between stages. The learner should not advance unless there is evidence that the prior step happened properly.

Examples from the lesson:
- Before Run, a written prediction must exist.
- Before Investigate, the learner must record how prediction and actual output compare.
- Before Modify, the learner must be able to explain how the program works, not merely describe what it prints.
- Before Make, a written specification must exist.

The most durable part of Lesson 2 is the five-rule card:

1. Never run code you have not predicted.
2. Never trust an explanation you have not tested.
3. Modify before you make.
4. Write the spec before the code.
5. Use AI as a partner, not a crutch.

Those rules restate the chapter's philosophy in operational form. The line between partner and crutch is not whether AI was involved; it is whether the interaction increased the learner's understanding.

## Lesson 3: The PRIMM-AI+ toolkit

Lesson 3 shifts from workflow control to measurement and transfer. It answers two questions the prior lesson leaves open: how does the learner know whether they are improving, and how does this training connect to real engineering work?

The lesson introduces five tools.

### Verification ladder

The verification ladder scales the same predict-then-verify habit upward from beginner exercises to production practice:

1. Prediction
2. Types
3. Tests
4. Pipeline
5. Observability

The point is not that a novice should jump straight to observability. The point is that the same discipline is present at every level. First form an expectation, then check it with a stronger mechanism. The ladder makes learning exercises continuous with professional software practice instead of treating them as unrelated school tasks.

### Confidence scoring

The learner records a 1-to-5 confidence score alongside each prediction, the actual result, and a revised explanation. The lesson argues that false confidence is the dangerous state, especially when AI is generating plausible-looking code. Being unsure and wrong is normal. Being certain and wrong is what causes silent trust in bad code.

### Error taxonomy

The toolkit introduces five bug categories:
- type errors
- logic errors
- specification errors
- data errors
- orchestration errors

This gives the learner a vocabulary for diagnosis before they ask AI to fix anything. The chapter treats naming the bug class as a way to narrow the search space and avoid cargo-cult debugging.

### Professional practice mapping

The chapter directly maps each PRIMM stage to workplace behavior:
- Predict maps to reading code and forecasting whether it is safe to trust.
- Run maps to testing.
- Investigate maps to review and debugging.
- Modify maps to iterative refinement.
- Make maps to shipping from requirements.

This is one of the chapter's strongest moves. It refuses the usual split between "learning exercises" and "real work." The same habits stay in place. Only the stakes rise.

### Chapter-end rubric

Later programming chapters will end with a short self-assessment. The chapter presents that rubric as a standing checkpoint, not as decoration. The learner is supposed to judge whether they can predict, explain, modify, specify, and verify with increasing independence.

## Lesson 4: The complete teaching and learning system

Lesson 4 zooms out. The earlier lessons defined the stages, AI boundaries, and measurement tools. This lesson explains how the whole curriculum is built from them.

Its first contribution is the insertion of four teaching methods inside the PRIMM sequence:

- worked examples, mainly in Predict and Investigate
- Parsons problems, between Investigate and Modify
- live coding, across Investigate and Modify
- peer instruction, across all stages

The lesson's point is structural. These are not extra teaching ornaments laid on top of PRIMM-AI+. They are the techniques that live inside specific parts of the sequence.

Its second contribution is the classroom-mode versus solo-mode distinction. PRIMM originally assumed teachers and classmates. The book is designed for solo learners, so the chapter explains how system safeguards replace some of the social enforcement that classrooms provide. In solo mode, the learner writes the prediction first, records confidence, and only then uses AI. The AI plays some of the role that a peer or instructor would play, but only after the learner has committed to an independent attempt.

Its third contribution is the practical architecture for later lessons. A typical programming lesson in the book will follow this pattern:

1. Predict a compact worked example without AI.
2. Run it and compare actual output to the prediction.
3. Investigate through tracing, explanation, and sometimes a Parsons problem.
4. Modify the working program.
5. Make something new from a written specification.

The chapter then scales the same logic up one level higher. Whole chapters will follow an analogous pattern: opening worked examples, investigation-heavy middle lessons, structural bridges, modification tasks, and a make-oriented capstone. This is the largest claim in Lesson 4. PRIMM-AI+ is not only the micro-structure of a lesson; it is also the macro-structure of the programming curriculum.

## What the quiz page tells you

The quiz page is brief, but it confirms the intended scope. It explicitly says the assessment covers all four lessons. That matters because it tells you what the authors think the chapter actually contains: not just the five PRIMM stages, but also the AI controls, the measurement toolkit, and the teaching-system architecture.

## The chapter's operating logic

Taken as a whole, the chapter builds a layered system.

At the base is PRIMM itself: predict, run, investigate, modify, make.

On top of that, PRIMM-AI+ adds safeguards:
- AI-free checkpoints
- mastery gates
- confidence scoring
- artifact requirements
- rules for when AI may assist

On top of that, the toolkit measures and extends the learner's judgment:
- verification ladder
- calibration through confidence scoring
- bug taxonomy
- professional-practice mapping
- end-of-chapter rubric

Finally, the teaching-system lesson explains how all of those parts recur across later lessons and chapters.

That layered structure matters because the chapter is not really teaching Python yet. It is teaching the control system the learner will use when Python instruction starts.

## What Chapter 42 is trying to prevent

The chapter is designed to block a specific failure mode: AI gives the learner working code, the learner mistakes that for learning, and confidence rises faster than understanding.

Each safeguard attacks one part of that failure:
- prediction blocks passive execution
- comparison blocks hand-wavy "I basically got it"
- investigation blocks black-box success
- modification blocks premature creation
- specification blocks vague making
- confidence scoring blocks hidden overconfidence
- mastery gates block skipping

That is why the chapter spends so much time on structure. It is not padding. It is the actual content.

## Practical takeaway

If you compress the whole chapter into one sentence, it is this: from Chapter 45 onward, every programming lesson in the book is supposed to make the learner earn code-writing through prior acts of prediction, verification, explanation, and modification, with AI allowed only where it does not erase the learning work.

## Sources

- Chapter overview: https://agentfactory.panaversity.org/docs/Programming-in-the-AI-Era/the-workbench/the-primm-ai-framework
- The PRIMM Framework: https://agentfactory.panaversity.org/docs/Programming-in-the-AI-Era/the-workbench/the-primm-ai-framework/the-primm-framework
- PRIMM-AI+: AI as Your Learning Partner: https://agentfactory.panaversity.org/docs/Programming-in-the-AI-Era/the-workbench/the-primm-ai-framework/primm-ai-plus-ai-as-your-learning-partner
- The PRIMM-AI+ Toolkit: https://agentfactory.panaversity.org/docs/Programming-in-the-AI-Era/the-workbench/the-primm-ai-framework/the-primm-ai-plus-toolkit
- The Complete Teaching and Learning System: https://agentfactory.panaversity.org/docs/Programming-in-the-AI-Era/the-workbench/the-primm-ai-framework/the-complete-teaching-system
- Chapter quiz: https://agentfactory.panaversity.org/docs/Programming-in-the-AI-Era/the-workbench/the-primm-ai-framework/chapter-42-quiz
