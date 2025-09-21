<?php

declare(strict_types=1);

namespace ContextAltText\Support;

class FeatureFlags
{
    public function abilitiesEnabled(): bool
    {
        $enabled = defined('CAT_ENABLE_ABILITIES') ? (bool) CAT_ENABLE_ABILITIES : false;
        /**
         * Filter the abilities flag so environments can enable via code.
         */
        return (bool) apply_filters('cat_enable_abilities', $enabled);
    }

    public function mcpEnabled(): bool
    {
        $enabled = defined('CAT_ENABLE_MCP') ? (bool) CAT_ENABLE_MCP : false;

        return (bool) apply_filters('cat_enable_mcp', $enabled);
    }
}
