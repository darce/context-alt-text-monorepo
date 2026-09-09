<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Admin\Admin;
use AltContext\Support\ViteManifest;
use AltContext\Tests\TestCase;
use ReflectionClass;

/**
 * Enqueue gate + multi-entry manifest resolution for SPA and attachment-edit.
 *
 * @covers \AltContext\Admin\Admin
 */
class AdminEnqueueTest extends TestCase
{
    private function dualManifestPath(): string
    {
        return dirname(__DIR__) . '/fixtures/admin-manifest-with-attachment-edit.json';
    }

    private function spaOnlyManifestPath(): string
    {
        return dirname(__DIR__) . '/fixtures/admin-manifest.json';
    }

    private function importedChunkManifestPath(): string
    {
        return dirname(__DIR__) . '/fixtures/vite-manifest/admin-with-import.json';
    }

    private function seedAttachmentPost(int $postId = 55): void
    {
        $_GET['post'] = (string) $postId;
        $GLOBALS['__ac_posts'][$postId] = (object) [
            'ID' => $postId,
            'post_type' => 'attachment',
        ];
        $GLOBALS['__ac_attachment_urls'][$postId] = 'http://example.test/wp-content/uploads/face.jpg';
        $GLOBALS['__ac_attachment_metadata'][$postId] = [
            'width' => 1200,
            'height' => 800,
        ];
        $GLOBALS['__ac_attachment_image_src'][$postId]['full'] = [
            'http://example.test/wp-content/uploads/face.jpg',
            1200,
            800,
        ];
    }

    public function testAdminEnqueueFiresOnPostPhpAttachmentWithManageOptions(): void
    {
        unset($_ENV['WP_ENVIRONMENT_TYPE']);
        $this->setUserCapability('manage_options', true);
        $this->seedAttachmentPost(55);

        $admin = new Admin($this->dualManifestPath());
        $admin->enqueue_scripts('post.php');

        $this->assertArrayHasKey('alt-context-attachment-edit', $GLOBALS['__ac_scripts']);
        $this->assertSame(
            'http://example.test/wp-content/plugins/alt-context/public/assets/dist/assets/attachment-edit-test.js',
            $GLOBALS['__ac_scripts']['alt-context-attachment-edit']['src'] ?? null
        );
        $this->assertArrayHasKey('alt-context-attachment-edit-0', $GLOBALS['__ac_styles']);
        $this->assertSame(
            'http://example.test/wp-content/plugins/alt-context/public/assets/dist/assets/attachment-edit-test.css',
            $GLOBALS['__ac_styles']['alt-context-attachment-edit-0']['src'] ?? null
        );

        $localized = $GLOBALS['__ac_localized_scripts']['alt-context-attachment-edit']['AltContextAttachmentEdit'] ?? null;
        $this->assertIsArray($localized);
        // wp_localize_script casts every scalar to string on the way out, so
        // these are the shapes the browser actually parses.
        $this->assertSame('55', $localized['attachmentId'] ?? null);
        $this->assertSame('http://example.test/wp-content/uploads/face.jpg', $localized['imageUrl'] ?? null);
        $this->assertSame('1200', $localized['imageWidth'] ?? null);
        $this->assertSame('800', $localized['imageHeight'] ?? null);
        $this->assertSame(
            '/wp-admin/admin.php?page=alt-context-workbench',
            $localized['workbenchUrl'] ?? null
        );
        $this->assertSame(
            'http://example.test/wp-json/acx/v1/recognition/media-identities',
            $localized['endpoints']['recognitionMediaIdentities'] ?? null
        );
        $this->assertArrayHasKey('nonce', $localized);
        $this->assertArrayHasKey('ajaxUrl', $localized);
        $this->assertSame('/wp-admin/admin-ajax.php', $localized['ajaxUrl'] ?? null);
        $this->assertArrayNotHasKey('alt-context-admin', $GLOBALS['__ac_scripts']);
    }

    public function testAdminEnqueueSkipsPostPhpWithoutManageOptions(): void
    {
        unset($_ENV['WP_ENVIRONMENT_TYPE']);
        $this->setUserCapability('manage_options', false);
        $this->seedAttachmentPost(55);

        $admin = new Admin($this->dualManifestPath());
        $admin->enqueue_scripts('post.php');

        $this->assertArrayNotHasKey('alt-context-attachment-edit', $GLOBALS['__ac_scripts']);
        $this->assertArrayNotHasKey('alt-context-admin', $GLOBALS['__ac_scripts']);
    }

    public function testAdminEnqueueSkipsNonAttachmentPostPhp(): void
    {
        unset($_ENV['WP_ENVIRONMENT_TYPE']);
        $this->setUserCapability('manage_options', true);
        $_GET['post'] = '99';
        $GLOBALS['__ac_posts'][99] = (object) [
            'ID' => 99,
            'post_type' => 'post',
        ];

        $admin = new Admin($this->dualManifestPath());
        $admin->enqueue_scripts('post.php');

        $this->assertArrayNotHasKey('alt-context-attachment-edit', $GLOBALS['__ac_scripts']);
    }

    public function testAdminEnqueueSkipsNonPostPhpHooks(): void
    {
        unset($_ENV['WP_ENVIRONMENT_TYPE']);
        $this->setUserCapability('manage_options', true);
        $this->seedAttachmentPost(55);

        $admin = new Admin($this->dualManifestPath());
        $admin->enqueue_scripts('upload.php');

        $this->assertArrayNotHasKey('alt-context-attachment-edit', $GLOBALS['__ac_scripts']);
    }

    public function testAdminEnqueueResolvesSpaAndAttachmentEntriesIndependently(): void
    {
        unset($_ENV['WP_ENVIRONMENT_TYPE']);
        $this->setUserCapability('manage_options', true);

        $admin = new Admin($this->dualManifestPath());

        // SPA path
        $admin->enqueue_scripts('toplevel_page_alt-context-dashboard');
        $this->assertArrayHasKey('alt-context-admin', $GLOBALS['__ac_scripts']);
        $this->assertArrayHasKey('alt-context-admin-0', $GLOBALS['__ac_styles']);
        $this->assertArrayNotHasKey('alt-context-attachment-edit', $GLOBALS['__ac_scripts']);

        // Reset enqueue globals; re-seed attachment screen.
        $GLOBALS['__ac_scripts'] = [];
        $GLOBALS['__ac_styles'] = [];
        $GLOBALS['__ac_localized_scripts'] = [];
        $this->seedAttachmentPost(55);

        $admin->enqueue_scripts('post.php');
        $this->assertArrayHasKey('alt-context-attachment-edit', $GLOBALS['__ac_scripts']);
        $this->assertArrayHasKey('alt-context-attachment-edit-0', $GLOBALS['__ac_styles']);
        $this->assertArrayNotHasKey('alt-context-admin', $GLOBALS['__ac_scripts']);
    }

    public function testAdminEnqueueMissingAttachmentEditEntryReportsBootstrapFailure(): void
    {
        unset($_ENV['WP_ENVIRONMENT_TYPE']);
        $this->setUserCapability('manage_options', true);
        $this->seedAttachmentPost(55);

        // SPA-only manifest: attachment-edit key missing.
        $admin = new Admin($this->spaOnlyManifestPath());
        $admin->enqueue_scripts('post.php');

        $this->assertArrayNotHasKey('alt-context-attachment-edit', $GLOBALS['__ac_scripts']);
        $this->assertArrayNotHasKey('alt-context-attachment-edit', $GLOBALS['__ac_localized_scripts']);
        $this->assertArrayHasKey('admin_notices', $GLOBALS['__ac_actions']);

        $noticeCallbacks = $GLOBALS['__ac_actions']['admin_notices'][10] ?? [];
        $this->assertNotEmpty($noticeCallbacks);

        ob_start();
        foreach ($noticeCallbacks as $callback) {
            ($callback['callback'])();
        }
        $output = (string) ob_get_clean();

        $this->assertStringContainsString('Alt Context admin assets could not be loaded.', $output);
    }

    public function testGetManifestEntryResolvesByEntryKey(): void
    {
        $admin = new Admin($this->dualManifestPath());
        $reflection = new ReflectionClass($admin);
        $method = $reflection->getMethod('get_manifest_entry');
        $method->setAccessible(true);

        $spa = $method->invoke($admin, 'js/admin/main.tsx');
        $attachment = $method->invoke($admin, 'js/attachment-edit/main.tsx');
        $missing = $method->invoke($admin, 'js/missing/main.tsx');

        $this->assertIsArray($spa);
        $this->assertSame('assets/admin-test.js', $spa['file'] ?? null);
        $this->assertIsArray($attachment);
        $this->assertSame('assets/attachment-edit-test.js', $attachment['file'] ?? null);
        $this->assertNull($missing);
    }

    public function testDefaultConstructorUsesFromPluginManifestPath(): void
    {
        unset($_ENV['WP_ENVIRONMENT_TYPE']);
        $admin = new Admin();
        $reflection = new ReflectionClass($admin);
        $method = $reflection->getMethod('vite_manifest');
        $method->setAccessible(true);
        $manifest = $method->invoke($admin);

        $this->assertInstanceOf(ViteManifest::class, $manifest);
        $this->assertSame(
            ViteManifest::from_plugin()->manifest_path(),
            $manifest->manifest_path()
        );
    }

    public function testDefaultAdminBootstrapFailureUsesFromPluginPath(): void
    {
        unset($_ENV['WP_ENVIRONMENT_TYPE']);
        $expectedPath = ViteManifest::from_plugin()->manifest_path();
        if (is_readable($expectedPath)) {
            $this->markTestSkipped('Default plugin manifest is present; failure path is unobservable.');
        }

        $admin = new Admin();
        $admin->enqueue_scripts('toplevel_page_alt-context-dashboard');

        $events = array_values(array_filter(
            $GLOBALS['__ac_do_action_log'] ?? [],
            static fn(array $event): bool => ($event['hook'] ?? '') === 'acx_admin_asset_bootstrap_failure'
        ));
        $this->assertNotEmpty($events);
        $this->assertSame($expectedPath, $events[0]['args'][1]['manifest_path'] ?? null);
        $this->assertStringContainsString($expectedPath, (string) ($events[0]['args'][0] ?? ''));
    }

    public function testInjectedManifestPathIsUsedInBootstrapFailure(): void
    {
        unset($_ENV['WP_ENVIRONMENT_TYPE']);
        $path = $this->importedChunkManifestPath() . '.missing';

        $admin = new Admin($path);
        $admin->enqueue_scripts('toplevel_page_alt-context-dashboard');

        $events = array_values(array_filter(
            $GLOBALS['__ac_do_action_log'] ?? [],
            static fn(array $event): bool => ($event['hook'] ?? '') === 'acx_admin_asset_bootstrap_failure'
        ));
        $this->assertNotEmpty($events);
        $this->assertSame($path, $events[0]['args'][1]['manifest_path'] ?? null);
        $this->assertStringContainsString($path, (string) ($events[0]['args'][0] ?? ''));
    }

    public function testAdminEnqueueIncludesImportedChunkCss(): void
    {
        unset($_ENV['WP_ENVIRONMENT_TYPE']);
        $this->setUserCapability('manage_options', true);

        $admin = new Admin($this->importedChunkManifestPath());
        $admin->enqueue_scripts('toplevel_page_alt-context-dashboard');

        $this->assertArrayHasKey('alt-context-admin', $GLOBALS['__ac_scripts']);
        $this->assertSame(
            'http://example.test/wp-content/plugins/alt-context/public/assets/dist/assets/admin-test.js',
            $GLOBALS['__ac_scripts']['alt-context-admin']['src'] ?? null
        );
        $this->assertArrayHasKey('alt-context-admin-0', $GLOBALS['__ac_styles']);
        $this->assertSame(
            'http://example.test/wp-content/plugins/alt-context/public/assets/dist/assets/admin-shared.css',
            $GLOBALS['__ac_styles']['alt-context-admin-0']['src'] ?? null
        );
        $this->assertArrayHasKey('alt-context-admin-1', $GLOBALS['__ac_styles']);
        $this->assertSame(
            'http://example.test/wp-content/plugins/alt-context/public/assets/dist/assets/admin-test.css',
            $GLOBALS['__ac_styles']['alt-context-admin-1']['src'] ?? null
        );
    }

    public function testModuleHandleScriptTagRendersTypeModule(): void
    {
        $admin = new Admin($this->spaOnlyManifestPath());
        wp_script_add_data('alt-context-admin', 'type', 'module');

        // WHY: these are filter inputs under test, not emitted scripts.
        $tag = '<script id="alt-context-admin-js" src="http://example.test/admin.js?ver=0.0.5"></script>'; // phpcs:ignore WordPress.WP.EnqueuedResources.NonEnqueuedScript
        $filtered = $admin->filter_module_script_tag($tag, 'alt-context-admin', 'http://example.test/admin.js');

        // Without this, a code-split ESM entry loads as a classic script and the SPA never mounts.
        $this->assertStringContainsString('type="module"', $filtered);
        $this->assertStringContainsString('id="alt-context-admin-js"', $filtered);
    }

    public function testNonModuleHandleScriptTagIsUnchanged(): void
    {
        $admin = new Admin($this->spaOnlyManifestPath());

        // No 'type' => 'module' data registered for this handle: discrimination guard.
        $tag = '<script id="jquery-core-js" src="http://example.test/jquery.js"></script>'; // phpcs:ignore WordPress.WP.EnqueuedResources.NonEnqueuedScript
        $filtered = $admin->filter_module_script_tag($tag, 'jquery-core', 'http://example.test/jquery.js');

        $this->assertSame($tag, $filtered);
    }

    public function testModuleTypeIsNotDoubled(): void
    {
        $admin = new Admin($this->spaOnlyManifestPath());
        wp_script_add_data('alt-context-admin', 'type', 'module');

        $tag = '<script type="module" id="alt-context-admin-js" src="http://example.test/admin.js"></script>'; // phpcs:ignore WordPress.WP.EnqueuedResources.NonEnqueuedScript
        $filtered = $admin->filter_module_script_tag($tag, 'alt-context-admin', 'http://example.test/admin.js');

        $this->assertSame(1, substr_count($filtered, 'type="module"'));
    }

    public function testInitWiresScriptLoaderTagFilterWithThreeArgs(): void
    {
        // Exercises the real add_filter registration end-to-end: a wrong hook name or
        // accepted_args < 3 would drop $handle/$src, no-op the filter, and break the SPA
        // in production while every direct-call test stayed green.
        $admin = new Admin($this->spaOnlyManifestPath());
        $admin->init();
        wp_script_add_data('alt-context-admin', 'type', 'module');

        $tag = '<script id="alt-context-admin-js" src="http://example.test/admin.js?ver=0.0.5"></script>'; // phpcs:ignore WordPress.WP.EnqueuedResources.NonEnqueuedScript
        $filtered = apply_filters('script_loader_tag', $tag, 'alt-context-admin', 'http://example.test/admin.js');

        $this->assertStringContainsString('type="module"', $filtered);
        $this->assertStringContainsString('src="http://example.test/admin.js', $filtered);
    }

    public function testSingleQuotedModuleTagIsNotDoubled(): void
    {
        $admin = new Admin($this->spaOnlyManifestPath());
        wp_script_add_data('alt-context-admin', 'type', 'module');

        $tag = "<script type='module' id='alt-context-admin-js' src='/a.js'></script>"; // phpcs:ignore WordPress.WP.EnqueuedResources.NonEnqueuedScript
        $filtered = $admin->filter_module_script_tag($tag, 'alt-context-admin', '/a.js');

        $this->assertStringNotContainsString('type="module"', $filtered);
        $this->assertSame(1, substr_count($filtered, "type='module'"));
    }

    public function testEnqueueMarksAttachmentEditHandleAsModule(): void
    {
        // The filter is inert unless enqueue actually stamps the module data on the handle;
        // pin that seam so removing wp_script_add_data(...,'module') fails a test.
        unset($_ENV['WP_ENVIRONMENT_TYPE']);
        $this->setUserCapability('manage_options', true);
        $this->seedAttachmentPost(55);

        $admin = new Admin($this->dualManifestPath());
        $admin->enqueue_scripts('post.php');

        $this->assertSame(
            'module',
            $GLOBALS['__ac_scripts']['alt-context-attachment-edit']['data']['type'] ?? null
        );
    }

    public function testEnqueueWiresJsTranslationsForBothEntries(): void
    {
        // Without this the wp-i18n dependency ships but never receives a locale JED,
        // so every SPA string stays in the source language on a non-English site.
        // Pin the seam so deleting wp_set_script_translations(...) fails a test.
        unset($_ENV['WP_ENVIRONMENT_TYPE']);
        $this->setUserCapability('manage_options', true);

        $admin = new Admin($this->dualManifestPath());

        $admin->enqueue_scripts('toplevel_page_alt-context-dashboard');
        $this->assertSame(
            ['domain' => 'alt-context', 'path' => ACX_PLUGIN_DIR . 'public/languages'],
            $GLOBALS['__ac_script_translations']['alt-context-admin'] ?? null
        );

        $GLOBALS['__ac_scripts'] = [];
        $GLOBALS['__ac_styles'] = [];
        $GLOBALS['__ac_script_translations'] = [];
        $this->seedAttachmentPost(55);

        $admin->enqueue_scripts('post.php');
        $this->assertSame(
            ['domain' => 'alt-context', 'path' => ACX_PLUGIN_DIR . 'public/languages'],
            $GLOBALS['__ac_script_translations']['alt-context-attachment-edit'] ?? null
        );
    }
}
