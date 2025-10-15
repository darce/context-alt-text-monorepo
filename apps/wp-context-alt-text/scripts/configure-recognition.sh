#!/bin/bash
# Configure Context Alt Text Recognition Service
# Run this from the plugin directory

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

RECOGNITION_URL="${CAT_RECOGNITION_BASE_URL:-http://localhost:7860}"

echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  Configure Recognition Service${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo ""

# Check if wp-cli exists
if ! command -v wp &> /dev/null; then
    echo -e "${RED}✗ WP-CLI not found. Using SQL instead...${NC}"
    echo ""
    echo "Add this to your wp-config.php:"
    echo ""
    echo -e "${YELLOW}define('CAT_RECOGNITION_BASE_URL', '${RECOGNITION_URL}');${NC}"
    echo ""
    exit 1
fi

# Check if recognition service is running
echo -e "${YELLOW}Checking recognition service at ${RECOGNITION_URL}...${NC}"
if curl -s --max-time 2 "${RECOGNITION_URL}/api/v0/health" 2>/dev/null | grep -q '"status":"ok"'; then
    echo -e "${GREEN}✓ Recognition service is running${NC}"
else
    echo -e "${YELLOW}⚠ Recognition service not responding${NC}"
    echo "  Continue anyway? (y/n)"
    read -r response
    if [[ ! "$response" =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi
echo ""

# Configure recognition settings
echo -e "${YELLOW}Configuring recognition service URL...${NC}"
wp option update context_alt_text_recognition_settings \
  "{\"base_url\":\"${RECOGNITION_URL}\",\"timeout_ms\":\"30000\"}" \
  --format=json

echo -e "${GREEN}✓ Recognition service configured${NC}"
echo ""

# Verify
echo -e "${YELLOW}Verifying configuration...${NC}"
SETTINGS=$(wp option get context_alt_text_recognition_settings --format=json 2>/dev/null || echo "{}")
BASE_URL=$(echo "$SETTINGS" | jq -r '.base_url' 2>/dev/null || echo "")

if [ "$BASE_URL" = "${RECOGNITION_URL}" ]; then
    echo -e "${GREEN}✓ Configuration verified${NC}"
    echo ""
    echo -e "${GREEN}═══════════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}  Setup Complete! ✓${NC}"
    echo -e "${GREEN}═══════════════════════════════════════════════════════════${NC}"
    echo ""
    echo -e "${BLUE}Recognition is now auto-enabled!${NC}"
    echo ""
    echo "  Recognition feature will automatically enable when the"
    echo "  service URL is configured. No additional flags needed."
    echo ""
    echo -e "${BLUE}Next steps:${NC}"
    echo "  1. Go to the Workbench page in WordPress admin"
    echo "  2. Select some images"
    echo "  3. Click 'Trigger Recognition' (now enabled)"
    echo ""
    echo -e "${BLUE}Test via CLI:${NC}"
    echo "  wp cat-recognition health"
    echo "  wp cat-recognition analyze <attachment_id>"
    echo ""
else
    echo -e "${RED}✗ Configuration failed${NC}"
    echo "  Expected: ${RECOGNITION_URL}"
    echo "  Got: ${BASE_URL}"
    exit 1
fi
