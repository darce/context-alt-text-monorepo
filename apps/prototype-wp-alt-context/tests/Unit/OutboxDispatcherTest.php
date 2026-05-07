<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\Sync\OutboxDispatcher;
use AltContext\Tests\TestCase;
use WP_Error;

class OutboxDispatcherTest extends TestCase
{
    public function testDispatchReturnsAcknowledgedForSuccessfulResponse(): void
    {
        $this->setOption('acx_recognition_url', 'http://localhost:8000');
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => wp_json_encode([
                'status' => 'acknowledged',
                'backend_version' => 41,
            ]),
        ]);

        $dispatcher = new OutboxDispatcher();
        $result = $dispatcher->dispatch($this->sampleOperation());

        $this->assertSame('acknowledged', $result['status']);
        $this->assertSame(41, $result['backend_version']);

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $this->assertStringContainsString('/roster/curation/sync', $calls[0]['url']);
        $this->assertSame('POST', $calls[0]['method']);

        $body = (string) ($calls[0]['body'] ?? '');
        $this->assertStringContainsString('"operation_type":"cluster_person_bound"', $body);
        $this->assertStringContainsString('"entity_type":"cluster"', $body);
        $this->assertStringContainsString('"entity_key":"cluster-1"', $body);
        $this->assertStringContainsString('"idempotency_key":"idem-1"', $body);
        $this->assertStringContainsString('"expected_base_version":12', $body);
        $this->assertStringContainsString('"local_revision":4', $body);
        $this->assertStringContainsString('"cluster_uuid":"cluster-1"', $body);
        $this->assertStringContainsString('"person_uuid":"person-1"', $body);
        $this->assertStringContainsString('"person_name":"Person One"', $body);
    }

    public function testDispatchReturnsConflictFor409Response(): void
    {
        $this->setOption('acx_recognition_url', 'http://localhost:8000');
        $this->queueHttpResponse([
            'response' => ['code' => 409, 'message' => 'Conflict'],
            'body' => wp_json_encode([
                'status' => 'conflict',
                'conflict_code' => 'version_conflict',
                'backend_version' => 22,
                'machine_payload' => ['cluster_uuid' => 'cluster-1'],
            ]),
        ]);

        $dispatcher = new OutboxDispatcher();
        $result = $dispatcher->dispatch($this->sampleOperation());

        $this->assertSame('conflict', $result['status']);
        $this->assertSame('version_conflict', $result['conflict_code']);
        $this->assertSame(22, $result['backend_version']);
        $this->assertSame(['cluster_uuid' => 'cluster-1'], $result['machine_payload']);
    }

    public function testDispatchBatchSendsMultipleOperationsInOneRequest(): void
    {
        $this->setOption('acx_recognition_url', 'http://localhost:8000');
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => wp_json_encode([
                'results' => [
                    [
                        'status' => 'acknowledged',
                        'backend_version' => 41,
                        'idempotency_key' => 'idem-1',
                    ],
                    [
                        'status' => 'conflict',
                        'backend_version' => 42,
                        'idempotency_key' => 'idem-2',
                        'conflict_code' => 'version_conflict',
                        'machine_payload' => ['cluster_uuid' => 'cluster-2'],
                    ],
                ],
            ]),
        ]);

        $dispatcher = new OutboxDispatcher();
        $results = $dispatcher->dispatch_batch([
            $this->sampleOperation(),
            [
                'operation_type' => 'cluster_person_unbound',
                'entity_type' => 'cluster',
                'entity_key' => 'cluster-2',
                'idempotency_key' => 'idem-2',
                'expected_base_version' => 12,
                'local_revision' => 5,
                'payload' => [
                    'cluster_uuid' => 'cluster-2',
                    'person_uuid' => null,
                ],
            ],
        ]);

        $this->assertCount(2, $results);
        $this->assertSame('acknowledged', $results[0]['status']);
        $this->assertSame(41, $results[0]['backend_version']);
        $this->assertSame('conflict', $results[1]['status']);
        $this->assertSame(42, $results[1]['backend_version']);
        $this->assertSame('version_conflict', $results[1]['conflict_code']);

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $body = (string) ($calls[0]['body'] ?? '');
        $this->assertStringContainsString('"operations":[', $body);
        $this->assertStringContainsString('"idempotency_key":"idem-1"', $body);
        $this->assertStringContainsString('"idempotency_key":"idem-2"', $body);
    }

    public function testDispatchReturnsFailedForTransportError(): void
    {
        $this->setOption('acx_recognition_url', 'http://localhost:8000');
        $this->queueHttpResponse(new WP_Error('connection_refused', 'Connection refused'));
        $this->queueHttpResponse(new WP_Error('connection_refused', 'Connection refused'));
        $this->queueHttpResponse(new WP_Error('connection_refused', 'Connection refused'));

        $dispatcher = new OutboxDispatcher();
        $result = $dispatcher->dispatch($this->sampleOperation());

        $this->assertSame('failed', $result['status']);
        $this->assertSame('connection_refused', $result['error_code']);
        $this->assertTrue($result['retryable']);
    }

    public function testDispatchRoutesTopologyOperationsToRecognitionEndpoints(): void
    {
        $this->setOption('acx_recognition_url', 'http://localhost:8000');
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => wp_json_encode([
                'cluster_id' => 'cluster-target',
            ]),
        ]);

        $dispatcher = new OutboxDispatcher();
        $result = $dispatcher->dispatch([
            'operation_type' => 'cluster_merged',
            'entity_type' => 'cluster',
            'entity_key' => 'cluster-source',
            'idempotency_key' => 'idem-merge',
            'expected_base_version' => 19,
            'local_revision' => 7,
            'payload' => [
                'target_cluster_id' => 'cluster-target',
                'target_label' => 'Merged Cluster',
            ],
        ]);

        $this->assertSame('acknowledged', $result['status']);

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $this->assertStringContainsString('/recognition/clusters/cluster-source/merge', $calls[0]['url']);

        $body = (string) ($calls[0]['body'] ?? '');
        $this->assertStringContainsString('"tenant_id"', $body);
        $this->assertStringContainsString('"target_cluster_id":"cluster-target"', $body);
        $this->assertStringContainsString('"idempotency_key":"idem-merge"', $body);
    }

    public function testDispatchBatchPartitionsTopologyAndStateOnlyOperations(): void
    {
        $this->setOption('acx_recognition_url', 'http://localhost:8000');
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => wp_json_encode(['cluster_id' => 'cluster-source']),
        ]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => wp_json_encode(['cluster_id' => 'cluster-2']),
        ]);

        $dispatcher = new OutboxDispatcher();
        $results = $dispatcher->dispatch_batch([
            [
                'operation_type' => 'cluster_merged',
                'entity_type' => 'cluster',
                'entity_key' => 'cluster-source',
                'idempotency_key' => 'idem-merge',
                'expected_base_version' => 19,
                'local_revision' => 7,
                'payload' => [
                    'target_cluster_id' => 'cluster-target',
                ],
            ],
            [
                'operation_type' => 'cluster_person_bound',
                'entity_type' => 'cluster',
                'entity_key' => 'cluster-2',
                'idempotency_key' => 'idem-bind',
                'expected_base_version' => 21,
                'local_revision' => 3,
                'payload' => [
                    'cluster_uuid' => 'cluster-2',
                    'person_uuid' => 'person-2',
                ],
            ],
        ]);

        $this->assertCount(2, $results);
        $this->assertSame('acknowledged', $results[0]['status']);
        $this->assertSame('acknowledged', $results[1]['status']);

        $calls = $this->getHttpCalls();
        $this->assertCount(2, $calls);
        $this->assertStringContainsString('/recognition/clusters/cluster-source/merge', $calls[0]['url']);
        $this->assertStringContainsString('/roster/curation/sync', $calls[1]['url']);

        $stateBody = (string) ($calls[1]['body'] ?? '');
        $this->assertStringContainsString('"operation_type":"cluster_person_bound"', $stateBody);
        $this->assertStringContainsString('"idempotency_key":"idem-bind"', $stateBody);
    }

    public function testDispatchRoutesRepresentativePinOperationsToRecognitionEndpoint(): void
    {
        $this->setOption('acx_recognition_url', 'http://localhost:8000');
        $this->queueHttpResponse([
            'response' => ['code' => 204, 'message' => 'No Content'],
            'body' => '',
        ]);

        $dispatcher = new OutboxDispatcher();
        $result = $dispatcher->dispatch([
            'operation_type' => 'representative_pin_updated',
            'entity_type' => 'cluster',
            'entity_key' => 'cluster-source',
            'idempotency_key' => 'idem-pin',
            'expected_base_version' => 27,
            'local_revision' => 5,
            'payload' => [
                'cluster_uuid' => 'cluster-source',
                'representative_id' => 'identity-77',
                'is_pinned' => true,
            ],
        ]);

        $this->assertSame('acknowledged', $result['status']);

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $this->assertSame('PATCH', $calls[0]['method']);
        $this->assertStringContainsString('/recognition/clusters/cluster-source/representatives/identity-77/pin', $calls[0]['url']);

        $body = (string) ($calls[0]['body'] ?? '');
        $this->assertStringContainsString('"tenant_id"', $body);
        $this->assertStringContainsString('"is_pinned":true', $body);
    }

    public function testDispatchBatchKeepsValidStateOperationsWhenAnotherStatePayloadIsInvalid(): void
    {
        $this->setOption('acx_recognition_url', 'http://localhost:8000');
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => wp_json_encode([
                'status' => 'acknowledged',
                'backend_version' => 44,
            ]),
        ]);

        $dispatcher = new OutboxDispatcher();
        $results = $dispatcher->dispatch_batch([
            $this->sampleOperation(),
            [
                'operation_type' => 'cluster_person_bound',
                'entity_type' => 'cluster',
                'entity_key' => '',
                'idempotency_key' => 'idem-invalid',
                'expected_base_version' => 0,
                'local_revision' => 1,
                'payload' => [
                    'cluster_uuid' => '',
                    'person_uuid' => 'person-x',
                ],
            ],
        ]);

        $this->assertCount(2, $results);
        $this->assertSame('acknowledged', $results[0]['status']);
        $this->assertSame(44, $results[0]['backend_version']);
        $this->assertSame('failed', $results[1]['status']);
        $this->assertSame('invalid_payload', $results[1]['error_code']);
        $this->assertFalse($results[1]['retryable']);

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $body = (string) ($calls[0]['body'] ?? '');
        $this->assertStringContainsString('"operation_type":"cluster_person_bound"', $body);
        $this->assertStringNotContainsString('"idempotency_key":"idem-invalid"', $body);
    }

    public function testDispatchRoutesCreateClusterForIdentityWithDesiredClusterId(): void
    {
        $this->setOption('acx_recognition_url', 'http://localhost:8000');
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => wp_json_encode([
                'cluster_id' => 'cluster-new',
            ]),
        ]);

        $dispatcher = new OutboxDispatcher();
        $result = $dispatcher->dispatch([
            'operation_type' => 'cluster_created_for_identity',
            'entity_type' => 'cluster',
            'entity_key' => 'cluster-new',
            'idempotency_key' => 'idem-create',
            'expected_base_version' => 0,
            'local_revision' => 1,
            'payload' => [
                'identity_id' => 'identity-1',
                'label' => 'Known Person',
                'desired_cluster_id' => 'cluster-new',
            ],
        ]);

        $this->assertSame('acknowledged', $result['status']);

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $this->assertStringContainsString('/recognition/clusters/create-for-identity', $calls[0]['url']);
        $body = (string) ($calls[0]['body'] ?? '');
        $this->assertStringContainsString('"identity_id":"identity-1"', $body);
        $this->assertStringContainsString('"label":"Known Person"', $body);
        $this->assertStringContainsString('"desired_cluster_id":"cluster-new"', $body);
    }

    public function testDispatchRoutesRevertMergeClusterToRecognitionEndpoint(): void
    {
        $this->setOption('acx_recognition_url', 'http://localhost:8000');
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => wp_json_encode([
                'restored_cluster_id' => 'cluster-restored',
                'backend_version' => 17,
            ]),
        ]);

        $dispatcher = new OutboxDispatcher();
        $result = $dispatcher->dispatch([
            'operation_type' => 'revert_merge_cluster',
            'entity_type' => 'cluster',
            'entity_key' => 'cluster-target',
            'idempotency_key' => 'idem-revert',
            'expected_base_version' => 13,
            'local_revision' => 6,
            'payload' => [
                'target_cluster_id' => 'cluster-target',
                'desired_source_cluster_id' => 'cluster-restored',
                'moved_identity_ids' => ['identity-1', 'identity-2'],
            ],
        ]);

        $this->assertSame('acknowledged', $result['status']);
        $this->assertSame(17, $result['backend_version']);

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $this->assertStringContainsString('/recognition/clusters/revert-merge', $calls[0]['url']);
        $body = (string) ($calls[0]['body'] ?? '');
        $this->assertStringContainsString('"target_cluster_id":"cluster-target"', $body);
        $this->assertStringContainsString('"desired_source_cluster_id":"cluster-restored"', $body);
        $this->assertStringContainsString('"expected_base_version":13', $body);
    }

    public function testDispatchRoutesAssignOutlierToClusterToRecognitionEndpoint(): void
    {
        $this->setOption('acx_recognition_url', 'http://localhost:8000');
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => wp_json_encode([
                'id' => 'cluster-target',
                'tenant_id' => 'tenant-1',
                'label' => 'Target',
                'is_labeled' => true,
                'is_auto_label' => false,
                'identity_count' => 3,
                'backend_version' => 21,
                'representatives' => [],
            ]),
        ]);

        $dispatcher = new OutboxDispatcher();
        $result = $dispatcher->dispatch([
            'operation_type' => 'assign_outlier_to_cluster',
            'entity_type' => 'cluster',
            'entity_key' => 'cluster-target',
            'idempotency_key' => 'idem-assign',
            'expected_base_version' => 20,
            'local_revision' => 5,
            'payload' => [
                'identity_id' => 'identity-1',
                'similarity' => 0.42,
            ],
        ]);

        $this->assertSame('acknowledged', $result['status']);
        $this->assertSame(21, $result['backend_version']);

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $this->assertStringContainsString('/recognition/clusters/cluster-target/assign', $calls[0]['url']);
        $body = (string) ($calls[0]['body'] ?? '');
        $this->assertStringContainsString('"identity_id":"identity-1"', $body);
        $this->assertStringContainsString('"expected_base_version":20', $body);
        $this->assertStringContainsString('"idempotency_key":"idem-assign"', $body);
    }

    /**
     * @return array<string,mixed>
     */
    private function sampleOperation(): array
    {
        return [
            'operation_type' => 'cluster_person_bound',
            'entity_type' => 'cluster',
            'entity_key' => 'cluster-1',
            'idempotency_key' => 'idem-1',
            'expected_base_version' => 12,
            'local_revision' => 4,
            'payload' => [
                'cluster_uuid' => 'cluster-1',
                'person_uuid' => 'person-1',
                'person_name' => 'Person One',
            ],
        ];
    }
}
