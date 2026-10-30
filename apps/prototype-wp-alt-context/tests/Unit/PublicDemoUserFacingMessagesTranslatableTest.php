<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

require_once __DIR__ . '/../../src/public/class-public-demo-shortcode.php';

use AltContext\Admin\Admin;
use AltContext\PublicSite\PublicDemoShortcode;
use AltContext\Tests\TestCase;

final class PublicDemoUserFacingMessagesTranslatableTest extends TestCase
{
    public function testDemoScriptDependsOnWpI18nAndLoadsTranslations(): void
    {
        $this->seedImages();
        (new PublicDemoShortcode(static fn (): ?array => null))->render();

        self::assertSame(['wp-i18n'], $GLOBALS['__ac_scripts']['acx-public-demo-describe']['deps']);
        self::assertSame(
            ['domain' => 'alt-context', 'path' => ACX_PLUGIN_DIR . 'public/languages'],
            $GLOBALS['__ac_script_translations']['acx-public-demo-describe'] ?? null
        );
    }

    public function testTranslatedShortcodeEscapesCatalogueTextAndFormatsUntitledImage(): void
    {
        $result = $this->translatedOutput();

        self::assertStringContainsString('«The image description demo is not available right now.»', $result['disabled']);
        self::assertStringContainsString('«No demo images are available right now.»', $result['empty']);
        foreach ([
            'Illustrative example — not a live result',
            'Alex stands beside a bicycle outside a cafe.',
            'This example is not a description of your selected image. Your live result may differ.',
            'Describe selected image',
            'Select an image, then choose Describe.',
        ] as $message) {
            self::assertStringContainsString('«' . $message . '»', $result['enabled']);
        }
        self::assertStringContainsString('<legend>Choisir &lt;une image&gt; &amp; décrire</legend>', $result['enabled']);
        self::assertStringNotContainsString('<une image>', $result['enabled']);
        self::assertStringContainsString('<span>Image 41 de démonstration</span>', $result['enabled']);
    }

    public function testTranslatedValidationPreservesErrorCodeStatusAndOrderedPlaceholders(): void
    {
        $result = $this->translatedOutput();

        self::assertSame([
            'code' => 'acx_public_demo_disabled',
            'message' => '«The public description demo is not enabled.»',
            'data' => ['status' => 403],
        ], $result['permission']);
        self::assertSame([
            'code' => 'acx_public_demo_invalid_idempotency_key',
            'message' => 'Maximum 128, minimum 16.',
            'data' => ['status' => 422, 'field' => 'idempotency_key'],
        ], $result['invalidKey']);
        self::assertSame(429, $result['dailyLimit']['status']);
        self::assertSame('acx_public_demo_daily_cap_reached', $result['dailyLimit']['data']['code']);
        self::assertSame('«Today\'s demo limit has been reached. Please return tomorrow.»', $result['dailyLimit']['data']['message']);
    }

    public function testUntitledAttachmentFallsBackToDemoImageId(): void
    {
        $this->seedImages();
        $GLOBALS['__ac_attachment_titles'][41] = '';

        self::assertStringContainsString(
            '<span>Demo image 41</span>',
            (new PublicDemoShortcode(static fn (): ?array => null))->render()
        );
    }

    public function testModuleFilterKeepsDemoTranslationsInlineClassic(): void
    {
        $this->seedImages();
        (new PublicDemoShortcode(static fn (): ?array => null))->render();
        $admin = new Admin();

        // WHY: these are filter inputs under test, not emitted scripts.
        $translations = '<script id="acx-public-demo-describe-js-translations">wp.i18n.setLocaleData({}, "alt-context");</script>'; // phpcs:ignore WordPress.WP.EnqueuedResources.NonEnqueuedScript
        $tag = $translations . "\n" . '<script id="acx-public-demo-describe-js" src="http://example.test/demo-describe.js"></script>'; // phpcs:ignore WordPress.WP.EnqueuedResources.NonEnqueuedScript
        $filtered = $admin->filter_module_script_tag($tag, 'acx-public-demo-describe', 'http://example.test/demo-describe.js');

        self::assertSame(1, substr_count($filtered, 'type="module"'));
        self::assertStringStartsWith($translations . "\n", $filtered);
        self::assertStringContainsString('<script type="module" id="acx-public-demo-describe-js"', $filtered);
    }

    public function testEnglishRenderMatchesRadioFixture(): void
    {
        $this->seedImages();
        $shortcode = new PublicDemoShortcode(static fn (): ?array => null);
        $actual = $shortcode->render() . "\n" . $shortcode->render() . "\n";
        $expected = file_get_contents(ACX_PLUGIN_DIR . 'js/public/__tests__/fixtures/public-demo-radio/two-instances.html');
        self::assertIsString($expected);

        self::assertSame(
            preg_replace('/acx-demo-media-\d+/', 'acx-demo-media-N', $expected),
            preg_replace('/acx-demo-media-\d+/', 'acx-demo-media-N', $actual)
        );
    }

    private function seedImages(): void
    {
        $this->setOption('acx_public_demo_enabled', true);
        $this->setOption('acx_public_demo_media_ids', [41, 42]);
        $GLOBALS['__ac_attachment_urls'] = [41 => 'https://example.test/uploads/lake.jpg', 42 => 'https://example.test/uploads/path.jpg'];
        $GLOBALS['__ac_attachment_titles'] = [41 => 'Lake', 42 => 'Path'];
    }

    /** @return array<string, mixed> */
    private function translatedOutput(): array
    {
        // The shared WP stub returns English unconditionally. Define a catalogue
        // before loading it in a subprocess; no shared stub or production hook changes.
        $script = <<<'PHP'
function __($text, $domain = 'default') {
    if ('alt-context' !== $domain) {
        return $text;
    }
    return [
        'Choose an image to describe' => 'Choisir <une image> & décrire',
        'Demo image %d' => 'Image %d de démonstration',
        'idempotency_key must be %1$d-%2$d characters using only letters, digits, underscore, or hyphen.' => 'Maximum %2$d, minimum %1$d.',
    ][$text] ?? '«' . $text . '»';
}
function esc_html__($text, $domain = 'default') {
    return esc_html(__($text, $domain));
}
require 'tests/bootstrap.php';
require_once 'src/public/class-public-demo-shortcode.php';
require_once 'src/api/class-public-demo-describe-controller.php';
$shortcode = new AltContext\PublicSite\PublicDemoShortcode(static fn () => null);
$controller = new AltContext\Api\PublicDemoDescribeController();
$permission = $controller->check_public_permission(new WP_REST_Request());
$result = [
    'disabled' => $shortcode->render(),
    'permission' => ['code' => $permission->get_error_code(), 'message' => $permission->get_error_message(), 'data' => $permission->get_error_data()],
];
update_option('acx_public_demo_enabled', true);
$result['empty'] = $shortcode->render();
update_option('acx_public_demo_media_ids', [41]);
$GLOBALS['__ac_attachment_urls'][41] = 'https://example.test/uploads/lake.jpg';
$GLOBALS['__ac_attachment_titles'][41] = '';
$result['enabled'] = $shortcode->render();
$_SERVER['REMOTE_ADDR'] = '203.0.113.42';
$request = new WP_REST_Request('POST');
$request->set_param('media_id', 41);
$request->set_body_params(['idempotency_key' => 'short']);
$invalidKey = $controller->submit($request);
$result['invalidKey'] = ['code' => $invalidKey->get_error_code(), 'message' => $invalidKey->get_error_message(), 'data' => $invalidKey->get_error_data()];
update_option('acx_public_demo_daily_cap', 0);
$request->set_body_params(['idempotency_key' => 'translated-demo-key-0001']);
$limit = $controller->submit($request);
$result['dailyLimit'] = ['status' => $limit->get_status(), 'data' => $limit->get_data()];
echo json_encode($result, JSON_THROW_ON_ERROR);
PHP;
        $output = shell_exec(sprintf(
            'cd %s && %s -r %s',
            escapeshellarg(ACX_PLUGIN_DIR),
            escapeshellarg(PHP_BINARY),
            escapeshellarg($script)
        ));
        self::assertIsString($output);
        return json_decode($output, true, 512, JSON_THROW_ON_ERROR);
    }
}
