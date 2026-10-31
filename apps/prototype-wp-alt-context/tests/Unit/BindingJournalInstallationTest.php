<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Support\LifecycleManager;
use AltContext\Tests\TestCase;

final class BindingJournalInstallationTest extends TestCase {
	public function test_journal_is_registered_in_install_fingerprint_and_uninstall_inventory(): void {
		$manager = new LifecycleManager();
		$statements = $manager->build_projection_schema_statements( 'lane_', 'DEFAULT CHARACTER SET utf8mb4' );
		self::assertArrayHasKey( 'acx_binding_journal', $statements );
		$sql = $statements['acx_binding_journal'];
		self::assertStringContainsString( 'ENGINE=InnoDB', $sql );
		self::assertStringContainsString( 'ascii_bin', $sql );
		self::assertSame( array( 'tenant_id', 'state_json' ), LifecycleManager::parse_create_table_column_names( $sql ) );
		$inventory = new \ReflectionMethod( $manager, 'owned_table_suffixes' );
		self::assertContains( 'acx_binding_journal', $inventory->invoke( $manager ) );
		self::assertSame( $manager->compute_projection_schema_fingerprint(), $manager->compute_projection_schema_fingerprint() );
	}

	public function test_upgrade_is_idempotent_and_keeps_durable_intent_data(): void {
		global $wpdb;
		$manager = new LifecycleManager();
		$wpdb->tableRows['wp_acx_binding_journal'] = array( array( 'tenant_id' => 'tenant', 'state_json' => '{"durable":"authority"}' ) );
		$manager->maybe_upgrade();
		self::assertSame( $manager->compute_projection_schema_fingerprint(), get_option( 'acx_schema_fingerprint' ) );
		$count = count( $GLOBALS['__ac_dbdelta_queries'] );
		$manager->maybe_upgrade();
		self::assertSame( $count, count( $GLOBALS['__ac_dbdelta_queries'] ) );
		self::assertSame( '{"durable":"authority"}', $wpdb->tableRows['wp_acx_binding_journal'][0]['state_json'] );
	}

	public function test_failed_engine_conversion_does_not_certify_installation(): void {
		global $wpdb;
		$wpdb->tableEngines['wp_acx_binding_journal'] = 'MyISAM';
		$wpdb->queryResults['ALTER TABLE `wp_acx_binding_journal` ENGINE=InnoDB'] = false;
		( new LifecycleManager() )->maybe_upgrade();
		self::assertFalse( get_option( 'acx_schema_fingerprint' ) );
	}
}
