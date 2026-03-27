# Shared Contracts

Machine-readable JSON schemas and shared golden fixtures for cross-service contracts between the WordPress plugin and the description service.

## Structure

```
packages/shared-contracts/
├── recognition/
│   ├── roster-roundtrip.sample.json   # Sample roster sync payload
│   └── *.golden.json                  # Cross-boundary fixture payloads
└── schemas/
    ├── coverage-stats.schema.json
    ├── recognition-cluster-snapshot.schema.json
    ├── recognition-job.schema.json
    ├── recognition-observation.schema.json
    ├── roster-entry.schema.json
    └── workbench-media-item.schema.json
```

## Purpose

These canonical schema definitions and shared fixtures are used to keep cross-boundary payloads aligned across backend, WordPress, and frontend consumers. Until code generation tooling is in place, the schemas serve as the authoritative machine-readable specification.

## vs. docs/agentic/contracts/

| This Package                 | docs/agentic/contracts/          |
| ---------------------------- | -------------------------------- |
| Machine-readable schemas     | Human-readable documentation     |
| JSON Schema specs            | Markdown with rationale          |
| For code generators/runtime  | For developers and agents        |

## Related

- `docs/agentic/contracts/` -- human-readable contract documentation
- `docs/agentic/rules/contract-change-checklist.md` -- boundary-owner, schema-evolution, and fixture expectations
- `apps/prototype-wp-alt-context/` -- WordPress plugin (consumer)
- `apps/prototype-description-service/` -- description service (consumer)
