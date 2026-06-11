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

    public function testBuildClusterListEnvelopeUsesTotalCountFromRows(): void
    {
        $rows = [['total_count' => 5]];
        $clusters = [['id' => 'c1']];

        $envelope = $this->service->build_cluster_list_envelope($rows, $clusters, 1);

        $this->assertSame($clusters, $envelope['clusters']);
        $this->assertSame(1, $envelope['limit']);
        $this->assertSame(5, $envelope['total']);
        $this->assertTrue($envelope['truncated']);
    }

    public function testNormalizeClusterMembersResponseAcceptsCanonicalEnvelope(): void
    {
        $response = new WP_REST_Response([
            'members' => [['id' => 'm1']],
            'limit' => 10,
            'total' => 1,
            'truncated' => false,
        ], 200);

        $result = $this->service->normalize_cluster_members_response($response, 10);

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $this->assertSame(200, $result->get_status());
        $data = $result->get_data();
        $this->assertSame([['id' => 'm1']], $data['members']);
        $this->assertSame(10, $data['limit']);
        $this->assertSame(1, $data['total']);
        $this->assertFalse($data['truncated']);
    }

    public function testNormalizeClusterLabelsResponseAcceptsCanonicalEnvelope(): void
    {
        $response = new WP_REST_Response([
            'labels' => ['Alice'],
            'limit' => 5,
            'total' => 1,
            'truncated' => false,
        ], 200);

        $result = $this->service->normalize_cluster_labels_response($response, 5);

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $this->assertSame(['Alice'], $result->get_data()['labels']);
    }
}
