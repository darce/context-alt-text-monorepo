<?php

declare(strict_types=1);

namespace ContextAltText\Tests\Integration;

use ContextAltText\Recognition\RecognitionSettings;
use ContextAltText\Shared\Config\SettingsRepository;
use ContextAltText\Support\Env;
use PHPUnit\Framework\TestCase;

/**
 * Integration tests for configuration system.
 * Tests the interaction between .env files, environment variables, and WordPress options.
 */
class ConfigurationIntegrationTest extends TestCase
{
    private string $tempEnvFile;
    private array $originalEnv = [];
    private array $originalOptions = [];

    protected function setUp(): void
    {
        parent::setUp();

        // Save original environment
        $this->originalEnv = [
            'CAT_RECOGNITION_BASE_URL' => getenv('CAT_RECOGNITION_BASE_URL'),
            'CAT_RECOGNITION_API_KEY' => getenv('CAT_RECOGNITION_API_KEY'),
            'CAT_RECOGNITION_TIMEOUT_MS' => getenv('CAT_RECOGNITION_TIMEOUT_MS'),
            'CAT_RECOGNITION_MODEL_PROFILE' => getenv('CAT_RECOGNITION_MODEL_PROFILE'),
        ];

        // Clear environment
        foreach (array_keys($this->originalEnv) as $key) {
            putenv($key);
            unset($_ENV[$key]);
        }

        // Create temp .env file
        $this->tempEnvFile = sys_get_temp_dir() . '/.env.test.' . uniqid();

        // Save original WordPress options (if any)
        if (isset($GLOBALS['__cat_options'])) {
            $this->originalOptions = $GLOBALS['__cat_options'];
        }
        $GLOBALS['__cat_options'] = [];
    }

    protected function tearDown(): void
    {
        // Restore environment
        foreach ($this->originalEnv as $key => $value) {
            if ($value !== false) {
                putenv("$key=$value");
                $_ENV[$key] = $value;
            } else {
                putenv($key);
                unset($_ENV[$key]);
            }
        }

        // Clean up temp file
        if (file_exists($this->tempEnvFile)) {
            unlink($this->tempEnvFile);
        }

        // Restore original options
        $GLOBALS['__cat_options'] = $this->originalOptions;

        parent::tearDown();
    }

    public function test_env_file_loads_variables(): void
    {
        // Create .env file
        file_put_contents($this->tempEnvFile, implode("\n", [
            'CAT_RECOGNITION_BASE_URL=http://test-from-file.local',
            'CAT_RECOGNITION_API_KEY=secret-key-from-file',
            'CAT_RECOGNITION_TIMEOUT_MS=45000',
            'CAT_RECOGNITION_MODEL_PROFILE=custom-profile',
        ]));

        // Load .env file
        Env::load($this->tempEnvFile);

        // Verify environment variables are set
        $this->assertSame('http://test-from-file.local', getenv('CAT_RECOGNITION_BASE_URL'));
        $this->assertSame('secret-key-from-file', getenv('CAT_RECOGNITION_API_KEY'));
        $this->assertSame('45000', getenv('CAT_RECOGNITION_TIMEOUT_MS'));
        $this->assertSame('custom-profile', getenv('CAT_RECOGNITION_MODEL_PROFILE'));

        // Verify RecognitionSettings uses them
        $settings = new RecognitionSettings();
        $this->assertSame('http://test-from-file.local', $settings->getBaseUrl());
        $this->assertSame('secret-key-from-file', $settings->getApiKey());
        $this->assertSame(45000, $settings->getTimeoutMs());
        $this->assertSame('custom-profile', $settings->getModelProfile());
    }

    public function test_environment_variables_take_priority_over_database(): void
    {
        // Set database options
        $GLOBALS['__cat_options']['context_alt_text_recognition_settings'] = [
            'base_url' => 'http://from-database.local',
            'api_key' => 'db-key',
            'timeout_ms' => 20000,
            'model_profile' => 'db-profile',
        ];

        // Set environment variables
        putenv('CAT_RECOGNITION_BASE_URL=http://from-env.local');
        putenv('CAT_RECOGNITION_API_KEY=env-key');
        putenv('CAT_RECOGNITION_TIMEOUT_MS=35000');
        putenv('CAT_RECOGNITION_MODEL_PROFILE=env-profile');

        $_ENV['CAT_RECOGNITION_BASE_URL'] = 'http://from-env.local';
        $_ENV['CAT_RECOGNITION_API_KEY'] = 'env-key';
        $_ENV['CAT_RECOGNITION_TIMEOUT_MS'] = '35000';
        $_ENV['CAT_RECOGNITION_MODEL_PROFILE'] = 'env-profile';

        // Environment variables should win
        $settings = new RecognitionSettings();
        $this->assertSame('http://from-env.local', $settings->getBaseUrl());
        $this->assertSame('env-key', $settings->getApiKey());
        $this->assertSame(35000, $settings->getTimeoutMs());
        $this->assertSame('env-profile', $settings->getModelProfile());
    }

    public function test_database_options_used_when_no_environment_variables(): void
    {
        // Set database options in the new format
        $GLOBALS['__cat_options']['cat_settings'] = [
            'recognition' => [
                'baseUrl' => 'http://from-database.local',
                'apiKey' => 'db-key',
                'timeoutMs' => 25000,
                'modelProfile' => 'db-profile',
                'enabled' => true,
            ],
        ];

        // Database options should be used
        $settings = new RecognitionSettings();
        $this->assertSame('http://from-database.local', $settings->getBaseUrl());
        $this->assertSame('db-key', $settings->getApiKey());
        $this->assertSame(25000, $settings->getTimeoutMs());
        $this->assertSame('db-profile', $settings->getModelProfile());
    }

    public function test_env_file_does_not_override_existing_environment_variables(): void
    {
        // Set environment variable first
        putenv('CAT_RECOGNITION_BASE_URL=http://existing.local');
        $_ENV['CAT_RECOGNITION_BASE_URL'] = 'http://existing.local';

        // Create .env file with different value
        file_put_contents($this->tempEnvFile, 'CAT_RECOGNITION_BASE_URL=http://from-file.local');

        // Load .env file
        Env::load($this->tempEnvFile);

        // Existing environment variable should NOT be overridden
        $this->assertSame('http://existing.local', getenv('CAT_RECOGNITION_BASE_URL'));
    }

    public function test_env_file_handles_comments_and_empty_lines(): void
    {
        file_put_contents($this->tempEnvFile, implode("\n", [
            '# This is a comment',
            '',
            'CAT_RECOGNITION_BASE_URL=http://test.local',
            '  ',
            '# Another comment',
            'CAT_RECOGNITION_API_KEY=test-key',
        ]));

        Env::load($this->tempEnvFile);

        $this->assertSame('http://test.local', getenv('CAT_RECOGNITION_BASE_URL'));
        $this->assertSame('test-key', getenv('CAT_RECOGNITION_API_KEY'));
    }

    public function test_env_file_handles_quoted_values(): void
    {
        file_put_contents($this->tempEnvFile, implode("\n", [
            'CAT_RECOGNITION_BASE_URL="http://quoted.local"',
            "CAT_RECOGNITION_API_KEY='single-quoted'",
            'CAT_RECOGNITION_MODEL_PROFILE=unquoted',
        ]));

        Env::load($this->tempEnvFile);

        // Quotes should be stripped
        $this->assertSame('http://quoted.local', getenv('CAT_RECOGNITION_BASE_URL'));
        $this->assertSame('single-quoted', getenv('CAT_RECOGNITION_API_KEY'));
        $this->assertSame('unquoted', getenv('CAT_RECOGNITION_MODEL_PROFILE'));
    }

    public function test_env_file_handles_spaces_around_equals(): void
    {
        file_put_contents($this->tempEnvFile, implode("\n", [
            'CAT_RECOGNITION_BASE_URL = http://test.local',
            'CAT_RECOGNITION_API_KEY= test-key ',
            ' CAT_RECOGNITION_MODEL_PROFILE =test-profile',
        ]));

        Env::load($this->tempEnvFile);

        $this->assertSame('http://test.local', getenv('CAT_RECOGNITION_BASE_URL'));
        $this->assertSame('test-key', getenv('CAT_RECOGNITION_API_KEY'));
        $this->assertSame('test-profile', getenv('CAT_RECOGNITION_MODEL_PROFILE'));
    }

    public function test_missing_env_file_does_not_error(): void
    {
        // Should not throw exception
        Env::load('/non/existent/.env');

        // Settings should still work with database fallback
        $GLOBALS['__cat_options']['context_alt_text_recognition_settings'] = [
            'base_url' => 'http://from-database.local',
        ];

        $settings = new RecognitionSettings();
        $this->assertSame('http://from-database.local', $settings->getBaseUrl());
    }

    public function test_malformed_env_lines_are_skipped(): void
    {
        file_put_contents($this->tempEnvFile, implode("\n", [
            'VALID_KEY=valid-value',
            'INVALID_LINE_NO_EQUALS',
            'ALSO=VALID=WITH=MULTIPLE=EQUALS',
            '=VALUE_WITHOUT_KEY',
            'CAT_RECOGNITION_BASE_URL=http://test.local',
        ]));

        Env::load($this->tempEnvFile);

        $this->assertSame('valid-value', getenv('VALID_KEY'));
        $this->assertSame('VALID=WITH=MULTIPLE=EQUALS', getenv('ALSO'));
        $this->assertSame('http://test.local', getenv('CAT_RECOGNITION_BASE_URL'));
        $this->assertFalse(getenv('INVALID_LINE_NO_EQUALS'));
    }

    public function test_is_configured_returns_false_when_no_url(): void
    {
        $settings = new RecognitionSettings();
        $this->assertFalse($settings->isConfigured());
    }

    public function test_is_configured_returns_true_with_valid_url(): void
    {
        putenv('CAT_RECOGNITION_BASE_URL=http://test.local');
        $_ENV['CAT_RECOGNITION_BASE_URL'] = 'http://test.local';

        $settings = new RecognitionSettings();
        $this->assertTrue($settings->isConfigured());
    }

    public function test_complete_configuration_flow_env_to_settings(): void
    {
        // Simulate complete setup flow
        file_put_contents($this->tempEnvFile, implode("\n", [
            '# Recognition Service Configuration',
            'CAT_RECOGNITION_BASE_URL=http://localhost:7860',
            'CAT_RECOGNITION_TIMEOUT_MS=30000',
            'CAT_RECOGNITION_API_KEY=',
            'CAT_RECOGNITION_MODEL_PROFILE=insightface_w600k',
        ]));

        // Load environment
        Env::load($this->tempEnvFile);

        // Create settings instance
        $settings = new RecognitionSettings();

        // Verify all settings are accessible
        $this->assertSame('http://localhost:7860', $settings->getBaseUrl());
        $this->assertSame(30000, $settings->getTimeoutMs());
        $this->assertNull($settings->getApiKey()); // Empty string becomes null
        $this->assertSame('insightface_w600k', $settings->getModelProfile());
        $this->assertTrue($settings->isConfigured());
    }
}
