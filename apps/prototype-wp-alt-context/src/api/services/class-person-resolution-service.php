<?php

declare(strict_types=1);

namespace AltContext\Api\Services;

require_once dirname( __DIR__ ) . '/class-tenant-identity.php';

use AltContext\Api\TenantIdentity;
use WP_Error;

/**
 * Single-writer person resolve-or-create by normalized name.
 *
 * Transaction-agnostic: the caller owns the surrounding transaction.
 * Do not call run_transactional from this service — nested START TRANSACTION
 * would implicitly commit an outer transaction (see RunsTransactional).
 */
class PersonResolutionService {

	private ?string $table_prefix;

	public function __construct( ?string $table_prefix = null ) {
		$this->table_prefix = $table_prefix;
	}

	/**
	 * Trim + Unicode case-fold. No diacritic folding ("José" ≠ "Jose").
	 */
	public static function normalize_name( string $name ): string {
		$trimmed = \trim( $name );
		if ( '' === $trimmed ) {
			return '';
		}

		return \mb_convert_case( $trimmed, \MB_CASE_FOLD, 'UTF-8' );
	}

	/**
	 * Resolve an existing person by normalized_name or create a new one.
	 *
	 * On match: rebind (return existing identity, no insert).
	 * On unique-index race after insert failure: re-lookup and rebind.
	 *
	 * @param callable(string $person_uuid, string $name, array<int,mixed> $tags): bool $enqueue_person_created
	 * @return array{person_id:int,person_uuid:string,name:string,outcome:string}|WP_Error
	 */
	public function resolve_or_create( string $display_name, callable $enqueue_person_created ): array|WP_Error {
		global $wpdb;

		$display_name = \sanitize_text_field( $display_name );
		$normalized   = self::normalize_name( $display_name );
		if ( '' === $normalized ) {
			return new WP_Error(
				'acx_invalid_name',
				__( 'Person name cannot be empty.', 'alt-context' ),
				array( 'status' => 400 )
			);
		}

		if ( ! isset( $wpdb ) || ! \is_object( $wpdb ) || ! \method_exists( $wpdb, 'prepare' ) || ! \method_exists( $wpdb, 'get_row' ) || ! \method_exists( $wpdb, 'insert' ) ) {
			return new WP_Error(
				'acx_db_error',
				__( 'Database access is unavailable.', 'alt-context' ),
				array( 'status' => 500 )
			);
		}

		$table_persons = $this->persons_table();
		$existing      = $this->find_by_normalized_name( $table_persons, $normalized );
		if ( null !== $existing ) {
			return $existing;
		}

		$tenant_id = TenantIdentity::resolve()['value'] ?? '';
		if ( ! \is_string( $tenant_id ) || '' === \trim( $tenant_id ) ) {
			return new WP_Error(
				'acx_db_error',
				__( 'Tenant identity is unavailable.', 'alt-context' ),
				array( 'status' => 500 )
			);
		}

		$person_uuid       = \wp_generate_uuid4();
		$person_created_at = \current_time( 'mysql' );
		$inserted          = $wpdb->insert(
			$table_persons,
			array(
				'person_uuid'     => $person_uuid,
				'tenant_id'       => $tenant_id,
				'name'            => $display_name,
				'normalized_name' => $normalized,
				'tags'            => \wp_json_encode( array() ),
				'local_revision'  => 1,
				'created_at'      => $person_created_at,
				'updated_at'      => $person_created_at,
			),
			array( '%s', '%s', '%s', '%s', '%s', '%d', '%s', '%s' )
		);

		if ( false === $inserted ) {
			// Unique-index race: a concurrent writer committed first. Under InnoDB
			// REPEATABLE READ the pre-insert SELECT can miss that peer (snapshot
			// residual). A fresh statement after the failed INSERT sees the winner
			// and rebinds — accepted residual; no gap-lock retry loop.
			$race_match = $this->find_by_normalized_name( $table_persons, $normalized );
			if ( null !== $race_match ) {
				return $race_match;
			}

			return new WP_Error(
				'acx_db_error',
				__( 'Could not create person for cluster assignment.', 'alt-context' ),
				array( 'status' => 500 )
			);
		}

		$person_id = (int) $wpdb->insert_id;
		if ( $person_id <= 0 ) {
			return new WP_Error(
				'acx_db_error',
				__( 'Could not create person for cluster assignment.', 'alt-context' ),
				array( 'status' => 500 )
			);
		}

		$queued = $enqueue_person_created( $person_uuid, $display_name, array() );
		if ( ! $queued ) {
			return new WP_Error(
				'acx_db_error',
				__( 'Could not queue person creation replay operation.', 'alt-context' ),
				array( 'status' => 500 )
			);
		}

		return array(
			'person_id'   => $person_id,
			'person_uuid' => $person_uuid,
			'name'        => $display_name,
			'outcome'     => 'created',
		);
	}

	/**
	 * Observe an existing tenant/group association; a label never authorizes one.
	 *
	 * ADR019 rule 1b: snapshot/projection/backfill labels remain evidence only.
	 * Unlinked results carry person_id=0 and the unchanged label so projection
	 * callers can retain it. ClusterCurationWriter treats that ID as a no-op.
	 * A positive result comes only from this group's stored person association,
	 * independent of name equality. Explicit human naming uses resolve_or_create.
	 *
	 * The callback is retained for caller compatibility and is never invoked.
	 * This service does not create binding intent or continue journal commands.
	 *
	 * @param callable(string $person_uuid, string $name, array<int,mixed> $tags): bool $enqueue_person_created
	 * @return array{person_id:int,person_uuid:string,name:string,outcome:string,collision:bool}|WP_Error
	 */
	public function resolve_for_automatic_bind(
		string $display_name,
		string $tenant_id,
		string $cluster_uuid,
		callable $enqueue_person_created
	): array|WP_Error {
		global $wpdb;

		$unlinked = array(
			'person_id'   => 0,
			'person_uuid' => '',
			'name'        => $display_name,
			'outcome'     => 'unlinked',
			'collision'   => false,
		);
		$tenant_id    = trim( $tenant_id );
		$cluster_uuid = trim( $cluster_uuid );
		if ( '' === $tenant_id || '' === $cluster_uuid ) {
			return $unlinked;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'get_row' ) ) {
			return new WP_Error( 'acx_db_error', __( 'Database access is unavailable.', 'alt-context' ), array( 'status' => 500 ) );
		}

		$prefix = is_string( $this->table_prefix ) && '' !== $this->table_prefix ? $this->table_prefix : $wpdb->prefix;
		$group  = $wpdb->get_row(
			$wpdb->prepare(
				'SELECT person_id FROM %i WHERE cluster_uuid = %s AND tenant_id = %s',
				$prefix . 'acx_clusters',
				$cluster_uuid,
				$tenant_id
			)
		);
		$person_id = is_object( $group ) ? (int) ( $group->person_id ?? 0 ) : 0;
		if ( $person_id <= 0 ) {
			return $unlinked;
		}

		$person = $wpdb->get_row(
			$wpdb->prepare(
				'SELECT id, person_uuid, name FROM %i WHERE id = %d AND tenant_id = %s',
				$this->persons_table(),
				$person_id,
				$tenant_id
			)
		);
		if ( ! is_object( $person ) || (int) ( $person->id ?? 0 ) !== $person_id || '' === trim( (string) ( $person->person_uuid ?? '' ) ) ) {
			return $unlinked;
		}

		return array(
			'person_id'   => $person_id,
			'person_uuid' => (string) $person->person_uuid,
			'name'        => (string) ( $person->name ?? '' ),
			'outcome'     => 'rebound',
			'collision'   => false,
		);
	}

	public function person_is_bound_to_cluster( int $person_id, string $cluster_uuid ): bool {
		global $wpdb;

		$normalized_cluster = trim( $cluster_uuid );
		if ( $person_id <= 0 || '' === $normalized_cluster ) {
			return false;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'get_var' ) || ! method_exists( $wpdb, 'prepare' ) ) {
			return false;
		}

		$bound = $wpdb->get_var(
			$wpdb->prepare(
				'SELECT person_id FROM %i WHERE cluster_uuid = %s AND person_id = %d LIMIT 1',
				$wpdb->prefix . 'acx_clusters',
				$normalized_cluster,
				$person_id
			)
		);

		return is_numeric( $bound ) && (int) $bound > 0;
	}

	public function person_is_bound_in_tenant( int $person_id, string $tenant_id ): bool {
		global $wpdb;

		$normalized_tenant = trim( $tenant_id );
		if ( $person_id <= 0 || '' === $normalized_tenant ) {
			return false;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'get_var' ) || ! method_exists( $wpdb, 'prepare' ) ) {
			return false;
		}

		$bound = $wpdb->get_var(
			$wpdb->prepare(
				'SELECT person_id FROM %i WHERE tenant_id = %s AND person_id = %d LIMIT 1',
				$wpdb->prefix . 'acx_clusters',
				$normalized_tenant,
				$person_id
			)
		);

		return is_numeric( $bound ) && (int) $bound > 0;
	}

	/**
	 * @param callable(string $person_uuid, string $name, array<int,mixed> $tags): bool $enqueue_person_created
	 * @return array{person_id:int,person_uuid:string,name:string,outcome:string}|WP_Error
	 */
	public function create_distinct( string $display_name, callable $enqueue_person_created ): array|WP_Error {
		global $wpdb;

		$base = \sanitize_text_field( $display_name );
		if ( '' === $base ) {
			return new WP_Error(
				'acx_invalid_name',
				__( 'Person name cannot be empty.', 'alt-context' ),
				array( 'status' => 400 )
			);
		}

		if ( ! isset( $wpdb ) || ! \is_object( $wpdb ) || ! \method_exists( $wpdb, 'prepare' ) || ! \method_exists( $wpdb, 'get_row' ) || ! \method_exists( $wpdb, 'insert' ) ) {
			return new WP_Error(
				'acx_db_error',
				__( 'Database access is unavailable.', 'alt-context' ),
				array( 'status' => 500 )
			);
		}

		for ( $suffix = 2; $suffix <= 99; $suffix++ ) {
			$candidate = $base . ' (' . $suffix . ')';
			$normalized = self::normalize_name( $candidate );
			$existing   = $this->find_by_normalized_name( $this->persons_table(), $normalized );
			if ( null !== $existing ) {
				continue;
			}

			return $this->resolve_or_create( $candidate, $enqueue_person_created );
		}

		return new WP_Error(
			'acx_name_collision',
			\sprintf(
				/* translators: %s: colliding display name */
				__( 'Could not create a distinct person for the colliding label "%s".', 'alt-context' ),
				$base
			),
			array( 'status' => 409 )
		);
	}

	private function persons_table(): string {
		if ( is_string( $this->table_prefix ) && '' !== $this->table_prefix ) {
			return $this->table_prefix . 'acx_persons';
		}

		global $wpdb;
		return $wpdb->prefix . 'acx_persons';
	}

	/**
	 * @return array{person_id:int,person_uuid:string,name:string,outcome:string}|null
	 */
	private function find_by_normalized_name( string $table_persons, string $normalized ): ?array {
		global $wpdb;

		$tenant_id = TenantIdentity::resolve()['value'] ?? '';
		if ( ! \is_string( $tenant_id ) || '' === \trim( $tenant_id ) ) {
			return null;
		}

		$row = $wpdb->get_row(
			$wpdb->prepare(
				'SELECT id, person_uuid, name FROM %i WHERE normalized_name = %s AND tenant_id = %s',
				$table_persons,
				$normalized,
				$tenant_id
			)
		);

		if ( ! \is_object( $row ) ) {
			return null;
		}

		$person_id   = isset( $row->id ) ? (int) $row->id : 0;
		$person_uuid = \trim( (string) ( $row->person_uuid ?? '' ) );
		$name        = \trim( (string) ( $row->name ?? '' ) );

		if ( $person_id <= 0 || '' === $person_uuid || '' === $name ) {
			return null;
		}

		return array(
			'person_id'   => $person_id,
			'person_uuid' => $person_uuid,
			'name'        => $name,
			'outcome'     => 'rebound',
		);
	}
}
