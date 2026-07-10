# Chapter 18 Drilldown: Claude Code for Teams, CI/CD & Advanced Configuration

## Source record
- Chapter: [Chapter 18: Claude Code for Teams, CI/CD & Advanced Configuration](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/claude-code-teams-cicd)
- Course: Agent Factory
- Publisher: Panaversity
- Output type: chapter drilldown summary
- Scope covered here: overview page, eight exposed lesson pages, exercises page, and quiz page

## Main idea
In Chapter 18, Agent Factory presents Claude Code as team infrastructure rather than a personal coding assistant. The chapter argues that teams get better results when they place instructions at the right scope, load only the rules that match the current file, package recurring workflows as reusable skills, run Claude non-interactively inside CI, separate code generation from review, and treat sessions as persistent workspaces.

## Chapter thesis in one paragraph
The chapter moves from configuration to automation. It starts with instruction placement, then narrows to file-specific rule loading, then turns common checklists into commands and skills, then explains when to ask Claude to plan before touching code, then shows how to tighten ambiguous prompts through examples and tests, then shifts into CI execution, review design, and session recovery. The throughline is operational discipline. Claude Code is useful on its own, but the larger gain comes from putting it inside repeatable team workflows.

## Structure of the published chapter
1. [Overview](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/claude-code-teams-cicd)
2. [The CLAUDE.md Configuration Hierarchy](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/claude-code-teams-cicd/claude-md-configuration-hierarchy)
3. [Path-Specific Rules with Glob Patterns](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/claude-code-teams-cicd/path-specific-rules-with-glob-patterns)
4. [Custom Skills with Frontmatter](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/claude-code-teams-cicd/custom-skills-with-frontmatter)
5. [Plan Mode vs Direct Execution](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/claude-code-teams-cicd/plan-mode-vs-direct-execution)
6. [Iterative Refinement Techniques](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/claude-code-teams-cicd/iterative-refinement-techniques)
7. [Claude Code in CI/CD Pipelines](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/claude-code-teams-cicd/claude-code-in-cicd-pipelines)
8. [Multi-Pass Review Architecture](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/claude-code-teams-cicd/multi-pass-review-architecture)
9. [Session Management: Resume, Fork, and Recovery](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/claude-code-teams-cicd/session-management-resume-fork-recovery)
10. [Exercises](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/claude-code-teams-cicd/teams-cicd-exercises)
11. [Quiz](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/claude-code-teams-cicd/chapter-quiz)

## Note on chapter-page mismatch
The overview page lists a chapter segment called "Advanced Hook Types and Events" in the chapter structure, but the live page sequence and sidebar do not expose a separate lesson page for it. This drilldown covers the pages that are currently published in the visible sequence.

## Drilldown by page

### 1) Overview
Source: [Chapter overview](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/claude-code-teams-cicd)

The overview frames Claude Code as shared engineering infrastructure. It says the tool becomes more valuable when configured for teams, wired into automation, and shaped by path-aware conventions. The page sets the learning arc: hierarchy design, path scoping, skills, execution strategy, refinement, CI, review architecture, and session control. It also ties the chapter to the Claude Certified Architect: Foundations exam, especially the domains covering configuration, workflows, CI, and multi-pass review.

What the overview contributes:
- the chapter-level claim that configuration discipline matters more than ad hoc usage
- the list of concrete deliverables, including a complete hierarchy, path-scoped rule files, skills, a CI pipeline, and a review workflow
- the exam framing that tells the reader this chapter is meant to produce operational fluency, not just vocabulary

### 2) The CLAUDE.md Configuration Hierarchy
Source: [Lesson 1](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/claude-code-teams-cicd/claude-md-configuration-hierarchy)

This lesson defines the three configuration levels: user, project, and directory. The main point is scope control. Personal preferences belong in `~/.claude/CLAUDE.md`, shared repository standards belong in a project-level `CLAUDE.md`, and package-specific conventions belong in directory-level files that load only when Claude reads those directories.

Key ideas:
- more specific files override broader ones
- Claude walks up the directory tree, so ancestor instructions still matter
- user-level settings are private and should not carry team rules
- project-level files hold build commands, coding standards, and architecture notes shared through git
- directory-level files solve monorepo drift by giving frontend, backend, and infrastructure code different local conventions

The lesson then adds two composition tools:
- `@import` for pulling in existing docs such as `README.md`, coding guides, or project-specific notes
- `.claude/rules/` for splitting large instruction sets into smaller topic files

The practical message is simple: use the smallest scope that actually matches the audience. The diagnostic command is `/memory`, which lets the team verify what Claude loaded in the current session.

### 3) Path-Specific Rules with Glob Patterns
Source: [Lesson 2](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/claude-code-teams-cicd/path-specific-rules-with-glob-patterns)

Lesson 2 extends configuration beyond directory boundaries. Some rules apply across many directories, such as test conventions or config-file rules. The lesson introduces path-scoped files in `.claude/rules/` that use YAML frontmatter with a `paths` array. When Claude reads a file matching any listed pattern, the rule loads.

Core mechanics:
- `*` matches within a single filename
- `**` matches recursively across directories
- `{}` matches alternatives such as file extensions
- multiple patterns in `paths` work as OR conditions

The lesson spends time on pattern errors because bad globs create silent misconfiguration. A common mistake is using `*.ts` where `**/*.ts` is needed. Another is anchoring a path too narrowly, such as `src/**/*` when the actual need is `**/src/**/*`.

The hands-on deliverable is four cross-cutting rule files. The text explicitly uses test conventions as a flagship example, then expands the pattern to React components, Go services, Terraform, Docker, and security-oriented rules. The operational discipline here is verification: read a matching file, run `/memory`, confirm the rule loaded, then test a non-matching file and confirm it did not.

The lesson's value is token control and relevance. Instead of loading every convention for every task, the system loads only the rules that match the file under review.

### 4) Custom Skills with Frontmatter
Source: [Lesson 3](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/claude-code-teams-cicd/custom-skills-with-frontmatter)

This lesson moves from always-on instructions to on-demand workflows. The chapter first turns a code-review checklist into a slash command, then expands the idea into skills with frontmatter.

The chapter's basic distinction is:
- CLAUDE.md and rules files are always in force
- skills are invoked when a user needs a specific workflow

Three frontmatter fields carry most of the lesson:
1. `context: fork` for verbose work that should run in an isolated subagent and return a summary
2. `allowed-tools` for restricting what a skill can do, including read-only patterns or narrowly scoped Bash access
3. `argument-hint` for making expected parameters visible in autocomplete

Examples anchor each field:
- an architecture explorer uses `context: fork` because exploration can flood the main conversation
- a dependency checker or safe reviewer uses `allowed-tools` to prevent unwanted writes or shell behavior
- a fix-issue or test-generator style skill uses `argument-hint` so the caller knows what to pass

The lesson ends with a decision rule. Universal conventions go into CLAUDE.md or rules files. Triggered workflows go into skills. If the workflow produces long output, fork it. If the workflow should be incapable of editing, restrict its toolset.

### 5) Plan Mode vs Direct Execution
Source: [Lesson 4](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/claude-code-teams-cicd/plan-mode-vs-direct-execution)

This lesson is a task-classification guide. It argues that execution mode should follow scope and ambiguity.

Direct execution is for work that is:
- narrow in scope
- obvious in implementation
- easy to review after the fact
- limited to one file or a small number of files

The lesson uses examples such as fixing a null pointer, adding a small validation check, or renaming a variable. In those cases, the overhead of planning is unnecessary.

Plan mode is for tasks with architectural choice, broad file impact, or unclear boundaries. The microservice split example makes the case: if Claude begins editing before the team decides service ownership and interface boundaries, it can commit the wrong architecture before anyone has examined the plan.

The lesson includes a compact decision tree:
- if the task is well-scoped and the implementation is obvious, execute directly
- if the task spans many files or requires design choices, plan first
- if the scope is unclear and the current code state is unclear, explore first and then plan

This section treats planning as risk control. The point is not to slow Claude down. The point is to avoid hidden design commitments.

### 6) Iterative Refinement Techniques
Source: [Lesson 5](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/claude-code-teams-cicd/iterative-refinement-techniques)

Lesson 5 focuses on prompt precision. It starts from a failed instruction like "normalize the dates" and argues that ambiguous prose produces reasonable but wrong implementations.

The lesson teaches three refinement methods.

**A. Concrete input/output examples**
Use exact before-and-after pairs when the task is a transformation. The chapter shows this for date formatting, JSON reshaping, and SQL generation. The point is to remove interpretive room.

**B. Test-driven iteration**
Use tests as an external check on correctness. Write or supply the tests, run the code, pass failures back to Claude, and iterate. The chapter treats this as a fail-fix-rerun loop that forces the work toward measurable correctness.

**C. The interview pattern**
Use this when the domain is unfamiliar and the developer does not know the right edge cases up front. Claude asks clarifying questions, surfaces interacting decisions, and helps build a better spec before implementation.

The lesson also contrasts single-message and sequential refinement. If multiple requested fixes interact, bundle them. If they are independent, apply them one at a time so regressions are easier to localize.

### 7) Claude Code in CI/CD Pipelines
Source: [Lesson 6](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/claude-code-teams-cicd/claude-code-in-cicd-pipelines)

This lesson makes Claude scriptable. Its first hard rule is that CI needs non-interactive mode, which means the `-p` flag. Without it, the process waits for terminal interaction and the job stalls.

Key mechanics:
- `claude -p` runs in print mode and exits
- `--allowedTools` exposes only the tools the pipeline step needs
- `--output-format json` returns structured metadata around the response
- `--json-schema` constrains the machine-readable output shape for CI consumers
- `--bare` disables auto-discovered hooks, skills, plugins, MCP servers, and CLAUDE.md files so runs are reproducible

The lesson treats structured output as a serious engineering requirement. A CI job usually needs findings, severity, file, line, and summary fields, not just prose. The schema-constrained example shows how to force Claude's output into a predictable structure that downstream automation can parse.

The chapter also stresses review scoping. A CI reviewer should be told what counts as a real finding and what not to report. That keeps the output away from lint-level noise and duplicate documentation comments.

A second thread is cost and latency. The page distinguishes between real-time checks for merge-blocking work and batch processing for slower, cheaper reports such as overnight analysis.

### 8) Multi-Pass Review Architecture
Source: [Lesson 7](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/claude-code-teams-cicd/multi-pass-review-architecture)

This lesson argues that self-review inside the same Claude session is structurally weak. The model remembers the reasoning that produced the code, so a same-session review has the same blindness a human author has when rereading their own work.

The fix is session separation. The chapter proposes a staged review design:
1. generate code in one session
2. run independent per-file reviews in separate Claude invocations
3. run a cross-file pass that sees the whole change and the already collected local findings
4. combine the outputs into a final report grouped by severity and confidence

The page gives shell-script sketches for per-file review and cross-file integration review. The principle is context isolation. Each file review should be independent, and the cross-file review should focus only on interactions that local review cannot see.

Another strong point in this lesson is criteria specificity. A vague instruction like "review this code" produces weak output. The chapter recommends explicit criteria such as race conditions, missing error handling, off-by-one boundaries, security issues, and compatibility with existing middleware patterns. That forces the review pass to search for concrete defect classes rather than offer generic commentary.

### 9) Session Management: Resume, Fork, and Recovery
Source: [Lesson 8](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/claude-code-teams-cicd/session-management-resume-fork-recovery)

The final lesson treats sessions as saved workspaces. The chapter says Claude Code stores conversations locally and lets developers continue, resume, fork, and compact them.

Main tools and ideas:
- `claude --continue` resumes the most recent conversation in the current directory
- `claude --resume` opens a picker for prior sessions
- named sessions make retrieval practical when many investigations are active
- resuming is useful only when the file state and tool results are still materially valid
- if the code changed significantly, start fresh or explicitly brief the resumed session about what changed

The lesson also introduces forking with `/branch`. This allows two alternative lines of investigation to start from the same accumulated context. That is useful when the team wants to compare competing approaches without redoing the discovery work.

The last topic is `/compact`. The chapter treats context as a finite resource. Compaction compresses the conversation into a summary that preserves key decisions and current direction while freeing context window space. This is framed as a maintenance tool for long-running investigations.

### 10) Exercises
Source: [Exercises](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/claude-code-teams-cicd/teams-cicd-exercises)

The exercises page turns the chapter into applied practice. It organizes the work into modules that map back to the lesson sequence:
- Module 1: configuration architecture
- Module 2: skills and execution strategy
- Module 3: iterative refinement
- Module 4: CI/CD pipeline
- Module 5: review architecture
- Module 6: session mastery
- Module 7: integration capstones

The page also defines a general workflow for each exercise:
1. identify the right scope
2. choose the right mechanism
3. implement it in the correct location
4. verify the load behavior
5. test boundaries
6. document the reasoning

Representative exercises:
- **Exercise 1.1** builds a full monorepo hierarchy with package-level conventions and cross-cutting rules, then verifies them with `/memory`
- **Exercise 1.2** debugs broken loading behavior, which teaches inspection and diagnosis rather than greenfield setup
- **Exercise 2.1** builds three skills with `context: fork`, read-only `allowed-tools`, and `argument-hint`
- **Exercise 2.2** classifies tasks into plan mode, direct execution, or explore-then-execute
- **Exercise 3.1** uses I/O examples plus tests to normalize messy real-world data
- **Exercise 3.2** compares refinement techniques and asks the learner to try a mismatched technique on purpose

The capstones are the most revealing part of the page because they combine the chapter into end-to-end systems:
- **Capstone A** builds full team infrastructure for a multi-package monorepo
- **Capstone B** builds a production CI pipeline under a daily cost budget, with real-time versus batch tradeoffs and duplicate-avoidance requirements
- **Capstone C** audits the learner's own setup across configuration, skills, CI/CD, and session management, then asks for at least one real improvement

### 11) Quiz
Source: [Quiz](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/claude-code-teams-cicd/chapter-quiz)

The quiz page states the assessment target directly. It tests mastery of configuration hierarchy, custom skills, path-specific rules, plan mode, refinement, CI integration, multi-pass review, and session management. It also links the chapter to certification domains and task statements, including multi-pass review and session handling.

## What the chapter adds to the broader course
This chapter is where earlier concepts become operational. Chapter 14 introduced CLAUDE.md, skills, and hooks at a foundational level. Chapter 16 focused on spec-driven development. Chapter 18 turns those pieces into a team system. It is less about writing prompts and more about designing a controlled environment in which prompts, rules, automation, and review can work together.

## Major takeaways
- Put instructions at the narrowest scope that matches the audience.
- Use path-scoped rules for concerns that cut across directories.
- Use skills for triggered workflows, and use frontmatter to control isolation, permissions, and parameters.
- Plan before execution when the task contains design choices or hidden architectural commitments.
- Replace vague prose with examples, tests, or guided questioning.
- In CI, use non-interactive execution, structured output, and reproducible context.
- Separate writing from review so the reviewer does not inherit the writer's blind spots.
- Treat sessions as persistent assets, but resume them only when their context is still trustworthy.

## Chapter conclusion
Chapter 18 argues that the value of Claude Code scales with workflow design. A solo session can be productive, but a team gets the larger payoff when instructions are scoped, skills are reusable, pipelines are structured, review is isolated, and long investigations survive interruption. The chapter's real subject is not one command or flag. It is operational control.

## Source links
- [Overview](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/claude-code-teams-cicd)
- [The CLAUDE.md Configuration Hierarchy](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/claude-code-teams-cicd/claude-md-configuration-hierarchy)
- [Path-Specific Rules with Glob Patterns](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/claude-code-teams-cicd/path-specific-rules-with-glob-patterns)
- [Custom Skills with Frontmatter](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/claude-code-teams-cicd/custom-skills-with-frontmatter)
- [Plan Mode vs Direct Execution](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/claude-code-teams-cicd/plan-mode-vs-direct-execution)
- [Iterative Refinement Techniques](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/claude-code-teams-cicd/iterative-refinement-techniques)
- [Claude Code in CI/CD Pipelines](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/claude-code-teams-cicd/claude-code-in-cicd-pipelines)
- [Multi-Pass Review Architecture](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/claude-code-teams-cicd/multi-pass-review-architecture)
- [Session Management: Resume, Fork, and Recovery](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/claude-code-teams-cicd/session-management-resume-fork-recovery)
- [Exercises](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/claude-code-teams-cicd/teams-cicd-exercises)
- [Quiz](https://agentfactory.panaversity.org/docs/General-Agents-Foundations/claude-code-teams-cicd/chapter-quiz)
