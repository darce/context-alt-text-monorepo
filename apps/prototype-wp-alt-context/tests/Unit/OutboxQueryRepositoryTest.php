<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\Sync\OutboxQueryRepository;
use AltContext\Tests\TestCase;

class OutboxQueryRepositoryTest extends TestCase
{
    public function testFindFailedOperationsReturnsDecodedRowsOrderedByDate(): void
    {
        global $wpdb;

        $tenantId = 'tenant-test-123';
        $rows = [
            [
                'id' => 12,
                'tenant_id' => $tenantId,
                'operation_type' => 'cluster_label_updated',
                'entity_type' => 'cluster',
                'entity_key' => 'cluster-2',
                'status' => 'failed',
                'attempts' => 5,
                'expected_base_version' => 8,
                'local_revision' => 3,
                'last_error_code' => 'dispatch_failed',
                'last_error_message' => 'newer failure',
                'payload' => '{"cluster_uuid":"cluster-2"}',
                'created_at' => '2026-03-10 12:05:00',
                'last_attempted_at' => '2026-03-10 12:06:00',
                'acknowledged_at' => null,
            ],
            [
                'id' => 11,
                'tenant_id' => $tenantId,
                'operation_type' => 'cluster_dismissed',
                'entity_type' => 'cluster',
                'entity_key' => 'cluster-1',
                'status' => 'failed',
                'attempts' => 4,
                'expected_base_version' => 7,
                'local_revision' => 2,
                'last_error_code' => 'remote_error',
                'last_error_message' => 'older failure',
                'payload' => '{"cluster_uuid":"cluster-1"}',
                'created_at' => '2026-03-10 12:00:00',
                'last_attempted_at' => '2026-03-10 12:01:00',
                'acknowledged_at' => null,
            ],
        ];

        $wpdb->mockResults = $rows;

        $repository = new OutboxQueryRepository();
        $result = $repository->find_operations_by_status($tenantId, 'failed', 50, 0);

        $this->assertSame([12, 11], array_column($result, 'id'));
        $this->assertSame(['cluster_uuid' => 'cluster-2'], $result[0]['payload']);
        $this->assertSame('dispatch_failed', $result[0]['last_error_code']);
    }
}
