#!/bin/bash
# Switch between environment configurations
# Usage: ./scripts/switch-env.sh local|local-remote|staging|production

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$PLUGIN_DIR/.env"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

show_usage() {
    echo ""
    echo -e "${BLUE}Usage:${NC} $0 <environment>"
    echo ""
    echo "Available environments:"
    echo "  local         - Full local stack (LocalWP + local recognition service)"
    echo "  local-remote  - Hybrid dev (LocalWP + remote HuggingFace Space)"
    echo "  staging       - Staging environment"
    echo "  production    - Production environment"
    echo ""
    echo "Example:"
    echo "  $0 local"
    echo ""
}

if [ $# -eq 0 ]; then
    echo -e "${RED}Error: No environment specified${NC}"
    show_usage
    exit 1
fi

ENVIRONMENT=$1

case $ENVIRONMENT in
    local)
        ENV_SOURCE=".env.local"
        ;;
    local-remote)
        ENV_SOURCE=".env.local-remote"
        ;;
    staging)
        ENV_SOURCE=".env.staging"
        ;;
    production)
        ENV_SOURCE=".env.production"
        ;;
    *)
        echo -e "${RED}Error: Unknown environment '${ENVIRONMENT}'${NC}"
        show_usage
        exit 1
        ;;
esac

ENV_SOURCE_PATH="$PLUGIN_DIR/$ENV_SOURCE"

if [ ! -f "$ENV_SOURCE_PATH" ]; then
    echo -e "${RED}Error: Environment file not found: ${ENV_SOURCE_PATH}${NC}"
    echo ""
    echo "Create it by copying .env.template:"
    echo "  cp .env.template $ENV_SOURCE"
    exit 1
fi

# Show current environment (if .env exists)
if [ -L "$ENV_FILE" ]; then
    CURRENT=$(readlink "$ENV_FILE")
    echo -e "${BLUE}Current environment:${NC} $(basename "$CURRENT")"
elif [ -f "$ENV_FILE" ]; then
    echo -e "${YELLOW}Current .env is a regular file (not a symlink)${NC}"
fi

echo -e "${BLUE}Switching to:${NC} $ENV_SOURCE"

# Remove existing .env (whether symlink or file)
rm -f "$ENV_FILE"

# Create symlink
ln -s "$ENV_SOURCE" "$ENV_FILE"

echo -e "${GREEN}✓ Environment switched successfully${NC}"
echo ""

# Show recognition service URL
RECOGNITION_URL=$(grep "^CAT_RECOGNITION_BASE_URL=" "$ENV_SOURCE_PATH" | cut -d'=' -f2)
if [ -n "$RECOGNITION_URL" ]; then
    echo -e "${BLUE}Recognition Service:${NC} $RECOGNITION_URL"
else
    echo -e "${YELLOW}Recognition Service:${NC} Not configured"
fi

# Show Vite dev server
VITE_SERVER=$(grep "^CAT_VITE_DEV_SERVER=" "$ENV_SOURCE_PATH" | cut -d'=' -f2)
if [ -n "$VITE_SERVER" ]; then
    echo -e "${BLUE}Vite Dev Server:${NC} $VITE_SERVER"
fi

echo ""
echo -e "${GREEN}Ready to use!${NC}"
echo ""

# Helpful next steps
case $ENVIRONMENT in
    local)
        echo "Next steps:"
        echo "  1. Start recognition service: cd ../recognition-service && ./scripts/start_recognition_local.sh"
        echo "  2. Start Vite: npm run dev"
        echo "  3. Open WordPress: http://localhost:10008/wp-admin"
        ;;
    local-remote)
        echo "Next steps:"
        echo "  1. Update CAT_RECOGNITION_BASE_URL in $ENV_SOURCE with your HuggingFace Space URL"
        echo "  2. Start Vite: npm run dev"
        echo "  3. Open WordPress: http://localhost:10008/wp-admin"
        ;;
    staging|production)
        echo "Next steps:"
        echo "  1. Ensure built assets are up to date: npm run build"
        echo "  2. Deploy to your $ENVIRONMENT server"
        echo "  3. Verify recognition service is accessible"
        ;;
esac
