<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\DescribeController;
use AltContext\Tests\TestCase;
use WP_REST_Request;

use function json_encode;

/**
 * GPUFLOW-3 E1 / C5: describe-run items carry WP thumbnail_url/srcset so a
 * draft can sit beside its image (PERC-01, HAI-01).
 *
 * @covers \AltContext\Api\DescribeController::get_describe_run_items
 */
final class DescribeRunItemsThumbnailTest extends TestCase
{
    private DescribeController $controller;

    protected function setUp(): void
    {
        parent::setUp();
        self::installSrcsetStub();
        $GLOBALS['__ac_attachment_image_srcset'] = [];
        $this->setOption('acx_recognition_url', 'http://localhost:8000');
        $this->setOption('acx_recognition_api_key', 'test-key');
        $this->controller = new DescribeController();
    }

    public function testGetDescribeRunItemsEnrichesWordpressThumbnailUrlAndSrcset(): void
    {
        $this->setPostMeta(81, '_wp_attachment_image_alt', 'human-authored alt');
        $this->plantMediumSrc(81, 'http://example.test/uploads/81-medium.jpg', 300, 200);
        $this->plantMediumSrcset(
            81,
            'http://example.test/uploads/81-medium.jpg 300w, http://example.test/uploads/81-full.jpg 800w'
        );

        $runId = '11111111-1111-1111-1111-111111111111';
        $this->queueRunItems($runId, [
            [
                'media_id' => 81,
                'status' => 'completed',
                'alt_text_draft' => 'Ada stands by a window.',
                'caption' => 'A person by a window.',
                'provenance' => ['adapter' => 'gpu'],
            ],
        ]);

        $response = $this->controller->get_describe_run_items($this->itemsRequest($runId));

        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $item = $response->get_data()['items'][0];
        $this->assertArrayHasKey('thumbnail_url', $item);
        $this->assertArrayHasKey('thumbnail_srcset', $item);
        $this->assertSame('http://example.test/uploads/81-medium.jpg', $item['thumbnail_url']);
        $this->assertSame(
            'http://example.test/uploads/81-medium.jpg 300w, http://example.test/uploads/81-full.jpg 800w',
            $item['thumbnail_srcset']
        );
        $this->assertTrue($item['existing_alt']);
        $this->assertSame('Ada stands by a window.', $item['alt_text_draft']);
        $this->assertSame('gpu', $item['provenance']['adapter']);
    }

    public function testGetDescribeRunItemsYieldsNullThumbnailsWhenAttachmentIsMissing(): void
    {
        $runId = '22222222-2222-2222-2222-222222222222';
        $this->queueRunItems($runId, [
            [
                'media_id' => 99,
                'status' => 'completed',
                'alt_text_draft' => 'a cat on a sofa',
                'caption' => 'cat',
                'provenance' => null,
            ],
        ]);

        $response = $this->controller->get_describe_run_items($this->itemsRequest($runId));

        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $item = $response->get_data()['items'][0];
        $this->assertArrayHasKey('thumbnail_url', $item);
        $this->assertArrayHasKey('thumbnail_srcset', $item);
        $this->assertNull($item['thumbnail_url']);
        $this->assertNull($item['thumbnail_srcset']);
        $this->assertSame('a cat on a sofa', $item['alt_text_draft']);
    }

    public function testGetDescribeRunItemsDoesNotFabricateUrlWhenImageSrcIsFalse(): void
    {
        $GLOBALS['__ac_attachment_image_src'][70]['medium'] = false;
        $this->plantMediumSrcset(70, 'http://example.test/uploads/should-not-leak.jpg 300w');

        $runId = '33333333-3333-3333-3333-333333333333';
        $this->queueRunItems($runId, [
            [
                'media_id' => 70,
                'status' => 'completed',
                'alt_text_draft' => 'draft',
                'caption' => null,
                'provenance' => null,
            ],
            [
                'media_id' => 0,
                'status' => 'failed',
                'alt_text_draft' => null,
                'caption' => null,
                'provenance' => null,
            ],
        ]);

        $response = $this->controller->get_describe_run_items($this->itemsRequest($runId));

        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $items = $response->get_data()['items'];
        $this->assertArrayHasKey('thumbnail_url', $items[0]);
        $this->assertArrayHasKey('thumbnail_srcset', $items[0]);
        $this->assertNull($items[0]['thumbnail_url']);
        $this->assertNull($items[0]['thumbnail_srcset']);
        $this->assertArrayHasKey('thumbnail_url', $items[1]);
        $this->assertArrayHasKey('thumbnail_srcset', $items[1]);
        $this->assertNull($items[1]['thumbnail_url']);
        $this->assertNull($items[1]['thumbnail_srcset']);
    }

    public function testGetDescribeRunItemsKeepsSrcsetNullWhenWordpressOmitsIt(): void
    {
        $this->plantMediumSrc(82, 'http://example.test/uploads/82.jpg', 800, 600);

        $runId = '44444444-4444-4444-4444-444444444444';
        $this->queueRunItems($runId, [
            [
                'media_id' => 82,
                'status' => 'completed',
                'alt_text_draft' => 'a dog in a park',
                'caption' => 'dog',
                'provenance' => null,
            ],
        ]);

        $response = $this->controller->get_describe_run_items($this->itemsRequest($runId));

        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $item = $response->get_data()['items'][0];
        $this->assertArrayHasKey('thumbnail_url', $item);
        $this->assertArrayHasKey('thumbnail_srcset', $item);
        $this->assertSame('http://example.test/uploads/82.jpg', $item['thumbnail_url']);
        $this->assertNull($item['thumbnail_srcset']);
    }

    /**
     * @param list<array<string, mixed>> $items
     */
    private function queueRunItems(string $runId, array $items): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'run_id' => $runId,
                'items' => $items,
            ]),
        ]);
    }

    private function itemsRequest(string $runId): WP_REST_Request
    {
        $request = new WP_REST_Request('GET', '/acx/v1/recognition/describe/runs/' . $runId . '/items');
        $request->set_param('run_id', $runId);
        return $request;
    }

    private function plantMediumSrc(int $id, string $url, int $width, int $height): void
    {
        $GLOBALS['__ac_attachment_image_src'][$id]['medium'] = [$url, $width, $height];
    }

    private function plantMediumSrcset(int $id, string $srcset): void
    {
        $GLOBALS['__ac_attachment_image_srcset'][$id]['medium'] = $srcset;
    }

    /**
     * Shared stubs omit srcset; plant via $GLOBALS['__ac_attachment_image_srcset'].
     */
    private static function installSrcsetStub(): void
    {
        if (function_exists('wp_get_attachment_image_srcset')) {
            return;
        }

        // phpcs:ignore Squiz.PHP.Eval.Discouraged -- global helper omitted by shared stubs.
        eval(
            <<<'PHP'
function wp_get_attachment_image_srcset($attachment_id, $size = 'medium')
{
    $id = (int) $attachment_id;
    $sizeKey = is_string($size) ? $size : 'custom';
    if (isset($GLOBALS['__ac_attachment_image_srcset'][$id][$sizeKey])) {
        return $GLOBALS['__ac_attachment_image_srcset'][$id][$sizeKey];
    }
    return false;
}
PHP
        );
    }
}
