# Agent Working Memory (Blackboard)

This directory provides a shared space for agents to persist state across tool invocations.

## Files

| File                     | Purpose                                    |
| ------------------------ | ------------------------------------------ |
| `current_task_state.md`  | Agent writes understanding of current task |
| `implementation_plan.md` | Step-by-step implementation plan           |

## Usage

Agents can write to these files to:

- Record intermediate findings
- Persist state across context windows
- Leave notes for subsequent agent invocations

## Guidelines

1. Keep entries timestamped
2. Clear old entries when starting fresh tasks
3. Use structured markdown for parseability
