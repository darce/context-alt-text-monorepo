# Monorepo Scripts

Cross-project scripts and integration tests for the entire monorepo.

## Purpose

This directory contains **monorepo-wide automation** that spans multiple applications or packages. These scripts are not specific to any single app.

## Contents

- **`smoke-test-local-integration.sh`** - End-to-end integration test
  - Tests WordPress plugin + recognition service together
  - Verifies cross-service communication
  - Runs locally before deployment

## vs. `/apps/wp-context-alt-text/scripts/`

| This Directory            | apps/wp-context-alt-text/scripts/ |
| ------------------------- | --------------------------------- |
| **Monorepo-wide scripts** | **Plugin-specific scripts**       |
| Test multiple services    | Test single app                   |
| Integration tests         | Unit/component tests              |
| Cross-project automation  | Single-project automation         |

## Example

```bash
# In this directory (/scripts/)
smoke-test-local-integration.sh
- Starts WordPress plugin
- Starts recognition service
- Tests API communication between them
- Verifies end-to-end workflow

# In apps/wp-context-alt-text/scripts/
check-architecture-compliance.js
- Lints only the WordPress plugin
- Checks component architecture rules
- Plugin-specific quality checks
```

## Usage

```bash
# Run integration tests
./scripts/smoke-test-local-integration.sh

# Run from monorepo root
cd /path/to/context-alt-text-monorepo
./scripts/smoke-test-local-integration.sh
```

## Future Scripts (Examples)

Potential future additions:

- `deploy-all.sh` - Deploy all services
- `version-bump.sh` - Synchronize versions across packages
- `generate-contracts.sh` - Regenerate all DTOs from shared-contracts
- `backup-prod.sh` - Backup all production data
- `migrate-data.sh` - Run migrations across services

## Related Directories

- **`/apps/wp-context-alt-text/scripts/`** - WordPress plugin scripts
- **`/apps/recognition-service/scripts/`** - Recognition service scripts
- **`/tools/scripts/`** - Development tool scripts (if exists)

## Guidelines

**When to add scripts here:**

- Script affects multiple applications
- Integration or E2E testing
- Cross-service deployment
- Monorepo-wide code generation

**When to add to app scripts:**

- Script affects only one application
- App-specific linting/testing
- Single-app deployment
- App-specific development workflow
