<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Tests\TestCase;

/**
 * Example unit test to verify PHPUnit setup works.
 */
class ExampleTest extends TestCase
{
    public function testWordPressStubsLoaded(): void
    {
        // Verify WordPress stubs are loaded
        $this->assertTrue(function_exists('get_option'));
        $this->assertTrue(function_exists('update_option'));
        $this->assertTrue(function_exists('add_action'));
        $this->assertTrue(function_exists('add_filter'));
        $this->assertTrue(class_exists('WP_Error'));
        $this->assertTrue(class_exists('WP_REST_Request'));
    }

    public function testPluginConstantsDefined(): void
    {
        $this->assertTrue(defined('ALT_CONTEXT_PLUGIN_DIR'));
        $this->assertTrue(defined('ALT_CONTEXT_PLUGIN_URL'));
        $this->assertTrue(defined('ALT_CONTEXT_VERSION'));
    }

    public function testOptionHelpers(): void
    {
        // Test that we can set and get options
        $this->setOption('test_option', 'test_value');
        $this->assertSame('test_value', get_option('test_option'));
    }

    public function testPostMetaHelpers(): void
    {
        // Test that we can set and get post meta
        $this->setPostMeta(123, 'test_meta', 'meta_value');
        $this->assertSame('meta_value', get_post_meta(123, 'test_meta', true));
    }

    public function testWpErrorClass(): void
    {
        $error = new \WP_Error('test_code', 'Test message', ['extra' => 'data']);

        $this->assertSame('test_code', $error->get_error_code());
        $this->assertSame('Test message', $error->get_error_message());
        $this->assertSame(['extra' => 'data'], $error->get_error_data());
        $this->assertTrue(is_wp_error($error));
    }

    public function testHttpMocking(): void
    {
        // Queue a mock HTTP response
        $this->queueHttpResponse([
            'response' => [
                'code' => 200,
                'message' => 'OK',
            ],
            'body' => '{"success": true}',
        ]);

        // Make an HTTP call
        $response = wp_remote_get('https://example.com/api');

        // Verify the response
        $this->assertSame(200, wp_remote_retrieve_response_code($response));
        $this->assertSame('{"success": true}', wp_remote_retrieve_body($response));

        // Verify the call was recorded
        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $this->assertSame('https://example.com/api', $calls[0]['url']);
        $this->assertSame('GET', $calls[0]['method']);
    }
}
