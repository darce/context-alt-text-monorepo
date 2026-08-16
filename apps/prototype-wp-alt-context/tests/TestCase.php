<?php

declare(strict_types=1);

namespace AltContext\Tests;

use PHPUnit\Framework\TestCase as PHPUnitTestCase;

/**
 * Base PHPUnit test case for Alt Context test suites.
 */
abstract class TestCase extends PHPUnitTestCase
{
    protected static function currentTenantId(): string
    {
        return \AltContext\Api\TenantIdentity::resolve()['value'];
    }

    protected function setUp(): void
    {
        parent::setUp();
        $this->resetGlobalState();
        // Default recognition config so proxy controllers don't fail on missing API key.
        // Individual tests override these when testing config resolution behavior.
        $this->setOption('acx_recognition_api_key', 'test-key');
    }

    protected function tearDown(): void
    {
        $this->resetGlobalState();
        parent::tearDown();
    }

    /**
     * Reset global WordPress stub state between tests.
     */
    protected function resetGlobalState(): void
    {
        // Reset WordPress stubs global state
        $GLOBALS['__ac_actions'] = [];
        $GLOBALS['__ac_filters'] = [];
        $GLOBALS['__ac_options'] = [];
        $GLOBALS['__ac_post_meta'] = [];
        $GLOBALS['__ac_update_post_meta_fail'] = [];
        $GLOBALS['__ac_update_post_meta_mutate'] = [];
        $GLOBALS['__ac_delete_post_meta_fail'] = [];
        $GLOBALS['__ac_wp_update_post_fail'] = [];
        $GLOBALS['__ac_transients'] = [];
        $GLOBALS['__ac_scheduled'] = [];
        $GLOBALS['__ac_schedule_single_event_calls'] = [];
        $GLOBALS['__ac_do_action_log'] = [];
        $GLOBALS['__ac_action_scheduler'] = [];
        $GLOBALS['__ac_action_scheduler_enqueue_result'] = null;
        $GLOBALS['__ac_http_calls'] = [];
        $GLOBALS['__ac_http_queue'] = [];
        $GLOBALS['__ac_terms'] = [];
        $GLOBALS['__ac_object_terms'] = [];
        $GLOBALS['__ac_rest_routes'] = [];
        $GLOBALS['__ac_scripts'] = [];
        $GLOBALS['__ac_styles'] = [];
        $GLOBALS['__ac_menu_pages'] = [];
        $GLOBALS['__ac_submenu_pages'] = [];
        $GLOBALS['__ac_localized_scripts'] = [];
        $GLOBALS['__ac_script_translations'] = [];
        $GLOBALS['__ac_current_user_capabilities'] = [];
        $GLOBALS['__ac_attachment_metadata'] = [];
        $GLOBALS['__ac_attachment_urls'] = [];
        $GLOBALS['__ac_attachment_mimes'] = [];
        $GLOBALS['__ac_attachment_image_src'] = [];
        $GLOBALS['__ac_attached_file'] = [];
        $GLOBALS['__ac_description_usage_rows'] = [];
        $GLOBALS['__ac_get_posts_results'] = [];
        $GLOBALS['__ac_posts'] = [];
        $GLOBALS['__ac_updated_posts'] = [];
        $GLOBALS['__ac_json_response'] = null;
        $GLOBALS['__ac_dbdelta_queries'] = [];
        $GLOBALS['__ac_error_log'] = [];
        $GLOBALS['__ac_connection_aborted'] = false;
        $GLOBALS['__ac_connection_aborted_call_count'] = 0;
        unset($GLOBALS['__ac_site_url']);
        unset($GLOBALS['__ac_dbdelta_fail_on_match'], $GLOBALS['__ac_dbdelta_fail_error']);
        // BR-50: clear the current_time freeze here, not in the test body — a
        // failing assertion aborts before an in-body unset and would leave every
        // later test in the process running on a frozen 2023 clock.
        unset($GLOBALS['__ac_current_time']);

        // Reset wpdb stub
        if (isset($GLOBALS['wpdb']) && method_exists($GLOBALS['wpdb'], 'reset')) {
            $GLOBALS['wpdb']->reset();
        }
    }

    /**
     * Returns the captured error_log calls made during the test.
     * @return string[]
     */
    protected function getErrorLog(): array
    {
        return $GLOBALS['__ac_error_log'] ?? [];
    }

    /**
     * Set a WordPress option for testing.
     */
    protected function setOption(string $key, mixed $value): void
    {
        $GLOBALS['__ac_options'][$key] = $value;
    }

    /**
     * Set post meta for testing.
     */
    protected function setPostMeta(int $postId, string $key, mixed $value): void
    {
        if (!isset($GLOBALS['__ac_post_meta'][$postId])) {
            $GLOBALS['__ac_post_meta'][$postId] = [];
        }
        $GLOBALS['__ac_post_meta'][$postId][$key] = $value;
    }

    /**
     * Set user capability for testing.
     */
    protected function setUserCapability(string $capability, bool|array|callable $value): void
    {
        $GLOBALS['__ac_current_user_capabilities'][$capability] = $value;
    }

    /**
     * Queue an HTTP response for wp_remote_* functions.
     * Can be an array (success) or WP_Error (failure).
     */
    protected function queueHttpResponse(array|\WP_Error $response): void
    {
        if (!isset($GLOBALS['__ac_http_queue'])) {
            $GLOBALS['__ac_http_queue'] = [];
        }
        $GLOBALS['__ac_http_queue'][] = $response;
    }

    /**
     * Get all HTTP calls made during the test.
     */
    protected function getHttpCalls(): array
    {
        return $GLOBALS['__ac_http_calls'] ?? [];
    }
}
