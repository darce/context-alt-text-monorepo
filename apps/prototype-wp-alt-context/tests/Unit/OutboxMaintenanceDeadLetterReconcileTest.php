<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\Repositories\SyncStateRepository;
use AltContext\Sovereign\Sync\OutboxMaintenanceService;
use AltContext\Sovereign\Sync\OutboxStatus;
use AltContext\Tests\TestCase;

class OutboxMaintenanceDeadLetterReconcileTest extends TestCase
{
    public function testPurgeDiscardsDeadLetteredRowsForMissingClusters(): void
    {
        global $wpdb;

        $tenantId = 'tenant-exhausted-orphan';
        $wpdb->defaultQueryResult = 0;
        $wpdb->tableRows['wp_acx_sync_outbox'] = [
            $this->buildDeadLetteredLabelRow(401, $tenantId, 'cluster-missing', 'Old label'),
        ];

        $service = new OutboxMaintenanceService(
            null,
            $this->trackingSyncStateRepository(),
            'wp_acx_sync_outbox',
            'wp_acx_sync_conflicts'
        );
        $purged = $service->purge_terminal_rows($tenantId);

        $this->assertSame(1, $purged['orphaned']);
        $this->assertSame(OutboxStatus::DISCARDED, $wpdb->tableRows['wp_acx_sync_outbox'][0]['status']);
        $audits = $this->actionsNamed('acx_sync_outbox_orphan_discarded');
        $this->assertCount(1, $audits);
        $this->assertSame('auto_retry_exhausted', $audits[0]['args'][0]['last_error_code']);
    }

    public function testPurgeDiscardsDeadLetteredLabelWhenTenantCurrentLabelSupersedesPayload(): void
    {
        global $wpdb;

        $tenantId = 'tenant-superseded-label';
        $wpdb->defaultQueryResult = 0;
        $wpdb->tableRows['wp_acx_sync_outbox'] = [
            $this->buildDeadLetteredLabelRow(402, $tenantId, 'cluster-live', 'Old label'),
        ];
        $wpdb->tableRows['wp_acx_clusters'] = [
            [
                'cluster_uuid' => 'cluster-live',
                'tenant_id' => $tenantId,
                'label' => 'Current label',
            ],
            [
                'cluster_uuid' => 'cluster-live',
                'tenant_id' => 'tenant-other',
                'label' => 'Old label',
            ],
        ];

        $service = new OutboxMaintenanceService(
            null,
            $this->trackingSyncStateRepository(),
            'wp_acx_sync_outbox',
            'wp_acx_sync_conflicts'
        );
        $purged = $service->purge_terminal_rows($tenantId);

        $this->assertSame(1, $purged['superseded']);
        $this->assertSame(OutboxStatus::DISCARDED, $wpdb->tableRows['wp_acx_sync_outbox'][0]['status']);
        $labelQuery = $this->findQueryContaining($wpdb->queries, 'SELECT label FROM `wp_acx_clusters`');
        $this->assertStringContainsString("cluster_uuid = 'cluster-live'", $labelQuery);
        $this->assertStringContainsString("tenant_id = '{$tenantId}'", $labelQuery);
        $this->assertStringContainsString('FOR UPDATE', $labelQuery);
        $this->assertSame([], $this->actionsNamed('acx_sync_outbox_orphan_discarded'));
    }

    /**
     * @return array<string,mixed>
     */
    private function buildDeadLetteredLabelRow(int $id, string $tenantId, string $clusterUuid, string $label): array
    {
        $stamp = '2026-09-16 00:00:00';

        return [
            'id' => $id,
            'tenant_id' => $tenantId,
            'operation_type' => 'cluster_label_updated',
            'entity_type' => 'cluster',
            'entity_key' => $clusterUuid,
            'status' => OutboxStatus::FAILED,
            'attempts' => 3,
            'last_error_code' => 'auto_retry_exhausted',
            'last_error_message' => 'retry budget exhausted',
            'last_error_retryable' => 1,
            'first_failed_at' => $stamp,
            'last_attempted_at' => $stamp,
            'created_at' => $stamp,
            'payload' => wp_json_encode(['label' => $label, 'acx_auto_attempts' => 3]),
            'next_attempt_at' => null,
        ];
    }

    private function trackingSyncStateRepository(): SyncStateRepository
    {
        return new class() extends SyncStateRepository {
            public function refresh_curation_metrics(string $tenant_id): void
            {
            }
        };
    }

    /**
     * @param array<int,string> $queries
     */
    private function findQueryContaining(array $queries, string $needle): string
    {
        foreach ($queries as $query) {
            if (str_contains($query, $needle)) {
                return $query;
            }
        }

        $this->fail(sprintf('Unable to find query containing "%s".', $needle));
    }
}
