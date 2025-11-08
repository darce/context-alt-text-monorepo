# Configuration Guide

This guide explains how to configure the Context Alt Text plugin for different development and deployment scenarios.

## Table of Contents

- [Quick Start](#quick-start)
- [Environment Profiles](#environment-profiles)
- [Configuration Priority](#configuration-priority)
- [Feature Auto-Enabling](#feature-auto-enabling)
- [Manual Configuration](#manual-configuration)
- [CI/CD Integration](#cicd-integration)
- [Troubleshooting](#troubleshooting)
- [Testing](#testing)

---

## Quick Start

The plugin supports three environment profiles. Choose the one that matches your workflow:

```bash
cd apps/wp-context-alt-text

# Full local development (WordPress + Recognition both on localhost)
./scripts/switch-env.sh local

# Local WordPress + Remote Recognition (e.g., Hugging Face Space)
./scripts/switch-env.sh dev-remote

# Production deployment
./scripts/switch-env.sh production
```

**What happens when you switch?**

- ✅ Copies the selected profile (`.env.{profile}`) to `.env`
- ✅ Validates the profile exists
- ✅ Shows confirmation with active configuration
- ✅ Provides next steps for that environment

---

## Environment Profiles

### Overview

| Profile        | WordPress             | Recognition Service                     | Typical Use Case                                    |
| -------------- | --------------------- | --------------------------------------- | --------------------------------------------------- |
| **local**      | LocalWP (`localhost`) | Local Python service (`localhost:7860`) | Full local development, debugging both services     |
| **dev-remote** | LocalWP (`localhost`) | Remote Hugging Face Space               | Frontend development with stable remote recognition |
| **production** | Production server     | Production recognition service          | Live deployment                                     |

---

### Option 1: Full Local Development

**Use when:** You're developing both the WordPress plugin AND the recognition service.

```bash
cd apps/wp-context-alt-text
./scripts/switch-env.sh local
```

**What this configures:**

- Vite dev server: `http://localhost:5173`
- Recognition service: `http://localhost:7860`
- Timeout: 30 seconds (longer for local debugging)

**Next steps:**

1. Start the recognition service:
    ```bash
    cd ../recognition-service
    ./scripts/start_recognition_local.sh
    ```
2. Start Vite: `npm run dev`
3. Open WordPress dashboard

---

### Option 2: Local WordPress + Remote Recognition

**Use when:** You're developing the WordPress plugin but want to use a stable recognition service hosted remotely.

```bash
cd apps/wp-context-alt-text
./scripts/switch-env.sh dev-remote
```

**What this configures:**

- Vite dev server: `http://localhost:5173`
- Recognition service: `https://your-username-recognition.hf.space` (edit `.env.dev-remote`)
- Timeout: 60 seconds (longer for remote API calls)

**Customization:**

1. Edit `.env.dev-remote` with your actual Hugging Face Space URL
2. Re-run `./scripts/switch-env.sh dev-remote` to apply changes

**Next steps:**

1. Start Vite: `npm run dev`
2. Open WordPress dashboard
3. Recognition service is already running remotely

---

### Option 3: Production Deployment

**Use when:** Deploying to a live production environment.

```bash
cd apps/wp-context-alt-text
./scripts/switch-env.sh production
```

**What this configures:**

- Vite: Production build (no dev server)
- Recognition service: Production URL (edit `.env.production`)
- Timeout: 30 seconds (production-optimized)

**Customization:**

1. Edit `.env.production` with your production URLs
2. Re-run `./scripts/switch-env.sh production` to apply changes

**Production checklist:**

- [ ] Build assets: `npm run build`
- [ ] Test production build locally
- [ ] Deploy plugin to production server
- [ ] Verify recognition service connectivity
- [ ] Test end-to-end workflow

---

### Environment Workflow

```
┌─────────────────────────────────────────────────────────────┐
│                    Development Workflow                      │
└─────────────────────────────────────────────────────────────┘

1. Choose Environment:
   ├─> local          (WordPress localhost + Recognition localhost)
   ├─> dev-remote     (WordPress localhost + Recognition remote)
   └─> production     (Both services remote/production)

2. Switch Environment:
   ./scripts/switch-env.sh <profile>

3. Customize (Optional):
   Edit .env.<profile> with your URLs
   Re-run: ./scripts/switch-env.sh <profile>

4. Start Services:
   ├─> local:          Start recognition service, then npm run dev
   ├─> dev-remote:     Just npm run dev (recognition is remote)
   └─> production:     npm run build (no dev server)

5. Verify:
   - WordPress admin → Context Alt Text → Settings
   - Or: wp cat-recognition health
```

---

## Configuration Priority

The plugin follows [12-factor app](https://12factor.net/config) principles. Configuration sources are checked in this order:

1. **Environment variables** (`.env` file or system environment) - **Highest priority**
2. **WordPress database** (Settings page) - Fallback if `.env` not set
3. **Constants** (`wp-config.php`) - Legacy support

**Example:** If you set `CAT_RECOGNITION_BASE_URL` in `.env`, it overrides any value set in the WordPress admin Settings page.

### Available Environment Variables

```bash
# Vite Development Server (for frontend development with HMR)
CAT_VITE_DEV_SERVER=http://localhost:5173

# Recognition Service Configuration
CAT_RECOGNITION_BASE_URL=http://localhost:7860
CAT_RECOGNITION_TIMEOUT_MS=30000
CAT_RECOGNITION_API_KEY=               # Optional: API key for authentication
CAT_RECOGNITION_MODEL_PROFILE=         # Optional: specific model profile
```

### Environment File Structure

```
apps/wp-context-alt-text/
├── .env.template        # Template with all variables documented
├── .env.local           # Local development profile
├── .env.dev-remote      # Remote recognition profile
├── .env.production      # Production profile
├── .env                 # Active environment (gitignored)
└── scripts/
    └── switch-env.sh    # Environment switcher script
```

---

## Feature Auto-Enabling

The plugin **automatically enables recognition features** when a recognition service URL is configured. No additional feature flags are required!

### What Gets Auto-Enabled

When `CAT_RECOGNITION_BASE_URL` is configured:

- ✅ **Workbench Recognition** - "Trigger Recognition" and "Re-run Recognition" buttons
- ✅ **Roster UI** - Roster management interface
- ✅ **Recognition REST API** - `/wp-json/context-alt-text/v1/recognition/*` endpoints
- ✅ **Observation Matching** - Automatic label propagation from roster entries

### How Auto-Enable Works

The plugin checks if a recognition service is configured by looking for:

1. **Environment variable**: `CAT_RECOGNITION_BASE_URL`
2. **OR WordPress database**: `cat_settings['recognition']['baseUrl']`

If either is set and non-empty, recognition features automatically enable.

### Manual Override (Optional)

**Disable even when configured:**

```php
// In wp-config.php
define('CAT_FEATURE_WORKBENCH_RECOGNITION', false);
define('CAT_FEATURE_ROSTER_UI_ENABLED', false);
```

**Force enable without service URL:**

```php
// In wp-config.php
define('CAT_FEATURE_WORKBENCH_RECOGNITION', true);
define('CAT_FEATURE_ROSTER_UI_ENABLED', true);
```

**Via filter hooks:**

```php
// In functions.php or plugin
add_filter('cat_feature_workbench_recognition', '__return_false'); // Force disable
add_filter('cat_feature_roster_ui_enabled', '__return_true');      // Force enable
```

### Why Auto-Enable?

- 🎯 **Zero configuration** after setting up the recognition service
- 🚀 **Instant feature discovery** - no hidden toggles to find
- 🔒 **Safe by default** - features only appear when service is available
- 🧪 **Testable** - can override for testing UI without running the service

---

## Manual Configuration

If you need a custom configuration that doesn't fit the profiles:

```bash
cp .env.template .env
# Edit .env with your custom settings
```

### Using WordPress Admin UI

1. Go to **WordPress Admin → Context Alt Text → Settings**
2. Configure recognition service URL
3. Set timeout (optional, default: 30000ms)
4. Test connection

**Note:** Environment variables take precedence over admin settings.

### Using wp-config.php (Legacy)

Add to your `wp-config.php` (anywhere before "stop editing"):

```php
// Context Alt Text Recognition Service
define('CAT_RECOGNITION_BASE_URL', 'http://localhost:7860');
define('CAT_RECOGNITION_TIMEOUT_MS', '30000');
```

**Note:** Environment variables and admin settings take precedence over constants.

### Using WP-CLI

```bash
# Configure the recognition service URL
wp option update cat_settings \
  '{"recognition":{"baseUrl":"http://localhost:7860","timeoutMs":30000}}' \
  --format=json

# Verify
wp option get cat_settings --format=json

# Test connection
wp cat-recognition health
```

---

## CI/CD Integration

### Docker

```dockerfile
# Dockerfile
FROM wordpress:latest

# Copy plugin
COPY apps/wp-context-alt-text /var/www/html/wp-content/plugins/context-alt-text

# Set environment variables (overrides .env)
ENV CAT_RECOGNITION_BASE_URL=https://recognition.production.com
ENV CAT_RECOGNITION_TIMEOUT_MS=30000
ENV CAT_RECOGNITION_API_KEY=your-production-api-key
```

### Kubernetes

```yaml
# ConfigMap
apiVersion: v1
kind: ConfigMap
metadata:
    name: context-alt-text-config
data:
    CAT_RECOGNITION_BASE_URL: "https://recognition.production.com"
    CAT_RECOGNITION_TIMEOUT_MS: "30000"

---
# Secret
apiVersion: v1
kind: Secret
metadata:
    name: context-alt-text-secrets
type: Opaque
stringData:
    CAT_RECOGNITION_API_KEY: "your-production-api-key"
```

### GitHub Actions

```yaml
# .github/workflows/deploy.yml
- name: Configure Production Environment
  run: |
      cd apps/wp-context-alt-text
      ./scripts/switch-env.sh production

- name: Override with Secrets
  env:
      CAT_RECOGNITION_API_KEY: ${{ secrets.RECOGNITION_API_KEY }}
  run: |
      echo "CAT_RECOGNITION_API_KEY=${CAT_RECOGNITION_API_KEY}" >> .env
```

---

## Troubleshooting

### "Recognition service not connected"

1. **Check which profile is active:**

    ```bash
    cat .env | grep CAT_RECOGNITION_BASE_URL
    ```

2. **Verify the service is accessible:**

    ```bash
    # For local:
    curl http://localhost:7860/api/v0/health

    # For remote:
    curl https://your-username-recognition.hf.space/api/v0/health
    ```

3. **Check WordPress admin:**
    - Go to **Context Alt Text → Settings**
    - Look for the service status indicator

4. **Use WP-CLI:**
    ```bash
    wp cat-recognition health
    ```

### "Trigger Recognition" button still disabled

1. **Check configuration:**

    ```bash
    wp option get cat_settings --format=json
    ```

    Should return: `{"recognition":{"baseUrl":"http://localhost:7860","timeoutMs":30000,"enabled":true}}`

2. **Clear browser cache:**
    - Hard refresh the Workbench page (Cmd+Shift+R or Ctrl+Shift+R)

3. **Verify recognition service is running:**

    ```bash
    curl http://localhost:7860/api/v0/health
    ```

    Should return: `{"status":"ok"}`

4. **Check feature flag override:**
    ```bash
    # Look for CAT_FEATURE_WORKBENCH_RECOGNITION in wp-config.php
    grep CAT_FEATURE_WORKBENCH_RECOGNITION wp-config.php
    ```
    If it's set to `false`, either remove it or set to `true`

### "Vite dev server not working"

1. **Ensure Vite is running:**

    ```bash
    npm run dev
    ```

2. **Check the dev server URL:**

    ```bash
    cat .env | grep CAT_VITE_DEV_SERVER
    ```

3. **Verify LocalWP environment type:**
    - Add to `wp-config.php`: `define('WP_ENVIRONMENT_TYPE', 'development');`

### "Switch script not working"

1. **Make script executable:**

    ```bash
    chmod +x scripts/switch-env.sh
    ```

2. **Run with explicit profile:**

    ```bash
    ./scripts/switch-env.sh local
    ```

3. **Check profile file exists:**
    ```bash
    ls -la .env.*
    ```

### Recognition runs but fails

1. **Increase timeout for first run:**

    ```bash
    wp option patch update cat_settings recognition timeoutMs 60000
    ```

2. **Check WordPress debug log:**

    ```bash
    tail -f wp-content/uploads/cat-logs/debug-$(date +%Y-%m-%d).log
    ```

3. **Check recognition service logs:**
   Look at the terminal where the service is running

4. **Test with WP-CLI:**

    ```bash
    # Upload test image
    wp media import /path/to/image.jpg --post_id=0

    # Run recognition (use attachment ID from previous command)
    wp cat-recognition analyze 123
    ```

---

## Testing

### Unit Tests

Test the configuration system:

```bash
# Test RecognitionSettings class (environment variable priority, fallbacks, validation)
composer test -- tests/Recognition/RecognitionSettingsTest.php

# Test full configuration integration (env loading, priority order, edge cases)
composer test -- tests/Integration/ConfigurationIntegrationTest.php

# Test feature flag auto-enable behavior
composer test -- tests/Support/FeatureFlagsTest.php

# Run all tests
composer test
```

**Test Coverage:**

- ✅ Environment variable priority over database settings (32 tests)
- ✅ Database fallback when env vars not set (12 tests)
- ✅ URL validation and normalization
- ✅ Timeout bounds checking
- ✅ Empty/invalid value handling
- ✅ `.env` file loading integration
- ✅ Feature flag auto-enable behavior (14 tests)

### Manual Testing

```bash
# 1. Health check
wp cat-recognition health

# 2. Upload test image
wp media import /path/to/image.jpg --post_id=0

# 3. Run recognition on it (use attachment ID from step 2)
wp cat-recognition analyze 123

# 4. Check roster status
wp cat-roster status

# 5. Sync roster from remote
wp cat-roster sync
```

---

## Best Practices

### Development

✅ **DO:**

- Use `local` profile for full-stack development
- Use `dev-remote` profile when recognition service is stable
- Commit `.env.template`, `.env.local`, `.env.dev-remote`, `.env.production`
- Add custom variables to all profile files
- Test with production profile locally before deploying

❌ **DON'T:**

- Commit `.env` (it's gitignored - contains active environment)
- Commit `.env.*.local` (user-specific overrides)
- Hard-code API keys in profile files (use environment variables or secrets)

### Production

✅ **DO:**

- Use environment variables in Docker/K8s (overrides `.env`)
- Set API keys via secrets management (not in `.env` files)
- Test with production profile locally before deploying
- Monitor recognition service health endpoints
- Set appropriate timeouts for your infrastructure

❌ **DON'T:**

- Deploy with `local` or `dev-remote` profiles active
- Use development timeouts in production
- Expose API keys in version control
- Skip testing the production profile locally

---

## Architecture

The configuration system is implemented across several classes:

### `src/Recognition/RecognitionSettings.php`

Centralized configuration management with environment-first priority:

```php
public function getBaseUrl(): string
{
    // Check environment variable first
    $url = $this->getEnv('CAT_RECOGNITION_BASE_URL');

    // Fall back to database settings
    if (empty($url)) {
        $settings = $this->settingsRepository->getRecognitionSettings();
        $url = $settings['baseUrl'] ?? '';
    }

    return $url;
}
```

### `src/Support/FeatureFlags.php`

Auto-enable logic when recognition service is configured:

```php
public function workbenchRecognitionEnabled(): bool
{
    // Check constant first
    $enabled = $this->boolFromConstant('CAT_FEATURE_WORKBENCH_RECOGNITION', false);

    // Auto-enable if recognition service is configured
    if (!$enabled && $this->isRecognitionServiceConfigured()) {
        $enabled = true;
    }

    // Allow filters to override
    return (bool) apply_filters('cat_feature_workbench_recognition', $enabled);
}
```

This ensures:

- Constants take precedence (explicit override)
- Auto-enable when service is configured (convenience)
- Filters can still override (flexibility)

---

## Support

For issues or questions:

- Check the [Troubleshooting](#troubleshooting) section
- Review the [main README](../README.md)
- Check WordPress logs: `/wp-content/uploads/cat-logs/debug-YYYY-MM-DD.log`
- Open an issue in the repository
