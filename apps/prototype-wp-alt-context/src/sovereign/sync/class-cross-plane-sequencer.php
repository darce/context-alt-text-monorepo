<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Sync;

require_once __DIR__ . '/../repositories/trait-prepares-sql-queries.php';
require_once __DIR__ . '/interface-topology-command-repository.php';

use AltContext\Sovereign\Repositories\PreparesSqlQueries;
use function array_fill;
use function array_filter;
use function array_map;
use function array_merge;
use function array_unique;
use function count;
use function implode;
use function is_array;
use function is_object;
use function is_string;
use function json_decode;
use function max;
use function method_exists;
use function trim;

class CrossPlaneSequencer {
	use PreparesSqlQueries;

	/**
	 * @var string[]
	 */
	private const REPLAY_PLANE_TOPOLOGY_OPERATIONS = array(
		'cluster_merged',
		'identity_reassigned',
		'cluster_created_for_identity',
		'revert_merge_cluster',
		'assign_outlier_to_cluster',
	);

	private TopologyCommandRepositoryInterface $topology_repository;
	private string $outbox_table_name;

	public function __construct( TopologyCommandRepositoryInterface $topology_repository, ?string $outbox_table_name = null ) {
		global $wpdb;

		$default_table = 'wp_acx_sync_outbox';
		if ( isset( $wpdb ) && is_object( $wpdb ) && isset( $wpdb->prefix ) && is_string( $wpdb->prefix ) ) {
			$default_table = $wpdb->prefix . 'acx_sync_outbox';
		}

		$this->topology_repository = $topology_repository;
		$this->outbox_table_name = $outbox_table_name ?? $default_table;
	}

	/**
	 * @param array<int,array<string,mixed>> $operations
	 * @return array<int,array<string,mixed>>
	 */
	public function filter_ready_outbox_operations( array $operations ): array {
		$ready = array();
		foreach ( $operations as $operation ) {
			if ( ! is_array( $operation ) ) {
				continue;
			}

			if ( ! $this->is_replay_plane_topology_operation( $operation ) || ! $this->has_blocking_split_command( $operation ) ) {
				$ready[] = $operation;
			}
		}

		return $ready;
	}

	/**
	 * @param array<string,mixed> $command
	 */
	public function is_split_command_ready( array $command ): bool {
		$tenant_id = trim( (string) ( $command['tenant_id'] ?? '' ) );
		if ( '' === $tenant_id ) {
			return true;
		}

		$command_sequence_keys = $this->extract_split_sequence_keys( $command );
		if ( empty( $command_sequence_keys ) ) {
			return true;
		}

		foreach ( $this->load_pending_replay_topology_operations( $tenant_id ) as $operation ) {
			if ( ! $this->shares_sequence_key( $command_sequence_keys, $this->extract_operation_sequence_keys( $operation ) ) ) {
				continue;
			}

			if ( $this->compare_records( $operation, $command ) <= 0 ) {
				return false;
			}
		}

		return true;
	}

	/**
	 * @param array<string,mixed> $operation
	 */
	private function has_blocking_split_command( array $operation ): bool {
		$tenant_id = trim( (string) ( $operation['tenant_id'] ?? '' ) );
		if ( '' === $tenant_id ) {
			return false;
		}

		$operation_sequence_keys = $this->extract_operation_sequence_keys( $operation );
		if ( empty( $operation_sequence_keys ) ) {
			return false;
		}

		$limit = max( 25, count( $operation_sequence_keys ) * 25 );
		$commands = $this->topology_repository->find_reconcilable( $tenant_id, $limit );
		foreach ( $commands as $command ) {
			if ( ! is_array( $command ) || 'cluster_split' !== trim( (string) ( $command['command_type'] ?? '' ) ) ) {
				continue;
			}

			if ( ! $this->shares_sequence_key( $operation_sequence_keys, $this->extract_split_sequence_keys( $command ) ) ) {
				continue;
			}

			if ( $this->compare_records( $command, $operation ) <= 0 ) {
				return true;
			}
		}

		return false;
	}

	/**
	 * @param array<string,mixed> $operation
	 */
	private function is_replay_plane_topology_operation( array $operation ): bool {
		$operation_type = trim( (string) ( $operation['operation_type'] ?? '' ) );
		return '' !== $operation_type && in_array( $operation_type, self::REPLAY_PLANE_TOPOLOGY_OPERATIONS, true );
	}

	/**
	 * @return array<int,array<string,mixed>>
	 */
	private function load_pending_replay_topology_operations( string $tenant_id ): array {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'get_results' ) ) {
			return array();
		}

		$placeholders = implode( ', ', array_fill( 0, count( self::REPLAY_PLANE_TOPOLOGY_OPERATIONS ), '%s' ) );
		$query = $this->prepare_query(
			'SELECT id, tenant_id, operation_type, entity_type, entity_key, payload, status, created_at
			FROM %i
			WHERE tenant_id = %s
				AND status = %s
				AND operation_type IN (' . $placeholders . ')
			ORDER BY created_at ASC, id ASC',
			array_merge(
				array( $this->outbox_table_name, $tenant_id, 'pending' ),
				self::REPLAY_PLANE_TOPOLOGY_OPERATIONS
			)
		);

		if ( ! is_string( $query ) || '' === $query ) {
			return array();
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$rows = $wpdb->get_results( $query, ARRAY_A );
		if ( ! is_array( $rows ) ) {
			return array();
		}

		foreach ( $rows as $index => $row ) {
			if ( ! is_array( $row ) ) {
				unset( $rows[ $index ] );
				continue;
			}

			$payload = $row['payload'] ?? array();
			if ( is_string( $payload ) ) {
				$decoded = json_decode( $payload, true );
				$payload = is_array( $decoded ) ? $decoded : array();
			}

			$rows[ $index ]['payload'] = is_array( $payload ) ? $payload : array();
		}

		return array_values( $rows );
	}

	/**
	 * @param array<string,mixed> $operation
	 * @return string[]
	 */
	private function extract_operation_sequence_keys( array $operation ): array {
		$payload = $operation['payload'] ?? array();
		if ( is_string( $payload ) ) {
			$decoded = json_decode( $payload, true );
			$payload = is_array( $decoded ) ? $decoded : array();
		}
		if ( ! is_array( $payload ) ) {
			$payload = array();
		}

		return $this->normalize_sequence_keys(
			array_merge(
				array(
					$operation['entity_key'] ?? '',
					$payload['cluster_id'] ?? '',
					$payload['source_cluster_id'] ?? '',
					$payload['target_cluster_id'] ?? '',
					$payload['desired_cluster_id'] ?? '',
				),
				is_array( $payload['desired_cluster_ids'] ?? null ) ? $payload['desired_cluster_ids'] : array(),
				is_array( $payload['affected_cluster_ids'] ?? null ) ? $payload['affected_cluster_ids'] : array()
			)
		);
	}

	/**
	 * @param array<string,mixed> $command
	 * @return string[]
	 */
	private function extract_split_sequence_keys( array $command ): array {
		$payload = $command['payload_json'] ?? array();
		if ( is_string( $payload ) ) {
			$decoded = json_decode( $payload, true );
			$payload = is_array( $decoded ) ? $decoded : array();
		}
		if ( ! is_array( $payload ) ) {
			$payload = array();
		}

		$result = $command['result_json'] ?? array();
		if ( is_string( $result ) ) {
			$decoded = json_decode( $result, true );
			$result = is_array( $decoded ) ? $decoded : array();
		}
		if ( ! is_array( $result ) ) {
			$result = array();
		}

		return $this->normalize_sequence_keys(
			array_merge(
				array(
					$command['entity_key'] ?? '',
					$payload['cluster_id'] ?? '',
					$result['original_cluster_id'] ?? '',
				),
				is_array( $payload['desired_cluster_ids'] ?? null ) ? $payload['desired_cluster_ids'] : array(),
				is_array( $result['affected_cluster_ids'] ?? null ) ? $result['affected_cluster_ids'] : array(),
				is_array( $result['new_cluster_ids'] ?? null ) ? $result['new_cluster_ids'] : array()
			)
		);
	}

	/**
	 * @param string[] $left
	 * @param string[] $right
	 */
	private function shares_sequence_key( array $left, array $right ): bool {
		if ( empty( $left ) || empty( $right ) ) {
			return false;
		}

		return ! empty( array_intersect( $left, $right ) );
	}

	/**
	 * @param array<string,mixed> $left
	 * @param array<string,mixed> $right
	 */
	private function compare_records( array $left, array $right ): int {
		$left_created = trim( (string) ( $left['created_at'] ?? '' ) );
		$right_created = trim( (string) ( $right['created_at'] ?? '' ) );
		if ( '' !== $left_created && '' !== $right_created && $left_created !== $right_created ) {
			return $left_created <=> $right_created;
		}

		return max( 0, (int) ( $left['id'] ?? 0 ) ) <=> max( 0, (int) ( $right['id'] ?? 0 ) );
	}

	/**
	 * @param array<int,mixed> $values
	 * @return string[]
	 */
	private function normalize_sequence_keys( array $values ): array {
		return array_values(
			array_unique(
				array_filter(
					array_map(
						static function ( $value ): string {
							return trim( (string) $value );
						},
						$values
					),
					static function ( string $value ): bool {
						return '' !== $value;
					}
				)
			)
		);
	}
}
