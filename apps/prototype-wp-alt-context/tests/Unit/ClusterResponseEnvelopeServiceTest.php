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

    /**
     * Legacy bare-array list payloads must not fabricate total/limit [rg-015].
     */
    public function testNormalizeClusterListResponseRejectsLegacyBareArray(): void
    {
        $response = new WP_REST_Response([
            ['id' => 'c1'],
            ['id' => 'c2'],
        ], 200);

        $result = $this->service->normalize_cluster_list_response($response, 50);

        $this->assertInstanceOf(WP_Error::class, $result);
        $this->assertSame('invalid_cluster_list_envelope', $result->get_error_code());
        $this->assertSame(502, $result->get_error_data()['status']);
    }

    /**
     * Legacy bare-array top-unlabeled payloads must not fabricate total/limit [rg-015].
     */
    public function testNormalizeTopUnlabeledResponseRejectsLegacyBareArray(): void
    {
        $response = new WP_REST_Response([
            ['id' => 'c1', 'label' => null, 'identity_count' => 4],
        ], 200);

        $result = $this->service->normalize_top_unlabeled_response($response);

        $this->assertInstanceOf(WP_Error::class, $result);
        $this->assertSame('invalid_top_unlabeled_envelope', $result->get_error_code());
        $this->assertSame(502, $result->get_error_data()['status']);
    }

    public function testNormalizeTopUnlabeledResponseAcceptsCanonicalEnvelope(): void
    {
        $response = new WP_REST_Response([
            'clusters' => [['id' => 'c1', 'representatives' => [['id' => 'r1', 'media_id' => 1, 'is_pinned' => false]]]],
            'limit' => 10,
            'total' => 1,
            'truncated' => false,
        ], 200);

        $result = $this->service->normalize_top_unlabeled_response($response);

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $data = $result->get_data();
        $this->assertSame('c1', $data['clusters'][0]['id']);
        $this->assertSame(10, $data['limit']);
        $this->assertSame(1, $data['total']);
        $this->assertFalse($data['truncated']);
        $this->assertFalse($data['repair_pending']);
        $this->assertSame('unlabeled', $data['clusters'][0]['label_state']);
    }

    /**
     * Plugin-owned proxy envelope backfills omitted label_state from label.
     */
    public function testNormalizeTopUnlabeledResponseBackfillsOmittedLabelState(): void
    {
        $response = new WP_REST_Response([
            'clusters' => [
                [
                    'id' => 'cluster-omit',
                    'label' => null,
                    'identity_count' => 2,
                    'representatives' => [
                        ['id' => 'r1', 'media_id' => 1, 'is_pinned' => false],
                    ],
                ],
            ],
            'limit' => 10,
            'total' => 1,
            'truncated' => false,
        ], 200);

        $result = $this->service->normalize_top_unlabeled_response($response);

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $this->assertSame('unlabeled', $result->get_data()['clusters'][0]['label_state']);
    }

    /**
     * A valid upstream label_state must not be overwritten.
     */
    public function testNormalizeTopUnlabeledResponsePreservesUpstreamLabelState(): void
    {
        $response = new WP_REST_Response([
            'clusters' => [
                [
                    'id' => 'cluster-person',
                    'label' => 'Ada',
                    'label_state' => 'person',
                    'identity_count' => 2,
                    'representatives' => [
                        ['id' => 'r1', 'media_id' => 1, 'is_pinned' => false],
                    ],
                ],
            ],
            'limit' => 10,
            'total' => 1,
            'truncated' => false,
        ], 200);

        $result = $this->service->normalize_top_unlabeled_response($response);

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $this->assertSame('person', $result->get_data()['clusters'][0]['label_state']);
    }

    /**
     * R2-02: proxy must drop empty-representative rows (schema minItems=1).
     */
    public function testNormalizeTopUnlabeledResponseDropsEmptyRepresentativeRows(): void
    {
        $response = new WP_REST_Response([
            'clusters' => [
                [
                    'id' => 'cluster-empty-reps',
                    'label' => null,
                    'identity_count' => 4,
                    'representatives' => [],
                ],
                [
                    'id' => 'cluster-kept',
                    'label' => null,
                    'identity_count' => 2,
                    'representatives' => [
                        ['id' => 'r1', 'media_id' => 1, 'is_pinned' => false],
                    ],
                ],
            ],
            'limit' => 10,
            'total' => 2,
            'truncated' => false,
        ], 200);

        $result = $this->service->normalize_top_unlabeled_response($response);

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $data = $result->get_data();
        $this->assertCount(1, $data['clusters']);
        $this->assertSame('cluster-kept', $data['clusters'][0]['id']);
        $this->assertSame(2, $data['total']);
        $this->assertFalse($data['truncated']);
        $this->assertTrue($data['repair_pending']);
    }

    /**
     * R3-02 / R3-04: dropped empty-rep rows set repair_pending and do not shrink total.
     */
    public function testNormalizeTopUnlabeledResponseDropsDoNotShrinkTotal(): void
    {
        $response = new WP_REST_Response([
            'clusters' => [
                [
                    'id' => 'cluster-empty-a',
                    'label' => null,
                    'identity_count' => 3,
                    'representatives' => [],
                ],
                [
                    'id' => 'cluster-kept',
                    'label' => null,
                    'identity_count' => 4,
                    'representatives' => [
                        ['id' => 'r1', 'media_id' => 1, 'is_pinned' => false],
                    ],
                ],
                [
                    'id' => 'cluster-empty-b',
                    'label' => null,
                    'identity_count' => 5,
                    'representatives' => [],
                ],
            ],
            'limit' => 10,
            'total' => 12,
            'truncated' => false,
        ], 200);

        $result = $this->service->normalize_top_unlabeled_response($response);

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $data = $result->get_data();
        $this->assertCount(1, $data['clusters']);
        $this->assertSame(12, $data['total']);
        $this->assertTrue($data['repair_pending']);
        $this->assertFalse($data['truncated']);
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

        $result = $this->service->normalize_cluster_members_response($response);

        $this->assertInstanceOf(WP_REST_Response::class, $result);
        $this->assertSame(200, $result->get_status());
        $data = $result->get_data();
        $this->assertSame([['id' => 'm1']], $data['members']);
        $this->assertSame(10, $data['limit']);
        $this->assertSame(1, $data['total']);
        $this->assertFalse($data['truncated']);
    }

    /**
     * Legacy bare-array payloads carry no envelope metadata; fabricating
     * total/limit from count() would invent contract metadata [rg-015].
     */
    public function testNormalizeClusterMembersResponseRejectsLegacyBareArray(): void
    {
        $response = new WP_REST_Response([
            ['id' => 'm1'],
            ['id' => 'm2'],
        ], 200);

        $result = $this->service->normalize_cluster_members_response($response);

        $this->assertInstanceOf(WP_Error::class, $result);
        $this->assertSame('invalid_cluster_members_envelope', $result->get_error_code());
        $this->assertSame(502, $result->get_error_data()['status']);
    }

    public function testBuildClusterMembersEnvelopeUsesOffsetForTruncated(): void
    {
        $envelope = $this->service->build_cluster_members_envelope(
            [['id' => 'm3']],
            2,
            5,
            4
        );

        $this->assertSame(2, $envelope['limit']);
        $this->assertSame(5, $envelope['total']);
        $this->assertFalse($envelope['truncated']);

        $midPage = $this->service->build_cluster_members_envelope(
            [['id' => 'm2'], ['id' => 'm3']],
            2,
            5,
            2
        );
        $this->assertTrue($midPage['truncated']);
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
