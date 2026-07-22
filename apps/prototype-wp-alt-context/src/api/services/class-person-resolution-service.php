<?php

declare(strict_types=1);

namespace AltContext\Api\Services;

use WP_Error;

/**
 * Single-writer person resolve-or-create by normalized name.
 *
 * Transaction-agnostic: the caller owns the surrounding transaction.
 * Do not call run_transactional from this service — nested START TRANSACTION
 * would implicitly commit an outer transaction (see RunsTransactional).
 */
class PersonResolutionService {

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

		$table_persons = $wpdb->prefix . 'acx_persons';
		$existing      = $this->find_by_normalized_name( $table_persons, $normalized );
		if ( null !== $existing ) {
			return $existing;
		}

		$person_uuid       = \wp_generate_uuid4();
		$person_created_at = \current_time( 'mysql' );
		$inserted          = $wpdb->insert(
			$table_persons,
			array(
				'person_uuid'     => $person_uuid,
				'name'            => $display_name,
				'normalized_name' => $normalized,
				'tags'            => \wp_json_encode( array() ),
				'local_revision'  => 1,
				'created_at'      => $person_created_at,
				'updated_at'      => $person_created_at,
			),
			array( '%s', '%s', '%s', '%s', '%d', '%s', '%s' )
		);

		if ( false === $inserted ) {
			// Unique-index race or residual collision: rebind instead of 500.
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
	 * @return array{person_id:int,person_uuid:string,name:string,outcome:string}|null
	 */
	private function find_by_normalized_name( string $table_persons, string $normalized ): ?array {
		global $wpdb;

		$row = $wpdb->get_row(
			$wpdb->prepare(
				'SELECT id, person_uuid, name FROM %i WHERE normalized_name = %s',
				$table_persons,
				$normalized
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
