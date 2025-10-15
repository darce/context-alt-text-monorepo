# Configuring Recognition Service

The Context Alt Text plugin will **automatically enable recognition features** when a recognition service URL is configured. No additional feature flags are required.

## Quick Setup

### Option 1: Using the Configuration Script (Recommended)

```bash
# From the plugin directory
cd apps/wp-context-alt-text
chmod +x scripts/configure-recognition.sh
./scripts/configure-recognition.sh
```

This will:

- Check if the recognition service is running
- Configure the service URL in WordPress
- Verify the configuration
- Auto-enable recognition features

### Option 2: Using WP-CLI Directly

```bash
# Configure the recognition service URL
wp option update context_alt_text_recognition_settings \
  '{"base_url":"http://localhost:7860","timeout_ms":"30000"}' \
  --format=json

# Verify
wp option get context_alt_text_recognition_settings --format=json
```

### Option 3: Via wp-config.php (Environment Variable)

Add to your `wp-config.php` (anywhere before "stop editing"):

Add to your `wp-config.php` (anywhere before "stop editing"):

```php
// Context Alt Text Recognition Service
define('CAT_RECOGNITION_BASE_URL', 'http://localhost:7860');
define('CAT_RECOGNITION_TIMEOUT_MS', '30000');
```

## How Auto-Enable Works

The plugin automatically enables recognition features when:

1. **Recognition Service URL is configured** via:
   - WordPress option: `context_alt_text_recognition_settings['base_url']`
   - OR environment variable: `CAT_RECOGNITION_BASE_URL`

2. **The URL is valid**:
   - Non-empty string
   - Valid URL format
   - Accessible (though plugin will enable even if temporarily unreachable)

### What Gets Auto-Enabled

When a recognition service URL is configured:

- ✅ **Workbench Recognition** - "Trigger Recognition" button in Workbench
- ✅ **Roster UI** - Roster management interface
- ✅ **Recognition REST API** - `/wp-json/context-alt-text/v1/recognition/*` endpoints

### Manual Control

You can still override the auto-enable behavior:

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

## Verification

Check if recognition is enabled:

```bash
# Via WP-CLI
wp option get context_alt_text_recognition_settings --format=json

# Test the service
wp cat-recognition health

# Expected output: Recognition service health check: OK
```

## Troubleshooting

### "Trigger Recognition" button still disabled

1. **Check configuration:**

   ```bash
   wp option get context_alt_text_recognition_settings --format=json
   ```
   
   Should return: `{"base_url":"http://localhost:7860","timeout_ms":"30000"}`

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

### Recognition service not accessible

If you see errors like "Connection refused":

1. **Start the recognition service:**

   ```bash
   cd apps/recognition-service
   ./scripts/start_recognition_local.sh start
   ```

2. **Verify it's running:**

   ```bash
   lsof -i :7860
   curl http://localhost:7860/api/v0/health
   ```

3. **Check the URL in WordPress:**

   ```bash
   wp option get context_alt_text_recognition_settings --format=json
   ```

4. **Rewriting media URLs (optional):**

   If the recognition service runs in Docker or on another host, set a base URL override so media URLs resolve correctly:

   ```bash
   export CAT_MEDIA_BASE_URL=http://host.docker.internal:10008
   ./scripts/start_recognition_local.sh start
   ```

   The service will rewrite incoming image URLs to use the specified base before downloading.

### Recognition runs but fails

1. **Increase timeout for first run:**

   ```bash
   wp option patch update context_alt_text_recognition_settings timeout_ms 60000
   ```

2. **Check WordPress debug log:**

   ```bash
   tail -f wp-content/debug.log
   ```

3. **Check recognition service logs:**
   Look at the terminal where the service is running

## Architecture

The auto-enable logic is implemented in `src/Support/FeatureFlags.php`:

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

## Testing

```bash

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

## For Developers

When developing locally:

1. **Start recognition service:**

   ```bash
   cd apps/recognition-service
   ./scripts/start_recognition_local.sh start
   ```

2. **Configure WordPress:**

   ```bash
   cd apps/wp-context-alt-text
   ./scripts/configure-recognition.sh
   ```

3. **That's it!** Recognition features are now enabled automatically.

No need to modify `wp-config.php` or set environment variables outside the plugin - everything is self-contained.

## Production Deployment

For production:

1. **Deploy recognition service** to Hugging Face Space or your server

2. **Configure WordPress** with production URL:

   ```bash
   wp option update context_alt_text_recognition_settings \
     '{"base_url":"https://your-recognition-service.com","timeout_ms":"30000"}' \
     --format=json
   ```

3. **Recognition features enable automatically** - no additional configuration needed!

## Summary

✅ **No feature flags to manage**  
✅ **Auto-enables when service URL is set**  
✅ **Self-contained within plugin**  
✅ **Can still be overridden if needed**  
✅ **Works in dev and production**
