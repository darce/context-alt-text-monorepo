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
use function getenv;
use function is_array;
use function is_file;
use function is_string;
use function json_decode;
use function rtrim;
use function sprintf;

/**
 * @covers \AltContext\Sovereign\Sync\SnapshotProjector
 */
class ContractSnapshotSchemaTest extends TestCase
{
    /**
     * Relative path of the golden fixture under the monorepo root.
     */
    private const GOLDEN_FIXTURE_RELATIVE = 'packages/shared-contracts/recognition/cluster-snapshot.golden.json';

    /**
     * Max parent directories to walk from the start dir before giving up.
     * Bounds the search so a missing fixture terminates instead of walking to /.
     */
    private const MAX_WALK_LEVELS = 8;

    /**
     * Env var name for an explicit monorepo-root override.
     *
     * ACX_CONTRACTS_DIR must point at the monorepo root — the directory that
     * *contains* `packages/` — not at packages/ or packages/shared-contracts/.
     * Fixture is then resolved as:
     *   {ACX_CONTRACTS_DIR}/packages/shared-contracts/recognition/cluster-snapshot.golden.json
     */
    private const CONTRACTS_DIR_ENV = 'ACX_CONTRACTS_DIR';

    public function testGoldenSnapshotFixtureMatchesPhpProjectionExpectations(): void
    {
        $resolution = self::resolveGoldenFixturePath(__DIR__);
        if ($resolution['path'] === null) {
            $this->markTestSkipped(
                self::formatMissingFixtureSkipMessage($resolution['levels_walked'])
            );
        }

        $fixture_path = $resolution['path'];
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

    /**
     * Resolve the golden cluster-snapshot fixture path.
     *
     * Resolution order:
     * 1. ACX_CONTRACTS_DIR (monorepo root containing packages/) when set and the
     *    fixture file exists under it at GOLDEN_FIXTURE_RELATIVE.
     * 2. Walk up from $start_dir looking for GOLDEN_FIXTURE_RELATIVE at each
     *    ancestor, up to MAX_WALK_LEVELS levels (stops early at filesystem root).
     *
     * First hit wins. When nothing is found, path is null and levels_walked is
     * the number of parent steps actually taken (capped by the bound).
     *
     * @param string      $start_dir     Directory to start walk-up from (typically __DIR__).
     * @param string|null $contracts_dir Explicit ACX_CONTRACTS_DIR value; null reads getenv.
     *                                   Pass '' to force "no env" when testing walk-up.
     * @return array{path: ?string, levels_walked: int, used_env: bool}
     */
    private static function resolveGoldenFixturePath(string $start_dir, ?string $contracts_dir = null): array
    {
        if ($contracts_dir === null) {
            $env = getenv(self::CONTRACTS_DIR_ENV);
            $contracts_dir = (is_string($env) && $env !== '') ? $env : null;
        } elseif ($contracts_dir === '') {
            $contracts_dir = null;
        }

        if ($contracts_dir !== null) {
            $candidate = rtrim($contracts_dir, "/\\") . '/' . self::GOLDEN_FIXTURE_RELATIVE;
            if (is_file($candidate)) {
                return [
                    'path' => $candidate,
                    'levels_walked' => 0,
                    'used_env' => true,
                ];
            }
        }

        $dir = $start_dir;
        $levels_walked = 0;

        while ($levels_walked <= self::MAX_WALK_LEVELS) {
            $candidate = rtrim($dir, "/\\") . '/' . self::GOLDEN_FIXTURE_RELATIVE;
            if (is_file($candidate)) {
                return [
                    'path' => $candidate,
                    'levels_walked' => $levels_walked,
                    'used_env' => false,
                ];
            }

            if ($levels_walked === self::MAX_WALK_LEVELS) {
                break;
            }

            $parent = dirname($dir);
            if ($parent === $dir) {
                // Filesystem root — stop without claiming we walked past the bound.
                break;
            }

            $dir = $parent;
            ++$levels_walked;
        }

        return [
            'path' => null,
            'levels_walked' => $levels_walked,
            'used_env' => false,
        ];
    }

    /**
     * Skip message when the golden fixture cannot be resolved.
     */
    private static function formatMissingFixtureSkipMessage(int $levels_walked): string
    {
        return sprintf(
            'Golden contract fixture not found at %s after walking %d level(s) from %s; set %s to the monorepo root (directory containing packages/) to override.',
            self::GOLDEN_FIXTURE_RELATIVE,
            $levels_walked,
            __DIR__,
            self::CONTRACTS_DIR_ENV
        );
    }
}
