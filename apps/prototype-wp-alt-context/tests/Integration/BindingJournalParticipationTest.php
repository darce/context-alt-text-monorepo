<?php

declare(strict_types=1);

namespace AltContext\Tests\Integration;

use AltContext\Api\Services\ClusterMutationService;
use AltContext\Sovereign\Curation\BindingIntentJournal;
use AltContext\Sovereign\Curation\WpBindingJournalStore;
use AltContext\Sovereign\Curation\WpBindingIntentParticipant;
use AltContext\Support\LifecycleManager;
use PHPUnit\Framework\TestCase;

/*
 * Opt in explicitly. No wp-load.php or live wp-config.php is loaded.
 * Run with --no-configuration so the real dbDelta loads before WP test shims:
 * ACX_JOURNAL_MYSQL_TEST=1 ACX_TEST_WORDPRESS_ROOT=/path/to/wordpress \
 * vendor/bin/phpunit --no-configuration tests/Integration/BindingJournalParticipationTest.php
 * The host is fixed to the authorized ephemeral instance. A per-test, lane-owned
 * acx_uxfir_cj_part_* database is created/dropped; registries are never touched.
 */
if ( '1' === getenv( 'ACX_JOURNAL_MYSQL_TEST' ) ) {
	$wordpress = rtrim( (string) getenv( 'ACX_TEST_WORDPRESS_ROOT' ), '/' );
	if ( is_file( $wordpress . '/wp-admin/includes/upgrade.php' ) && ! function_exists( 'dbDelta' ) ) {
		// Loading upgrade.php itself also loads admin.php and a possible install.php.
		// Extract its complete, unchanged dbDelta declaration to avoid those side effects.
		$tokens = \PhpToken::tokenize( (string) file_get_contents( $wordpress . '/wp-admin/includes/upgrade.php' ) );
		$declaration = '';
		foreach ( $tokens as $index => $token ) {
			if ( T_FUNCTION !== $token->id ) { continue; }
			$next = $index + 1;
			while ( $tokens[ $next ]->isIgnorable() ) { ++$next; }
			if ( 'dbDelta' !== $tokens[ $next ]->text ) { continue; }
			$depth = 0;
			$opened = false;
			for ( $cursor = $index; $cursor < count( $tokens ); ++$cursor ) {
				$current = $tokens[ $cursor ];
				$declaration .= $current->text;
				if ( $current->is( '{' ) ) { ++$depth; $opened = true; }
				if ( $current->is( '}' ) && 0 === --$depth && $opened ) { break; }
			}
			break;
		}
		if ( '' === $declaration ) { throw new \RuntimeException( 'Cannot locate actual WordPress dbDelta.' ); }
		$temporary = tempnam( sys_get_temp_dir(), 'cj-dbdelta-' );
		try {
			file_put_contents( $temporary, "<?php\n" . $declaration );
			require $temporary;
		} finally {
			unlink( $temporary );
		}
		foreach ( array( 'WP_DEBUG' => false, 'WP_DEBUG_DISPLAY' => false, 'DB_CHARSET' => 'utf8mb4', 'DB_COLLATE' => '' ) as $constant => $value ) {
			if ( ! defined( $constant ) ) { define( $constant, $value ); }
		}
		require_once $wordpress . '/wp-includes/load.php';
		require_once $wordpress . '/wp-includes/class-wpdb.php';
	}
}
require_once dirname( __DIR__ ) . '/bootstrap.php';

final class BindingJournalParticipationTest extends TestCase {
	private ?object $db = null;
	private LifecycleManager $manager;
	private string $prefix = '';
	private string $database_name = '';

	protected function setUp(): void {
		if ( '1' !== getenv( 'ACX_JOURNAL_MYSQL_TEST' ) ) {
			self::markTestSkipped( 'Requires explicit isolated MariaDB opt-in.' );
		}
		self::assertTrue( extension_loaded( 'mysqli' ), 'Isolated MariaDB qualification requires mysqli; a skipped fixture is not engine evidence.' );
		self::assertTrue( class_exists( 'wpdb' ), 'Supply ACX_TEST_WORDPRESS_ROOT and --no-configuration.' );
		$delta = new \ReflectionFunction( 'dbDelta' );
		self::assertStringNotContainsString( '/tests/stubs/', (string) $delta->getFileName(), 'Use real WordPress dbDelta, not the unit fixture.' );
		$this->prefix = 'cj_part_' . bin2hex( random_bytes( 6 ) ) . '_';
		$this->database_name = 'acx_uxfir_cj_part_' . bin2hex( random_bytes( 6 ) );
		$this->db = new \wpdb( 'root', 'uxfir-ephemeral-test-only', 'acx_uxfir_test', '127.0.0.1:13316' );
		$this->db->suppress_errors( true );
		self::assertNotFalse( $this->db->query( $this->db->prepare( 'CREATE DATABASE %i CHARACTER SET utf8mb4', $this->database_name ) ) );
		$this->db->select( $this->database_name );
		$this->db->set_prefix( $this->prefix );
		$GLOBALS['wpdb'] = $this->db;
		$this->manager = new LifecycleManager();
		$this->install();
		$this->seed();
	}

	private function install(): void {
		$install = new \ReflectionMethod( $this->manager, 'maybe_create_projection_tables' );
		self::assertTrue( $install->invoke( $this->manager ), 'Actual dbDelta/engine/column verification failed: ' . $this->db->last_error );
	}

	private function seed(): void {
		$now = '2026-10-31 00:00:00';
		self::assertSame( 1, $this->db->insert( $this->prefix . 'acx_persons', array( 'person_uuid' => 'person', 'tenant_id' => 'tenant', 'name' => 'Saved name', 'normalized_name' => 'saved name', 'local_revision' => 4, 'tags' => '[]' ) ) );
		$person_id = (int) $this->db->insert_id;
		foreach ( array( 'group', 'unrelated' ) as $group ) {
			self::assertSame( 1, $this->db->insert( $this->prefix . 'acx_clusters', array( 'cluster_uuid' => $group, 'tenant_id' => 'tenant', 'person_id' => $person_id, 'label' => 'Saved name', 'curation_state' => 'confirmed', 'is_user_confirmed' => 1, 'local_revision' => 2, 'snapshot_version' => 9, 'created_at' => $now, 'updated_at' => $now, 'last_synced_at' => $now ) ) );
		}
		self::assertSame( 1, $this->db->insert( $this->prefix . 'acx_identity_members', array( 'identity_uuid' => 'face', 'cluster_uuid' => 'group', 'attachment_id' => 17, 'bbox_json' => '[1,2,3,4]', 'projection_version' => 9, 'created_at' => $now, 'updated_at' => $now ) ) );
	}

	private function command( string $kind, string $request ): array {
		$data = ( new WpBindingIntentParticipant( $this->db ) )->inspect( 'tenant', 'person', 'group' );
		unset( $data['positive_binding_available'] );
		return $data + array( 'kind' => $kind, 'person_uuid' => 'person', 'request_id' => $request );
	}

	private function rows( string $suffix ): array {
		return $this->db->get_results( $this->db->prepare( 'SELECT * FROM %i', $this->prefix . $suffix ), ARRAY_A );
	}

	public function test_real_unlink_replay_rollback_and_foreign_tenant(): void {
		$command = $this->command( 'unlink', 'negative' );
		$service = new ClusterMutationService();
		$result = $service->apply_binding_intent( 'tenant', 'group', $command );
		self::assertInstanceOf( \WP_REST_Response::class, $result );
		$receipt = $result->get_data()['binding_intent'];
		self::assertTrue( $receipt['after']['auto_rebind_suppressed'] );
		self::assertSame( $command['guards']['person']['name'], $this->rows( 'acx_persons' )[0]['name'] );
		self::assertCount( 1, $this->rows( 'acx_sync_outbox' ) );
		self::assertSame( $result->get_data(), $service->apply_binding_intent( 'tenant', 'group', $command )->get_data() );
		self::assertCount( 1, $this->rows( 'acx_sync_outbox' ) );
		$command['request_id'] = 'competing';
		self::assertInstanceOf( \WP_Error::class, $service->apply_binding_intent( 'tenant', 'group', $command ) );
		self::assertInstanceOf( \WP_Error::class, $service->apply_binding_intent( 'foreign', 'group', $command ) );
		self::assertCount( 1, $this->rows( 'acx_binding_journal' ) );
		$state = ( new BindingIntentJournal( new WpBindingJournalStore( $this->db, $this->prefix . 'acx_binding_journal' ) ) )->inspect( 'tenant' );
		self::assertSame( $receipt['after'], $state['people']['person'] );
	}

	public function test_real_rename_and_late_database_failure_roll_back_every_effect(): void {
		$command = $this->command( 'rename', 'name' );
		$command['name'] = 'New name';
		$before = array_map( fn( string $table ): array => $this->rows( $table ), array( 'acx_persons', 'acx_clusters', 'acx_sync_outbox', 'acx_binding_journal', 'acx_sync_state' ) );
		// Engine-enforced fault after actual group/person/outbox writes, before commit.
		$trigger = $this->prefix . 'fail_journal';
		self::assertNotFalse( $this->db->query( $this->db->prepare( "CREATE TRIGGER %i BEFORE UPDATE ON %i FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'journal qualification fault'", $trigger, $this->prefix . 'acx_binding_journal' ) ) );
		$result = ( new ClusterMutationService() )->apply_binding_intent( 'tenant', 'group', $command );
		self::assertInstanceOf( \WP_Error::class, $result );
		self::assertSame( $before, array_map( fn( string $table ): array => $this->rows( $table ), array( 'acx_persons', 'acx_clusters', 'acx_sync_outbox', 'acx_binding_journal', 'acx_sync_state' ) ) );
		self::assertNotFalse( $this->db->query( $this->db->prepare( 'DROP TRIGGER %i', $trigger ) ) );
		self::assertInstanceOf( \WP_REST_Response::class, ( new ClusterMutationService() )->apply_binding_intent( 'tenant', 'group', $command ) );
		self::assertSame( 'New name', $this->rows( 'acx_persons' )[0]['name'] );
		self::assertSame( array( 'New name', 'New name' ), array_column( $this->rows( 'acx_clusters' ), 'label' ) );
		self::assertCount( 3, $this->rows( 'acx_sync_outbox' ) );
	}

	public function test_real_install_is_idempotent_and_journal_is_owned_but_not_a_projection_reset(): void {
		$command = $this->command( 'unlink', 'persist' );
		( new WpBindingIntentParticipant( $this->db ) )->apply( 'tenant', 'group', $command );
		$before = $this->rows( 'acx_binding_journal' );
		$this->install();
		self::assertSame( $before, $this->rows( 'acx_binding_journal' ) );
		self::assertSame( 'InnoDB', $this->db->get_var( $this->db->prepare( 'SELECT ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s', $this->prefix . 'acx_binding_journal' ) ) );
		$drop = new \ReflectionMethod( $this->manager, 'drop_tables' );
		$drop->invoke( $this->manager );
		self::assertNull( $this->db->get_var( $this->db->prepare( 'SHOW TABLES LIKE %s', $this->prefix . 'acx_binding_journal' ) ) );
	}

	public function test_real_tenant_fence_excludes_same_tenant_and_allows_other_tenant(): void {
		$second = new \wpdb( 'root', 'uxfir-ephemeral-test-only', $this->database_name, '127.0.0.1:13316' );
		$second->suppress_errors( true );
		$second->set_prefix( $this->prefix );
		self::assertNotFalse( $second->query( 'SET SESSION innodb_lock_wait_timeout = 1' ) );
		$table = $this->prefix . 'acx_binding_journal';
		try {
			( new WpBindingJournalStore( $this->db, $table ) )->transaction( 'tenant', function ( array &$state ) use ( $second, $table ): void {
				try {
					( new WpBindingJournalStore( $second, $table ) )->transaction( 'tenant', static function (): void { throw new \LogicException( 'A competing callback must not enter the held fence.' ); } );
					self::fail( 'Same-tenant fence was not exclusive.' );
				} catch ( \RuntimeException $error ) {
					self::assertStringContainsString( 'database operation failed', $error->getMessage() );
				}
				$result = ( new WpBindingJournalStore( $second, $table ) )->transaction( 'foreign', static function ( array &$foreign ): string { $foreign['isolation_probe'] = 'test-only'; return 'independent'; } );
				self::assertSame( 'independent', $result );
				$state['isolation_probe'] = 'test-only';
			} );
		} finally {
			$second->close();
		}
	}

	protected function tearDown(): void {
		if ( null !== $this->db && 1 === preg_match( '/^cj_part_[a-f0-9]{12}_$/D', $this->prefix ) && 1 === preg_match( '/^acx_uxfir_cj_part_[a-f0-9]{12}$/D', $this->database_name ) ) {
			$this->db->query( 'ROLLBACK' );
			foreach ( array_keys( ( new LifecycleManager() )->build_projection_schema_statements( $this->prefix, '' ) ) as $suffix ) {
				$this->db->query( $this->db->prepare( 'DROP TABLE IF EXISTS %i', $this->prefix . $suffix ) );
			}
			$this->db->query( $this->db->prepare( 'DROP DATABASE IF EXISTS %i', $this->database_name ) );
			$this->db->close();
		}
	}
}
