<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\Services\ClusterResponseEnvelopeService;
use AltContext\Tests\TestCase;
use WP_Error;
use WP_REST_Response;

/**
 * @covers \AltContext\Api\Services\ClusterResponseEnvelopeService
 */
class ClusterResponseEnvelopeServiceTest extends TestCase
{
    private ClusterResponseEnvelopeService $service;

    protected function setUp(): void
    {
        parent::setUp();
        $this->service = new ClusterResponseEnvelopeService();
    }

    public function testNormalizeClusterListResponseRejectsPartialEnvelope(): void
    {
        $response = new WP_REST_Response([
            'clusters' => [],
            'limit' => 50,
        ], 200);

        $result = $this->service->normalize_cluster_list_response($response, 50);

        $this->assertInstanceOf(WP_Error::class, $result);
        $this->assertSame('invalid_cluster_list_envelope', $result->get_error_code());
        $this->assertSame(502, $result->get_error_data()['status']);
    }

    public function testBuildClusterLabelsEnvelopeTruncatesWhenTotalExceedsCount(): void
    {
        $envelope = $this->service->build_cluster_labels_envelope(['Alice'], 1, 2);

        $this->assertSame(['Alice'], $envelope['labels']);
        $this->assertSame(1, $envelope['limit']);
        $this->assertSame(2, $envelope['total']);
        $this->assertTrue($envelope['truncated']);
    }
}
