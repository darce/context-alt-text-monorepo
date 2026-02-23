<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\Sync\SnapshotClient;
use AltContext\Tests\TestCase;

/**
 * @covers \AltContext\Sovereign\Sync\SnapshotClient
 */
class SnapshotClientTest extends TestCase
{
    private SnapshotClient $client;

    protected function setUp(): void
    {
        parent::setUp();
        $this->setOption('acx_recognition_url', 'http://localhost:8000');
        $this->client = new SnapshotClient();
    }

    public function testFetchSnapshotUsesDefaultEndpointPath(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'snapshot_version' => 19,
                'clusters' => [],
                'members' => [],
            ]),
        ]);

        $result = $this->client->fetch_snapshot('tenant-default');

        $this->assertIsArray($result);
        $this->assertSame(19, $result['snapshot_version']);

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $this->assertStringContainsString('/recognition/tenants/tenant-default/clusters/snapshot', $calls[0]['url']);
    }

    public function testFetchSnapshotUsesFilterableEndpointPath(): void
    {
        add_filter(
            'acx_snapshot_endpoint_path',
            static function (): string {
                return '/snapshot/export/%s';
            }
        );

        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'snapshot_version' => 20,
                'clusters' => [],
                'members' => [],
            ]),
        ]);

        $result = $this->client->fetch_snapshot('tenant-filtered');

        $this->assertIsArray($result);
        $this->assertSame(20, $result['snapshot_version']);

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $this->assertStringContainsString('/snapshot/export/tenant-filtered', $calls[0]['url']);
    }

    public function testFetchSnapshotNormalizesCompactUuidTenantInDefaultPath(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'snapshot_version' => 21,
                'clusters' => [],
                'members' => [],
            ]),
        ]);

        $result = $this->client->fetch_snapshot('cc42f496c7e15631b3b5cfa270c763f8');

        $this->assertIsArray($result);
        $this->assertSame(21, $result['snapshot_version']);

        $calls = $this->getHttpCalls();
        $this->assertCount(1, $calls);
        $this->assertStringContainsString(
            '/recognition/tenants/cc42f496-c7e1-5631-b3b5-cfa270c763f8/clusters/snapshot',
            $calls[0]['url']
        );
    }

    public function testFetchSnapshotReturnsErrorWhenPayloadInvalid(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => '"invalid"',
        ]);

        $result = $this->client->fetch_snapshot('tenant-invalid');

        $this->assertTrue(is_wp_error($result));
        $this->assertSame('invalid_snapshot_payload', $result->get_error_code());
    }

    public function testFetchSnapshotUsesBackgroundRetryPolicy(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 500, 'message' => 'Internal Server Error'],
            'body' => '{"error":"temporary"}',
        ]);
        $this->queueHttpResponse([
            'response' => ['code' => 200, 'message' => 'OK'],
            'body' => json_encode([
                'snapshot_version' => 22,
                'clusters' => [],
                'members' => [],
            ]),
        ]);

        $result = $this->client->fetch_snapshot('tenant-retry');

        $this->assertIsArray($result);
        $this->assertSame(22, $result['snapshot_version']);

        $calls = $this->getHttpCalls();
        $this->assertCount(2, $calls, 'Background sync should retry transient 5xx responses.');
        $this->assertSame(30, $calls[0]['args']['timeout'] ?? null);
    }

    public function testFetchSnapshotReturnsEmptySnapshotOn404(): void
    {
        $this->queueHttpResponse([
            'response' => ['code' => 404, 'message' => 'Not Found'],
            'body' => json_encode(['detail' => 'No clusters found for tenant']),
        ]);

        $result = $this->client->fetch_snapshot('tenant-empty');

        $this->assertIsArray($result);
        $this->assertSame(0, $result['snapshot_version']);
        $this->assertSame([], $result['clusters']);
        $this->assertSame([], $result['members']);
        $this->assertTrue($result['empty']);
    }
}
