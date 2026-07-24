<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\Sync\SnapshotProjector;
use AltContext\Tests\Stubs\NullClustersRepository;
use AltContext\Tests\Stubs\NullIdentityMembersRepository;
use AltContext\Tests\Stubs\NullSyncStateRepository;
use AltContext\Tests\TestCase;

use function dirname;
use function file_get_contents;
use function is_array;
use function json_decode;

/**
 * @covers \AltContext\Sovereign\Sync\SnapshotProjector
 */
class ContractSnapshotSchemaTest extends TestCase
{
    public function testGoldenSnapshotFixtureMatchesPhpProjectionExpectations(): void
    {
        $fixture_path = dirname(__DIR__, 4) . '/packages/shared-contracts/recognition/cluster-snapshot.golden.json';
        $payload = json_decode((string) file_get_contents($fixture_path), true);

        $this->assertIsArray($payload);
        $this->assertSame(104, $payload['snapshot_version']);
        $this->assertCount(2, $payload['clusters']);
        $this->assertCount(3, $payload['members']);

        $clusters_repo = new class() extends NullClustersRepository {
            public array $calls = [];

            public function merge_snapshot_for_tenant(string $tenant_id, array $clusters, int $snapshot_version): void
            {
                $this->calls[] = [$tenant_id, $clusters, $snapshot_version];
            }
        };

        $members_repo = new class() extends NullIdentityMembersRepository {
            public array $calls = [];

            public function merge_snapshot_for_tenant(string $tenant_id, array $members, int $snapshot_version, bool $suppress_conflict_storm = false): void
            {
                $this->calls[] = [$tenant_id, $members, $snapshot_version];
            }
        };

        $sync_repo = new class() extends NullSyncStateRepository {
            public array $versions = [];

            public function upsert_snapshot_version(string $tenant_id, int $snapshot_version): void
            {
                $this->versions[] = [$tenant_id, $snapshot_version];
            }
        };

        $projector = new SnapshotProjector($clusters_repo, $members_repo, $sync_repo);
        $projector->project($payload['tenant_id'], $payload);

        $this->assertCount(1, $clusters_repo->calls);
        $this->assertCount(1, $members_repo->calls);
        $this->assertCount(1, $sync_repo->versions);

        [$tenant_id, $clusters, $snapshot_version] = $clusters_repo->calls[0];
        $this->assertSame($payload['tenant_id'], $tenant_id);
        $this->assertSame($payload['snapshot_version'], $snapshot_version);
        $this->assertIsArray($clusters);
        $this->assertSame('6c1a2e32-31b2-4d54-a4de-98b1a73d77a1', $clusters[0]['cluster_uuid']);
        $this->assertSame('4b8f0a3e-3f1f-4f59-96f2-bfb6c8c1d3bb', $clusters[0]['representative_id']);
        $this->assertTrue($clusters[0]['is_pinned']);
        $this->assertArrayHasKey('representative_thumb_path', $clusters[0]);
        $this->assertNull($clusters[1]['representative_id']);

        [$members_tenant_id, $members, $members_snapshot_version] = $members_repo->calls[0];
        $this->assertSame($payload['tenant_id'], $members_tenant_id);
        $this->assertSame($payload['snapshot_version'], $members_snapshot_version);
        $this->assertIsArray($members);
        $this->assertSame(501, $members[0]['attachment_id']);
        $this->assertTrue(is_array($members[0]['bbox']));
        $this->assertSame(80, $members[0]['bbox']['width']);
        $this->assertSame('acx://identity/4b8f0a3e-3f1f-4f59-96f2-bfb6c8c1d3bb/thumb', $members[0]['thumb_path']);
    }
}
