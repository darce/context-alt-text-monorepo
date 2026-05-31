# Shared Contracts

Machine-readable JSON schemas and shared golden fixtures for cross-service contracts between the WordPress plugin and the description service.

## Structure

```text
packages/shared-contracts/
├── recognition/
│   ├── cluster-list-response.golden.json # Sample cluster-list envelope payload
│   ├── cluster-members-response.golden.json # Sample cluster-members envelope payload
│   ├── roster-roundtrip.sample.json   # Sample roster sync payload
│   ├── workbench-media-detail-response.golden.json
│   └── *.golden.json                  # Cross-boundary fixture payloads
└── schemas/
    ├── coverage-stats.schema.json
    ├── recognition-cluster-list-response.schema.json
    ├── recognition-cluster-members-response.schema.json
    ├── recognition-cluster-snapshot.schema.json
    ├── recognition-job.schema.json
    ├── recognition-observation.schema.json
    ├── roster-entry.schema.json
    ├── workbench-media-detail-response.schema.json
    ├── workbench-media-detail.schema.json
    └── workbench-media-item.schema.json
```

## Purpose

These canonical schema definitions and shared fixtures are used to keep cross-boundary payloads aligned across backend, WordPress, and frontend consumers. Until code generation tooling is in place, the schemas serve as the authoritative machine-readable specification.

The repo-level guard `python3 scripts/check_shared_contract_fixtures.py` validates the shared list-response golden fixtures against their declared schemas so envelope drift is caught before review.

## vs. docs/workstate/contracts/

| This Package                 | docs/workstate/contracts/          |
| ---------------------------- | -------------------------------- |
| Machine-readable schemas     | Human-readable documentation     |
| JSON Schema specs            | Markdown with rationale          |
| For code generators/runtime  | For developers and agents        |

## Related

- `docs/workstate/contracts/` -- human-readable contract documentation
- `docs/workstate/rules/contract-change-checklist.md` -- boundary-owner, schema-evolution, and fixture expectations
- `apps/prototype-wp-alt-context/` -- WordPress plugin (consumer)
- `apps/prototype-description-service/` -- description service (consumer)
