# Monorepo Scripts

Cross-project scripts and integration tests for the entire monorepo.

## Directory Structure

```
scripts/
├── README.md                   # This file
├── local-wp-cli.sh             # WordPress CLI wrapper for Local by Flywheel
└── mcp/
    └── unified_server.py       # Unified MCP server for all codebases
```

- **`smoke-test-local-integration.sh`** - End-to-end integration test

  - Tests WordPress plugin + recognition service together
  - Verifies cross-service communication
  - Tests face detection, clustering, and roster workflows
  - Runs locally before deployment

- **`diagnose-401-error.sh`** - Diagnostic for 401 authorization errors
  - **Important:** Must be copied to WordPress root before running
  - Checks user capabilities, REST API nonce, feature flags
  - See detailed usage instructions below

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

### Integration Tests

```bash
# Run integration tests
./scripts/smoke-test-local-integration.sh

# Run from monorepo root
cd /path/to/context-alt-text-monorepo
./scripts/smoke-test-local-integration.sh
```

### Diagnostic Scripts

#### diagnose-401-error.sh

**⚠️ Important:** This script must be run from the WordPress root directory, not from the plugin directory.

**For Local by Flywheel:**

```bash
# 1. Copy script to WordPress root
cp scripts/diagnose-401-error.sh ~/Development/wp-context-alt-text/app/public/

# 2. SSH into Local site
# From Local app: Right-click site → Open Site Shell

# 3. Run diagnostic
bash diagnose-401-error.sh
```

**For Standard WordPress:**

```bash
# 1. Copy script to WordPress root
cp scripts/diagnose-401-error.sh /path/to/wordpress/

# 2. Navigate to WordPress root
cd /path/to/wordpress/

# 3. Run diagnostic
bash diagnose-401-error.sh
```

**What it checks:**

- User capabilities (`upload_files`)
- REST API nonce generation
- Plugin activation status
- Feature flags configuration
- Endpoint registration
- Authentication test

**Common fixes it provides:**

```bash
# Grant upload_files capability
wp user add-cap username upload_files

# Activate plugin
wp plugin activate context-alt-text

# Hard refresh page (for stale nonce)
# Cmd+Shift+R (Mac) or Ctrl+Shift+F5 (Windows)
```

See [`docs/troubleshooting/401-identify-faces-error.md`](../apps/wp-context-alt-text/docs/troubleshooting/401-identify-faces-error.md) for more details.

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
