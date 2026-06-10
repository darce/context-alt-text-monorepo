<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\Services\TenantLocalRekeyService;
use AltContext\Tests\TestCase;

class TenantLocalRekeyServiceTest extends TestCase
{
    public function testRekeyUpdatesTenantScopedRowsAndMigratesSyncStream(): void
    {
        global $wpdb;

        $from = '11111111-1111-4111-8111-111111111111';
        $to   = '22222222-2222-4222-8222-222222222222';

        $wpdb->insert(
            $wpdb->prefix . 'acx_clusters',
            array(
                'cluster_uuid'     => 'cluster-1',
                'tenant_id'        => $from,
                'label'            => 'A',
                'curation_state'   => 'unlabeled',
                'snapshot_version' => 1,
                'created_at'       => '2026-01-01 00:00:00',
                'updated_at'       => '2026-01-01 00:00:00',
                'last_synced_at'   => '2026-01-01 00:00:00',
            )
        );
        $wpdb->insert(
            $wpdb->prefix . 'acx_sync_state',
            array(
                'stream_name'           => 'tenant:' . $from . ':clusters',
                'last_snapshot_version' => 9,
                'last_sync_result'      => 'ok',
                'updated_at'            => '2026-01-01 00:00:00',
            )
        );

        $service = new TenantLocalRekeyService();
        $result  = $service->reconcile_identity_change( $from, $to );

        $this->assertSame( 'rekey', $result['strategy'] );
        $this->assertGreaterThanOrEqual( 1, $result['updated_rows'] );
        $this->assertSame(
            $to,
            $wpdb->get_var(
                $wpdb->prepare(
                    'SELECT tenant_id FROM ' . $wpdb->prefix . 'acx_clusters WHERE cluster_uuid = %s',
                    'cluster-1'
                )
            )
        );
        $this->assertNull(
            $wpdb->get_var(
                $wpdb->prepare(
                    'SELECT stream_name FROM ' . $wpdb->prefix . 'acx_sync_state WHERE stream_name = %s',
                    'tenant:' . $from . ':clusters'
                )
            )
        );
        $this->assertTrue(
            $this->queriesInclude(
                $wpdb->queries,
                'tenant:' . $to . ':clusters',
                'resync_required'
            )
        );
    }

    public function testThresholdFallbackMarksResyncOnTargetTenantStream(): void
    {
        global $wpdb;

        $from = '33333333-3333-4333-8333-333333333333';
        $to   = '44444444-4444-4444-8444-444444444444';

        $service = new class () extends TenantLocalRekeyService {
            protected function count_rows_for_tenant( string $tenant_id ): int {
                return TenantLocalRekeyService::ROW_THRESHOLD + 1;
            }
        };

        $result = $service->reconcile_identity_change( $from, $to );

        $this->assertSame( 'resync', $result['strategy'] );
        $this->assertSame( 0, $result['updated_rows'] );
        $this->assertTrue(
            $this->queriesInclude(
                $wpdb->queries,
                'tenant:' . $to . ':clusters',
                'resync_required'
            )
        );
    }

    public function testRekeyUpdatesAllSixTenantScopedTables(): void
    {
        global $wpdb;

        $from = '55555555-5555-4555-8555-555555555555';
        $to   = '66666666-6666-4666-8666-666666666666';

        $service = new TenantLocalRekeyService();
        $result  = $service->reconcile_identity_change( $from, $to );

        $this->assertSame( 'rekey', $result['strategy'] );

        // Regression guard for the table list -- notably acx_batch_run_failures, whose earlier
        // misspelling (acx_batch_failures) silently skipped batch-failure rows against a real DB.
        $suffixes = array(
            'acx_clusters',
            'acx_batch_runs',
            'acx_batch_run_failures',
            'acx_sync_outbox',
            'acx_topology_commands',
            'acx_sync_conflicts',
        );
        foreach ( $suffixes as $suffix ) {
            $expected = sprintf(
                "UPDATE %s%s SET tenant_id = '%s' WHERE tenant_id = '%s'",
                $wpdb->prefix,
                $suffix,
                $to,
                $from
            );
            $this->assertContains( $expected, $wpdb->queries, "re-key must UPDATE {$suffix}" );
        }
    }

    public function testRekeyRollsBackAndThrowsWhenAMidLoopUpdateFails(): void
    {
        global $wpdb;

        $from = '11111111-1111-4111-8111-111111111111';
        $to   = '22222222-2222-4222-8222-222222222222';

        // Force the second tenant table's UPDATE to fail mid-loop (acx_clusters succeeds first).
        $failSql = sprintf(
            "UPDATE %sacx_batch_runs SET tenant_id = '%s' WHERE tenant_id = '%s'",
            $wpdb->prefix,
            $to,
            $from
        );
        $wpdb->updateResults[ $failSql ] = false;

        $service = new TenantLocalRekeyService();

        try {
            $service->reconcile_identity_change( $from, $to );
            $this->fail( 'expected RuntimeException when an UPDATE fails' );
        } catch ( \RuntimeException $e ) {
            $this->assertStringContainsString( 'acx_batch_runs', $e->getMessage() );
        }

        $this->assertContains( 'ROLLBACK', $wpdb->queries, 'a failed re-key must issue ROLLBACK' );
        $this->assertNotContains( 'COMMIT', $wpdb->queries, 'a failed re-key must not COMMIT' );
        $this->assertTrue(
            $this->queriesInclude( $wpdb->queries, $wpdb->prefix . 'acx_clusters', $to ),
            'the first table must have been updated before the mid-loop failure rolled back'
        );
    }

    /**
     * @param list<string> $queries
     */
    private function queriesInclude( array $queries, string $needle_a, string $needle_b ): bool {
        foreach ( $queries as $query ) {
            if ( str_contains( $query, $needle_a ) && str_contains( $query, $needle_b ) ) {
                return true;
            }
        }

        return false;
    }
}