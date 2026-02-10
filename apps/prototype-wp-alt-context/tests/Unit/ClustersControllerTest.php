<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\ClustersController;
use AltContext\Tests\TestCase;
use WP_REST_Request;

/**
 * @covers \AltContext\Api\ClustersController
 */
class ClustersControllerTest extends TestCase
{
    private ClustersController $controller;

    protected function setUp(): void
    {
        parent::setUp();
        $this->setOption('acx_recognition_url', 'http://localhost:8000');
        $this->controller = new ClustersController();
    }

    public function testRegisterRoutesIncludesReadOnlyClusterSurfaces(): void
    {
        $this->controller->register_routes();

        $routes = array_map(
            static fn (array $definition): string => $definition['route'],
            $GLOBALS['__ac_rest_routes']
        );

        $this->assertContains('/recognition/clusters', $routes);
        $this->assertContains('/recognition/clusters/top-unlabeled', $routes);
        $this->assertContains('/recognition/clusters/labels', $routes);
        $this->assertContains('/recognition/clusters/(?P<cluster_id>[a-f0-9-]+)', $routes);
        $this->assertContains('/recognition/clusters/(?P<cluster_id>[a-f0-9-]+)/members', $routes);

        $this->assertNotContains('/recognition/clusters/reassign', $routes);
        $this->assertNotContains('/recognition/media-identities', $routes);
    }

    public function testTopUnlabeledClustersHydrateThumbnailFallbacks(): void
    {
        $GLOBALS['__ac_attachment_urls'][101] = 'http://example.test/media/101.jpg';

        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                [
                    'id' => 'cluster-1',
                    'representatives' => [
                        [
                            'id' => 'rep-1',
                            'media_id' => 101,
                            'thumb_url' => null,
                        ],
                        [
                            'id' => 'rep-2',
                            'media_id' => 202,
                            'thumbnail_url' => 'http://example.test/media/legacy-202.jpg',
                        ],
                    ],
                ],
            ]),
        ]);

        $request = new WP_REST_Request('GET', '/acx/v1/recognition/clusters/top-unlabeled');
        $response = $this->controller->list_top_unlabeled_clusters($request);

        $this->assertInstanceOf(\WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());

        $data = $response->get_data();
        $this->assertSame('http://example.test/media/101.jpg', $data[0]['representatives'][0]['thumb_url']);
        $this->assertSame('http://example.test/media/legacy-202.jpg', $data[0]['representatives'][1]['thumb_url']);
    }
}
