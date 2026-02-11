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
        $this->assertStringContainsString('/tenants/tenant-default/clusters/snapshot', $calls[0]['url']);
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
}
