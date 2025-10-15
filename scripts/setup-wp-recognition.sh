#!/bin/bash
# Quick setup script for WordPress + Recognition Service integration
# Usage: ./scripts/setup-wp-recognition.sh [wordpress-path]

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

WP_PATH="${1:-.}"
RECOGNITION_URL="http://localhost:7860"

echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  Context Alt Text - WordPress Recognition Setup${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo ""

# Check if wp-cli exists
if ! command -v wp &> /dev/null; then
    echo -e "${RED}✗ WP-CLI not found${NC}"
    echo "  Please install WP-CLI: https://wp-cli.org/"
    exit 1
fi

# Check if recognition service is running
echo -e "${YELLOW}Checking recognition service...${NC}"
if ! curl -s "${RECOGNITION_URL}/api/v0/health" | grep -q '"status":"ok"'; then
    echo -e "${RED}✗ Recognition service not running${NC}"
    echo ""
    echo "  Start it with:"
    echo "    cd apps/recognition-service"
    echo "    ./scripts/start_recognition_local.sh start"
    exit 1
fi
echo -e "${GREEN}✓ Recognition service is running${NC}"
echo ""

# Configure recognition settings
echo -e "${YELLOW}Configuring recognition service URL...${NC}"
wp option update context_alt_text_recognition_settings \
  "{\"base_url\":\"${RECOGNITION_URL}\",\"timeout_ms\":\"30000\"}" \
  --format=json \
  --path="$WP_PATH"
echo -e "${GREEN}✓ Recognition URL configured${NC}"
echo ""

# Enable feature flags
echo -e "${YELLOW}Enabling recognition feature flags...${NC}"

# Method 1: Via database option
wp option update cat_feature_workbench_recognition 1 --path="$WP_PATH"
echo -e "${GREEN}✓ Workbench recognition enabled via option${NC}"

# Method 2: Show wp-config.php constant (if user wants to use that instead)
echo ""
echo -e "${BLUE}Alternative: Add to wp-config.php (before 'stop editing'):${NC}"
echo -e "${YELLOW}"
cat << 'EOF'
// Enable Context Alt Text Recognition
define('CAT_FEATURE_WORKBENCH_RECOGNITION', true);
define('CAT_RECOGNITION_BASE_URL', 'http://localhost:7860');
define('CAT_RECOGNITION_TIMEOUT_MS', '30000');
EOF
echo -e "${NC}"

# Enable roster UI (optional but recommended)
echo -e "${YELLOW}Enabling roster UI...${NC}"
wp option update cat_feature_roster_ui_enabled 1 --path="$WP_PATH"
echo -e "${GREEN}✓ Roster UI enabled${NC}"
echo ""

# Verify configuration
echo -e "${YELLOW}Verifying configuration...${NC}"

RECOGNITION_SETTINGS=$(wp option get context_alt_text_recognition_settings --format=json --path="$WP_PATH" 2>/dev/null || echo "{}")
BASE_URL=$(echo "$RECOGNITION_SETTINGS" | jq -r '.base_url' 2>/dev/null || echo "")
FEATURE_FLAG=$(wp option get cat_feature_workbench_recognition --path="$WP_PATH" 2>/dev/null || echo "0")

if [ "$BASE_URL" = "${RECOGNITION_URL}" ] && [ "$FEATURE_FLAG" = "1" ]; then
    echo -e "${GREEN}✓ Configuration verified${NC}"
    echo ""
    echo -e "${GREEN}═══════════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}  Setup Complete! ✓${NC}"
    echo -e "${GREEN}═══════════════════════════════════════════════════════════${NC}"
    echo ""
    echo -e "${BLUE}Next steps:${NC}"
    echo "  1. Go to: http://localhost:10008/wp-admin/admin.php?page=context-alt-text-workbench"
    echo "  2. Select some images"
    echo "  3. Click 'Trigger Recognition' (should now be enabled)"
    echo ""
    echo -e "${BLUE}To test via CLI:${NC}"
    echo "  wp cat-recognition health"
    echo "  wp cat-recognition analyze <attachment_id>"
    echo ""
else
    echo -e "${RED}✗ Configuration incomplete${NC}"
    echo "  Base URL: $BASE_URL"
    echo "  Feature Flag: $FEATURE_FLAG"
    exit 1
fi
