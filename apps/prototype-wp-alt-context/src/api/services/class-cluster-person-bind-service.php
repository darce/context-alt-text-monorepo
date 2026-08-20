<?php

declare(strict_types=1);

namespace AltContext\Api\Services;

use WP_Error;

/**
 * Shared cluster→person bind used by commit_roster_cluster and create-for-identity.
 *
 * Transaction-agnostic: the caller owns START/COMMIT/ROLLBACK.
 */
class ClusterPersonBindService {

	/**
	 * @return array{person_id:int,person_uuid:string,person_name:?string}|WP_Error
	 */
	public function resolve_person( int $person_id ): array|WP_Error {
		global $wpdb;

		if ( $person_id <= 0 ) {
			return new WP_Error(
				'acx_db_error',
				__( 'Could not resolve person UUID for cluster assignment.', 'alt-context' ),
				array( 'status' => 500 )
			);
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'get_var' ) || ! method_exists( $wpdb, 'prepare' ) ) {
			return new WP_Error( 'acx_db_error', __( 'Database access is unavailable.', 'alt-context' ), array( 'status' => 500 ) );
		}

		$table_persons = $wpdb->prefix . 'acx_persons';
		$person_uuid   = $this->get_person_uuid_by_id( $person_id, $table_persons );
		if ( ! is_string( $person_uuid ) || '' === trim( $person_uuid ) ) {
			return new WP_Error(
				'acx_db_error',
				__( 'Could not resolve person UUID for cluster assignment.', 'alt-context' ),
				array( 'status' => 500 )
			);
		}

		$person_name = $this->get_person_name_by_id( $person_id, $table_persons );

		return array(
			'person_id'   => $person_id,
			'person_uuid' => $person_uuid,
			'person_name' => $person_name,
		);
	}

	/**
	 * Apply the same cluster row + cluster_person_bound outbox rows as commit_roster_cluster.
	 *
	 * @param callable(string $operation_type, string $cluster_id, int $local_revision, array<string,mixed> $payload): bool $enqueue
	 * @return array{person_id:int,person_uuid:string,person_name:?string,updated_at:string}|WP_Error
	 */
	public function bind_cluster_to_person(
		string $cluster_id,
		int $person_id,
		callable $enqueue,
		?string $person_uuid = null,
		?string $person_name = null
	): array|WP_Error {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'update' ) || ! method_exists( $wpdb, 'query' ) || ! method_exists( $wpdb, 'prepare' ) ) {
			return new WP_Error( 'acx_db_error', __( 'Database access is unavailable.', 'alt-context' ), array( 'status' => 500 ) );
		}

		if ( ! is_string( $person_uuid ) || '' === trim( $person_uuid ) ) {
			$resolved = $this->resolve_person( $person_id );
			if ( is_wp_error( $resolved ) ) {
				return $resolved;
			}
			$person_uuid = $resolved['person_uuid'];
			if ( ! is_string( $person_name ) || '' === trim( $person_name ) ) {
				$person_name = $resolved['person_name'];
			}
		} elseif ( ! is_string( $person_name ) || '' === trim( $person_name ) ) {
			$person_name = $this->get_person_name_by_id( $person_id, $wpdb->prefix . 'acx_persons' );
		}

		$now          = current_time( 'mysql' );
		$table_clusters = $wpdb->prefix . 'acx_clusters';
		$update_data    = array(
			'person_id'         => $person_id,
			'curation_state'    => 'confirmed',
			'is_user_confirmed' => 1,
			'updated_at'        => $now,
		);
		$update_fmt = array( '%d', '%s', '%d', '%s' );

		$trimmed_name = is_string( $person_name ) ? trim( $person_name ) : '';
		if ( '' !== $trimmed_name ) {
			$update_data['label'] = $trimmed_name;
			$update_fmt[]         = '%s';
			$person_name          = $trimmed_name;
		} else {
			$person_name = null;
		}

		$cluster_updated = $wpdb->update(
			$table_clusters,
			$update_data,
			array( 'cluster_uuid' => $cluster_id ),
			$update_fmt,
			array( '%s' )
		);
		if ( false === $cluster_updated ) {
			return new WP_Error( 'acx_db_error', __( 'Could not update cluster assignment.', 'alt-context' ), array( 'status' => 500 ) );
		}

		$revision_updated = $wpdb->query(
			$wpdb->prepare(
				'UPDATE %i SET local_revision = local_revision + 1 WHERE cluster_uuid = %s',
				$table_clusters,
				$cluster_id
			)
		);
		if ( false === $revision_updated ) {
			return new WP_Error( 'acx_db_error', __( 'Could not update cluster revision.', 'alt-context' ), array( 'status' => 500 ) );
		}

		$local_revision = (int) $wpdb->get_var(
			$wpdb->prepare( 'SELECT local_revision FROM %i WHERE cluster_uuid = %s', $table_clusters, $cluster_id )
		);

		$queued = $enqueue(
			'cluster_person_bound',
			$cluster_id,
			max( 1, $local_revision ),
			$this->bound_curation_payload( $cluster_id, $person_uuid, $person_name )
		);
		if ( ! $queued ) {
			return new WP_Error( 'acx_db_error', __( 'Could not queue curation replay operation.', 'alt-context' ), array( 'status' => 500 ) );
		}

		return array(
			'person_id'   => $person_id,
			'person_uuid' => $person_uuid,
			'person_name' => $person_name,
			'updated_at'  => $now,
		);
	}

	/**
	 * @return array{cluster_uuid:string,person_uuid:string,person_name:?string}
	 */
	public function bound_curation_payload( string $cluster_id, string $person_uuid, ?string $person_name ): array {
		return array(
			'cluster_uuid' => $cluster_id,
			'person_uuid'  => $person_uuid,
			'person_name'  => $person_name,
		);
	}

	private function get_person_uuid_by_id( int $person_id, string $table_persons ): ?string {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'get_var' ) || ! method_exists( $wpdb, 'prepare' ) ) {
			return null;
		}

		$resolved_uuid = $wpdb->get_var(
			$wpdb->prepare( 'SELECT person_uuid FROM %i WHERE id = %d', $table_persons, $person_id )
		);

		return is_string( $resolved_uuid ) && '' !== trim( $resolved_uuid ) ? $resolved_uuid : null;
	}

	private function get_person_name_by_id( int $person_id, string $table_persons ): ?string {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'get_var' ) || ! method_exists( $wpdb, 'prepare' ) ) {
			return null;
		}

		$resolved_name = $wpdb->get_var(
			$wpdb->prepare( 'SELECT name FROM %i WHERE id = %d', $table_persons, $person_id )
		);

		return is_string( $resolved_name ) && '' !== trim( $resolved_name ) ? trim( $resolved_name ) : null;
	}
}
