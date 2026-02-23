# Shared Contracts

Machine-readable JSON schemas for cross-service contracts between the WordPress plugin and the description service.

## Structure

```
packages/shared-contracts/
├── recognition/
│   └── roster-roundtrip.sample.json   # Sample roster sync payload
└── schemas/
    ├── coverage-stats.schema.json
    ├── recognition-cluster-snapshot.schema.json
    ├── recognition-job.schema.json
    ├── recognition-observation.schema.json
    ├── roster-entry.schema.json
    └── workbench-media-item.schema.json
```

## Purpose

These canonical schema definitions will be used to generate language-specific types for each consuming app (TypeScript, PHP DTOs, Pydantic models). Until code generation tooling is in place, the schemas serve as the authoritative specification.

## vs. docs/agentic/contracts/

| This Package                 | docs/agentic/contracts/          |
| ---------------------------- | -------------------------------- |
| Machine-readable schemas     | Human-readable documentation     |
| JSON Schema specs            | Markdown with rationale          |
| For code generators/runtime  | For developers and agents        |

## Related

- `docs/agentic/contracts/` -- human-readable contract documentation
- `apps/prototype-wp-alt-context/` -- WordPress plugin (consumer)
- `apps/prototype-description-service/` -- description service (consumer)
