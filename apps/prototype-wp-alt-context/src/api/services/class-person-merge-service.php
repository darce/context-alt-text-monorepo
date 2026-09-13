<?php

declare(strict_types=1);

namespace AltContext\Api\Services;

require_once __DIR__ . '/../../support/trait-runs-transactional.php';
require_once __DIR__ . '/../../sovereign/repositories/class-sync-state-repository.php';

use AltContext\Support\RunsTransactional;
use AltContext\Sovereign\Repositories\SyncStateRepository;
use AltContext\Sovereign\Repositories\SyncStateRepositoryInterface;
use WP_Error;

/** Explicit roster merges; names are never used to resolve identity. */
class PersonMergeService {
	use RunsTransactional;

	/** Proper UUID v4 syntax (8-4-4-4-12); shared by the controller and this service (IDCHIP-1-API-R-04). */
	public const UNDO_TOKEN_PATTERN = '/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/Di';

	/** Undo tokens expire 24h after commit (IDCHIP-1-API-R-01). */
	public const UNDO_TOKEN_TTL_SECONDS = 86400;

	private PersonMergeRepository $repository;
	private SyncStateRepositoryInterface $sync;

	public function __construct( ?PersonMergeRepository $repository = null, ?SyncStateRepositoryInterface $sync = null ) {
		$this->repository = $repository ?? new PersonMergeRepository();
		$this->sync = $sync ?? new SyncStateRepository();
	}

	public function preview( string $tenant_id, int $survivor_id, int $loser_id ): array|WP_Error {
		try {
			return $this->inspect( $tenant_id, $survivor_id, $loser_id, false );
		} catch ( \RuntimeException $error ) {
			return $this->error( 'acx_db_error', 500 );
		}
	}

	private function inspect( string $tenant, int $survivor, int $loser, bool $lock ): array|WP_Error {
		if ( '' === trim( $tenant ) || $survivor <= 0 || $loser <= 0 || $survivor === $loser ) {
			return $this->error( 'invalid_person_ids', 400 );
		}
		// Stable lock order serializes overlapping merges.
		$ids = array( $survivor, $loser );
		sort( $ids );
		$people = array();
		foreach ( $ids as $id ) {
			$row = $this->repository->person( $id, $lock );
			if ( null === $row ) {
				return $this->error( 'person_not_found', 404 );
			}
			if ( $row['tenant_id'] !== $tenant ) {
				return $this->error( 'person_tenant_conflict', 409 );
			}
			$people[ $id ] = $row;
		}
		$clusters = $this->repository->clusters( $ids, $lock );
		$counts = array( $survivor => 0, $loser => 0 );
		foreach ( $clusters as $cluster ) {
			if ( $cluster['tenant_id'] !== $tenant ) {
				return $this->error( 'person_tenant_conflict', 409 );
			}
			++$counts[ (int) $cluster['person_id'] ];
		}
		return array(
			'survivor' => array( 'id' => $survivor, 'name' => $people[ $survivor ]['name'], 'cluster_count' => $counts[ $survivor ] ),
			'loser' => array( 'id' => $loser, 'name' => $people[ $loser ]['name'], 'cluster_count' => $counts[ $loser ] ),
			'tags' => array_values( array_unique( array_merge( $this->tags( $people[ $survivor ] ), $this->tags( $people[ $loser ] ) ), SORT_REGULAR ) ),
			'conflicts' => array(),
		) + ( $lock ? array( 'people' => $people, 'clusters' => $clusters ) : array() );
	}

	public function commit( string $tenant_id, int $survivor_id, int $loser_id ): array|WP_Error {
		return $this->transaction( function () use ( $tenant_id, $survivor_id, $loser_id ) {
			$preview = $this->inspect( $tenant_id, $survivor_id, $loser_id, true );
			if ( is_wp_error( $preview ) ) {
				if ( 'person_not_found' === $preview->get_error_code() ) {
					// IDCHIP-1-API-R-05: a retried commit after a lost 200 finds the loser
					// already gone. Recover the original result instead of 404ing forever.
					$recovered = $this->recover_idempotent_commit( $tenant_id, $survivor_id, $loser_id );
					if ( null !== $recovered ) {
						return $recovered;
					}
				}
				return $preview;
			}
			$moved = array_values( array_filter( $preview['clusters'], static fn( $row ) => (int) $row['person_id'] === $loser_id ) );
			$tags = wp_json_encode( $preview['tags'] );
			$token = wp_generate_uuid4();
			$this->repository->save_undo( $tenant_id, $token, array(
				'loser' => $preview['people'][ $loser_id ],
				'survivor_id' => $survivor_id,
				'survivor_tags' => $preview['people'][ $survivor_id ]['tags'],
				'merged_tags' => $tags,
				'clusters' => $moved,
				'expires_at' => time() + self::UNDO_TOKEN_TTL_SECONDS,
			) );
			$this->repository->save_merge_idempotency( $tenant_id, $survivor_id, $loser_id, $token );
			foreach ( $moved as $row ) {
				$this->repository->bind( $tenant_id, $row['cluster_uuid'], $survivor_id );
			}
			$this->repository->set_tags( $tenant_id, $survivor_id, $tags );
			$this->repository->remove_person( $tenant_id, $loser_id );
			$this->sync->touch_local_curation_marker( $tenant_id );
			return array( 'survivor_id' => $survivor_id, 'merged_cluster_ids' => array_column( $moved, 'cluster_uuid' ), 'undo_token' => $token );
		} );
	}

	/**
	 * Recover the original commit result for a retried request whose loser
	 * row is already gone (IDCHIP-1-API-R-05). Returns null when no matching
	 * idempotency record exists so the caller falls back to the 404.
	 */
	private function recover_idempotent_commit( string $tenant_id, int $survivor_id, int $loser_id ): ?array {
		$token = $this->repository->load_merge_idempotency( $tenant_id, $survivor_id, $loser_id );
		if ( null === $token ) {
			return null;
		}
		try {
			$record = $this->repository->load_undo( $tenant_id, $token );
		} catch ( \JsonException $error ) {
			return null;
		}
		if ( ! $this->is_valid_undo_record( $record ) || (int) $record['survivor_id'] !== $survivor_id || (int) $record['loser']['id'] !== $loser_id ) {
			return null;
		}
		return array(
			'survivor_id' => $survivor_id,
			'merged_cluster_ids' => array_column( $record['clusters'], 'cluster_uuid' ),
			'undo_token' => $token,
		);
	}

	public function undo( string $tenant_id, string $undo_token ): array|WP_Error {
		if ( '' === trim( $tenant_id ) || ! preg_match( self::UNDO_TOKEN_PATTERN, $undo_token ) ) {
			return $this->error( 'invalid_undo_token', 400 );
		}
		return $this->transaction( function () use ( $tenant_id, $undo_token ) {
			try {
				$record = $this->repository->load_undo( $tenant_id, $undo_token );
			} catch ( \JsonException $error ) {
				return $this->error( 'person_merge_undo_corrupt', 500 );
			}
			if ( null === $record ) {
				return $this->error( 'person_merge_undo_conflict', 409 );
			}
			if ( ! $this->is_valid_undo_record( $record ) ) {
				$this->repository->consume_undo( $tenant_id, $undo_token );
				return $this->error( 'person_merge_undo_corrupt', 500 );
			}
			if ( (int) $record['expires_at'] < time() ) {
				$this->repository->consume_undo( $tenant_id, $undo_token );
				return $this->error( 'person_merge_undo_expired', 409 );
			}
			$ids = array( (int) $record['survivor_id'], (int) $record['loser']['id'] );
			sort( $ids );
			$people = array();
			foreach ( $ids as $id ) {
				$people[ $id ] = $this->repository->person( $id, true );
			}
			$survivor = $people[ $record['survivor_id'] ];
			if ( null === $survivor || $survivor['tenant_id'] !== $tenant_id || $survivor['tags'] !== $record['merged_tags'] || null !== $people[ $record['loser']['id'] ] ) {
				return $this->error( 'person_merge_undo_conflict', 409 );
			}
			$current = array_column( $this->repository->clusters( $ids, true ), null, 'cluster_uuid' );
			foreach ( $record['clusters'] as $row ) {
				$bound = $current[ $row['cluster_uuid'] ] ?? null;
				if ( null === $bound || $bound['tenant_id'] !== $tenant_id || (int) $bound['person_id'] !== (int) $record['survivor_id'] ) {
					return $this->error( 'person_merge_undo_conflict', 409 );
				}
			}
			$this->repository->restore_person( $record['loser'] );
			foreach ( $record['clusters'] as $row ) {
				$this->repository->bind( $tenant_id, $row['cluster_uuid'], (int) $row['person_id'] );
			}
			$this->repository->set_tags( $tenant_id, (int) $record['survivor_id'], $record['survivor_tags'] );
			$this->repository->consume_undo( $tenant_id, $undo_token );
			$this->sync->touch_local_curation_marker( $tenant_id );
			return array( 'restored_person_id' => (int) $record['loser']['id'], 'restored_cluster_ids' => array_column( $record['clusters'], 'cluster_uuid' ) );
		} );
	}

	/**
	 * Validate the stored undo record shape before trusting its fields.
	 * IDCHIP-1-API-R-03: malformed/truncated records must not throw uncaught.
	 */
	private function is_valid_undo_record( mixed $record ): bool {
		if ( ! is_array( $record ) ) {
			return false;
		}
		if ( ! isset( $record['survivor_id'], $record['loser'], $record['survivor_tags'], $record['merged_tags'], $record['clusters'], $record['expires_at'] ) ) {
			return false;
		}
		if ( ! is_numeric( $record['survivor_id'] ) || ! is_numeric( $record['expires_at'] ) ) {
			return false;
		}
		if ( ! is_array( $record['loser'] ) || ! isset( $record['loser']['id'], $record['loser']['tenant_id'] ) ) {
			return false;
		}
		if ( ! is_array( $record['clusters'] ) ) {
			return false;
		}
		return true;
	}

	private function tags( array $person ): array {
		$tags = json_decode( (string) $person['tags'], true );
		return is_array( $tags ) ? $tags : array();
	}

	private function transaction( callable $operation ): array|WP_Error {
		try {
			return $this->run_transactional( $operation );
		} catch ( \RuntimeException $error ) {
			return $this->error( 'acx_db_error', 500 );
		}
	}

	private function error( string $code, int $status ): WP_Error {
		return new WP_Error( $code, 'Person merge could not be completed.', array( 'status' => $status ) );
	}
}

/** Storage kept alongside the service to avoid changing shared repository contracts. */
class PersonMergeRepository {
	public function person( int $id, bool $lock ): ?array {
		global $wpdb;
		$row = $wpdb->get_row( $wpdb->prepare( 'SELECT * FROM %i WHERE id = %d' . ( $lock ? ' FOR UPDATE' : '' ), $wpdb->prefix . 'acx_persons', $id ), ARRAY_A );
		$this->check_read();
		return $row;
	}

	public function clusters( array $ids, bool $lock ): array {
		global $wpdb;
		$rows = $wpdb->get_results( $wpdb->prepare( 'SELECT cluster_uuid, person_id, tenant_id FROM %i WHERE person_id IN (%d, %d) ORDER BY cluster_uuid' . ( $lock ? ' FOR UPDATE' : '' ), $wpdb->prefix . 'acx_clusters', $ids[0], $ids[1] ), ARRAY_A );
		$this->check_read();
		return $rows ?? array();
	}

	public function bind( string $tenant, string $cluster, int $person ): void {
		global $wpdb;
		$this->check( $wpdb->update( $wpdb->prefix . 'acx_clusters', array( 'person_id' => $person ), array( 'cluster_uuid' => $cluster, 'tenant_id' => $tenant ) ) );
	}

	public function set_tags( string $tenant, int $id, ?string $tags ): void {
		global $wpdb;
		$this->check( $wpdb->update( $wpdb->prefix . 'acx_persons', array( 'tags' => $tags ), array( 'id' => $id, 'tenant_id' => $tenant ) ) );
	}

	public function remove_person( string $tenant, int $id ): void {
		global $wpdb;
		$this->check( $wpdb->delete( $wpdb->prefix . 'acx_persons', array( 'id' => $id, 'tenant_id' => $tenant ) ) );
	}

	public function restore_person( array $row ): void {
		global $wpdb;
		$this->check( $wpdb->insert( $wpdb->prefix . 'acx_persons', $row ) );
	}

	// Direct SQL deliberately bypasses the option cache: tokens must roll back with the merge.
	private function key( string $tenant, string $token ): string {
		return 'acx_person_merge_' . hash( 'sha256', $tenant . ':' . $token );
	}

	public function save_undo( string $tenant, string $token, array $record ): void {
		global $wpdb;
		$this->check( $wpdb->insert( $wpdb->prefix . 'options', array( 'option_name' => $this->key( $tenant, $token ), 'option_value' => wp_json_encode( $record ), 'autoload' => 'no' ) ) );
	}

	// IDCHIP-1-API-R-05: indexes the undo token by merge participants so a retried
	// commit can recover the original result instead of re-running the merge.
	private function idempotency_key( string $tenant, int $survivor, int $loser ): string {
		return 'acx_person_merge_idem_' . hash( 'sha256', $tenant . ':' . $survivor . ':' . $loser );
	}

	public function save_merge_idempotency( string $tenant, int $survivor, int $loser, string $token ): void {
		global $wpdb;
		$key = $this->idempotency_key( $tenant, $survivor, $loser );
		$wpdb->delete( $wpdb->prefix . 'options', array( 'option_name' => $key ) );
		$this->check( $wpdb->insert( $wpdb->prefix . 'options', array( 'option_name' => $key, 'option_value' => $token, 'autoload' => 'no' ) ) );
	}

	public function load_merge_idempotency( string $tenant, int $survivor, int $loser ): ?string {
		global $wpdb;
		$value = $wpdb->get_var( $wpdb->prepare( 'SELECT option_value FROM %i WHERE option_name = %s', $wpdb->prefix . 'options', $this->idempotency_key( $tenant, $survivor, $loser ) ) );
		$this->check_read();
		return is_string( $value ) && '' !== $value ? $value : null;
	}

	public function load_undo( string $tenant, string $token ): ?array {
		global $wpdb;
		$value = $wpdb->get_var( $wpdb->prepare( 'SELECT option_value FROM %i WHERE option_name = %s FOR UPDATE', $wpdb->prefix . 'options', $this->key( $tenant, $token ) ) );
		$this->check_read();
		return null === $value ? null : json_decode( $value, true, 512, JSON_THROW_ON_ERROR );
	}

	public function consume_undo( string $tenant, string $token ): void {
		global $wpdb;
		$this->check( $wpdb->delete( $wpdb->prefix . 'options', array( 'option_name' => $this->key( $tenant, $token ) ) ) );
	}

	private function check( $result ): void {
		if ( false === $result ) {
			throw new \RuntimeException( 'Person merge database write failed.' );
		}
	}

	private function check_read(): void {
		global $wpdb;
		if ( ! empty( $wpdb->last_error ) ) {
			throw new \RuntimeException( 'Person merge database read failed.' );
		}
	}
}
