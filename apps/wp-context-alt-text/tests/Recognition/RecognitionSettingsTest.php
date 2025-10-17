<?php

declare(strict_types=1);

namespace ContextAltText\Tests\Recognition;

use ContextAltText\Recognition\RecognitionSettings;
use ContextAltText\Shared\Config\SettingsRepository;
use PHPUnit\Framework\TestCase;

/**
 * Tests for RecognitionSettings configuration priority and validation.
 * 
 * Priority order (12-factor app principle):
 * 1. Environment variable (highest priority)
 * 2. WordPress database option (fallback)
 * 3. Default value (where applicable)
 */
class RecognitionSettingsTest extends TestCase
{
    private RecognitionSettings $settings;
    private SettingsRepository $mockRepository;

    protected function setUp(): void
    {
        parent::setUp();

        // Clear environment variables before each test
        $this->clearEnvVars();

        // Create mock repository
        $this->mockRepository = $this->createMock(SettingsRepository::class);
        $this->settings = new RecognitionSettings($this->mockRepository);
    }

    protected function tearDown(): void
    {
        // Clean up environment variables after each test
        $this->clearEnvVars();
        parent::tearDown();
    }

    private function clearEnvVars(): void
    {
        $vars = [
            'CAT_RECOGNITION_BASE_URL',
            'CAT_RECOGNITION_API_KEY',
            'CAT_RECOGNITION_TIMEOUT_MS',
            'CAT_RECOGNITION_MODEL_PROFILE',
        ];

        foreach ($vars as $var) {
            putenv($var);
            unset($_ENV[$var]);
        }
    }

    private function setEnv(string $name, string $value): void
    {
        putenv("$name=$value");
        $_ENV[$name] = $value;
    }

    // ============================================================================
    // Base URL Tests
    // ============================================================================

    public function test_getBaseUrl_returns_null_when_no_config(): void
    {
        $this->mockRepository
            ->method('getRecognitionSettings')
            ->willReturn([]);

        $result = $this->settings->getBaseUrl();

        $this->assertNull($result);
    }

    public function test_getBaseUrl_prioritizes_env_over_database(): void
    {
        $this->setEnv('CAT_RECOGNITION_BASE_URL', 'http://env-service:8080');

        $this->mockRepository
            ->method('getRecognitionSettings')
            ->willReturn(['baseUrl' => 'http://db-service:9090']);

        $result = $this->settings->getBaseUrl();

        $this->assertSame('http://env-service:8080', $result);
    }

    public function test_getBaseUrl_falls_back_to_database_when_no_env(): void
    {
        $this->mockRepository
            ->method('getRecognitionSettings')
            ->willReturn(['baseUrl' => 'http://db-service:9090']);

        $result = $this->settings->getBaseUrl();

        $this->assertSame('http://db-service:9090', $result);
    }

    public function test_getBaseUrl_trims_trailing_slash(): void
    {
        $this->setEnv('CAT_RECOGNITION_BASE_URL', 'http://service:8080/');

        $this->mockRepository
            ->method('getRecognitionSettings')
            ->willReturn([]);

        $result = $this->settings->getBaseUrl();

        $this->assertSame('http://service:8080', $result);
    }

    public function test_getBaseUrl_validates_url_format(): void
    {
        $this->setEnv('CAT_RECOGNITION_BASE_URL', 'not-a-valid-url');

        $this->mockRepository
            ->method('getRecognitionSettings')
            ->willReturn([]);

        $result = $this->settings->getBaseUrl();

        $this->assertNull($result);
    }

    public function test_getBaseUrl_trims_whitespace(): void
    {
        $this->setEnv('CAT_RECOGNITION_BASE_URL', '  http://service:8080  ');

        $this->mockRepository
            ->method('getRecognitionSettings')
            ->willReturn([]);

        $result = $this->settings->getBaseUrl();

        $this->assertSame('http://service:8080', $result);
    }

    public function test_getBaseUrl_handles_empty_string(): void
    {
        $this->setEnv('CAT_RECOGNITION_BASE_URL', '');

        $this->mockRepository
            ->method('getRecognitionSettings')
            ->willReturn(['baseUrl' => '']);

        $result = $this->settings->getBaseUrl();

        $this->assertNull($result);
    }

    // ============================================================================
    // API Key Tests
    // ============================================================================

    public function test_getApiKey_returns_null_when_no_config(): void
    {
        $this->mockRepository
            ->method('getRecognitionSettings')
            ->willReturn([]);

        $result = $this->settings->getApiKey();

        $this->assertNull($result);
    }

    public function test_getApiKey_prioritizes_env_over_database(): void
    {
        $this->setEnv('CAT_RECOGNITION_API_KEY', 'env-api-key-123');

        $this->mockRepository
            ->method('getRecognitionSettings')
            ->willReturn(['apiKey' => 'db-api-key-456']);

        $result = $this->settings->getApiKey();

        $this->assertSame('env-api-key-123', $result);
    }

    public function test_getApiKey_falls_back_to_database_when_no_env(): void
    {
        $this->mockRepository
            ->method('getRecognitionSettings')
            ->willReturn(['apiKey' => 'db-api-key-456']);

        $result = $this->settings->getApiKey();

        $this->assertSame('db-api-key-456', $result);
    }

    public function test_getApiKey_trims_whitespace(): void
    {
        $this->setEnv('CAT_RECOGNITION_API_KEY', '  my-api-key  ');

        $this->mockRepository
            ->method('getRecognitionSettings')
            ->willReturn([]);

        $result = $this->settings->getApiKey();

        $this->assertSame('my-api-key', $result);
    }

    public function test_getApiKey_returns_null_for_empty_string(): void
    {
        $this->setEnv('CAT_RECOGNITION_API_KEY', '');

        $this->mockRepository
            ->method('getRecognitionSettings')
            ->willReturn(['apiKey' => '']);

        $result = $this->settings->getApiKey();

        $this->assertNull($result);
    }

    // ============================================================================
    // Timeout Tests
    // ============================================================================

    public function test_getTimeoutMs_returns_default_when_no_config(): void
    {
        $this->mockRepository
            ->method('getRecognitionSettings')
            ->willReturn([]);

        $result = $this->settings->getTimeoutMs();

        $this->assertSame(15000, $result);
    }

    public function test_getTimeoutMs_prioritizes_env_over_database(): void
    {
        $this->setEnv('CAT_RECOGNITION_TIMEOUT_MS', '25000');

        $this->mockRepository
            ->method('getRecognitionSettings')
            ->willReturn(['timeoutMs' => 30000]);

        $result = $this->settings->getTimeoutMs();

        $this->assertSame(25000, $result);
    }

    public function test_getTimeoutMs_falls_back_to_database_when_no_env(): void
    {
        $this->mockRepository
            ->method('getRecognitionSettings')
            ->willReturn(['timeoutMs' => 30000]);

        $result = $this->settings->getTimeoutMs();

        $this->assertSame(30000, $result);
    }

    public function test_getTimeoutMs_returns_default_for_invalid_timeout(): void
    {
        $this->setEnv('CAT_RECOGNITION_TIMEOUT_MS', '0');

        $this->mockRepository
            ->method('getRecognitionSettings')
            ->willReturn([]);

        $result = $this->settings->getTimeoutMs();

        $this->assertSame(15000, $result);
    }

    public function test_getTimeoutMs_returns_default_for_negative_timeout(): void
    {
        $this->setEnv('CAT_RECOGNITION_TIMEOUT_MS', '-5000');

        $this->mockRepository
            ->method('getRecognitionSettings')
            ->willReturn([]);

        $result = $this->settings->getTimeoutMs();

        $this->assertSame(15000, $result);
    }

    public function test_getTimeoutMs_handles_non_numeric_string(): void
    {
        $this->setEnv('CAT_RECOGNITION_TIMEOUT_MS', 'not-a-number');

        $this->mockRepository
            ->method('getRecognitionSettings')
            ->willReturn([]);

        $result = $this->settings->getTimeoutMs();

        // PHP's (int) cast of non-numeric string returns 0, which triggers default
        $this->assertSame(15000, $result);
    }

    // ============================================================================
    // Model Profile Tests
    // ============================================================================

    public function test_getModelProfile_returns_null_when_no_config(): void
    {
        $this->mockRepository
            ->method('getRecognitionSettings')
            ->willReturn([]);

        $result = $this->settings->getModelProfile();

        $this->assertNull($result);
    }

    public function test_getModelProfile_prioritizes_env_over_database(): void
    {
        $this->setEnv('CAT_RECOGNITION_MODEL_PROFILE', 'env-profile');

        $this->mockRepository
            ->method('getRecognitionSettings')
            ->willReturn(['modelProfile' => 'db-profile']);

        $result = $this->settings->getModelProfile();

        $this->assertSame('env-profile', $result);
    }

    public function test_getModelProfile_falls_back_to_database_when_no_env(): void
    {
        $this->mockRepository
            ->method('getRecognitionSettings')
            ->willReturn(['modelProfile' => 'db-profile']);

        $result = $this->settings->getModelProfile();

        $this->assertSame('db-profile', $result);
    }

    public function test_getModelProfile_trims_whitespace(): void
    {
        $this->setEnv('CAT_RECOGNITION_MODEL_PROFILE', '  fast-model  ');

        $this->mockRepository
            ->method('getRecognitionSettings')
            ->willReturn([]);

        $result = $this->settings->getModelProfile();

        $this->assertSame('fast-model', $result);
    }

    public function test_getModelProfile_returns_null_for_empty_string(): void
    {
        $this->setEnv('CAT_RECOGNITION_MODEL_PROFILE', '');

        $this->mockRepository
            ->method('getRecognitionSettings')
            ->willReturn(['modelProfile' => '']);

        $result = $this->settings->getModelProfile();

        $this->assertNull($result);
    }

    // ============================================================================
    // isConfigured Tests
    // ============================================================================

    public function test_isConfigured_returns_true_when_base_url_set(): void
    {
        $this->setEnv('CAT_RECOGNITION_BASE_URL', 'http://service:8080');

        $this->mockRepository
            ->method('getRecognitionSettings')
            ->willReturn([]);

        $result = $this->settings->isConfigured();

        $this->assertTrue($result);
    }

    public function test_isConfigured_returns_false_when_no_base_url(): void
    {
        $this->mockRepository
            ->method('getRecognitionSettings')
            ->willReturn([]);

        $result = $this->settings->isConfigured();

        $this->assertFalse($result);
    }

    public function test_isConfigured_returns_false_when_base_url_invalid(): void
    {
        $this->setEnv('CAT_RECOGNITION_BASE_URL', 'not-a-url');

        $this->mockRepository
            ->method('getRecognitionSettings')
            ->willReturn([]);

        $result = $this->settings->isConfigured();

        $this->assertFalse($result);
    }

    // ============================================================================
    // Integration / Edge Case Tests
    // ============================================================================

    public function test_all_settings_can_coexist(): void
    {
        $this->setEnv('CAT_RECOGNITION_BASE_URL', 'http://service:8080');
        $this->setEnv('CAT_RECOGNITION_API_KEY', 'test-key-123');
        $this->setEnv('CAT_RECOGNITION_TIMEOUT_MS', '45000');
        $this->setEnv('CAT_RECOGNITION_MODEL_PROFILE', 'production-model');

        $this->mockRepository
            ->method('getRecognitionSettings')
            ->willReturn([]);

        $this->assertSame('http://service:8080', $this->settings->getBaseUrl());
        $this->assertSame('test-key-123', $this->settings->getApiKey());
        $this->assertSame(45000, $this->settings->getTimeoutMs());
        $this->assertSame('production-model', $this->settings->getModelProfile());
        $this->assertTrue($this->settings->isConfigured());
    }

    public function test_env_vars_completely_override_database(): void
    {
        $this->setEnv('CAT_RECOGNITION_BASE_URL', 'http://env:1111');
        $this->setEnv('CAT_RECOGNITION_API_KEY', 'env-key');
        $this->setEnv('CAT_RECOGNITION_TIMEOUT_MS', '11111');
        $this->setEnv('CAT_RECOGNITION_MODEL_PROFILE', 'env-profile');

        $this->mockRepository
            ->method('getRecognitionSettings')
            ->willReturn([
                'baseUrl' => 'http://db:2222',
                'apiKey' => 'db-key',
                'timeoutMs' => 22222,
                'modelProfile' => 'db-profile',
            ]);

        // All should come from environment
        $this->assertSame('http://env:1111', $this->settings->getBaseUrl());
        $this->assertSame('env-key', $this->settings->getApiKey());
        $this->assertSame(11111, $this->settings->getTimeoutMs());
        $this->assertSame('env-profile', $this->settings->getModelProfile());
    }

    public function test_database_used_when_env_vars_not_set(): void
    {
        $this->mockRepository
            ->method('getRecognitionSettings')
            ->willReturn([
                'baseUrl' => 'http://db:3333',
                'apiKey' => 'db-key',
                'timeoutMs' => 33333,
                'modelProfile' => 'db-profile',
            ]);

        // All should come from database
        $this->assertSame('http://db:3333', $this->settings->getBaseUrl());
        $this->assertSame('db-key', $this->settings->getApiKey());
        $this->assertSame(33333, $this->settings->getTimeoutMs());
        $this->assertSame('db-profile', $this->settings->getModelProfile());
    }

    public function test_mixed_env_and_database_sources(): void
    {
        // Set only some env vars
        $this->setEnv('CAT_RECOGNITION_BASE_URL', 'http://env:4444');
        $this->setEnv('CAT_RECOGNITION_TIMEOUT_MS', '44444');

        $this->mockRepository
            ->method('getRecognitionSettings')
            ->willReturn([
                'baseUrl' => 'http://db:5555',
                'apiKey' => 'db-key',
                'timeoutMs' => 55555,
                'modelProfile' => 'db-profile',
            ]);

        // baseUrl and timeout from env, apiKey and modelProfile from db
        $this->assertSame('http://env:4444', $this->settings->getBaseUrl());
        $this->assertSame('db-key', $this->settings->getApiKey());
        $this->assertSame(44444, $this->settings->getTimeoutMs());
        $this->assertSame('db-profile', $this->settings->getModelProfile());
    }

    public function test_supports_https_urls(): void
    {
        $this->setEnv('CAT_RECOGNITION_BASE_URL', 'https://secure-service:443');

        $this->mockRepository
            ->method('getRecognitionSettings')
            ->willReturn([]);

        $result = $this->settings->getBaseUrl();

        $this->assertSame('https://secure-service:443', $result);
    }

    public function test_supports_localhost_urls(): void
    {
        $this->setEnv('CAT_RECOGNITION_BASE_URL', 'http://localhost:7860');

        $this->mockRepository
            ->method('getRecognitionSettings')
            ->willReturn([]);

        $result = $this->settings->getBaseUrl();

        $this->assertSame('http://localhost:7860', $result);
    }
}
