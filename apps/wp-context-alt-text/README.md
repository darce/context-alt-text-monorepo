# Context Alt Text Plugin

AI-powered alternative text generation for WordPress media, with facial recognition and roster management.

## Quick Start

```bash
cd apps/wp-context-alt-text

# Choose your environment:
./scripts/switch-env.sh local        # Full local development
./scripts/switch-env.sh dev-remote   # Local WP + Remote Recognition
./scripts/switch-env.sh production   # Production deployment

# Install dependencies
npm install
composer install

# Start development
npm run dev
```

**New to the project?** See [Getting Started](#getting-started) below.

---

## Table of Contents

- [Getting Started](#getting-started)
- [Development](#development)
- [Configuration](#configuration)
- [Testing](#testing)
- [Production Deployment](#production-deployment)
- [Documentation](#documentation)

---

## Getting Started

### Prerequisites

- **Node.js** >= 22.18.0 (use `nvm install 22.18.0` or FNM)
- **PHP** >= 8.2
- **Composer** >= 2.0
- **WordPress** >= 6.0 (LocalWP recommended for local development)

### LocalWP Setup

From your LocalWP site folder (e.g., `~/Development/wp-context-alt-text/app/public/wp-content/plugins`):

**Note:** The path below is an example. Your LocalWP site path may differ.

```bash
# Remove default plugin directory
rm -rf context-alt-text

# Symlink to monorepo (adjust path to match your setup)
ln -s ../../../../../context-alt-text/apps/wp-context-alt-text context-alt-text

# Activate plugin
wp plugin activate context-alt-text
```

### Environment Configuration

The plugin supports three environment profiles:

| Profile        | Use Case               | WordPress           | Recognition Service           |
| -------------- | ---------------------- | ------------------- | ----------------------------- |
| **local**      | Full local development | LocalWP (localhost) | Local Python (localhost:7860) |
| **dev-remote** | Frontend development   | LocalWP (localhost) | Remote (Hugging Face Space)   |
| **production** | Live deployment        | Production server   | Production service            |

**Switch environments:**

```bash
cd apps/wp-context-alt-text
./scripts/switch-env.sh <profile>
```

**📖 Detailed guide:** [`docs/configuration.md`](docs/configuration.md)

---

## Development

### Frontend Development (Vite + React)

```bash
# Install dependencies
npm install

# Start Vite dev server (with HMR)
npm run dev

# Build production assets
npm run build

# Run Storybook (component workbench)
npm run storybook
```

**Vite Dev Server:** `http://localhost:5173`

**LocalWP Integration:**

1. Set `WP_ENVIRONMENT_TYPE` to `development` in `wp-config.php`
2. Run `npm run dev` to start Vite
3. Visit WordPress admin dashboard - assets load from dev server with HMR

**Stopping the dev server:**

- Foreground: Press `Ctrl+C`
- Background: `pkill -f "vite"` or `kill $(lsof -ti:5173)`

### Backend Development (PHP)

```bash
# Install dependencies
composer install

# Run PHP unit tests
composer test

# Run specific test file
composer test -- tests/Recognition/RecognitionSettingsTest.php

# Run with coverage
composer test -- --coverage-text
```

**Code Structure:**

```
src/
  Admin/          # WordPress admin integration
  Api/            # REST API endpoints
  Domain/         # Business logic
  Frontend/       # Frontend asset management
  Recognition/    # Recognition service integration
  Roster/         # Roster management
  Services/       # Application services
  Support/        # Utilities, feature flags
```

### Component Development (Storybook)

```bash
# Start Storybook
npm run storybook

# Build static Storybook
npm run storybook:build
```

**Storybook:** `http://localhost:6006`

Stories live in `js/components/**/*.stories.tsx`. Add stories for each component variant (loading, empty, populated).

**📖 Contributing guide:** [`docs/development.md`](docs/development.md)

---

## Configuration

### Environment Variables

```bash
# Vite Development Server
CAT_VITE_DEV_SERVER=http://localhost:5173

# Recognition Service
CAT_RECOGNITION_BASE_URL=http://localhost:7860
CAT_RECOGNITION_TIMEOUT_MS=30000
CAT_RECOGNITION_API_KEY=               # Optional
CAT_RECOGNITION_MODEL_PROFILE=         # Optional
```

### Configuration Priority

The plugin checks configuration sources in this order:

1. **Environment variables** (`.env` file) - **Highest priority**
2. **WordPress database** (Settings page) - Fallback
3. **Constants** (`wp-config.php`) - Legacy support

### Recognition Service Setup

**Local Development:**

```bash
# Switch to local profile
./scripts/switch-env.sh local

# Start recognition service
cd ../recognition-service
./scripts/start_recognition_local.sh

# Verify connection
wp cat-recognition health
```

**Remote Development:**

```bash
# Switch to dev-remote profile
./scripts/switch-env.sh dev-remote

# Edit .env.dev-remote with your remote URL
nano .env.dev-remote

# Apply changes
./scripts/switch-env.sh dev-remote
```

**Recognition features auto-enable** when `CAT_RECOGNITION_BASE_URL` is configured. No manual feature flags needed!

**📖 Full configuration guide:** [`docs/configuration.md`](docs/configuration.md)

---

## Testing

### PHP Tests

```bash
# Run all tests
composer test

# Run specific test suite
composer test -- tests/Recognition/
composer test -- tests/Integration/
composer test -- tests/Support/

# Run with coverage
composer test -- --coverage-html coverage/
```

**Current Status:** 163 tests, 653 assertions, all passing ✅

### JavaScript Tests

```bash
# Run all tests
npm run test

# Run in watch mode
npm run test:watch

# Run with coverage
npm run test:coverage
```

### Manual Testing

```bash
# Health check
wp cat-recognition health

# Upload test image
wp media import /path/to/image.jpg --post_id=0

# Run recognition (use attachment ID from previous command)
wp cat-recognition analyze 123

# Check roster status
wp cat-roster status

# Sync roster from remote
wp cat-roster sync
```

**📖 Testing guide:** [`docs/development.md#testing`](docs/development.md#testing)

---

## Production Deployment

### Build Production Assets

```bash
# Switch to production profile
./scripts/switch-env.sh production

# Build assets
npm run build
```

### Production Checklist

- [ ] Edit `.env.production` with production URLs
- [ ] Build assets: `npm run build`
- [ ] Test production build locally
- [ ] Deploy plugin to production server
- [ ] Verify recognition service connectivity
- [ ] Test end-to-end workflow
- [ ] Monitor logs and health endpoints

### Docker Deployment

```dockerfile
FROM wordpress:latest

# Copy plugin
COPY apps/wp-context-alt-text /var/www/html/wp-content/plugins/context-alt-text

# Set environment variables
ENV CAT_RECOGNITION_BASE_URL=https://recognition.production.com
ENV CAT_RECOGNITION_TIMEOUT_MS=30000
ENV CAT_RECOGNITION_API_KEY=your-api-key
```

### Kubernetes Deployment

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
    name: context-alt-text-config
data:
    CAT_RECOGNITION_BASE_URL: "https://recognition.production.com"
    CAT_RECOGNITION_TIMEOUT_MS: "30000"
```

**📖 CI/CD integration:** [`docs/configuration.md#cicd-integration`](docs/configuration.md#cicd-integration)

---

## Documentation

### Plugin Documentation

- **[Configuration Guide](docs/configuration.md)** - Environment profiles, priority system, feature auto-enabling
- **[Development Guide](docs/development.md)** - Contributing, testing, code standards
- **[API Reference](docs/api-reference.md)** - REST API endpoints documentation
- **[Troubleshooting](docs/troubleshooting.md)** - Common issues and solutions

### Monorepo Documentation

- **[Architecture](../../docs/architecture/)** - System design, UML diagrams, contracts
- **[Getting Started (Monorepo)](../../docs/getting-started.md)** - Onboarding for new contributors

---

## Feature Flags

Recognition features **auto-enable** when a recognition service is configured. Manual control available via:

```php
// wp-config.php
define('CAT_FEATURE_WORKBENCH_RECOGNITION', false); // Force disable
define('CAT_FEATURE_ROSTER_UI_ENABLED', true);      // Force enable
```

**Other feature flags:**

- `CAT_ENABLE_ABILITIES` — Enables Abilities registrar (post-MVP, disabled by default)
- `CAT_ENABLE_MCP` — Enables MCP server adapter (post-MVP, disabled by default)

---

## Troubleshooting

### "Recognition service not connected"

```bash
# Check active profile
cat .env | grep CAT_RECOGNITION_BASE_URL

# Verify service is running
curl http://localhost:7860/api/v0/health

# Test from WordPress
wp cat-recognition health
```

### "Vite dev server not working"

```bash
# Check dev server URL
cat .env | grep CAT_VITE_DEV_SERVER

# Verify WP_ENVIRONMENT_TYPE
grep WP_ENVIRONMENT_TYPE wp-config.php
```

### "Switch script not working"

```bash
# Make executable
chmod +x scripts/switch-env.sh

# Run with explicit profile
./scripts/switch-env.sh local
```

**📖 Full troubleshooting guide:** [`docs/troubleshooting.md`](docs/troubleshooting.md)

---

## Project Structure

```
apps/wp-context-alt-text/
├── context-alt-text.php    # Plugin bootstrap
├── src/                    # PHP source code (PSR-4 autoloaded)
├── js/                     # TypeScript/React frontend
│   ├── admin/             # Admin dashboard SPA
│   └── components/        # Reusable UI components
├── public/                # Public assets, language files
│   └── assets/dist/       # Compiled Vite bundles (committed)
├── docs/                  # Plugin-specific documentation
├── tests/                 # PHPUnit tests
├── scripts/               # Utility scripts
├── .env.*                 # Environment profiles
├── composer.json          # PHP dependencies
├── package.json           # Node dependencies
└── vite.config.ts         # Vite configuration
```

---

## Support

- **Issues:** [GitHub Issues](https://github.com/darce/context-alt-text-monorepo/issues)
- **Documentation:** [`docs/`](docs/)
- **WordPress Logs:** `/wp-content/uploads/cat-logs/debug-YYYY-MM-DD.log`

---

## License

MIT License - see [LICENSE](../../LICENSE) file for details.

**Key Points:**

- ✅ Commercial use permitted
- ✅ Modification and redistribution allowed
- ✅ Can include other MIT-licensed libraries
- ⚠️ No warranty or liability
