# Troubleshooting: 401 "You do not have permission to identify faces" Error

## Problem

When trying to label faces in the workbench, you see this error:

```
POST http://localhost:10008/wp-json/cat/v1/recognition/identify 401 (Unauthorized)
Error: You do not have permission to identify faces.
```

## Root Causes

There are two potential causes for this 401 error:

### 1. Missing `upload_files` Capability

The `/wp-json/cat/v1/recognition/identify` endpoint requires the `upload_files` capability. This capability is:

- ✅ **Granted by default to**: Administrator, Editor, Author
- ❌ **Not granted to**: Contributor, Subscriber

The endpoint checks this capability because face labeling creates observations (WordPress posts) and potentially uploads reference images.

### 2. Missing or Invalid REST API Nonce

Even if you're an Administrator, the REST API request must include a valid nonce in the `X-WP-Nonce` header. This prevents CSRF attacks.

**Common nonce issues:**

- `window.catAltText.restNonce` is undefined (config not loaded)
- Nonce expired (WordPress nonces expire after 12-24 hours)
- Page cached with old nonce

## Solutions

### Solution 1: Verify REST API Nonce (Most Common Issue)

#### Check in Browser Console

1. Open browser DevTools (F12)
2. In console, type:
    ```javascript
    window.catAltText?.restNonce;
    ```
3. If `undefined` or `null` → nonce not loaded
4. If shows a string → nonce is present

#### Fix: Refresh the Page

WordPress nonces expire after 12-24 hours. Simply refresh the page to get a new nonce:

```bash
# Hard refresh to bypass cache
Cmd+Shift+R (Mac) or Ctrl+Shift+F5 (Windows)
```

#### Fix: Check Network Request

1. Open DevTools → Network tab
2. Try labeling a face
3. Click the failed `/identify` request
4. Check **Request Headers** section
5. Look for `X-WP-Nonce` header

If missing:

```javascript
// The nonce should be passed to usePeopleSuggestions hook
// Check WorkbenchApp.tsx line 189:
restNonce={window.catAltText?.restNonce}
```

#### Fix: Clear Page Cache

If using caching plugins (WP Super Cache, W3 Total Cache):

```bash
# Via WP-CLI
wp cache flush

# Or deactivate caching for admin pages
```

### Solution 2: Grant upload_files Capability

If you're using a Contributor or Subscriber account, grant the capability:

```bash
# Replace 'username' with your WordPress username
wp user add-cap username upload_files
```

### Solution 3: Use Administrator Account

Log in as a WordPress Administrator. Admins have all capabilities including `upload_files`.

### Solution 4: Development-Only Capability Override

Add this to your `wp-config.php` for development/testing (NOT for production):

```php
// DEVELOPMENT ONLY - Grant upload_files to all logged-in users
add_filter('user_has_cap', function($caps, $cap) {
    if (in_array('upload_files', $cap) && is_user_logged_in()) {
        $caps['upload_files'] = true;
    }
    return $caps;
}, 10, 2);
```

### Solution 5: Check User Capabilities

Use WP-CLI to verify what capabilities your user has:

```bash
# Check your user's role
wp user get admin --field=roles

# Check if you have upload_files capability
wp user get admin --field=allcaps | grep upload_files
```

## Verification

After applying a solution, verify the fix works:

1. **Check nonce is present:**

    ```javascript
    console.log(window.catAltText?.restNonce); // Should show a string like "21902eea51"
    ```

2. **Hard refresh the page** (Cmd+Shift+R on Mac, Ctrl+Shift+F5 on Windows)

3. **Try labeling a face again**

4. **Check Network tab in DevTools:**
    - Look for POST to `/wp-json/cat/v1/recognition/identify`
    - Should return **200 OK** (not 401)
    - Response should include `{ faces: [...] }`

5. **Check Console** - No more "You do not have permission" errors

## Code Reference

The capability check is in `src/Recognition/IdentifyController.php`:

```php
public function identify(WP_REST_Request $request): array|WP_Error
{
    // Verify user capability
    if (!$this->security->verifyCapability('upload_files')) {
        return new WP_Error(
            'rest_forbidden',
            __('You do not have permission to identify faces.', 'context-alt-text'),
            ['status' => 401]
        );
    }
    // ... rest of method
}
```

## Related

- WordPress Roles and Capabilities: https://wordpress.org/documentation/article/roles-and-capabilities/
- The `upload_files` capability is one of the core WordPress capabilities
- See `tests/Recognition/IdentifyControllerTest.php` for test coverage of this permission check
