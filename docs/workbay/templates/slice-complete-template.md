---
template_for: record_decision slice_complete_* rationale
---

# Slice Completion Decision Format

Use this format as the `rationale` value for every `record_decision` call where
`decision` starts with `slice_complete_`. The format is enforced at write time.

```
## Changes
- <file_path>: <function_or_class_name> ; <what changed>
- <file_path>: <route_or_endpoint> ; <what changed>

## Verification
- pytest <path>: <N> passed
- vitest <path>: <N> passed
- mypy: <N> source files clean

## Schema / Contract Changes
- <table.column> added/removed/renamed
- <REST route> added/removed ; <method> <path>
- <TypeScript type> field added: <field_name>: <type>

## Open Threads
- <what the next agent should pick up>
```

## Rules

- (a) List every changed file with the specific function, class, route, or hook modified.
- (b) Include concrete test counts, not just "tests pass".
- (c) List schema column names, REST routes, TypeScript type changes, and PHP hook names explicitly.
- (d) Note any open threads or follow-ups.
- (e) If a section has no entries, write `- none.` -- do not omit the section.
- (f) Freeform prose-only slice decisions are not acceptable.

## Packet-backed review rule

If you expect another agent to review "the latest completed slice", the slice completion
decision and nearest worker report together must be sufficient to derive a slice review
packet. Record concrete `changed_files`, verification commands, and any contract/doc
touches in the same handoff window instead of relying on later branch archaeology.
