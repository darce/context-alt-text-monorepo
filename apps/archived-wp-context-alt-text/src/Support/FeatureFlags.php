<?php

declare(strict_types=1);

namespace ContextAltText\Support;

use ContextAltText\Shared\Config\SettingsRepository;

use const FILTER_VALIDATE_BOOLEAN;
use const FILTER_VALIDATE_URL;
use function apply_filters;
use function defined;
use function filter_var;
use function getenv;
use function trim;
use function is_string;

class FeatureFlags
{
    private const FILTER_ABILITIES = 'cat_enable_abilities';
    private const FILTER_MCP = 'cat_enable_mcp';
    private const FILTER_COVERAGE_TREND = 'cat_feature_coverage_trend';
    private const FILTER_WORKBENCH = 'cat_feature_workbench_enabled';
    private const FILTER_WORKBENCH_RECOGNITION = 'cat_feature_workbench_recognition';
    private const FILTER_WORKBENCH_BULK_AI = 'cat_feature_workbench_bulk_ai';
    private const FILTER_ROSTER_UI = 'cat_feature_roster_ui_enabled';
    private SettingsRepository $settingsRepository;

    public function __construct(?SettingsRepository $settingsRepository = null)
    {
        $this->settingsRepository = $settingsRepository ?? new SettingsRepository();
    }

    public function abilitiesEnabled(): bool
    {
        $enabled = $this->boolFromConstant('CAT_ENABLE_ABILITIES', false);

        if (!$enabled && $this->isRecognitionServiceConfigured()) {
            $enabled = true;
        }

        /**
         * Filter the abilities flag so environments can enable via code.
         */
        return (bool) apply_filters(self::FILTER_ABILITIES, $enabled);
    }

    public function rosterUiEnabled(): bool
    {
        // Default to false, but can be enabled via constant
        $enabled = $this->boolFromConstant('CAT_FEATURE_ROSTER_UI_ENABLED', false);

        $option = null;
        if (function_exists('get_option')) {
            $option = get_option('cat_feature_roster_ui_enabled', null);
        }

        if ($option !== null) {
            $enabled = filter_var($option, FILTER_VALIDATE_BOOLEAN); // allow truthy string values.
        }

        // Auto-enable if recognition service is configured (unless explicitly disabled)
        if (!$enabled && $this->isRecognitionServiceConfigured()) {
            $enabled = true;
        }

        return (bool) apply_filters(self::FILTER_ROSTER_UI, $enabled);
    }

    public function mcpEnabled(): bool
    {
        $enabled = $this->boolFromConstant('CAT_ENABLE_MCP', false);

        return (bool) apply_filters(self::FILTER_MCP, $enabled);
    }

    public function coverageTrendEnabled(): bool
    {
        $enabled = $this->boolFromConstant('CAT_FEATURE_COVERAGE_TREND', false);

        return (bool) apply_filters(self::FILTER_COVERAGE_TREND, $enabled);
    }

    public function workbenchEnabled(): bool
    {
        $enabled = $this->boolFromConstant('CAT_FEATURE_WORKBENCH_ENABLED', true);

        return (bool) apply_filters(self::FILTER_WORKBENCH, $enabled);
    }

    public function workbenchRecognitionEnabled(): bool
    {
        // Default to false, but can be enabled via constant
        $enabled = $this->boolFromConstant('CAT_FEATURE_WORKBENCH_RECOGNITION', false);

        // Auto-enable if recognition service is configured (unless explicitly disabled)
        if (!$enabled && $this->isRecognitionServiceConfigured()) {
            $enabled = true;
        }

        return (bool) apply_filters(self::FILTER_WORKBENCH_RECOGNITION, $enabled);
    }

    /**
     * Check if recognition service is configured.
     */
    private function isRecognitionServiceConfigured(): bool
    {
        $settings = $this->settingsRepository->getRecognitionSettings();

        $baseUrl = trim((string) ($settings['baseUrl'] ?? ''));
        $enabled = (bool) ($settings['enabled'] ?? false);

        if ($baseUrl !== '' && $enabled && filter_var($baseUrl, FILTER_VALIDATE_URL) !== false) {
            return true;
        }

        // Allow environments to opt-in entirely via environment variables.
        $envUrl = getenv('CAT_RECOGNITION_BASE_URL');
        if ($envUrl !== false && is_string($envUrl)) {
            $envUrl = trim($envUrl);
            if ($envUrl !== '' && filter_var($envUrl, FILTER_VALIDATE_URL) !== false) {
                return true;
            }
        }

        return false;
    }

    public function workbenchBulkAIEnabled(): bool
    {
        $enabled = $this->boolFromConstant('CAT_FEATURE_WORKBENCH_BULK_AI', false);

        return (bool) apply_filters(self::FILTER_WORKBENCH_BULK_AI, $enabled);
    }

    private function boolFromConstant(string $constant, bool $default): bool
    {
        if (!defined($constant)) {
            return $default;
        }

        return (bool) \constant($constant);
    }
}
