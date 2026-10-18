<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\ClusterMutationsController;
use AltContext\Api\Services\ClusterLabelService;
use AltContext\Sovereign\Sync\CurationIdempotencyKey;
use AltContext\Tests\Support\ClusterMutationsMembersSpy;
use AltContext\Tests\Support\ClusterMutationsRepositorySpy;
use AltContext\Tests\Support\ClusterMutationsSyncStateSpy;
use AltContext\Tests\Support\ClusterMutationsTopologyCommandSpy;
use AltContext\Tests\TestCase;
use WP_REST_Request;
use WP_REST_Response;

/** Producer contract for decision 16679; production remains unchanged in RED. */
class ClusterLabelIntentProvenanceTest extends TestCase
{
    private const CLUSTER_UUID = 'd0955c89-090a-4eab-90ee-d3f619d9218f';
    private const LABEL = 'Canonical Person';
    private const PERSON_UUID = 'c7cd7183-a15f-4d85-9a52-b42fc650a109';

    private ?ClusterLabelService $service = null;

    /** @return list<array<string,mixed>> */
    private function executeCommand(bool $existingPerson = false): array
    {
        global $wpdb;

        $repository = new ClusterMutationsRepositorySpy();
        $repository->localClusterRows = [self::CLUSTER_UUID => [
            'cluster_uuid' => self::CLUSTER_UUID,
            'tenant_id' => self::currentTenantId(),
            'snapshot_version' => 17,
            'local_revision' => 0,
            'person_id' => null,
            'label' => 'Unassigned',
        ]];
        $wpdb->tableRows['wp_acx_clusters'] = array_values($repository->localClusterRows);
        $wpdb->tableRows['wp_acx_persons'] = $existingPerson ? [[
            'id' => 42,
            'person_uuid' => self::PERSON_UUID,
            'tenant_id' => self::currentTenantId(),
            'name' => self::LABEL,
            'normalized_name' => 'canonical person',
            'tags' => '[]',
        ]] : [];
        $wpdb->tableRows['wp_acx_sync_outbox'] = [];
        $wpdb->insert_id = 77;
        if (null === $this->service) {
            $syncState = new ClusterMutationsSyncStateSpy();
            $host = new ClusterMutationsController(
                $repository,
                $syncState,
                new ClusterMutationsMembersSpy(),
                null,
                new ClusterMutationsTopologyCommandSpy()
            );
            $this->service = new ClusterLabelService($host, $repository, $syncState);
        }
        $request = new WP_REST_Request('PATCH', '/acx/v1/recognition/clusters/' . self::CLUSTER_UUID);
        $request->set_param('cluster_id', self::CLUSTER_UUID);
        $request->set_param('label', self::LABEL);
        $queryStart = count($wpdb->queries);
        $response = $this->service->update_cluster_label($request);

        $this->assertInstanceOf(WP_REST_Response::class, $response);
        $this->assertSame(200, $response->get_status());
        $this->assertSame('pending', $response->get_data()['status']);
        $this->assertTrue($response->get_data()['roster_bound']);
        $this->assertSame(self::CLUSTER_UUID, $response->get_data()['cluster_id']);
        $this->assertSame(self::LABEL, $response->get_data()['label']);

        $queries = array_slice($wpdb->queries, $queryStart);
        $start = array_search('START TRANSACTION', $queries, true);
        $commit = array_search('COMMIT', $queries, true);
        $this->assertIsInt($start);
        $this->assertIsInt($commit);
        $this->assertSame(1, count(array_keys($queries, 'START TRANSACTION', true)));
        $this->assertNotContains('ROLLBACK', $queries);
        foreach ($queries as $index => $query) {
            if (str_contains($query, 'INSERT INTO wp_acx_sync_outbox')) {
                $this->assertGreaterThan($start, $index);
                $this->assertLessThan($commit, $index);
            }
        }

        return array_values($wpdb->tableRows['wp_acx_sync_outbox'] ?? []);
    }

    public function testLabelPersonCreatedAndBindShareOneValidIntent(): void
    {
        $rows = $this->executeCommand();
        $this->assertSame(
            ['cluster_label_updated', 'person_created', 'cluster_person_bound'],
            array_column($rows, 'operation_type')
        );
        $intents = [];
        foreach ($rows as $row) {
            $payload = json_decode($row['payload'], true, 512, JSON_THROW_ON_ERROR);
            $this->assertArrayHasKey('curation_intent_id', $payload, $row['operation_type'] . ' must carry explicit command provenance.');
            $this->assertIsString($payload['curation_intent_id']);
            $this->assertMatchesRegularExpression(
                '/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i',
                $payload['curation_intent_id']
            );
            $intents[] = $payload['curation_intent_id'];
        }
        $this->assertSame([$intents[0], $intents[0], $intents[0]], $intents);
    }

    public function testExistingPersonLabelAndBindShareOneValidIntent(): void
    {
        $rows = $this->executeCommand(true);
        $this->assertSame(['cluster_label_updated', 'cluster_person_bound'], array_column($rows, 'operation_type'));
        $label = json_decode($rows[0]['payload'], true, 512, JSON_THROW_ON_ERROR);
        $bind = json_decode($rows[1]['payload'], true, 512, JSON_THROW_ON_ERROR);
        $this->assertArrayHasKey('curation_intent_id', $label, 'An existing person still needs command provenance.');
        $this->assertIsString($label['curation_intent_id']);
        $this->assertMatchesRegularExpression(
            '/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i',
            $label['curation_intent_id']
        );
        $this->assertSame($label['curation_intent_id'], $bind['curation_intent_id'] ?? null);
    }

    public function testIndependentCommandsWithIdenticalClusterBaseAndRevisionHaveDifferentIntents(): void
    {
        // Two isolated device snapshots of the same cluster/person, with identical
        // label, base and revision. No global-state reset between public commands.
        $first = $this->executeCommand(true);
        $second = $this->executeCommand(true);
        foreach (['tenant_id', 'entity_key', 'expected_base_version', 'local_revision'] as $field) {
            $this->assertSame(array_column($first, $field), array_column($second, $field));
        }
        $firstPayload = json_decode($first[0]['payload'], true, 512, JSON_THROW_ON_ERROR);
        $secondPayload = json_decode($second[0]['payload'], true, 512, JSON_THROW_ON_ERROR);
        $this->assertNotSame(
            $firstPayload['curation_intent_id'] ?? null,
            $secondPayload['curation_intent_id'] ?? null,
            'Equal cluster/base/revision cannot identify independent curation commands.'
        );
        foreach ([$first, $second] as $rows) {
            $label = json_decode($rows[0]['payload'], true, 512, JSON_THROW_ON_ERROR);
            $bind = json_decode($rows[1]['payload'], true, 512, JSON_THROW_ON_ERROR);
            $this->assertIsString($label['curation_intent_id'] ?? null);
            $this->assertMatchesRegularExpression(
                '/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i',
                $label['curation_intent_id']
            );
            $this->assertSame($label['curation_intent_id'], $bind['curation_intent_id'] ?? null);
        }
    }

    public function testControlNewPersonPreservesPayloadIdentityAndIdempotency(): void
    {
        global $wpdb;

        $rows = $this->executeCommand();
        $personUuid = $wpdb->tableRows['wp_acx_persons'][0]['person_uuid'];
        $this->assertSame(['cluster_label_updated', 'person_created', 'cluster_person_bound'], array_column($rows, 'operation_type'));
        $this->assertPreservedOperation($rows[0], 'cluster', self::CLUSTER_UUID, [
            'cluster_uuid' => self::CLUSTER_UUID,
            'label' => self::LABEL,
        ]);
        $this->assertPreservedOperation($rows[1], 'person', $personUuid, [
            'person_uuid' => $personUuid,
            'name' => self::LABEL,
            'tags' => [],
        ]);
        $this->assertPreservedOperation($rows[2], 'cluster', self::CLUSTER_UUID, [
            'cluster_uuid' => self::CLUSTER_UUID,
            'person_uuid' => $personUuid,
            'person_name' => self::LABEL,
        ]);
    }

    public function testControlExistingPersonPreservesBindingWithoutCreatingPerson(): void
    {
        $rows = $this->executeCommand(true);
        $this->assertSame(['cluster_label_updated', 'cluster_person_bound'], array_column($rows, 'operation_type'));
        $this->assertPreservedOperation($rows[0], 'cluster', self::CLUSTER_UUID, [
            'cluster_uuid' => self::CLUSTER_UUID,
            'label' => self::LABEL,
        ]);
        $this->assertPreservedOperation($rows[1], 'cluster', self::CLUSTER_UUID, [
            'cluster_uuid' => self::CLUSTER_UUID,
            'person_uuid' => self::PERSON_UUID,
            'person_name' => self::LABEL,
        ]);
    }

    /** @param array<string,mixed> $row @param array<string,mixed> $expectedPayload */
    private function assertPreservedOperation(array $row, string $entityType, string $entityKey, array $expectedPayload): void
    {
        $this->assertSame(self::currentTenantId(), $row['tenant_id']);
        $this->assertSame($entityType, $row['entity_type']);
        $this->assertSame($entityKey, $row['entity_key']);
        $this->assertSame(17, (int) $row['expected_base_version']);
        $this->assertSame(1, (int) $row['local_revision']);
        $this->assertSame('pending', $row['status']);
        $payload = json_decode($row['payload'], true, 512, JSON_THROW_ON_ERROR);
        unset($payload['curation_intent_id']);
        $this->assertSame($expectedPayload, $payload);
        $this->assertSame(
            CurationIdempotencyKey::derive(self::currentTenantId(), $row['operation_type'], $entityType, $entityKey, 1, $expectedPayload),
            $row['idempotency_key'],
            'Adding command provenance must preserve the existing idempotency identity.'
        );
    }
}
