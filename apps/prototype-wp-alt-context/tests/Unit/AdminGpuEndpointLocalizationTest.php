<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Admin\Admin;
use AltContext\Tests\TestCase;
use ReflectionClass;

/**
 * RED: the SPA localize payload must carry the GPU REST endpoints the browser
 * reads (gpuApi.ts fetchGpuStatus -> getEndpoint('recognitionGpuStatus') and
 * postGpuIntent -> getEndpoint('recognitionGpuIntent')). Without these keys
 * getEndpoint() throws before any HTTP request is sent.
 *
 * @covers \AltContext\Admin\Admin
 */
class AdminGpuEndpointLocalizationTest extends TestCase
{
    private Admin $admin;

    protected function setUp(): void
    {
        parent::setUp();
        $_GET = [];
        $this->admin = new Admin();
    }

    /**
     * Helper to invoke private/protected methods.
     */
    private function invokePrivateMethod(object $object, string $methodName, array $args = []): mixed
    {
        $reflection = new ReflectionClass($object);
        $method = $reflection->getMethod($methodName);
        return $method->invokeArgs($object, $args);
    }

    /**
     * @return array<string, mixed>
     */
    private function localizeSpaConfig(): array
    {
        $this->invokePrivateMethod($this->admin, 'localize_spa_config', ['test-handle']);

        $localized = $GLOBALS['__ac_localized_scripts']['test-handle']['AltContextAdmin'] ?? null;
        $this->assertIsArray($localized);

        return $localized;
    }

    /**
     * Control: an existing consumed endpoint already resolves through the same
     * harness. If this fails the fixture is broken, not the GPU wiring.
     */
    public function testControlExistingRecognitionEndpointResolvesThroughHarness(): void
    {
        $localized = $this->localizeSpaConfig();

        $this->assertSame(
            'http://example.test/wp-json/acx/v1/recognition/media-identities',
            $localized['endpoints']['recognitionMediaIdentities'] ?? null
        );
    }

    /**
     * Canonical status route registered by GpuControlController::register_routes
     * (acx/v1 + /recognition/gpu/status).
     */
    public function testLocalizeSpaConfigIncludesCanonicalGpuStatusEndpoint(): void
    {
        $localized = $this->localizeSpaConfig();

        $this->assertSame(
            'http://example.test/wp-json/acx/v1/recognition/gpu/status',
            $localized['endpoints']['recognitionGpuStatus'] ?? null
        );
    }

    /**
     * Canonical intent route registered by GpuControlController::register_routes
     * (acx/v1 + /recognition/gpu/intent).
     */
    public function testLocalizeSpaConfigIncludesCanonicalGpuIntentEndpoint(): void
    {
        $localized = $this->localizeSpaConfig();

        $this->assertSame(
            'http://example.test/wp-json/acx/v1/recognition/gpu/intent',
            $localized['endpoints']['recognitionGpuIntent'] ?? null
        );
    }

    /**
     * The browser must call the WordPress REST proxy, never the backend
     * /scene/gpu/* paths directly. Both GPU endpoints must be same-origin
     * rest_url() values.
     */
    public function testGpuEndpointsAreSameOriginRestRoutesNotBackendScenePaths(): void
    {
        $localized = $this->localizeSpaConfig();
        $endpoints = $localized['endpoints'] ?? [];

        foreach (['recognitionGpuStatus', 'recognitionGpuIntent'] as $key) {
            $url = $endpoints[$key] ?? null;

            $this->assertIsString($url, $key);
            $this->assertStringStartsWith('http://example.test/wp-json/acx/v1/', $url);
            $this->assertStringNotContainsString('/scene/', $url);
        }
    }
}
