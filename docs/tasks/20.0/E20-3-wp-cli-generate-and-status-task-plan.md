# Task Plan

> **Metadata**
>
> - **Date**: 2026-07-04 22:45 EST
> - **Author**: Codex GPT-5
> - **Owning Epic**: [docs/epics/v0.5.0/production-alt-text-workflow-and-governance-epic.md](../../epics/v0.5.0/production-alt-text-workflow-and-governance-epic.md)
> - **Epic Short ID**: E20
> - **Target Branch**: `feature/e20-3`
> - **Review Coverage Target**: 2

---

## E20-3. WP-CLI Generate and Status Surface

## Objective

Add a headless WP-CLI surface for previewing, generating, and checking description/alt-text status for selected attachments. The commands must reuse E20-1 write semantics and E20-2 candidate selection.

## Problem Statement

Operators need automation before a full admin workflow. A WP-CLI command is the safest first automation surface because it is explicit, scriptable, and easy to dry-run in LocalWP.

## Constraints

- Depends on E20-1 and E20-2.
- `--dry-run` is the default or a required explicit proof path before writes in tests.
- Commands must use bounded limits and refuse unbounded generation.

## Workflow Principles

- CLI uses the same PHP services as REST.
- Status reports never trigger generation.
- Output supports both table and JSON for smoke evidence.

## Terminology

- **Generate command**: CLI path that calls describe and optionally writes alt text.
- **Status command**: read-only CLI path that reports candidate and provenance state.

## Current State Analysis

- Existing CLI commands live under `apps/prototype-wp-alt-context/src/cli/`.
- `class-reset-projection-command.php` and `class-xmp-backfill-command.php` show WP-CLI registration patterns.
- No description CLI command exists.

## Target Outcome

`wp alt-context describe generate` and `wp alt-context describe status` support `--media-id`, `--limit`, `--dry-run`, `--write`, `--force`, and `--format=json|table`, with tests proving they call the E20 services.

## Context Loading

- Rules: `docs/workbay/rules/backend-php-guidelines.md`
- Contracts: `docs/workbay/contracts/image-description-api.md`
- Code: `apps/prototype-wp-alt-context/src/cli/class-reset-projection-command.php`, `apps/prototype-wp-alt-context/src/cli/class-xmp-backfill-command.php`, `apps/prototype-wp-alt-context/src/class-alt-context.php`
- Prior-task surfaces: E20-1 `DescribeMediaService` write policy; E20-2 `DescriptionCandidateService` (new there)
- Handoff/MCP: tasks `E20-1`, `E20-2`, `E20-3`

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| WP-CLI | WordPress plugin | existing command registration | New `describe generate/status` commands | yes; no existing command breakage | command tests + LocalWP smoke |
| Description services | WordPress plugin | E20-1/E20-2 services | CLI consumes without duplicating policy | yes | unit tests with fake services |

## Proposed Solution

Create a focused CLI command class that delegates candidate lookup to `DescriptionCandidateService` and writes through `DescribeMediaService`. Add JSON output for evidence and a LocalWP smoke target for one dry-run and one write run.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| CLI command | `apps/prototype-wp-alt-context/src/cli/class-description-command.php` | New generate/status commands |
| Plugin bootstrap | `apps/prototype-wp-alt-context/src/class-alt-context.php` | Register CLI command when WP-CLI is present |
| Services | E20-1/E20-2 service files | Inject/reuse without reimplementing policy |
| Makefile | `apps/prototype-wp-alt-context/Makefile` | Add CLI smoke target |

## Related Files

| File | Note |
| --- | --- |
| `apps/prototype-wp-alt-context/src/cli/class-xmp-backfill-command.php` | Command style and output precedent |
| `apps/prototype-wp-alt-context/scripts/localwp/describe-run-smoke.php` | Local smoke evidence pattern |

## Verification Strategy

- Deterministic tests: `composer test -- --filter DescriptionCommand`
- Runtime-parity checks: LocalWP WP-CLI dry-run and single write
- Manual verification: `wp alt-context describe status --format=json`

## Slice Delivery

### Slice 1: Command registration and status

**Goal**: Register the CLI command and implement read-only status output.

Changes:

- Add command class and bootstrap registration.
- Implement `status` using E20-2 candidate/provenance reads.

Proof:

- `composer test -- --filter DescriptionCommandStatus`

### Slice 2: Generate with dry-run/write/force

**Goal**: Implement bounded generation using E20-1 write semantics.

Changes:

- Add `generate` command with `--media-id`, `--limit`, `--dry-run`, `--write`, `--force`, `--format`.
- Add LocalWP smoke target.

Proof:

- `composer test -- --filter DescriptionCommandGenerate`
- LocalWP smoke JSON shows dry-run no write and write with provenance.

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded CLI command patterns and E20-1/E20-2 services.
- [ ] Confirmed CLI delegates write policy instead of duplicating it.

### Checklist for Slice 1: Command registration and status

- [ ] Command class registered only under WP-CLI.
- [ ] `status` is read-only and supports JSON/table.
- [x] `composer test -- --filter DescriptionCommandStatus` green.

### Checklist for Slice 2: Generate with dry-run/write/force

- [ ] `generate` supports bounded dry-run/write/force.
- [ ] LocalWP CLI smoke target added.
- [x] `composer test -- --filter DescriptionCommandGenerate` green.

## Review Readiness

- [ ] No unbounded generation path.
- [ ] CLI write semantics match E20-1 tests.
- [ ] Handoff decision records command contract.

## Stretch Goals

- [ ] `--ids-from=-` support for piping selected media ids.

## Success Criteria

- [ ] Operator can preview and write one attachment via WP-CLI.
- [ ] CLI status reports candidate/provenance state without generation.
- [ ] JSON output is stable enough for smoke evidence.
