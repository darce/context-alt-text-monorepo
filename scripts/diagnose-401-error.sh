#!/bin/bash
# Diagnostic script for 401 "You do not have permission to identify faces" error
#
# IMPORTANT: This script must be run from your WordPress installation root directory.
#
# Usage:
#   1. Copy this script to your WordPress root (where wp-config.php is located)
#      cp scripts/diagnose-401-error.sh ~/Development/wp-context-alt-text/app/public/
#   2. SSH into Local site or navigate to WordPress root
#   3. Run: bash diagnose-401-error.sh

set -e

echo "=========================================="
echo "Context Alt Text - 401 Error Diagnostics"
echo "=========================================="
echo ""

# Check if we're in a WordPress installation
if [ ! -f "wp-config.php" ]; then
    echo "❌ ERROR: This script must be run from the WordPress root directory"
    echo "   (the directory containing wp-config.php)"
    echo ""
    echo "📋 To fix this:"
    echo "   1. Copy this script to your WordPress root:"
    echo "      cp scripts/diagnose-401-error.sh ~/Development/wp-context-alt-text/app/public/"
    echo ""
    echo "   2. Navigate to WordPress root:"
    echo "      cd ~/Development/wp-context-alt-text/app/public/"
    echo ""
    echo "   3. Run the script:"
    echo "      bash diagnose-401-error.sh"
    echo ""
    exit 1
fi

# Check if WP-CLI is available
if ! command -v wp &> /dev/null; then
    echo "❌ WP-CLI not found. Please install WP-CLI to run diagnostics."
    echo "   See: https://wp-cli.org/"
    exit 1
fi

echo "✅ WP-CLI found"
echo "✅ WordPress installation detected"
echo ""
echo "ℹ️  Note: PHP warnings from Local by Flywheel are suppressed"
echo ""

# Get current user (suppress PHP warnings from Local by Flywheel)
echo "📋 Current User Information"
echo "─────────────────────────────"
CURRENT_USER=$(wp user list --format=csv --fields=user_login 2>/dev/null | tail -n +2 | head -n 1)
if [ -z "$CURRENT_USER" ]; then
    echo "⚠️  Could not detect current user automatically"
    echo "   Please run: wp user list"
    echo ""
    exit 1
fi
echo "Username: $CURRENT_USER"

# Check user role
USER_ROLE=$(wp user get $CURRENT_USER --field=roles --format=json 2>/dev/null | jq -r '.[0]' 2>/dev/null)
if [ -n "$USER_ROLE" ]; then
    echo "Role: $USER_ROLE"
else
    echo "Role: (could not detect)"
fi

# Check upload_files capability
HAS_UPLOAD=$(wp user get $CURRENT_USER --field=allcaps --format=json 2>/dev/null | jq -r '.upload_files' 2>/dev/null)
if [ "$HAS_UPLOAD" = "true" ]; then
    echo "✅ Has upload_files capability: YES"
elif [ "$HAS_UPLOAD" = "false" ]; then
    echo "❌ Has upload_files capability: NO"
    echo ""
    echo "🔧 FIX: Grant capability with:"
    echo "   wp user add-cap $CURRENT_USER upload_files"
else
    echo "⚠️  Could not check upload_files capability"
    echo "   Manual check: wp user get $CURRENT_USER --field=allcaps"
fi
echo ""

# Check if nonce can be created
echo "📋 REST API Nonce Check"
echo "─────────────────────────────"
NONCE_TEST=$(wp eval 'echo wp_create_nonce("wp_rest");' 2>/dev/null)
if [ -n "$NONCE_TEST" ] && [ "$NONCE_TEST" != "Warning:"* ]; then
    echo "✅ Nonce creation: WORKING"
    echo "   Sample nonce: $NONCE_TEST"
else
    echo "❌ Nonce creation: FAILED"
fi
echo ""

# Check if REST API is enabled
echo "📋 REST API Status"
echo "─────────────────────────────"
REST_ENABLED=$(wp eval 'echo (function_exists("rest_url") && rest_url()) ? "true" : "false";' 2>/dev/null)
if [ "$REST_ENABLED" = "true" ]; then
    echo "✅ REST API: ENABLED"
else
    echo "❌ REST API: DISABLED"
fi
echo ""

# Check if Context Alt Text plugin is active
echo "📋 Plugin Status"
echo "─────────────────────────────"
PLUGIN_ACTIVE=$(wp plugin is-active context-alt-text 2>/dev/null && echo "true" || echo "false")
if [ "$PLUGIN_ACTIVE" = "true" ]; then
    echo "✅ Context Alt Text: ACTIVE"
else
    echo "❌ Context Alt Text: INACTIVE"
    echo ""
    echo "🔧 FIX: Activate plugin with:"
    echo "   wp plugin activate context-alt-text"
fi
echo ""

# Check recognition feature flag
echo "📋 Feature Flags"
echo "─────────────────────────────"
RECOGNITION_ENABLED=$(wp option get cat_settings --format=json 2>/dev/null | jq -r '.recognition.enabled // false')
if [ "$RECOGNITION_ENABLED" = "true" ]; then
    echo "✅ Recognition feature: ENABLED"
else
    echo "⚠️  Recognition feature: DISABLED (or not configured)"
fi
echo ""

# Check endpoint registration
echo "📋 REST Endpoint Registration"
echo "─────────────────────────────"
IDENTIFY_ROUTE=$(wp rest-api list 2>/dev/null | grep "cat/v1/recognition/identify" || echo "")
if [ -n "$IDENTIFY_ROUTE" ]; then
    echo "✅ /cat/v1/recognition/identify: REGISTERED"
else
    echo "❌ /cat/v1/recognition/identify: NOT REGISTERED"
    echo "   This indicates the plugin may not be loading correctly."
fi
echo ""

# Test REST API authentication
echo "📋 REST API Authentication Test"
echo "─────────────────────────────"
echo "Testing REST API with current user credentials..."

# Get WordPress URL
WP_URL=$(wp option get siteurl 2>/dev/null)

# Try to call a protected endpoint
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
    -H "Content-Type: application/json" \
    -u "$CURRENT_USER:password" \
    "$WP_URL/wp-json/cat/v1/recognition/identify" \
    -X POST \
    -d '{"attachmentId":1,"faces":[]}' 2>/dev/null || echo "000")

if [ "$HTTP_STATUS" = "401" ]; then
    echo "❌ Authentication failed (401)"
    echo "   This confirms the 401 error."
    echo ""
    echo "🔧 Common fixes:"
    echo "   1. Hard refresh page (Cmd+Shift+R / Ctrl+Shift+F5)"
    echo "   2. Check browser console: window.catAltText?.restNonce"
    echo "   3. Clear page cache if using caching plugin"
elif [ "$HTTP_STATUS" = "400" ]; then
    echo "✅ Authentication worked (400 = bad request, but auth passed)"
elif [ "$HTTP_STATUS" = "200" ]; then
    echo "✅ Endpoint accessible"
else
    echo "⚠️  Unexpected HTTP status: $HTTP_STATUS"
fi
echo ""

echo "=========================================="
echo "Summary"
echo "=========================================="
echo ""
echo "Most common fix for 401 errors:"
echo "1. Hard refresh page (Cmd+Shift+R)"
echo "2. Check nonce in console: window.catAltText?.restNonce"
echo "3. Ensure user is Administrator or has upload_files capability"
echo ""
echo "For more help, see:"
echo "docs/troubleshooting/401-identify-faces-error.md"
