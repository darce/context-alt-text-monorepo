<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\ClusterMutationsController;
use AltContext\Sovereign\Sync\CurationIdempotencyKey;
use AltContext\Tests\Support\ClusterMutationsMembersSpy;
use AltContext\Tests\Support\ClusterMutationsRepositorySpy;
use AltContext\Tests\Support\ClusterMutationsSyncStateSpy;
use AltContext\Tests\Support\ClusterMutationsTopologyCommandSpy;
use AltContext\Tests\TestCase;
use ReflectionMethod;

/**
 * Characterization guard (E15-35 Slice 3, PR3-01/[TEST-03]): the shared
 * idempotency-key helper extracted from ClusterMutationsController must produce
 * BYTE-IDENTICAL keys to the pre-extraction private derivation so replayed
 * curation operations keep collapsing onto the same outbox row.
 *
 * @covers \AltContext\Sovereign\Sync\CurationIdempotencyKey
 */
class CurationIdempotencyKeyTest extends TestCase
{
    public function testDeriveMatchesLegacyControllerDerivationByteForByte(): void
    {
        $payload = ['cluster_uuid' => 'cluster-a', 'label' => 'Alice'];

        // Inline copy of the pre-extraction derive_curation_idempotency_key() +
        // format_idempotency_key() algorithm.
        $basis = wp_json_encode(
            [
                'tenant_id'       => 'tenant-1',
                'operation_type'  => 'cluster_label_updated',
                'entity_type'     => 'cluster',
                'entity_key'      => 'cluster-a',
                'target_revision' => 4,
                'payload'         => $payload,
            ]
        );
        $this->assertIsString($basis);
        $hash = md5($basis);
        $expected = sprintf(
            '%s-%s-%s-%s-%s',
            substr($hash, 0, 8),
            substr($hash, 8, 4),
            substr($hash, 12, 4),
            substr($hash, 16, 4),
            substr($hash, 20, 12)
        );

        $this->assertSame(
            $expected,
            CurationIdempotencyKey::derive('tenant-1', 'cluster_label_updated', 'cluster', 'cluster-a', 4, $payload)
        );
    }

    public function testControllerPrivateDerivationDelegatesToSharedHelper(): void
    {
        $this->setOption('acx_recognition_url', 'http://localhost:8000');
        $this->setOption('acx_recognition_source', 'service');
        $controller = new ClusterMutationsController(
            new ClusterMutationsRepositorySpy(),
            new ClusterMutationsSyncStateSpy(),
            new ClusterMutationsMembersSpy(),
            null,
            new ClusterMutationsTopologyCommandSpy()
        );

        $payload = ['tenant_id' => 'tenant-2', 'identity_id' => 'identity-9', 'target_cluster_id' => 'cluster-z', 'user_id' => 0];
        $method = new ReflectionMethod(ClusterMutationsController::class, 'derive_curation_idempotency_key');
        $controllerKey = $method->invoke($controller, 'tenant-2', 'identity_reassigned', 'member', 'identity-9', 1, $payload);

        $this->assertSame(
            CurationIdempotencyKey::derive('tenant-2', 'identity_reassigned', 'member', 'identity-9', 1, $payload),
            $controllerKey
        );
    }

    public function testFormatMatchesLegacyUuidStyleGrouping(): void
    {
        $formatted = CurationIdempotencyKey::format('some-basis');
        $hash = md5('some-basis');

        $this->assertSame(
            sprintf(
                '%s-%s-%s-%s-%s',
                substr($hash, 0, 8),
                substr($hash, 8, 4),
                substr($hash, 12, 4),
                substr($hash, 16, 4),
                substr($hash, 20, 12)
            ),
            $formatted
        );
    }
}
