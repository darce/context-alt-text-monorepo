# Troubleshooting Guide

Common issues and solutions for the Context Alt Text plugin.

## Table of Contents

- [Environment & Configuration](#environment--configuration)
- [Recognition Service](#recognition-service)
- [Development](#development)
- [Frontend (Vite/React)](#frontend-vitereact)
- [Testing](#testing)
- [Performance](#performance)
- [Debugging](#debugging)

---

## Environment & Configuration

### "Recognition service not connected"

**Symptoms:**

- Recognition buttons disabled in Workbench
- Settings page shows "Disconnected" status
- Error: "Recognition service unavailable"

**Solutions:**

1. **Check active environment profile:**

    ```bash
    cat .env | grep CAT_RECOGNITION_BASE_URL
    ```

2. **Verify service is running:**

    ```bash
    # For local:
    curl http://localhost:7860/api/v0/health

    # For remote:
    curl https://your-username-recognition.hf.space/api/v0/health
    ```

    Expected response: `{"status":"ok"}`

3. **Test from WordPress:**

    ```bash
    wp cat-recognition health
    ```

4. **Check WordPress admin:**
    - Go to **Context Alt Text → Settings**
    - Look for service status indicator

5. **Restart recognition service:**
    ```bash
    cd apps/recognition-service
    ./scripts/start_recognition_local.sh restart
    ```

---

### "Switch script not working"

**Symptoms:**

- `./scripts/switch-env.sh` fails with "Permission denied"
- Script not found error

**Solutions:**

1. **Make script executable:**

    ```bash
    chmod +x scripts/switch-env.sh
    ```

2. **Run from correct directory:**

    ```bash
    cd apps/wp-context-alt-text
    ./scripts/switch-env.sh local
    ```

3. **Check profile file exists:**

    ```bash
    ls -la .env.*
    # Should show: .env.local, .env.dev-remote, .env.production
    ```

4. **Manually copy profile:**
    ```bash
    cp .env.local .env
    ```

---

### "Which environment am I using?"

**Check active configuration:**

```bash
# View all active environment variables
cat .env

# Check specific variable
cat .env | grep CAT_RECOGNITION_BASE_URL
```

**Verify what WordPress sees:**

```bash
# Check settings in database
wp option get cat_settings --format=json

# Check what plugin resolves (environment variables take precedence)
wp eval 'echo (new \ContextAltText\Recognition\RecognitionSettings())->getBaseUrl();'
```

---

### "Changes not taking effect"

**After editing `.env.<profile>`:**

1. **Re-run the switch script:**

    ```bash
    ./scripts/switch-env.sh <profile>
    ```

2. **Verify `.env` was updated:**

    ```bash
    cat .env | grep CAT_RECOGNITION_BASE_URL
    ```

3. **Clear WordPress caches:**
    - Clear object cache (if using persistent cache)
    - Clear page cache (if using caching plugin)
    - Restart PHP-FPM (if necessary)

4. **Hard refresh browser:**
    - Chrome/Edge: `Ctrl+Shift+R` (Windows) or `Cmd+Shift+R` (Mac)
    - Firefox: `Ctrl+Shift+F5` or `Cmd+Shift+R`

---

## Recognition Service

### "Trigger Recognition" button disabled

**Symptoms:**

- Button appears grayed out in Workbench
- No recognition options available

**Solutions:**

1. **Check if service is configured:**

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

4. **Check feature flag override:**

    ```bash
    # Look for CAT_FEATURE_WORKBENCH_RECOGNITION in wp-config.php
    grep CAT_FEATURE_WORKBENCH_RECOGNITION wp-config.php
    ```

    If set to `false`, remove it or set to `true`

5. **Check user permissions:**
    - Ensure you're logged in as an admin
    - Verify user has `manage_options` capability

---

### "Recognition runs but fails"

**Symptoms:**

- Recognition starts but times out
- Error: "Recognition request timed out"
- No observations returned

**Solutions:**

1. **Increase timeout for first run:**

    ```bash
    # Via WP-CLI
    wp option patch update cat_settings recognition timeoutMs 60000

    # Or edit .env
    echo "CAT_RECOGNITION_TIMEOUT_MS=60000" >> .env
    ```

2. **Check WordPress debug log:**

    ```bash
    tail -f wp-content/uploads/cat-logs/debug-$(date +%Y-%m-%d).log
    ```

3. **Check recognition service logs:**
    - Look at terminal where service is running
    - Check for memory issues, model loading errors

4. **Test with smaller image:**
    - Recognition is slower for large images
    - Try with image < 2MB first

5. **Verify image is accessible:**
    ```bash
    # From recognition service host
    curl -I http://localhost:10008/wp-content/uploads/2025/10/test.jpg
    ```

---

### "Recognition service times out on first request"

**Cause:** First request loads AI model into memory (can take 30-60 seconds).

**Solutions:**

1. **Increase timeout temporarily:**

    ```bash
    ./scripts/switch-env.sh local
    # Edit .env
    CAT_RECOGNITION_TIMEOUT_MS=90000
    ```

2. **Warm up the service:**

    ```bash
    curl -X POST http://localhost:7860/api/v0/recognition/analyze \
      -H "Content-Type: application/json" \
      -d '{"imageUrl":"http://localhost:10008/wp-content/uploads/test.jpg"}'
    ```

3. **Use remote service:**
    - Switch to `dev-remote` profile (remote service is already warm)

---

### "Connection refused" error

**Symptoms:**

- Error: "Failed to connect to localhost port 7860"
- Recognition service not accessible

**Solutions:**

1. **Check if service is running:**

    ```bash
    lsof -i :7860
    # Should show Python process
    ```

2. **Start recognition service:**

    ```bash
    cd apps/recognition-service
    ./scripts/start_recognition_local.sh start
    ```

3. **Check service URL matches:**

    ```bash
    # What plugin is configured with
    cat .env | grep CAT_RECOGNITION_BASE_URL

    # What service is running on
    lsof -i :7860
    ```

4. **Test connectivity:**

    ```bash
    # From WordPress host
    curl http://localhost:7860/api/v0/health
    ```

5. **Check firewall/network:**
    - Ensure port 7860 is not blocked
    - If using Docker, check port mapping

---

## Development

### "Vite dev server not working"

**Symptoms:**

- Assets not loading in WordPress admin
- Console error: "Failed to load module"
- White screen or missing dashboard

**Solutions:**

1. **Ensure Vite is running:**

    ```bash
    npm run dev
    ```

    Should show: `Local: http://localhost:5173`

2. **Check dev server URL in .env:**

    ```bash
    cat .env | grep CAT_VITE_DEV_SERVER
    ```

    Should match Vite's URL (default: `http://localhost:5173`)

3. **Verify WP_ENVIRONMENT_TYPE:**

    ```bash
    grep WP_ENVIRONMENT_TYPE wp-config.php
    ```

    Should be: `define('WP_ENVIRONMENT_TYPE', 'development');`

4. **Check browser console:**
    - Open DevTools (F12)
    - Look for CORS errors or connection refused

5. **Restart Vite with clean cache:**
    ```bash
    rm -rf node_modules/.vite
    npm run dev
    ```

---

### "Hot Module Replacement (HMR) not working"

**Symptoms:**

- Changes to React components don't update in browser
- Need to manually refresh page

**Solutions:**

1. **Check Vite is in dev mode:**

    ```bash
    # Should be running from npm run dev, not npm run build
    ps aux | grep vite
    ```

2. **Verify file is being watched:**
    - Check Vite terminal for file change logs
    - Ensure file is inside `js/` directory

3. **Check browser console:**
    - Look for HMR connection errors
    - Verify WebSocket connection to Vite

4. **Restart Vite:**
    ```bash
    # Ctrl+C to stop
    npm run dev
    ```

---

### "PHP changes not reflecting"

**Symptoms:**

- Code changes in `src/` not visible
- Old behavior persists

**Solutions:**

1. **Clear PHP opcache:**

    ```bash
    # Via WP-CLI
    wp cache flush

    # Or restart PHP-FPM
    # (command varies by setup)
    ```

2. **Check autoloader:**

    ```bash
    composer dump-autoload
    ```

3. **Verify file is being loaded:**

    ```php
    // Add to file temporarily
    error_log('File loaded: ' . __FILE__);

    // Check logs
    tail -f wp-content/uploads/cat-logs/debug-$(date +%Y-%m-%d).log
    ```

4. **Clear object cache:**
    - If using Redis, Memcached, etc.
    - May need to restart cache service

---

## Frontend (Vite/React)

### "Build fails with type errors"

**Symptoms:**

- `npm run build` fails
- TypeScript compilation errors

**Solutions:**

1. **Run type check:**

    ```bash
    npm run type-check
    ```

2. **Fix type errors:**
    - Address reported TypeScript errors
    - Use `// @ts-ignore` only as last resort

3. **Update dependencies:**

    ```bash
    npm install
    npm update
    ```

4. **Clear TypeScript cache:**
    ```bash
    rm -rf node_modules/.cache
    npm run build
    ```

---

### "Storybook not loading"

**Symptoms:**

- `npm run storybook` fails
- Stories not visible
- Build errors

**Solutions:**

1. **Check for build errors:**
    - Look at terminal output for specific errors
    - Common: missing dependencies, syntax errors

2. **Reinstall dependencies:**

    ```bash
    rm -rf node_modules
    npm install
    npm run storybook
    ```

3. **Clear Storybook cache:**

    ```bash
    rm -rf node_modules/.cache/storybook
    npm run storybook
    ```

4. **Check story file syntax:**
    - Ensure stories follow Storybook 7+ format
    - Verify imports are correct

---

## Testing

### "PHP tests failing"

**Symptoms:**

- `composer test` reports failures
- Unexpected test behavior

**Solutions:**

1. **Run specific test:**

    ```bash
    composer test -- tests/Recognition/RecognitionSettingsTest.php
    ```

2. **Check test environment:**

    ```bash
    # Ensure test dependencies are installed
    composer install --dev
    ```

3. **Clear test caches:**

    ```bash
    rm -rf tests/tmp/*
    composer test
    ```

4. **Check for environment pollution:**
    - Ensure tests don't depend on real WordPress installation
    - Use mocks and stubs provided in `tests/stubs/`

---

### "JavaScript tests failing"

**Symptoms:**

- `npm run test` reports failures
- Tests work locally but fail in CI

**Solutions:**

1. **Run tests in watch mode:**

    ```bash
    npm run test:watch
    ```

2. **Check for environment differences:**
    - Node version mismatch
    - Missing environment variables

3. **Update test snapshots:**

    ```bash
    npm run test -- -u
    ```

4. **Clear Jest/Vitest cache:**
    ```bash
    npm run test -- --clear-cache
    ```

---

## Performance

### "Slow recognition processing"

**Symptoms:**

- Recognition takes minutes instead of seconds
- High CPU/memory usage

**Solutions:**

1. **Check image size:**

    ```bash
    ls -lh wp-content/uploads/2025/10/
    ```

    Large images (>5MB) take longer to process

2. **Check recognition service resources:**

    ```bash
    # CPU usage
    top -p $(pgrep -f recognition-service)

    # Memory usage
    free -h
    ```

3. **Optimize image:**
    - Resize before uploading
    - WordPress automatically creates thumbnails

4. **Use async processing:**
    - Recognition happens in background
    - Don't block on results

---

### "Slow WordPress admin"

**Symptoms:**

- Dashboard loads slowly
- High server load

**Solutions:**

1. **Check if Vite dev server is running:**
    - Dev server adds overhead
    - Use production build for testing: `npm run build`

2. **Profile with Query Monitor:**

    ```bash
    wp plugin install query-monitor --activate
    ```

3. **Check for N+1 queries:**
    - Look at database query log
    - Optimize with caching or batch queries

---

## Debugging

### Enable Debug Logging

**wp-config.php:**

```php
define('WP_DEBUG', true);
define('WP_DEBUG_LOG', true);
define('WP_DEBUG_DISPLAY', false);
```

**View logs:**

```bash
# WordPress debug log
tail -f wp-content/uploads/cat-logs/debug-$(date +%Y-%m-%d).log

# PHP error log (location varies)
tail -f /var/log/php-fpm/error.log

# Web server error log
tail -f /var/log/apache2/error.log  # Apache
tail -f /var/log/nginx/error.log    # Nginx
```

---

### Enable Verbose Logging

**Add to wp-config.php:**

```php
// Enable verbose plugin logging
define('CAT_DEBUG_VERBOSE', true);
```

**Check logs:**

```bash
tail -f wp-content/uploads/cat-logs/debug-$(date +%Y-%m-%d).log
```

---

### Browser DevTools

**Console:**

- Check for JavaScript errors
- Look for failed network requests
- Verify nonce is present in AJAX requests

**Network Tab:**

- Check API request/response
- Verify correct endpoint being called
- Check request payload and headers

**React DevTools:**

- Install React DevTools extension
- Inspect component props and state
- Check component render times

---

### WP-CLI Debugging

```bash
# Check configuration
wp option list --search=context_alt_text

# Test recognition service
wp cat-recognition health

# View roster entries
wp cat-roster status

# Run recognition manually
wp cat-recognition analyze 123

# Check plugin status
wp plugin get context-alt-text
```

---

## Getting Help

If you're still experiencing issues:

1. **Search existing issues:**
    - [GitHub Issues](https://github.com/your-org/context-alt-text-monorepo/issues)

2. **Gather diagnostic information:**
    - WordPress version: `wp core version`
    - PHP version: `php -v`
    - Plugin version: `wp plugin get context-alt-text --field=version`
    - Active environment: `cat .env`
    - Recent logs: `tail -n 50 wp-content/uploads/cat-logs/debug-$(date +%Y-%m-%d).log`

3. **Create a minimal reproduction:**
    - Fresh WordPress installation
    - Only Context Alt Text plugin active
    - Specific steps to reproduce

4. **Open an issue:**
    - Include diagnostic information
    - Describe expected vs actual behavior
    - Attach relevant logs (remove sensitive data)

---

## Support

- **Documentation:** [`docs/`](.)
- **Issues:** [GitHub Issues](https://github.com/your-org/context-alt-text-monorepo/issues)
- **Discussions:** [GitHub Discussions](https://github.com/your-org/context-alt-text-monorepo/discussions)
