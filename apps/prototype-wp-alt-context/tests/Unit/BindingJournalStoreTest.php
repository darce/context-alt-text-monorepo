<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\Curation\WpBindingJournalStore;
use PHPUnit\Framework\TestCase;

// Reuse the existing transactional SQL double; this is not live DB evidence.
require_once __DIR__ . '/BindingIntentJournalTest.php';

final class BindingJournalStoreTest extends TestCase {
	public function test_corrupt_persisted_state_rolls_back_without_calling_a_writer(): void {
		foreach ( array( '{broken', 'null', '42', '"state"' ) as $json ) {
			$db = new BindingJournalConnection();
			$db->rows['tenant'] = $json;
			$called = false;
			try {
				( new WpBindingJournalStore( $db, 'wp_acx_binding_journal' ) )->transaction( 'tenant', static function () use ( &$called ): void {
					$called = true;
				} );
				self::fail( 'Corrupt authority must not be replaced by an empty journal.' );
			} catch ( \JsonException | \RuntimeException $error ) {
				self::assertFalse( $called );
				self::assertSame( array( 'tenant' => $json ), $db->rows );
				self::assertContains( 'ROLLBACK', $db->queries );
			}
		}
	}

	public function test_invalid_tenant_fences_never_enter_a_transaction(): void {
		foreach ( array( '', 'tenant ', ' tenant', "tenant\n", str_repeat( 'a', 192 ) ) as $tenant ) {
			$db = new BindingJournalConnection();
			try {
				( new WpBindingJournalStore( $db, 'wp_acx_binding_journal' ) )->transaction( $tenant, static function (): void {
					self::fail( 'An invalid tenant must not reach the writer.' );
				} );
				self::fail( 'Invalid tenant must be rejected.' );
			} catch ( \InvalidArgumentException $error ) {
				self::assertSame( 'Invalid tenant fence key.', $error->getMessage() );
				self::assertSame( array(), $db->queries );
				self::assertSame( array(), $db->rows );
			}
		}
	}

	public function test_an_outer_transaction_is_preserved_when_journal_entry_is_refused(): void {
		$db = new BindingJournalConnection();
		$db->query( 'START TRANSACTION' );
		$db->effects[] = 'outer-write';
		try {
			( new WpBindingJournalStore( $db, 'wp_acx_binding_journal' ) )->transaction( 'tenant', static function (): void {
				self::fail( 'A nested journal must not reach the writer.' );
			} );
			self::fail( 'An outer transaction must be rejected.' );
		} catch ( \RuntimeException $error ) {
			self::assertSame( 'Journal requires an idle transaction connection.', $error->getMessage() );
			self::assertSame( array( 'START TRANSACTION' ), $db->queries );
			self::assertSame( array( 'outer-write' ), $db->effects );
			self::assertSame( '1', $db->get_var( 'SELECT @@in_transaction' ) );
		} finally {
			$db->query( 'ROLLBACK' );
		}
	}
}
