# Local WordPress ↔ Recognition Service Integration Guide

**Purpose:** Enable end-to-end testing of the Context Alt Text plugin with the recognition service running locally in the same monorepo.

**Last Updated:** October 11, 2025

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                      Local Development Setup                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  WordPress (localhost:8080)                                      │
│  └─> Context Alt Text Plugin                                    │
│      └─> RecognitionClient                                      │
│          └─> HTTP Request                                        │
│              │                                                    │
│              └──────────────────> Recognition Service            │
│                                   (localhost:7860)               │
│                                   └─> FastAPI                    │
│                                       ├─> /api/v0/health         │
│                                       ├─> /api/v0/analyze-scene │
│                                       ├─> /api/v0/embeddings    │
│                                       └─> /api/v0/roster        │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Prerequisites

### 1. Recognition Service Running ✅

The recognition service should already be running on port 7860:

```bash
cd apps/recognition-service
./scripts/start_recognition_local.sh start
```

Verify it's running:
```bash
curl -s http://localhost:7860/api/v0/health | jq .
# Should return: {"status": "ok"}
```

### 2. WordPress Environment

You'll need a local WordPress installation. Options:

**Option A: Local by Flywheel** (Recommended)
- Install [Local](https://localwp.com/)
- Create a new site (PHP 8.0+, WordPress 6.0+)
- Note the site URL (e.g., `http://context-alt-text.local`)

**Option B: Docker Compose**
- Use `wordpress:latest` image with MySQL
- Map port 8080 to host

**Option C: Existing MAMP/XAMPP/Valet**
- Use your existing local WordPress setup

---

## Step 1: Configure the WordPress Plugin

### A. Link the Plugin to WordPress

Create a symlink from your WordPress plugins directory to the monorepo:

```bash
# Example with Local by Flywheel
cd ~/Local\ Sites/context-alt-text/app/public/wp-content/plugins/
ln -s /Users/daniel/Development/context-alt-text-monorepo/apps/wp-context-alt-text context-alt-text

# Or copy the plugin
# cp -r /Users/daniel/Development/context-alt-text-monorepo/apps/wp-context-alt-text ~/Local\ Sites/context-alt-text/app/public/wp-content/plugins/context-alt-text
```

### B. Set Environment Variables

Create a `.env` file in the WordPress root OR use `wp-config.php`:

**Method 1: Environment Variables (wp-config.php)**

Add to `wp-config.php` (before "That's all, stop editing!"):

```php
<?php
// Context Alt Text - Recognition Service Configuration
define('CAT_RECOGNITION_BASE_URL', 'http://localhost:7860');
define('CAT_RECOGNITION_TIMEOUT_MS', '30000'); // 30 seconds for first run
define('WP_DEBUG', true);
define('WP_DEBUG_LOG', true);
define('WP_DEBUG_DISPLAY', false);
```

**Method 2: Plugin Settings (via WordPress Admin)**

Once activated, go to:
1. WordPress Admin → Context Alt Text → Settings
2. Set "Recognition Service URL": `http://localhost:7860`
3. Set "Timeout (ms)": `30000`
4. Save Changes

### C. Activate the Plugin

```bash
# Via WP-CLI (if available)
wp plugin activate context-alt-text

# Or via WordPress Admin:
# Dashboard → Plugins → Activate "Context Alt Text"
```

---

## Step 2: Verify Plugin Configuration

### A. Check Recognition Settings

```bash
# Via WP-CLI
wp option get context_alt_text_recognition_settings --format=json

# Expected output:
# {
#   "base_url": "http://localhost:7860",
#   "timeout_ms": "30000"
# }
```

### B. Test Recognition Service Connectivity

Use the plugin's health check WP-CLI command:

```bash
wp cat-recognition health

# Expected output:
# Recognition service health check:
# URL: http://localhost:7860
# Status: OK
# Service Info: {...}
```

If this fails, check:
1. Recognition service is running (`lsof -i :7860`)
2. URL is correct in settings
3. No firewall blocking localhost connections

---

## Step 3: End-to-End Testing Flow

### Test 1: Upload an Image with a Face

```bash
# 1. Upload test image via WP-CLI
wp media import /path/to/image-with-face.jpg --post_id=0 --title="Test Face"

# Note the attachment ID from output (e.g., 123)

# 2. Trigger recognition
wp cat-recognition analyze 123

# Expected: Recognition job created, faces detected, observations stored
```

### Test 2: Via WordPress Admin UI

1. **Upload Image:**
   - Go to Media → Add New
   - Upload image with faces
   - Note the attachment ID

2. **Trigger Recognition:**
   - Go to Context Alt Text → Workbench
   - Select the uploaded image
   - Click "Run Recognition"
   - Wait for processing (watch browser console)

3. **Verify Results:**
   - Check recognition panel for detected faces
   - Verify observations are displayed
   - Check browser console for API calls

### Test 3: Roster Sync

```bash
# 1. Check roster status
wp cat-roster status

# Expected: Shows remote roster entries (25 mock entries)

# 2. Sync roster from remote
wp cat-roster sync

# Expected: Syncs roster entries from recognition service

# 3. Verify roster entries
wp option get cat_roster_entries --format=json
```

### Test 4: Create Roster Entry

1. **Via Admin UI:**
   - Go to Context Alt Text → Roster
   - Click "Add New Entry"
   - Fill in name and type
   - Upload avatar image
   - Save

2. **Verify Sync:**
   - Check the entry has a "SYNCED" badge
   - Verify `remote_id` is populated
   - Check recognition service: `curl http://localhost:7860/api/v0/roster | jq '.entries | map(select(.name=="test_name"))'`

---

## Step 4: Programmatic End-to-End Tests

### A. PHPUnit Integration Tests

Create an integration test file:

```php
<?php
// tests/Integration/RecognitionServiceIntegrationTest.php

declare(strict_types=1);

namespace ContextAltText\Tests\Integration;

use ContextAltText\Recognition\RecognitionClient;
use ContextAltText\Recognition\RecognitionSettings;
use PHPUnit\Framework\TestCase;

/**
 * @group integration
 * @group requires-recognition-service
 */
class RecognitionServiceIntegrationTest extends TestCase
{
    private RecognitionClient $client;

    protected function setUp(): void
    {
        parent::setUp();
        
        if (!$this->isRecognitionServiceAvailable()) {
            $this->markTestSkipped('Recognition service not running on localhost:7860');
        }

        $settings = new RecognitionSettings();
        $this->client = new RecognitionClient($settings);
    }

    private function isRecognitionServiceAvailable(): bool
    {
        $ch = curl_init('http://localhost:7860/api/v0/health');
        curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
        curl_setopt($ch, CURLOPT_TIMEOUT, 2);
        $response = curl_exec($ch);
        $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
        curl_close($ch);

        return $httpCode === 200;
    }

    public function test_health_check_returns_ok(): void
    {
        $response = $this->client->health();
        
        $this->assertIsArray($response);
        $this->assertArrayHasKey('status', $response);
        $this->assertEquals('ok', $response['status']);
    }

    public function test_service_info_returns_metadata(): void
    {
        $response = $this->client->getServiceInfo();
        
        $this->assertIsArray($response);
        $this->assertArrayHasKey('model', $response);
        $this->assertArrayHasKey('recognition', $response);
        $this->assertEquals('buffalo_l', $response['model']['name']);
    }

    public function test_analyze_scene_with_real_image(): void
    {
        // Use a 1x1 pixel test image
        $imageData = base64_decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8Xw8AAnEB7SBSYQAAAABJRU5ErkJggg==');
        $attachmentId = $this->createTestAttachment($imageData);

        try {
            $result = $this->client->analyzeScene([$attachmentId]);
            
            $this->assertIsArray($result);
            $this->assertArrayHasKey('results', $result);
            $this->assertCount(1, $result['results']);
        } finally {
            wp_delete_attachment($attachmentId, true);
        }
    }

    public function test_roster_roundtrip(): void
    {
        // This would test creating a roster entry locally,
        // syncing to remote, and verifying it appears in remote roster
        $this->markTestIncomplete('Roster roundtrip test to be implemented');
    }

    private function createTestAttachment(string $imageData): int
    {
        $upload = wp_upload_bits('test-image.png', null, $imageData);
        
        $attachmentId = wp_insert_attachment([
            'post_title' => 'Test Image',
            'post_content' => '',
            'post_status' => 'inherit',
            'post_mime_type' => 'image/png',
        ], $upload['file']);

        require_once ABSPATH . 'wp-admin/includes/image.php';
        $attachData = wp_generate_attachment_metadata($attachmentId, $upload['file']);
        wp_update_attachment_metadata($attachmentId, $attachData);

        return $attachmentId;
    }
}
```

**Run the integration tests:**

```bash
cd apps/wp-context-alt-text

# Run only integration tests
composer test -- --group integration

# Or with explicit flag
CAT_RECOGNITION_BASE_URL=http://localhost:7860 composer test -- --group integration
```

### B. WP-CLI Smoke Test Script

Create a shell script for automated testing:

```bash
#!/bin/bash
# scripts/smoke-test-local.sh

set -e

echo "🧪 Starting Context Alt Text Local Integration Smoke Tests"
echo "============================================================"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check recognition service
echo -e "\n${YELLOW}1. Checking Recognition Service...${NC}"
if curl -s http://localhost:7860/api/v0/health | grep -q '"status":"ok"'; then
    echo -e "${GREEN}✓ Recognition service is running${NC}"
else
    echo -e "${RED}✗ Recognition service is not responding${NC}"
    exit 1
fi

# Check plugin activation
echo -e "\n${YELLOW}2. Checking Plugin Activation...${NC}"
if wp plugin is-active context-alt-text; then
    echo -e "${GREEN}✓ Plugin is activated${NC}"
else
    echo -e "${RED}✗ Plugin is not activated${NC}"
    exit 1
fi

# Check recognition settings
echo -e "\n${YELLOW}3. Checking Recognition Settings...${NC}"
BASE_URL=$(wp option get context_alt_text_recognition_settings --format=json | jq -r '.base_url' 2>/dev/null || echo "")
if [ "$BASE_URL" = "http://localhost:7860" ]; then
    echo -e "${GREEN}✓ Recognition service URL configured correctly${NC}"
else
    echo -e "${YELLOW}⚠ Recognition service URL not configured. Setting it now...${NC}"
    wp option update context_alt_text_recognition_settings '{"base_url":"http://localhost:7860","timeout_ms":"30000"}' --format=json
    echo -e "${GREEN}✓ Configuration updated${NC}"
fi

# Test recognition health check
echo -e "\n${YELLOW}4. Testing Recognition Health Check...${NC}"
if wp cat-recognition health 2>&1 | grep -q "OK\|ok"; then
    echo -e "${GREEN}✓ Recognition health check passed${NC}"
else
    echo -e "${RED}✗ Recognition health check failed${NC}"
    exit 1
fi

# Test roster status
echo -e "\n${YELLOW}5. Testing Roster Status...${NC}"
if wp cat-roster status 2>&1; then
    echo -e "${GREEN}✓ Roster status command works${NC}"
else
    echo -e "${RED}✗ Roster status command failed${NC}"
    exit 1
fi

# Create test attachment
echo -e "\n${YELLOW}6. Creating Test Image...${NC}"
# Create a simple test image file
TEST_IMAGE="/tmp/cat-test-image.png"
echo "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8Xw8AAnEB7SBSYQAAAABJRU5ErkJggg==" | base64 -d > "$TEST_IMAGE"
ATTACHMENT_ID=$(wp media import "$TEST_IMAGE" --porcelain)
echo -e "${GREEN}✓ Created test attachment ID: $ATTACHMENT_ID${NC}"

# Test recognition on image
echo -e "\n${YELLOW}7. Testing Recognition on Image...${NC}"
if wp cat-recognition analyze "$ATTACHMENT_ID" 2>&1; then
    echo -e "${GREEN}✓ Recognition analysis completed${NC}"
else
    echo -e "${YELLOW}⚠ Recognition analysis may have issues (check output above)${NC}"
fi

# Cleanup
echo -e "\n${YELLOW}8. Cleaning Up...${NC}"
wp post delete "$ATTACHMENT_ID" --force
rm -f "$TEST_IMAGE"
echo -e "${GREEN}✓ Test attachment deleted${NC}"

echo -e "\n${GREEN}============================================================${NC}"
echo -e "${GREEN}✓ All smoke tests passed!${NC}"
echo -e "${GREEN}============================================================${NC}"
```

**Make it executable and run:**

```bash
chmod +x scripts/smoke-test-local.sh
./scripts/smoke-test-local.sh
```

### C. Frontend E2E Tests (Playwright/Cypress)

Create an E2E test for the browser UI:

```typescript
// tests/e2e/recognition-workflow.spec.ts
import { test, expect } from '@playwright/test';

test.describe('Recognition Workflow', () => {
  test.beforeEach(async ({ page }) => {
    // Login to WordPress
    await page.goto('http://localhost:8080/wp-admin');
    await page.fill('#user_login', 'admin');
    await page.fill('#user_pass', 'password');
    await page.click('#wp-submit');
  });

  test('should trigger recognition and display results', async ({ page }) => {
    // Navigate to Workbench
    await page.goto('http://localhost:8080/wp-admin/admin.php?page=context-alt-text');
    await page.click('a:has-text("Workbench")');

    // Wait for workbench to load
    await page.waitForSelector('[data-testid="workbench-container"]');

    // Select first image
    await page.click('[data-testid="media-item"]:first-child input[type="checkbox"]');

    // Click "Run Recognition" button
    await page.click('button:has-text("Run Recognition")');

    // Wait for recognition to complete
    await page.waitForSelector('[data-testid="recognition-complete"]', { timeout: 60000 });

    // Verify results displayed
    const results = await page.locator('[data-testid="recognition-result"]');
    await expect(results).toBeVisible();
  });

  test('should sync roster from remote service', async ({ page }) => {
    // Navigate to Roster
    await page.goto('http://localhost:8080/wp-admin/admin.php?page=context-alt-text-roster');

    // Click sync button
    await page.click('button:has-text("Sync from Remote")');

    // Wait for sync to complete
    await page.waitForSelector('[data-testid="sync-complete"]');

    // Verify roster entries loaded
    const entries = await page.locator('[data-testid="roster-entry"]');
    await expect(entries).toHaveCountGreaterThan(0);
  });
});
```

---

## Step 5: Debugging & Troubleshooting

### Enable Debug Logging

**WordPress Debug Log:**

```php
// wp-config.php
define('WP_DEBUG', true);
define('WP_DEBUG_LOG', true);
define('WP_DEBUG_DISPLAY', false);
```

View logs:
```bash
tail -f wp-content/debug.log
```

**Recognition Service Logs:**

The service logs are output to the terminal where it's running. Look for:
```
2025-10-11 18:48:41,837 - app - INFO - Application fully initialized
```

### Common Issues

**Issue 1: "Recognition service not configured"**
```bash
# Solution: Set the base URL
wp option update context_alt_text_recognition_settings '{"base_url":"http://localhost:7860","timeout_ms":"30000"}' --format=json
```

**Issue 2: "Connection refused" errors**
```bash
# Verify service is running
lsof -i :7860
curl http://localhost:7860/api/v0/health

# Restart if needed
cd apps/recognition-service
./scripts/start_recognition_local.sh stop
./scripts/start_recognition_local.sh start
```

**Issue 3: "Timeout" errors**
```bash
# Increase timeout for first run (model downloads)
wp option patch update context_alt_text_recognition_settings timeout_ms 60000
```

**Issue 4: CORS errors (if testing from Vite dev server)**
```bash
# The recognition service needs CORS headers for localhost:5173
# Check api/routes/main.py for CORS middleware
```

---

## Step 6: Continuous Integration

### GitHub Actions Workflow

Create `.github/workflows/local-integration-test.yml`:

```yaml
name: Local Integration Tests

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  integration-test:
    runs-on: ubuntu-latest
    
    services:
      mysql:
        image: mysql:8.0
        env:
          MYSQL_ROOT_PASSWORD: password
          MYSQL_DATABASE: wordpress_test
        ports:
          - 3306:3306
        options: --health-cmd="mysqladmin ping" --health-interval=10s --health-timeout=5s --health-retries=3

    steps:
      - uses: actions/checkout@v3

      - name: Setup Python 3.10
        uses: actions/setup-python@v4
        with:
          python-version: '3.10'

      - name: Setup PHP 8.1
        uses: shivammathur/setup-php@v2
        with:
          php-version: '8.1'
          extensions: mysqli, gd, zip
          tools: composer, wp-cli

      - name: Start Recognition Service
        run: |
          cd apps/recognition-service
          pip install -r requirements_local.txt
          uvicorn app:app --host 127.0.0.1 --port 7860 &
          sleep 10
          curl http://127.0.0.1:7860/api/v0/health

      - name: Setup WordPress
        run: |
          wp core download --path=/tmp/wordpress
          wp config create --path=/tmp/wordpress --dbname=wordpress_test --dbuser=root --dbpass=password --dbhost=127.0.0.1
          wp core install --path=/tmp/wordpress --url=http://localhost:8080 --title="Test Site" --admin_user=admin --admin_password=password --admin_email=test@example.com

      - name: Install Plugin
        run: |
          cd apps/wp-context-alt-text
          composer install
          ln -s $(pwd) /tmp/wordpress/wp-content/plugins/context-alt-text
          wp plugin activate context-alt-text --path=/tmp/wordpress

      - name: Configure Recognition Service
        run: |
          wp option update context_alt_text_recognition_settings '{"base_url":"http://127.0.0.1:7860","timeout_ms":"30000"}' --format=json --path=/tmp/wordpress

      - name: Run Integration Tests
        run: |
          cd apps/wp-context-alt-text
          composer test -- --group integration

      - name: Run Smoke Tests
        run: |
          cd apps/wp-context-alt-text
          ./scripts/smoke-test-local.sh
```

---

## Quick Reference

### Service Status Checks

```bash
# Recognition service
curl http://localhost:7860/api/v0/health

# WordPress plugin
wp plugin list | grep context-alt-text

# Recognition settings
wp option get context_alt_text_recognition_settings --format=json
```

### Reset Everything

```bash
# Stop recognition service
cd apps/recognition-service
./scripts/start_recognition_local.sh stop

# Deactivate plugin
wp plugin deactivate context-alt-text

# Clear plugin options
wp option delete context_alt_text_recognition_settings
wp option delete cat_roster_entries
wp option delete cat_roster_sync_state

# Start fresh
wp plugin activate context-alt-text
wp option update context_alt_text_recognition_settings '{"base_url":"http://localhost:7860","timeout_ms":"30000"}' --format=json
cd apps/recognition-service
./scripts/start_recognition_local.sh start
```

---

## Next Steps

Once local integration is working:

1. ✅ **Validate all endpoints** (COMPLETE)
2. ✅ **Configure WordPress plugin** (THIS GUIDE)
3. 📋 **Run smoke tests**
4. 📋 **Verify roster sync**
5. 📋 **Test with real images**
6. 📋 **Deploy to staging/production**

---

**Questions or Issues?**
- Check `debug.log` in WordPress
- Check recognition service terminal output
- Review validation report: `docs/architecture/rules/recognition_service_validation_2025-10-11.md`
