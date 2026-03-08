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
            ],
        ];
    }
}
