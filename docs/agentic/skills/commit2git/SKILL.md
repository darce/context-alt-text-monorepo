---
name: commit2git
description: Use when uncommitted changes on the current Git branch need to be split into clean commits by completed sub-feature, slice, or reviewable refactor. Inspect modified and untracked files, group only coherent completed work, stage each group deliberately, and write meaningful commit messages. If operating from a linked Git worktree, prefix each commit subject with the worktree name.
---

# Commit2Git

Use this skill when the user asks you to turn a dirty branch into a small set of reviewable commits.

## Goal

Create one commit per completed sub-feature, not one commit per directory or per file type.

## Worktree safety

Treat the current checkout as authoritative.

- Do not change to the orchestrator root or another sibling worktree just to make a commit.
- Do not replace a worker-lane commit flow with a root-repo commit flow.
- Do not run cleanup or refresh commands that would reset, replace, or abandon the current lane unless the user explicitly asked for that.
- After committing, remain in the same worktree and branch context you started in.

Before doing any staging, confirm where you are:

```bash
pwd
git rev-parse --show-toplevel
git branch --show-current
git rev-parse --git-dir
git rev-parse --git-common-dir
```

If the current branch is a lane branch such as `codex/p5-backend-domain`, treat that lane worktree as the only valid place to commit its changes.

## Inspect the current change set

Start by reading the shape of the diff:

```bash
git status --short
git diff --name-only
git diff --cached --name-only
```

Then inspect candidate groups with targeted diffs:

```bash
git diff -- path/to/file
git diff --stat
```

## Grouping rules

- Group by completed behavior, workflow slice, or reviewable refactor.
- Keep tests, fixtures, and docs with the code they verify when they describe the same slice.
- Split tooling or workflow changes away from product behavior unless both are required for one completed outcome.
- Do not create a commit for half-finished work unless the user explicitly asks for a checkpoint commit.
- Leave unrelated or ambiguous hunks unstaged until they can be split cleanly.

Prefer groups such as:

- new command/handler plus its tests
- one documentation slice for a newly introduced workflow
- one MCP or review-tooling improvement
- one refactor with no behavioral change

Do not group by:

- language alone
- folder alone
- "everything touched for this task" when the branch clearly contains multiple finished slices

## Stage deliberately

Use full-file staging only when the file belongs to one slice. Otherwise use hunk staging:

```bash
git add path/to/file
git add -p
git diff --cached --stat
git diff --cached
```

Before each commit, confirm the staged diff tells one story.

## Commit message format

Write subjects around the completed outcome, preferably using a Conventional Commit style for the core subject:

```text
feat(scope): add review dispatch routing
fix(scope): preserve finding provenance on updates
docs(agentic): document lane refresh recovery
refactor(scope): split report rendering from git inspection
test(scope): cover lane status edge cases
```

Avoid vague subjects such as:

- `misc updates`
- `wip`
- `fix stuff`
- `address feedback`

## Worktree-aware prefix and lane behavior

Detect whether the current checkout is a linked worktree:

```bash
git rev-parse --git-dir
git rev-parse --git-common-dir
basename "$(git rev-parse --show-toplevel)"
```

If `git rev-parse --git-dir` and `git rev-parse --git-common-dir` differ, treat the checkout as a linked worktree and prefix the commit subject with the worktree directory name:

```text
<worktree-name>: <subject>
```

Example:

```text
context-alt-text-monorepo-p5-frontend: feat(retention-export): add export progress banner
```

If the paths are the same, use the subject without a worktree prefix.

## Repo-specific note

This repo's `make lane-commit` and `make lane-handoff` helpers already prefix commits with the lane name and preserve lane ownership rules.

When you are inside a worker lane worktree in this repo:

- prefer `make lane-commit` over a manual root-level `git commit`
- do not switch to `/Users/daniel/Development/context-alt-text-monorepo` just to perform the commit
- do not leave the lane on the orchestrator branch after committing

If the user explicitly wants the worktree name instead of the lane name, prefer a manual `git commit -m "<worktree-name>: <subject>"` in the current worker worktree and then run the reporting step separately if needed.

## Final check per commit

For each commit group:

1. Stage only the files or hunks for that completed slice.
2. Re-read `git diff --cached`.
3. Commit with a meaningful subject.
4. Re-run `git status --short` and repeat for the next slice.

Stop and ask the user only if one file contains interleaved changes that cannot be split safely into separate sub-features.
