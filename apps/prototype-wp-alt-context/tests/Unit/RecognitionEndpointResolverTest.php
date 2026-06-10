<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\RecognitionEndpointResolver;
use AltContext\Tests\TestCase;

/**
 * @covers \AltContext\Api\RecognitionEndpointResolver
 */
class RecognitionEndpointResolverTest extends TestCase
{
    private RecognitionEndpointResolver $resolver;

    protected function setUp(): void
    {
        parent::setUp();
        $this->resolver = new RecognitionEndpointResolver();
    }

    public function testDefaultsToLocalTargetWhenNothingConfigured(): void
    {
        $snapshot = $this->resolver->resolve_settings_snapshot();

        $this->assertSame('local', $snapshot['recognition_source']);
        $this->assertSame('http://localhost:8000', $snapshot['local_url']);
        $this->assertSame('http://localhost:8000', $snapshot['effective_target_url']);
        $this->assertSame('local', $snapshot['effective_target_mode']);
    }

    public function testLocalModeIgnoresStoredServiceUrlForEffectiveTarget(): void
    {
        $this->setOption('acx_recognition_url', 'https://api.altcontext.com');
        $this->setOption('acx_recognition_source', 'local');

        $snapshot = $this->resolver->resolve_settings_snapshot();

        $this->assertSame('local', $snapshot['recognition_source']);
        $this->assertSame('https://api.altcontext.com', $snapshot['service_url']);
        $this->assertSame('http://localhost:8000', $snapshot['effective_target_url']);
    }

    public function testCustomLocalUrlOptionIsUsedInLocalMode(): void
    {
        $this->setOption('acx_recognition_source', 'local');
        $this->setOption('acx_recognition_local_url', 'http://localhost:8001');

        $snapshot = $this->resolver->resolve_settings_snapshot();

        $this->assertSame('http://localhost:8001', $snapshot['local_url']);
        $this->assertSame('http://localhost:8001', $snapshot['effective_target_url']);
        $this->assertSame('http://localhost:8001', $this->resolver->get_effective_base_url());
    }

    public function testServiceModeUsesStoredServiceUrl(): void
    {
        $this->setOption('acx_recognition_url', 'https://api.altcontext.com');
        $this->setOption('acx_recognition_source', 'service');

        $snapshot = $this->resolver->resolve_settings_snapshot();

        $this->assertSame('service', $snapshot['recognition_source']);
        $this->assertSame('https://api.altcontext.com', $snapshot['effective_target_url']);
    }
}
