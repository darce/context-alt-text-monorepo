# Shared Contracts

Machine-readable JSON schemas and OpenAPI specifications for cross-service contracts between the WordPress plugin and recognition service.

## Purpose

This package stores **canonical schema definitions** used to:

- Generate TypeScript types for the WordPress plugin frontend
- Generate PHP DTOs for the WordPress plugin backend
- Generate Python Pydantic models for the recognition service
- Validate API requests/responses at runtime

## vs. `/docs/architecture/contracts/`

| This Package                 | docs/architecture/contracts/     |
| ---------------------------- | -------------------------------- |
| **Machine-readable schemas** | **Human-readable documentation** |
| JSON Schema, OpenAPI specs   | Markdown files with explanations |
| For code generators          | For developers to read           |
| "Here's the schema"          | "Here's how it works"            |

## Example

```json
// In this package (packages/shared-contracts/)
recognition/roster.schema.json defines:
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "properties": {
    "id": { "type": "string" },
    "label": { "type": "string" }
  }
}

// Used to generate:
// - TypeScript: interface RosterEntry { id: string; label: string; }
// - PHP: class RosterEntryDTO { public string $id; public string $label; }
// - Python: class RosterEntry(BaseModel): id: str; label: str
```

```markdown
// In docs/architecture/contracts/
roster-contract.md explains:

- Why we structure roster entries this way
- How sync conflicts are resolved
- Edge cases and error handling
```

## Current Structure

```
packages/shared-contracts/
├── README.md (this file)
└── recognition/
    └── roster-roundtrip.sample.json  # Sample roster sync payload
```

## Planned Structure (Task 8.3)

```
packages/shared-contracts/
├── README.md
├── schemas/
│   ├── recognition/
│   │   ├── roster-entry.schema.json
│   │   ├── roster-sync.schema.json
│   │   ├── observation.schema.json
│   │   └── recognition-job.schema.json
│   ├── dashboard/
│   │   └── coverage-stats.schema.json
│   └── workbench/
│       └── media-item.schema.json
├── generated/
│   ├── typescript/  # Generated .ts files
│   ├── php/         # Generated PHP DTOs
│   └── python/      # Generated Pydantic models
└── samples/
    └── recognition/
        └── roster-roundtrip.sample.json  # Moved here
```

## Workflow

When an API contract changes:

1. **Update the canonical schema** in `schemas/`

   ```bash
   # Edit the JSON Schema file
   vim schemas/recognition/roster-entry.schema.json
   ```

2. **Regenerate language-specific types**

   ```bash
   npm run generate:types          # TypeScript
   composer generate:dtos          # PHP
   poetry run generate-models      # Python (recognition service)
   ```

3. **Bump package version**

   ```json
   {
     "name": "@context-alt-text/shared-contracts",
     "version": "1.2.0" // Increment
   }
   ```

4. **Update consuming apps**

   ```bash
   # In WordPress plugin
   npm install @context-alt-text/shared-contracts@1.2.0
   composer update context-alt-text/shared-contracts

   # In recognition service
   poetry add context-alt-text-shared-contracts@1.2.0
   ```

5. **Update documentation** in `/docs/architecture/contracts/`
   - Explain the change in human terms
   - Update testing guidelines
   - Add migration notes if breaking

## Benefits

✅ **Single source of truth** - Schema is the authority  
✅ **Type safety** - Generated types catch errors at compile time  
✅ **Cross-language consistency** - TS, PHP, and Python match exactly  
✅ **Runtime validation** - Validate payloads against schema  
✅ **Documentation** - Schema serves as API specification

## Related Directories

- **`/docs/architecture/contracts/`** - Human-readable contract documentation
- **`/apps/wp-context-alt-text/`** - WordPress plugin (consumes generated types)
- **`/apps/recognition-service/`** - Recognition service (consumes generated models)

## Tools

- **JSON Schema**: http://json-schema.org/
- **TypeScript code generation**: `json-schema-to-typescript`
- **PHP code generation**: `jane-php/json-schema`
- **Python code generation**: `datamodel-code-generator`

## Next Steps

See **Task 8.3** in `/REFACTORING_TASKS.md` for implementation plan.
