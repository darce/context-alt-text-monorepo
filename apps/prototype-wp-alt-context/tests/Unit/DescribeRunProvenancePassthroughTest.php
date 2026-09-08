<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\DescribeController;
use AltContext\Tests\TestCase;
use WP_REST_Request;

use function json_encode;

/**
 * @covers \AltContext\Api\DescribeController
 */
final class DescribeRunProvenancePassthroughTest extends TestCase
{
    private DescribeController $controller;

    protected function setUp(): void
    {
        parent::setUp();
        $this->setOption('acx_recognition_url', 'http://localhost:8000');
        $this->setOption('acx_recognition_api_key', 'test-key');
        $this->controller = new DescribeController();
    }

    public function testGetDescribeRunItemsPreservesNamingProvenanceFromService(): void
    {
        $runId = '11111111-1111-1111-1111-111111111111';
        $naming = [
            'status' => 'applied',
            'realizer' => 'positional_fallback',
            'names_applied' => ['Ada', 'Bea'],
        ];

        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'tenant_id' => self::currentTenantId(),
                'run_id' => $runId,
                'items' => [
                    [
                        'media_id' => 81,
                        'status' => 'completed',
                        'alt_text_draft' => 'Ada and Bea stand by a window.',
                        'caption' => 'Two people by a window.',
                        'provenance' => [
                            'naming' => $naming,
                            'adapter' => 'gpu',
                        ],
                    ],
                ],
            ]),
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/describe/runs/' . $runId . '/items');
        $request->set_param('run_id', $runId);

        $response = $this->controller->get_describe_run_items($request);

        $this->assertNotInstanceOf(\WP_Error::class, $response);
        $this->assertSame($naming, $response->get_data()['items'][0]['provenance']['naming']);
        // The WP-side annotation is additive; it must not replace upstream provenance.
        $this->assertSame('gpu', $response->get_data()['items'][0]['provenance']['adapter']);
        $this->assertFalse($response->get_data()['items'][0]['existing_alt']);
    }
}
