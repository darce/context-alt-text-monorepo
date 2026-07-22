<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Admin\Admin;
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
        $this->assertSame(55, $localized['attachmentId'] ?? null);
        $this->assertSame('http://example.test/wp-content/uploads/face.jpg', $localized['imageUrl'] ?? null);
        $this->assertSame(1200, $localized['imageWidth'] ?? null);
        $this->assertSame(800, $localized['imageHeight'] ?? null);
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
}
