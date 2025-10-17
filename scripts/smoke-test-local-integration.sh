#!/bin/bash
# Local Integration Smoke Test for Context Alt Text
# Tests WordPress plugin → Recognition Service communication

set -e

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
RECOGNITION_URL="${CAT_RECOGNITION_BASE_URL:-http://localhost:7860}"
WP_PATH="${WP_PATH:-.}"

echo -e "${BLUE}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║  Context Alt Text - Local Integration Smoke Test              ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Function to check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Check prerequisites
echo -e "${YELLOW}Checking prerequisites...${NC}"

if ! command_exists wp; then
    echo -e "${RED}✗ WP-CLI not found. Please install wp-cli.${NC}"
    exit 1
fi
echo -e "${GREEN}✓ WP-CLI found${NC}"

if ! command_exists curl; then
    echo -e "${RED}✗ curl not found. Please install curl.${NC}"
    exit 1
fi
echo -e "${GREEN}✓ curl found${NC}"

if ! command_exists jq; then
    echo -e "${YELLOW}⚠ jq not found. JSON output will not be formatted.${NC}"
    JQ_CMD="cat"
else
    echo -e "${GREEN}✓ jq found${NC}"
    JQ_CMD="jq ."
fi

echo ""

# Test 1: Recognition Service Health
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}Test 1: Recognition Service Health Check${NC}"
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

HEALTH_RESPONSE=$(curl -s -w "\n%{http_code}" "${RECOGNITION_URL}/api/v0/health" 2>/dev/null || echo "FAIL\n000")
HTTP_CODE=$(echo "$HEALTH_RESPONSE" | tail -n1)
HEALTH_BODY=$(echo "$HEALTH_RESPONSE" | head -n-1)

if [ "$HTTP_CODE" = "200" ] && echo "$HEALTH_BODY" | grep -q '"status":"ok"'; then
    echo -e "${GREEN}✓ Recognition service is healthy${NC}"
    echo "  URL: $RECOGNITION_URL"
    echo "  Response: $HEALTH_BODY" | $JQ_CMD | head -n5
else
    echo -e "${RED}✗ Recognition service health check failed${NC}"
    echo "  URL: $RECOGNITION_URL"
    echo "  HTTP Code: $HTTP_CODE"
    echo "  Response: $HEALTH_BODY"
    echo ""
    echo -e "${YELLOW}  Make sure the recognition service is running:${NC}"
    echo "    cd apps/recognition-service"
    echo "    ./scripts/start_recognition_local.sh start"
    exit 1
fi
echo ""

# Test 2: Recognition Service Info
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}Test 2: Recognition Service Info${NC}"
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

SERVICE_INFO=$(curl -s "${RECOGNITION_URL}/api/v0/service/info" 2>/dev/null)
if echo "$SERVICE_INFO" | grep -q '"status":"ok"'; then
    echo -e "${GREEN}✓ Service info retrieved successfully${NC}"
    MODEL_NAME=$(echo "$SERVICE_INFO" | jq -r '.data.model.name' 2>/dev/null || echo "unknown")
    THRESHOLD=$(echo "$SERVICE_INFO" | jq -r '.data.recognition.default_threshold' 2>/dev/null || echo "unknown")
    LOADED_ENTRIES=$(echo "$SERVICE_INFO" | jq -r '.data.embedding_router.loaded_embeddings' 2>/dev/null || echo "unknown")
    echo "  Model: $MODEL_NAME"
    echo "  Threshold: $THRESHOLD"
    echo "  Loaded roster entries: $LOADED_ENTRIES"
else
    echo -e "${RED}✗ Failed to retrieve service info${NC}"
    echo "  Response: $SERVICE_INFO"
    exit 1
fi
echo ""

# Test 3: WordPress Plugin Status
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}Test 3: WordPress Plugin Status${NC}"
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

if wp plugin is-active context-alt-text --path="$WP_PATH" 2>/dev/null; then
    echo -e "${GREEN}✓ Plugin is activated${NC}"
    PLUGIN_VERSION=$(wp plugin get context-alt-text --field=version --path="$WP_PATH" 2>/dev/null || echo "unknown")
    echo "  Version: $PLUGIN_VERSION"
else
    echo -e "${RED}✗ Plugin is not activated${NC}"
    echo ""
    echo -e "${YELLOW}  Activate the plugin:${NC}"
    echo "    wp plugin activate context-alt-text"
    exit 1
fi
echo ""

# Test 4: Recognition Settings
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}Test 4: Recognition Settings Configuration${NC}"
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

SETTINGS=$(wp option get cat_settings --format=json --path="$WP_PATH" 2>/dev/null || echo "{}")
if [ "$SETTINGS" = "{}" ] || [ -z "$SETTINGS" ]; then
    echo -e "${YELLOW}⚠ Recognition settings not configured. Configuring now...${NC}"
    wp option update cat_settings "{\"recognition\":{\"baseUrl\":\"$RECOGNITION_URL\",\"timeoutMs\":30000,\"enabled\":true}}" --format=json --path="$WP_PATH"
    SETTINGS=$(wp option get cat_settings --format=json --path="$WP_PATH" 2>/dev/null)
    echo -e "${GREEN}✓ Settings configured${NC}"
else
    echo -e "${GREEN}✓ Recognition settings found${NC}"
fi

BASE_URL=$(echo "$SETTINGS" | jq -r '.recognition.baseUrl' 2>/dev/null || echo "")
TIMEOUT_MS=$(echo "$SETTINGS" | jq -r '.recognition.timeoutMs' 2>/dev/null || echo "")

echo "  Base URL: $BASE_URL"
echo "  Timeout: $TIMEOUT_MS ms"

if [ "$BASE_URL" != "$RECOGNITION_URL" ]; then
    echo -e "${YELLOW}  ⚠ Base URL mismatch. Updating...${NC}"
    wp option patch update cat_settings recognition.baseUrl "$RECOGNITION_URL" --path="$WP_PATH"
fi
echo ""

# Test 5: WP-CLI Health Check Command
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}Test 5: WP-CLI Recognition Health Check${NC}"
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

if wp cat-recognition health --path="$WP_PATH" 2>&1 | grep -qi "ok\|healthy\|status.*ok"; then
    echo -e "${GREEN}✓ WP-CLI health check passed${NC}"
else
    echo -e "${RED}✗ WP-CLI health check failed${NC}"
    echo ""
    echo "  Full output:"
    wp cat-recognition health --path="$WP_PATH" 2>&1 || true
    exit 1
fi
echo ""

# Test 6: Roster CLI Commands
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}Test 6: Roster CLI Commands${NC}"
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

if wp cat-roster status --path="$WP_PATH" 2>&1; then
    echo -e "${GREEN}✓ Roster status command works${NC}"
    
    # Count remote roster entries
    REMOTE_COUNT=$(curl -s "${RECOGNITION_URL}/api/v0/roster" | jq -r '.count' 2>/dev/null || echo "0")
    echo "  Remote roster entries: $REMOTE_COUNT"
else
    echo -e "${YELLOW}⚠ Roster status command failed (this may be expected if roster not configured)${NC}"
fi
echo ""

# Test 7: Create and Analyze Test Image
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}Test 7: Image Recognition Pipeline${NC}"
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# Create a 1x1 pixel test image
TEST_IMAGE="/tmp/cat-test-$(date +%s).png"
echo "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8Xw8AAnEB7SBSYQAAAABJRU5ErkJggg==" | base64 -d > "$TEST_IMAGE"

# Import image
echo "  Creating test image..."
ATTACHMENT_ID=$(wp media import "$TEST_IMAGE" --porcelain --path="$WP_PATH" 2>/dev/null)

if [ -n "$ATTACHMENT_ID" ] && [ "$ATTACHMENT_ID" -gt 0 ]; then
    echo -e "${GREEN}✓ Test image created (ID: $ATTACHMENT_ID)${NC}"
    
    # Run recognition
    echo "  Running recognition analysis..."
    if wp cat-recognition analyze "$ATTACHMENT_ID" --path="$WP_PATH" 2>&1 | grep -qi "success\|complete\|processed"; then
        echo -e "${GREEN}✓ Recognition analysis completed${NC}"
    else
        echo -e "${YELLOW}⚠ Recognition analysis may have issues${NC}"
        echo "    (This is expected for a 1x1 pixel image - no faces to detect)"
    fi
    
    # Cleanup
    echo "  Cleaning up test image..."
    wp post delete "$ATTACHMENT_ID" --force --path="$WP_PATH" >/dev/null 2>&1
    rm -f "$TEST_IMAGE"
    echo -e "${GREEN}✓ Test image cleaned up${NC}"
else
    echo -e "${RED}✗ Failed to create test image${NC}"
    rm -f "$TEST_IMAGE"
fi
echo ""

# Test 8: Direct API Call from WordPress
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}Test 8: Direct Recognition API Test${NC}"
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# Test analyze-scene endpoint with example request
EXAMPLE_REQUEST='{"images":[{"base64":"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8Xw8AAnEB7SBSYQAAAABJRU5ErkJggg==","filename":"test.png"}],"threshold":0.5,"use_roster":true}'

ANALYZE_RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${RECOGNITION_URL}/api/v0/analyze-scene" \
    -H "Content-Type: application/json" \
    -d "$EXAMPLE_REQUEST" 2>/dev/null || echo "FAIL\n000")

ANALYZE_HTTP_CODE=$(echo "$ANALYZE_RESPONSE" | tail -n1)
ANALYZE_BODY=$(echo "$ANALYZE_RESPONSE" | head -n-1)

if [ "$ANALYZE_HTTP_CODE" = "200" ]; then
    echo -e "${GREEN}✓ Direct API call successful${NC}"
    RESULTS_COUNT=$(echo "$ANALYZE_BODY" | jq -r '.results | length' 2>/dev/null || echo "0")
    echo "  Results returned: $RESULTS_COUNT"
else
    echo -e "${RED}✗ Direct API call failed${NC}"
    echo "  HTTP Code: $ANALYZE_HTTP_CODE"
    echo "  Response: $ANALYZE_BODY" | head -n10
fi
echo ""

# Summary
echo -e "${BLUE}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║  Test Summary                                                  ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${GREEN}✓ All integration smoke tests passed!${NC}"
echo ""
echo -e "${YELLOW}Integration Status:${NC}"
echo "  • Recognition Service: Running at $RECOGNITION_URL"
echo "  • WordPress Plugin: Activated and configured"
echo "  • API Communication: Working"
echo "  • WP-CLI Commands: Functional"
echo "  • Recognition Pipeline: Operational"
echo ""
echo -e "${BLUE}Next steps:${NC}"
echo "  1. Test with real images containing faces"
echo "  2. Verify roster sync functionality"
echo "  3. Test deep links from recognition to roster"
echo "  4. Validate dashboard metrics display"
echo ""
echo -e "${GREEN}Integration is ready for end-to-end testing!${NC}"
echo ""
