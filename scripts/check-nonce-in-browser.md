# Browser-Based 401 Error Diagnostic

Since WP-CLI has PHP extension warnings in Local by Flywheel, let's debug directly in the browser.

## Step 1: Check Nonce in Browser Console

Open the WordPress admin page where you're seeing the 401 error, then open the browser console and run:

```javascript
// Check if nonce exists
console.log("REST Nonce:", window.catAltText?.restNonce);

// Check the full config
console.log("Full Config:", window.catAltText);

// Test if nonce is being sent
fetch("/wp-json/cat/v1/recognition/identify", {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "X-WP-Nonce": window.catAltText?.restNonce || "MISSING",
  },
  body: JSON.stringify({
    attachmentId: 1,
    faces: [],
  }),
})
  .then((r) => {
    console.log("Status:", r.status);
    return r.json();
  })
  .then((data) => console.log("Response:", data))
  .catch((err) => console.error("Error:", err));
```

## Expected Output

### If Nonce is Working ✅

```javascript
REST Nonce: "abc123def456"
Full Config: {
    restNonce: "abc123def456",
    endpoints: { /* ... */ },
    featureFlags: { /* ... */ }
}
Status: 400  // Bad request is OK - means auth passed
Response: { code: "invalid_request", message: "..." }
```

### If Nonce is Missing ❌

```javascript
REST Nonce: undefined
Full Config: undefined  // or missing restNonce property
Status: 401
Response: { code: "rest_forbidden", message: "You do not have permission..." }
```

## Step 2: Check Request Headers in Network Tab

1. Open **DevTools** → **Network** tab
2. Filter by **Fetch/XHR**
3. Try to label a face
4. Click on the failed request to `/wp-json/cat/v1/recognition/identify`
5. Look at **Request Headers**

### Should See:

```
X-WP-Nonce: abc123def456...
Content-Type: application/json
```

### If Missing X-WP-Nonce:

This confirms the nonce isn't being sent.

## Step 3: Quick Fixes

### Fix 1: Hard Refresh Page

Sometimes the nonce is stale if the page has been open for hours.

- **Mac:** `Cmd + Shift + R`
- **Windows:** `Ctrl + Shift + F5`

### Fix 2: Check Plugin is Enqueueing Config

In WordPress admin, check if the script is loaded:

```javascript
// Check if admin.js is loaded
console.log("Admin script loaded:", !!window.catAltText);

// Check script tags
Array.from(document.scripts)
  .filter((s) => s.src.includes("admin.js"))
  .forEach((s) => console.log("Found:", s.src));
```

### Fix 3: Verify User Capability via REST API

Open a new browser tab and navigate to:

```
http://localhost:10008/wp-json/wp/v2/users/me
```

This should show your user info. Check the `capabilities` field should include `"upload_files": true`.

## Step 4: Manual WP-CLI Check (Alternative)

If you want to use WP-CLI despite the warnings, redirect stderr to stdout and filter:

```bash
# Check user capabilities
wp user get admin --field=allcaps 2>&1 | grep -v "Warning:" | grep -v "Failed loading" | grep -v "Xdebug" | jq .

# Check if plugin is active
wp plugin list --status=active 2>&1 | grep -v "Warning:" | grep "context-alt-text"

# Check nonce
wp eval 'echo wp_create_nonce("wp_rest");' 2>&1 | grep -v "Warning:" | grep -v "Failed" | grep -v "Xdebug"
```

## Most Likely Causes

Based on the error, the most likely causes are:

1. **Stale Nonce** (page open >24hrs) → Hard refresh
2. **Missing Nonce in Request** → Check `X-WP-Nonce` header in Network tab
3. **Config Not Loaded** → Check `window.catAltText` in console
4. **Wrong User Context** → Verify you're logged in as admin

## Next Steps

Run the JavaScript diagnostic in Step 1 and share:

1. The value of `window.catAltText?.restNonce`
2. The Status code from the fetch test
3. Screenshot of the Network tab showing the request headers
