<?php

declare(strict_types=1);

namespace ContextAltText\Support;

class FeatureFlags
{
    private const FILTER_ABILITIES = 'cat_enable_abilities';
    private const FILTER_MCP = 'cat_enable_mcp';
    private const FILTER_COVERAGE_TREND = 'cat_feature_coverage_trend';
    private const FILTER_WORKBENCH = 'cat_feature_workbench_enabled';
    private const FILTER_WORKBENCH_RECOGNITION = 'cat_feature_workbench_recognition';
    private const FILTER_WORKBENCH_BULK_AI = 'cat_feature_workbench_bulk_ai';

    public function abilitiesEnabled(): bool
    {
        $enabled = defined('CAT_ENABLE_ABILITIES') ? (bool) CAT_ENABLE_ABILITIES : false;
        /**
         * Filter the abilities flag so environments can enable via code.
         */
        return (bool) apply_filters(self::FILTER_ABILITIES, $enabled);
    }

    public function mcpEnabled(): bool
    {
        $enabled = defined('CAT_ENABLE_MCP') ? (bool) CAT_ENABLE_MCP : false;

        return (bool) apply_filters(self::FILTER_MCP, $enabled);
    }

    public function coverageTrendEnabled(): bool
    {
        $enabled = defined('CAT_FEATURE_COVERAGE_TREND') ? (bool) CAT_FEATURE_COVERAGE_TREND : false;

        return (bool) apply_filters(self::FILTER_COVERAGE_TREND, $enabled);
    }

    public function workbenchEnabled(): bool
    {
        $enabled = defined('CAT_FEATURE_WORKBENCH_ENABLED') ? (bool) CAT_FEATURE_WORKBENCH_ENABLED : true;

        return (bool) apply_filters(self::FILTER_WORKBENCH, $enabled);
    }

    public function workbenchRecognitionEnabled(): bool
    {
        $enabled = defined('CAT_FEATURE_WORKBENCH_RECOGNITION') ? (bool) CAT_FEATURE_WORKBENCH_RECOGNITION : false;

        return (bool) apply_filters(self::FILTER_WORKBENCH_RECOGNITION, $enabled);
    }

    public function workbenchBulkAIEnabled(): bool
    {
        $enabled = defined('CAT_FEATURE_WORKBENCH_BULK_AI') ? (bool) CAT_FEATURE_WORKBENCH_BULK_AI : false;

        return (bool) apply_filters(self::FILTER_WORKBENCH_BULK_AI, $enabled);
    }
}
