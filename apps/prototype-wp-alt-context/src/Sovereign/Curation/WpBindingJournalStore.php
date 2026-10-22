<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Curation;

/**
 * InnoDB adapter. Dedicated durable table, outside projection reset lists.
 * Use the SAME wpdb connection for every participating writer. This adapter owns
 * the outer transaction; do not wrap it in RunsTransactional or START elsewhere.
 * The tenant row is the coarse common fence: acquire it BEFORE person/group locks.
 * All writers must join this fence; nonparticipating legacy writers remain unsafe.
 */
final class WpBindingJournalStore implements BindingJournalStore {
	private object $database;
	private string $table;
	private bool $active = false;

	public function __construct( object $database, string $table ) {
		if ( 1 !== preg_match( '/^[A-Za-z0-9_]+$/D', $table ) ) {
			throw new \InvalidArgumentException( 'Invalid journal table.' );
		}
		$this->database = $database;
		$this->table = $table;
	}

	/** Registration proposal only: schema owner must create this before use. */
	public function schema_sql(): string {
		return 'CREATE TABLE ' . $this->table . ' (tenant_id varchar(191) CHARACTER SET ascii COLLATE ascii_bin NOT NULL, state_json longtext NOT NULL, PRIMARY KEY (tenant_id)) ENGINE=InnoDB';
	}

	public function transaction( string $tenant_id, callable $operation ) {
		if ( '' === $tenant_id || strlen( $tenant_id ) > 191 || 1 !== preg_match( '/^[\x21-\x7e]+$/D', $tenant_id ) ) {
			throw new \InvalidArgumentException( 'Invalid tenant fence key.' );
		}
		if ( $this->active ) {
			throw new \LogicException( 'Nested journal transaction.' );
		}
		$this->active = true;
		try {
			// Refuse an existing transaction, including one on another adapter instance.
			$in_transaction = $this->database->get_var( 'SELECT @@in_transaction' );
			if ( '0' !== (string) $in_transaction ) {
				throw new \RuntimeException( 'Journal requires an idle transaction connection.' );
			}
			$this->execute( 'START TRANSACTION' );
		} catch ( \Throwable $error ) {
			$this->active = false;
			throw $error;
		}
		try {
			$this->execute( $this->database->prepare( 'INSERT INTO %i (tenant_id, state_json) VALUES (%s, %s) ON DUPLICATE KEY UPDATE tenant_id = tenant_id', $this->table, $tenant_id, '{}' ) );
			$json = $this->database->get_var( $this->database->prepare( 'SELECT state_json FROM %i WHERE tenant_id = %s FOR UPDATE', $this->table, $tenant_id ) );
			if ( ! is_string( $json ) ) {
				throw new \RuntimeException( 'Cannot read journal fence.' );
			}
			$state = json_decode( $json, true, 512, JSON_THROW_ON_ERROR );
			if ( ! is_array( $state ) ) {
				throw new \RuntimeException( 'Invalid journal state.' );
			}
			$result = $operation( $state );
			$this->execute( $this->database->prepare( 'UPDATE %i SET state_json = %s WHERE tenant_id = %s', $this->table, json_encode( $state, JSON_THROW_ON_ERROR | JSON_PRESERVE_ZERO_FRACTION ), $tenant_id ) );
			$this->execute( 'COMMIT' );
			return $result;
		} catch ( \Throwable $error ) {
			$this->execute( 'ROLLBACK' );
			throw $error;
		} finally {
			$this->active = false;
		}
	}

	private function execute( $sql ): void {
		if ( ! is_string( $sql ) || false === $this->database->query( $sql ) ) {
			throw new \RuntimeException( 'Journal database operation failed.' );
		}
	}
}
