<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\Repositories\SyncStateRepository;
use AltContext\Sovereign\Sync\OutboxMaintenanceService;
use AltContext\Sovereign\Sync\OutboxQueryRepository;
use AltContext\Sovereign\Sync\OutboxStatus;
use AltContext\Tests\TestCase;

/**
 * RED regression for conflict replay freshness.
 *
 * A cluster_person_bound conflict that is re-enqueued must rebase onto the current
 * same-tenant canonical person name and rotate the idempotency key for the changed
 * intent. Otherwise the backend's cached conflict replay can re-serve the stale bind
 * (stale label over the user's current person). The person and cluster UUIDs must be
 * preserved, and a missing or foreign-tenant person must fail closed.
 *
 * Only the re-enqueue behaviour is pinned here; no production source is changed.
 */
class OutboxConflictReplayFreshnessTest extends TestCase
{
    private const TENANT_ID = 'tenant-test-123';
    private const FOREIGN_TENANT_ID = 'tenant-foreign-999';
    private const OUTBOX_ID = 42;
    private const CLUSTER_UUID = 'cluster-uuid-freshness-1';
    private const PERSON_UUID = 'person-uuid-freshness-1';
    private const STALE_KEY = 'idem-stale-conflict-key-0001';
    private const STALE_NAME = 'Stale Label Beta';
    private const CANONICAL_NAME = 'Canonical Person Alpha';
    private const BACKEND_VERSION = 7;

    public function testControlReEnqueueRebasesBaseVersionForNonPersonOperation(): void
    {
        global $wpdb;

        // Control: the harness (row seed, fake wpdb update, re-enqueue status write)
        // works today. A failure here is fixture noise, not the causal RED below.
        $this->seedConflictRow('cluster_label_updated', [
            'cluster_uuid' => self::CLUSTER_UUID,
            'label' => self::STALE_NAME,
        ]);

        $service = $this->serviceFor($this->conflictRow('cluster_label_updated', [
            'cluster_uuid' => self::CLUSTER_UUID,
            'label' => self::STALE_NAME,
        ]));

        $this->assertTrue($service->re_enqueue_with_current_base(self::OUTBOX_ID, self::BACKEND_VERSION, self::TENANT_ID));

        $row = $wpdb->tableRows['wp_acx_sync_outbox'][0];
        $this->assertSame(OutboxStatus::PENDING, $row['status']);
        $this->assertSame(self::BACKEND_VERSION, (int) $row['expected_base_version']);
    }

    public function testReEnqueueClusterPersonBoundRebasesToCanonicalPersonName(): void
    {
        $result = $this->reEnqueueBoundConflict();

        $this->assertSame(
            self::CANONICAL_NAME,
            $result['payload']['person_name'],
            'Re-enqueue must rebase onto the current same-tenant canonical person name.'
        );
        $this->assertNotSame(self::STALE_NAME, $result['payload']['person_name'], 'The stale label must never overwrite the canonical person name.');
    }

    public function testReEnqueueClusterPersonBoundRotatesIdempotencyKeyForChangedIntent(): void
    {
        $result = $this->reEnqueueBoundConflict();

        // Changed intent must carry a fresh key so the cached conflict replay cannot re-serve the stale bind.
        $this->assertNotSame('', (string) $result['row']['idempotency_key']);
        $this->assertNotSame(self::STALE_KEY, $result['row']['idempotency_key'], 'Changed bind intent must rotate the idempotency key.');
    }

    /**
     * Preservation guard: the rebase must not change which person or cluster the bind targets.
     * Expected to pass on the current code, so it guards the fix rather than driving it.
     */
    public function testReEnqueueClusterPersonBoundPreservesPersonAndClusterUuidsAndRebasesBaseVersion(): void
    {
        $result = $this->reEnqueueBoundConflict();

        $this->assertSame(OutboxStatus::PENDING, $result['row']['status']);
        $this->assertSame(self::BACKEND_VERSION, (int) $result['row']['expected_base_version'], 'Rebase must use the provided backend version.');
        $this->assertSame(self::PERSON_UUID, $result['payload']['person_uuid']);
        $this->assertSame(self::CLUSTER_UUID, $result['payload']['cluster_uuid']);
    }

    public function testReEnqueueClusterPersonBoundFailsClosedWhenPersonIsMissing(): void
    {
        global $wpdb;

        $this->seedConflictRow('cluster_person_bound', $this->boundPayload(self::STALE_NAME));
        $wpdb->tableRows['wp_acx_persons'] = [];

        $service = $this->serviceFor($this->conflictRow('cluster_person_bound', $this->boundPayload(self::STALE_NAME)));

        $this->assertFalse(
            $service->re_enqueue_with_current_base(self::OUTBOX_ID, self::BACKEND_VERSION, self::TENANT_ID),
            'A missing person must fail closed rather than re-enqueue the stale bind.'
        );
        $this->assertBindRowUnchanged();
    }

    public function testReEnqueueClusterPersonBoundFailsClosedForForeignTenantPerson(): void
    {
        global $wpdb;

        $this->seedConflictRow('cluster_person_bound', $this->boundPayload(self::STALE_NAME));
        $wpdb->tableRows['wp_acx_persons'] = [$this->personRow(self::FOREIGN_TENANT_ID, self::CANONICAL_NAME)];

        $service = $this->serviceFor($this->conflictRow('cluster_person_bound', $this->boundPayload(self::STALE_NAME)));

        $this->assertFalse(
            $service->re_enqueue_with_current_base(self::OUTBOX_ID, self::BACKEND_VERSION, self::TENANT_ID),
            'A person that exists only under a foreign tenant must not supply the canonical name.'
        );
        $this->assertBindRowUnchanged();
    }

    /**
     * Seeds a cluster_person_bound conflict with a live same-tenant person whose canonical
     * name differs from the stale payload label, then performs the explicit re-enqueue.
     *
     * @return array{row:array<string,mixed>,payload:array<string,mixed>}
     */
    private function reEnqueueBoundConflict(): array
    {
        global $wpdb;

        $this->seedConflictRow('cluster_person_bound', $this->boundPayload(self::STALE_NAME));
        $wpdb->tableRows['wp_acx_persons'] = [$this->personRow(self::TENANT_ID, self::CANONICAL_NAME)];

        $service = $this->serviceFor($this->conflictRow('cluster_person_bound', $this->boundPayload(self::STALE_NAME)));

        $this->assertTrue(
            $service->re_enqueue_with_current_base(self::OUTBOX_ID, self::BACKEND_VERSION, self::TENANT_ID),
            'Explicit conflict re-enqueue must succeed for a same-tenant person that still exists.'
        );

        $row = $wpdb->tableRows['wp_acx_sync_outbox'][0];
        $payload = json_decode((string) $row['payload'], true);
        $this->assertIsArray($payload);

        return ['row' => $row, 'payload' => $payload];
    }

    /**
     * @return array<string,mixed>
     */
    private function boundPayload(string $personName): array
    {
        return [
            'cluster_uuid' => self::CLUSTER_UUID,
            'person_uuid' => self::PERSON_UUID,
            'person_name' => $personName,
        ];
    }

    /**
     * @return array<string,mixed>
     */
    private function personRow(string $tenantId, string $name): array
    {
        return [
            'id' => 7,
            'tenant_id' => $tenantId,
            'person_uuid' => self::PERSON_UUID,
            'name' => $name,
        ];
    }

    /**
     * @param array<string,mixed> $payload
     * @return array<string,mixed>
     */
    private function conflictRow(string $operationType, array $payload): array
    {
        return [
            'id' => self::OUTBOX_ID,
            'tenant_id' => self::TENANT_ID,
            'operation_type' => $operationType,
            'entity_type' => 'cluster',
            'entity_key' => self::CLUSTER_UUID,
            'idempotency_key' => self::STALE_KEY,
            'expected_base_version' => 3,
            'local_revision' => 1,
            'status' => OutboxStatus::CONFLICT,
            'attempts' => 0,
            'payload' => (string) json_encode($payload),
            'last_error_code' => 'version_conflict',
            'last_error_message' => 'Remote version moved.',
            'last_error_retryable' => 0,
            'last_attempted_at' => '2026-07-16 01:00:00',
            'first_failed_at' => null,
            'next_attempt_at' => null,
        ];
    }

    /**
     * @param array<string,mixed> $payload
     */
    private function seedConflictRow(string $operationType, array $payload): void
    {
        global $wpdb;

        $wpdb->tableRows['wp_acx_sync_outbox'] = [$this->conflictRow($operationType, $payload)];
    }

    /**
     * @param array<string,mixed> $operation
     */
    private function serviceFor(array $operation): OutboxMaintenanceService
    {
        $repository = new class($operation) extends OutboxQueryRepository {
            /** @var array<string,mixed> */
            private array $operation;

            /** @param array<string,mixed> $operation */
            public function __construct(array $operation)
            {
                $this->operation = $operation;
            }

            public function find_operation_by_id(int $outbox_id, string $tenant_id): ?array
            {
                return $this->operation;
            }
        };

        $syncState = new class extends SyncStateRepository {
            public function refresh_curation_metrics(string $tenant_id): void
            {
            }
        };

        return new OutboxMaintenanceService($repository, $syncState);
    }

    private function assertBindRowUnchanged(): void
    {
        global $wpdb;

        $row = $wpdb->tableRows['wp_acx_sync_outbox'][0];
        $this->assertSame(OutboxStatus::CONFLICT, $row['status'], 'Fail-closed path must leave the conflict row unresolved.');
        $this->assertSame(self::STALE_KEY, $row['idempotency_key'], 'Fail-closed path must not rotate or replay keys.');
        $this->assertSame(3, (int) $row['expected_base_version'], 'Fail-closed path must not rebase the base version.');
    }
}
