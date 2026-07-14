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

    public function testDefaultsToServiceTargetWhenNothingConfigured(): void
    {
        $snapshot = $this->resolver->resolve_settings_snapshot();

        $this->assertSame('service', $snapshot['recognition_source']);
        $this->assertSame('default', $snapshot['recognition_source_source']);
        $this->assertSame('service', $snapshot['effective_target_mode']);
        $this->assertSame('', $snapshot['effective_target_url']);
    }

    public function testServiceModeUsesStoredServiceUrl(): void
    {
        $this->setOption('acx_recognition_url', 'https://api.altcontext.com');

        $snapshot = $this->resolver->resolve_settings_snapshot();

        $this->assertSame('service', $snapshot['recognition_source']);
        $this->assertSame('https://api.altcontext.com', $snapshot['effective_target_url']);
    }

    public function testFilterSourcedServiceUrlResolvesService(): void
    {
        add_filter(
            'acx_recognition_base_url',
            static fn(): string => 'https://filter.example.com'
        );

        $snapshot = $this->resolver->resolve_settings_snapshot();

        $this->assertSame('service', $snapshot['recognition_source']);
        $this->assertSame('default', $snapshot['recognition_source_source']);
        $this->assertSame('https://filter.example.com', $snapshot['effective_target_url']);
        $this->assertSame('filter', $snapshot['service_url_source']);
    }

    /**
     * @runInSeparateProcess
     * @preserveGlobalState disabled
     */
    public function testConstantServiceUrlResolvesService(): void
    {
        if (!defined('ACX_RECOGNITION_URL')) {
            define('ACX_RECOGNITION_URL', 'https://constant.example.com');
        }

        $resolver = new RecognitionEndpointResolver();
        $snapshot = $resolver->resolve_settings_snapshot();

        $this->assertSame('service', $snapshot['recognition_source']);
        $this->assertSame('default', $snapshot['recognition_source_source']);
        $this->assertSame('https://constant.example.com', $snapshot['effective_target_url']);
        $this->assertSame('constant', $snapshot['service_url_source']);
    }

    /**
     * RECOG-1: the option tier for recognition_source is retired. A stale
     * acx_recognition_source='local' option must be ignored and resolve to the
     * service default (the documented upgrade transition).
     */
    public function testStoredSourceOptionIsIgnoredAfterRetirement(): void
    {
        $this->setOption('acx_recognition_url', 'https://api.altcontext.com');
        $this->setOption('acx_recognition_source', 'local');

        $snapshot = $this->resolver->resolve_settings_snapshot();

        $this->assertSame('service', $snapshot['recognition_source']);
        $this->assertSame('default', $snapshot['recognition_source_source']);
        $this->assertSame('https://api.altcontext.com', $snapshot['effective_target_url']);
    }

    /**
     * RECOG-1: the option tier for local_url is retired. A stored
     * acx_recognition_local_url option must be ignored; the dev hatch falls back
     * to the constant/filter/default chain only.
     */
    public function testStoredLocalUrlOptionIsIgnoredAfterRetirement(): void
    {
        add_filter('acx_recognition_source', static fn(): string => 'local');
        $this->setOption('acx_recognition_local_url', 'http://localhost:8001');

        $snapshot = $this->resolver->resolve_settings_snapshot();

        $this->assertSame('local', $snapshot['recognition_source']);
        $this->assertSame('http://localhost:8000', $snapshot['effective_target_url']);
    }

    /**
     * Dev hatch (filter tier): local remains reachable via the
     * acx_recognition_source filter even though the product no longer writes it.
     */
    public function testFilterSourcedRecognitionSourceEnablesLocalHatch(): void
    {
        $this->setOption('acx_recognition_url', 'https://api.altcontext.com');
        add_filter('acx_recognition_source', static fn(): string => 'local');

        $snapshot = $this->resolver->resolve_settings_snapshot();

        $this->assertSame('local', $snapshot['recognition_source']);
        $this->assertSame('filter', $snapshot['recognition_source_source']);
        $this->assertSame('http://localhost:8000', $snapshot['effective_target_url']);
    }

    /**
     * Dev hatch (constant tier): ACX_RECOGNITION_SOURCE=local still selects local
     * and overrides an otherwise service-default install.
     *
     * @runInSeparateProcess
     * @preserveGlobalState disabled
     */
    public function testConstantRecognitionSourceEnablesLocalHatch(): void
    {
        if (!defined('ACX_RECOGNITION_SOURCE')) {
            define('ACX_RECOGNITION_SOURCE', 'local');
        }

        $this->setOption('acx_recognition_url', 'https://api.altcontext.com');

        $resolver = new RecognitionEndpointResolver();
        $snapshot = $resolver->resolve_settings_snapshot();

        $this->assertSame('local', $snapshot['recognition_source']);
        $this->assertSame('constant', $snapshot['recognition_source_source']);
        $this->assertSame('http://localhost:8000', $snapshot['effective_target_url']);
    }

    /**
     * Dev hatch full form: ACX_RECOGNITION_SOURCE=local + ACX_RECOGNITION_LOCAL_URL
     * routes to the constant-supplied local URL.
     *
     * @runInSeparateProcess
     * @preserveGlobalState disabled
     */
    public function testConstantLocalUrlHatchRoutesToConstantUrl(): void
    {
        if (!defined('ACX_RECOGNITION_SOURCE')) {
            define('ACX_RECOGNITION_SOURCE', 'local');
        }
        if (!defined('ACX_RECOGNITION_LOCAL_URL')) {
            define('ACX_RECOGNITION_LOCAL_URL', 'http://localhost:8001');
        }

        $resolver = new RecognitionEndpointResolver();
        $snapshot = $resolver->resolve_settings_snapshot();

        $this->assertSame('local', $snapshot['recognition_source']);
        $this->assertSame('http://localhost:8001', $snapshot['effective_target_url']);
        $this->assertSame('http://localhost:8001', $resolver->get_effective_base_url());
    }

    /**
     * Constant source tier still precedes the filter tier.
     *
     * @runInSeparateProcess
     * @preserveGlobalState disabled
     */
    public function testConstantRecognitionSourcePrecedesFilter(): void
    {
        if (!defined('ACX_RECOGNITION_SOURCE')) {
            define('ACX_RECOGNITION_SOURCE', 'service');
        }

        add_filter('acx_recognition_source', static fn(): string => 'local');
        $this->setOption('acx_recognition_url', 'https://api.altcontext.com');

        $resolver = new RecognitionEndpointResolver();
        $snapshot = $resolver->resolve_settings_snapshot();

        $this->assertSame('service', $snapshot['recognition_source']);
        $this->assertSame('constant', $snapshot['recognition_source_source']);
        $this->assertSame('https://api.altcontext.com', $snapshot['effective_target_url']);
    }
}
