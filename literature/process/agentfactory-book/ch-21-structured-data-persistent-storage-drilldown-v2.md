# Chapter 21 Drilldown: Structured Data & Persistent Storage

## Source and scope

This document condenses the full published chapter sequence for **Structured Data & Persistent Storage** from Agent Factory. It follows the chapter overview, eight lesson pages, the practice page, and the quiz page.

**Current site note:** the overview page still renders this chapter as **Chapter 10** in its page title and heading, while the lesson pages and sidebar render it as **Chapter 21**. This drilldown treats it as Chapter 21 and notes the mismatch where relevant.

## Main idea

This chapter explains when a file-and-script workflow stops being the right tool and how to move into relational storage without losing the earlier escalation logic. The chapter’s claim is simple: once the problem becomes persistent, relational, multi-user, and failure-sensitive, SQLAlchemy plus PostgreSQL should replace handwritten loop logic, and high-stakes outputs should add an independent verification gate.

## Chapter throughline

The running example is a budget tracker. In the previous chapter, a Python script could answer one tax or spending question from CSV files. In this chapter, the same problem grows into multi-user history, category relationships, ad hoc reporting, safe edits, safe deletes, cloud persistence, and release checks. The chapter’s method is to tighten the system one layer at a time:

1. prove persistence across program restarts
2. define schema contracts in model code
3. verify CRUD through read paths
4. query linked data through joins
5. protect multi-step writes with transactions
6. move the database to Neon without changing the core model layer
7. add independent verification only where the cost of being wrong is high
8. collect release evidence instead of trusting a demo

## What changes from earlier chapters

The overview frames the escalation path as Bash -> Python -> SQL, with hybrid verification added only when output risk justifies the extra cost. Bash stays useful for orchestration and diagnostics. Python stays useful for deterministic parsing and computation. SQL becomes the primary tool once the job depends on persistence, relationships, shared state, and query flexibility. The chapter’s promise is not faster syntax. It is safer truth management.

## Lesson-by-lesson drilldown

### Overview: chapter contract

The overview identifies the breakpoints in the Chapter 9 approach: every new structured question forces more loops, relationships are enforced only by convention, and concurrent writes become a corruption risk. The chapter then defines the target system: a Neon-backed budget tracker with typed relational models for `User`, `Category`, and `Expense`, safe CRUD, relationship-aware queries, explicit transaction and rollback discipline, secure cloud connection setup, and selective hybrid verification. It also states the no-regression rules: do not weaken rollback discipline, foreign-key enforcement, secret handling, or the mismatch policy for high-stakes verification.

### Lesson 0: When Bash and Python Hit the Wall

This lesson names the exact breakpoint. A script that works for one report stops scaling once the data needs monthly, per-user, per-category analysis over several years, plus delete safety and relationship integrity. The lesson contrasts a CSV world of loosely coordinated files with a relational world of linked tables. Its operational test is decision-oriented: if every new question requires a new loop, the data model is already failing. The Braintrust/Vercel comparison is used to reinforce the point that structured querying is not only faster in SQL but more accurate for this problem class.

The key takeaway is not “always use a database.” It is “escalate when the cost of continuing with scripts exceeds the cost of formal structure.”

### Lesson 1: Build Your Database Skill

The first proof is deliberately small. The lesson asks for a persistence proof using two separate scripts: one writes a row, another reads it back in a different process. If the second script sees the row, you have shown durable state across process boundaries. That matters because a database is not just storage inside one running program; it is shared memory that outlives the program.

The lesson is building one habit: separate “I wrote something” from “the data now exists independently of this process.” That proof becomes the foundation for every later lesson.

### Lesson 2: Models as Code

This lesson shifts from persistence to contracts. The user describes the data model in plain English and the agent turns that into SQLAlchemy models. The emphasis is on meaning and rules, not ORM trivia. The chapter uses the budget tracker to show the required entities and constraints: users have unique emails, categories have names and optional colors, and expenses must reference real users and categories. The `amount` field has to use exact decimal storage rather than floating-point arithmetic because financial data cannot tolerate rounding drift.

The lesson’s core move is translation: describe business meaning precisely enough that the agent can generate the schema correctly, then verify that every generated field and constraint maps back to the original description. The hidden lesson is that most schema bugs begin as underspecified requirements.

### Lesson 3: Creating & Reading Data

After the schema exists, the chapter turns to write discipline. This lesson explains the session lifecycle: open a session, stage changes, preview or flush when needed, commit to make the write durable, and verify by reading the data back. A write without a verified read path is treated as incomplete evidence.

The chapter’s preferred verification pattern is practical: insert one known row, read it back through a separate query, inspect the field values, then force one failing insert and confirm that the failed write left no leftover data. The point is to trust the read path rather than trust the absence of an error message.

### Lesson 4: Relationships & Joins

This lesson moves from isolated rows to linked truth. It explains how users, categories, and expenses should be queried together, how to ask for filtered linked data, and how to reason about joins as the way to answer questions such as “show all Food expenses over $50 with the user’s name.” It also introduces the N+1 problem as a practical performance signal: code that makes one query for the parent set and then one query per parent will look fine with small data and degrade badly at scale.

The lesson’s verification pattern is explicit. Measure query counts before and after the fix. If 100 users trigger 101 queries before the fix and 2 after the fix, the optimization worked. It also reframes cascade behavior as a business rule, not a default technical choice.

### Lesson 5: Transactions & Atomicity

This lesson defines the business meaning of a transaction boundary. When a multi-step write fails halfway through, correctness requires all steps to be undone. The chapter uses transfer-style examples to show why partial writes are unacceptable. If one part fails, rollback must restore the pre-transaction state completely.

The verification pattern is stronger than “I caught an exception.” The lesson requires a rollback drill: force a failure after the first operation, query the database afterward, and prove that the row count or balances remain unchanged. The operational claim here is that transaction safety has to be demonstrated directly against database state.

### Lesson 6: Connecting to Neon

This lesson moves the system from local durability to cloud durability. The chapter stresses that the models and CRUD layer should not need a redesign; only the connection target changes. The operational details matter: keep `DATABASE_URL` in `.env`, keep `.env` out of source control, use pooled connections, and enable liveness checks such as `pool_pre_ping=True` so stale pooled connections do not silently fail.

The health check sequence is concrete: run `SELECT 1`, create the schema, write one row, read it back, restart the terminal, and read it again. That last restart-and-reread step proves the data lives in the cloud instead of inside process-local state.

### Lesson 7: Hybrid Patterns - When Tools Work Together

This lesson introduces selective independent verification. The chapter is careful here: SQL alone is the default for everyday structured queries. Hybrid verification is reserved for financial, audit, compliance, or similarly high-stakes outputs. The reason is not distrust of SQL as such. It is the need for a second computation path with different failure modes.

The chapter’s standard example is to compute a result through SQL and then compute the same scoped result through an independent path such as CSV export plus `awk`. If the results match within policy, release can proceed. If they differ, release is blocked until the mismatch is resolved. The lesson is explicit that re-running the same SQL query does not count as independent verification.

### Lesson 8: Capstone - Budget Tracker Complete App

The capstone integrates the whole chapter into a release discipline. The run sequence is schema -> CRUD -> rollback drill -> Neon health check -> summary -> verification gate -> release decision. The lesson distinguishes a working demo from a releasable system. A demo proves the happy path. A release requires evidence that failure modes were exercised and that the verification gate passed.

The output target is an evidence bundle. It should show what was tested, what passed, what failed safely, and what the final release decision is. The chapter’s strongest distinction appears here: “ready for demo” and “ready for release” are different states and should be named differently.

## Practice page

The practice page turns the chapter into six modules:

- Module 1: data modeling
- Module 2: CRUD operations
- Module 3: relationships
- Module 4: transactions
- Module 5: cloud deployment
- Module 6: hybrid verification

Each module includes realistic starter files, instructions, broken code or incomplete code, and a test-driven task. The examples show the intended shape of the work. Early exercises include a library catalog schema build and a broken pet store model debug task. Later exercises include an expense-audit hybrid verification build and a “wrong tool” analysis exercise that asks the learner to choose among Bash, Python, SQL, or a hybrid path. The practice page keeps the chapter’s escalation logic intact by making tool choice part of the exercise rather than an afterthought.

## Quiz page

The quiz page frames itself as an operational readiness check. It contains twenty-two questions and scores them as follows:

- 20-22: strong operational readiness for the chapter scope
- 16-19: good foundation, revisit weak outcome areas
- 15 or below: repeat core exercises before moving forward

The quiz measures six things: modeling and constraints, CRUD and session safety, relationship and query reasoning, transaction integrity, Neon operations and security, and escalation judgment across file processing, computation, and structured data.

## What this chapter is really teaching

On the surface, this is a chapter about SQLAlchemy and PostgreSQL. Underneath, it is a chapter about changing the unit of correctness.

Earlier chapters can treat correctness as “the script returned the right answer for this task.” Chapter 21 treats correctness as a broader chain:

- the schema rejects invalid states
- linked data stays linked
- writes either complete or disappear
- persistence survives process and machine boundaries
- critical outputs are checked by an independent path
- release claims are backed by repeatable evidence

That is the real upgrade. The learner is moving from script success to system integrity.

## Condensed chapter summary

In **Structured Data & Persistent Storage**, Agent Factory argues that file-and-loop workflows stop being reliable once the work requires persistence, shared history, relationships, and safe multi-step updates. The chapter teaches the learner to prove persistence across runs, define schema contracts in SQLAlchemy from plain-English requirements, verify CRUD through read paths, query linked data efficiently, protect writes with explicit rollback discipline, deploy the same model layer to Neon, and add hybrid verification only for high-stakes outputs. It ends by treating release readiness as an evidence problem rather than a demo problem.

## Source pages

- Overview: [Structured Data & Persistent Storage](https://agentfactory.panaversity.org/docs/Agent-Workflow-Primitives/structured-data-persistent-storage)
- Lesson 0: [When Bash and Python Hit the Wall](https://agentfactory.panaversity.org/docs/Agent-Workflow-Primitives/structured-data-persistent-storage/from-csv-to-databases)
- Lesson 1: [Build Your Database Skill](https://agentfactory.panaversity.org/docs/Agent-Workflow-Primitives/structured-data-persistent-storage/build-your-database-skill)
- Lesson 2: [Models as Code](https://agentfactory.panaversity.org/docs/Agent-Workflow-Primitives/structured-data-persistent-storage/models-as-code)
- Lesson 3: [Creating & Reading Data](https://agentfactory.panaversity.org/docs/Agent-Workflow-Primitives/structured-data-persistent-storage/creating-reading-data)
- Lesson 4: [Relationships & Joins](https://agentfactory.panaversity.org/docs/Agent-Workflow-Primitives/structured-data-persistent-storage/relationships-joins)
- Lesson 5: [Transactions & Atomicity](https://agentfactory.panaversity.org/docs/Agent-Workflow-Primitives/structured-data-persistent-storage/transactions-atomicity)
- Lesson 6: [Connecting to Neon](https://agentfactory.panaversity.org/docs/Agent-Workflow-Primitives/structured-data-persistent-storage/connecting-to-neon)
- Lesson 7: [Hybrid Patterns - When Tools Work Together](https://agentfactory.panaversity.org/docs/Agent-Workflow-Primitives/structured-data-persistent-storage/hybrid-patterns)
- Lesson 8: [Capstone - Budget Tracker Complete App](https://agentfactory.panaversity.org/docs/Agent-Workflow-Primitives/structured-data-persistent-storage/capstone-budget-tracker)
- Practice: [Structured Data Exercises](https://agentfactory.panaversity.org/docs/Agent-Workflow-Primitives/structured-data-persistent-storage/structured-data-exercises)
- Quiz: [Chapter 21 Quiz](https://agentfactory.panaversity.org/docs/Agent-Workflow-Primitives/structured-data-persistent-storage/chapter-quiz)
