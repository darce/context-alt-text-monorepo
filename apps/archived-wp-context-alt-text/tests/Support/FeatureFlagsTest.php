<?php

declare(strict_types=1);

namespace ContextAltText\Tests\Support;

use ContextAltText\Support\FeatureFlags;
use PHPUnit\Framework\TestCase;

class FeatureFlagsTest extends TestCase
{
    private FeatureFlags $featureFlags;

    protected function setUp(): void
    {
        parent::setUp();

        // Reset global state completely
        $GLOBALS['__cat_options'] = [];
        $GLOBALS['__cat_filters'] = [];

        // Clear ALL environment variables that might affect tests
        putenv('CAT_RECOGNITION_BASE_URL');
        putenv('CAT_FEATURE_WORKBENCH_RECOGNITION');
        putenv('CAT_FEATURE_ROSTER_UI_ENABLED');
        unset($_ENV['CAT_RECOGNITION_BASE_URL']);
        unset($_ENV['CAT_FEATURE_WORKBENCH_RECOGNITION']);
        unset($_ENV['CAT_FEATURE_ROSTER_UI_ENABLED']);

        $this->featureFlags = new FeatureFlags();
    }

    protected function tearDown(): void
    {
        parent::tearDown();

        // Ensure complete cleanup
        $GLOBALS['__cat_options'] = [];
        $GLOBALS['__cat_filters'] = [];
        putenv('CAT_RECOGNITION_BASE_URL');
        putenv('CAT_FEATURE_WORKBENCH_RECOGNITION');
        putenv('CAT_FEATURE_ROSTER_UI_ENABLED');
        unset($_ENV['CAT_RECOGNITION_BASE_URL']);
        unset($_ENV['CAT_FEATURE_WORKBENCH_RECOGNITION']);
        unset($_ENV['CAT_FEATURE_ROSTER_UI_ENABLED']);
    }

    // ========================================================================
    // AUTO-ENABLE BEHAVIOR
    // ========================================================================

    public function test_workbench_recognition_auto_enables_when_service_configured(): void
    {
        // Configure recognition service via environment variable
        putenv('CAT_RECOGNITION_BASE_URL=http://localhost:7860');
        $_ENV['CAT_RECOGNITION_BASE_URL'] = 'http://localhost:7860';

        $featureFlags = new FeatureFlags();

        // Should auto-enable
        $this->assertTrue($featureFlags->workbenchRecognitionEnabled());
    }

    public function test_workbench_recognition_disabled_when_service_not_configured(): void
    {
        // No recognition service configured
        $this->assertFalse($this->featureFlags->workbenchRecognitionEnabled());
    }

    public function test_roster_ui_auto_enables_when_service_configured(): void
    {
        // Configure recognition service
        putenv('CAT_RECOGNITION_BASE_URL=http://localhost:7860');
        $_ENV['CAT_RECOGNITION_BASE_URL'] = 'http://localhost:7860';

        $featureFlags = new FeatureFlags();

        // Should auto-enable
        $this->assertTrue($featureFlags->rosterUiEnabled());
    }

    public function test_roster_ui_disabled_when_service_not_configured(): void
    {
        // No recognition service configured
        $this->assertFalse($this->featureFlags->rosterUiEnabled());
    }

    // ========================================================================
    // MANUAL OVERRIDE VIA CONSTANTS
    // Note: Cannot test constant overrides in PHPUnit since constants can't be undefined
    // These are tested manually or via integration tests
    // ========================================================================

    // ========================================================================
    // FILTER HOOKS
    // ========================================================================

    public function test_workbench_recognition_respects_filter_hooks(): void
    {
        // Configure service
        putenv('CAT_RECOGNITION_BASE_URL=http://localhost:7860');
        $_ENV['CAT_RECOGNITION_BASE_URL'] = 'http://localhost:7860';

        // Add filter using WordPress stub format (priority => callbacks array)
        $GLOBALS['__cat_filters']['cat_feature_workbench_recognition'][10] = [
            ['callback' => fn($value) => false, 'accepted_args' => 1]
        ];

        $featureFlags = new FeatureFlags();

        // Filter should override auto-enable
        $this->assertFalse($featureFlags->workbenchRecognitionEnabled());
    }

    public function test_roster_ui_respects_filter_hooks(): void
    {
        // Set up environment so auto-enable would normally trigger
        putenv('CAT_RECOGNITION_BASE_URL=http://localhost:7860');
        $_ENV['CAT_RECOGNITION_BASE_URL'] = 'http://localhost:7860';

        // Add filter to override the auto-enable behavior
        add_filter('cat_feature_roster_ui_enabled', function ($enabled) {
            return false; // Force disable
        }, 10, 1);

        $featureFlags = new FeatureFlags();

        // Filter should override auto-enable
        $this->assertFalse($featureFlags->rosterUiEnabled());
    }

    // ========================================================================
    // SERVICE CONFIGURATION DETECTION
    // ========================================================================

    public function test_recognizes_service_configured_via_environment_variable(): void
    {
        putenv('CAT_RECOGNITION_BASE_URL=http://localhost:7860');
        $_ENV['CAT_RECOGNITION_BASE_URL'] = 'http://localhost:7860';

        $featureFlags = new FeatureFlags();

        // Indirect test via auto-enable
        $this->assertTrue($featureFlags->workbenchRecognitionEnabled());
    }

    public function test_recognizes_service_configured_via_database_option(): void
    {
        // Configure via WordPress option (database)
        $GLOBALS['__cat_options']['cat_settings'] = [
            'recognition' => [
                'baseUrl' => 'http://localhost:7860',
                'timeoutMs' => 30000,
                'enabled' => true,
            ],
        ];

        $featureFlags = new FeatureFlags();

        // Indirect test via auto-enable
        $this->assertTrue($featureFlags->workbenchRecognitionEnabled());
    }

    public function test_recognizes_service_configured_via_new_settings_format(): void
    {
        // Configure via new settings format (WordPress stores arrays, not JSON strings)
        // Note: Must set enabled=true for database config (env var doesn't require this)
        $GLOBALS['__cat_options']['cat_settings'] = [
            'recognition' => [
                'baseUrl' => 'http://localhost:7860',
                'timeoutMs' => 30000,
                'enabled' => true,  // Required for database-based configuration
            ]
        ];

        $featureFlags = new FeatureFlags();

        // Indirect test via auto-enable
        $this->assertTrue($featureFlags->workbenchRecognitionEnabled());
    }

    public function test_empty_service_url_does_not_trigger_auto_enable(): void
    {
        // Set environment variable to empty string
        putenv('CAT_RECOGNITION_BASE_URL=');
        $_ENV['CAT_RECOGNITION_BASE_URL'] = '';

        $featureFlags = new FeatureFlags();

        // Should NOT auto-enable with empty URL
        $this->assertFalse($featureFlags->workbenchRecognitionEnabled());
    }

    public function test_invalid_service_url_does_not_trigger_auto_enable(): void
    {
        // Set environment variable to invalid URL
        putenv('CAT_RECOGNITION_BASE_URL=not-a-valid-url');
        $_ENV['CAT_RECOGNITION_BASE_URL'] = 'not-a-valid-url';

        $featureFlags = new FeatureFlags();

        // Should NOT auto-enable with invalid URL
        $this->assertFalse($featureFlags->workbenchRecognitionEnabled());
    }

    // ========================================================================
    // EDGE CASES
    // ========================================================================

    public function test_whitespace_only_url_does_not_trigger_auto_enable(): void
    {
        putenv('CAT_RECOGNITION_BASE_URL=   ');
        $_ENV['CAT_RECOGNITION_BASE_URL'] = '   ';

        $featureFlags = new FeatureFlags();

        $this->assertFalse($featureFlags->workbenchRecognitionEnabled());
    }

    public function test_url_with_trailing_slash_still_triggers_auto_enable(): void
    {
        putenv('CAT_RECOGNITION_BASE_URL=http://localhost:7860/');
        $_ENV['CAT_RECOGNITION_BASE_URL'] = 'http://localhost:7860/';

        $featureFlags = new FeatureFlags();

        // Should auto-enable (RecognitionSettings normalizes trailing slash)
        $this->assertTrue($featureFlags->workbenchRecognitionEnabled());
    }

    public function test_https_url_triggers_auto_enable(): void
    {
        putenv('CAT_RECOGNITION_BASE_URL=https://recognition.example.com');
        $_ENV['CAT_RECOGNITION_BASE_URL'] = 'https://recognition.example.com';

        $featureFlags = new FeatureFlags();

        $this->assertTrue($featureFlags->workbenchRecognitionEnabled());
    }
}
