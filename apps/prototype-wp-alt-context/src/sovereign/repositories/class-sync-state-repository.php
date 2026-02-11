<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Repositories;

use function gmdate;
use function is_object;
use function is_string;
use function max;
use function method_exists;
use function preg_match_all;
use function preg_replace;
use function sprintf;
use function strpos;
use function trim;

class SyncStateRepository implements SyncStateRepositoryInterface {
	private string $table_name;

	public function __construct( ?string $table_name = null ) {
		global $wpdb;

		$default_table = 'wp_acx_sync_state';
		if ( isset( $wpdb ) && is_object( $wpdb ) && isset( $wpdb->prefix ) && is_string( $wpdb->prefix ) ) {
			$default_table = $wpdb->prefix . 'acx_sync_state';
		}

		$this->table_name = $table_name ?? $default_table;
	}

	public function upsert_snapshot_version( string $tenant_id, int $snapshot_version ): void {
		global $wpdb;

		if ( '' === trim( $tenant_id ) || ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'query' ) ) {
			return;
		}

		$stream_name = $this->stream_name_for_tenant( $tenant_id );
		$sql         = $this->prepare_query(
			'INSERT INTO %i
				(stream_name, last_snapshot_version, updated_at)
			VALUES (%s, %d, %s)
			ON DUPLICATE KEY UPDATE
				last_snapshot_version = GREATEST(last_snapshot_version, VALUES(last_snapshot_version)),
				updated_at = VALUES(updated_at)',
			array(
				$this->table_name,
				$stream_name,
				max( 0, $snapshot_version ),
				gmdate( 'Y-m-d H:i:s' ),
			)
		);

		if ( is_string( $sql ) && '' !== $sql ) {
			// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
			$wpdb->query( $sql );
		}
	}

	public function get_snapshot_version( string $tenant_id ): int {
		global $wpdb;

		$normalized_tenant_id = trim( $tenant_id );
		if ( '' === $normalized_tenant_id || ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'get_var' ) ) {
			return 0;
		}

		$sql = $this->prepare_query(
			'SELECT last_snapshot_version FROM %i WHERE stream_name = %s LIMIT 1',
			array(
				$this->table_name,
				$this->stream_name_for_tenant( $normalized_tenant_id ),
			)
		);

		if ( ! is_string( $sql ) || '' === $sql ) {
			return 0;
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$value = $wpdb->get_var( $sql );
		return max( 0, (int) $value );
	}

	private function stream_name_for_tenant( string $tenant_id ): string {
		return sprintf( 'tenant:%s:clusters', trim( $tenant_id ) );
	}

	/**
	 * @param array<int,mixed> $args
	 */
	private function prepare_query( string $query, array $args ): ?string {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) ) {
			return null;
		}

		$supports_identifier_placeholders = method_exists( $wpdb, 'has_cap' ) && true === $wpdb->has_cap( 'identifier_placeholders' );
		if ( ! $supports_identifier_placeholders && false !== strpos( $query, '%i' ) ) {
			$matches = array();
			preg_match_all( '/%[sdfi]/', $query, $matches );

			$value_args = array();
			foreach ( $matches[0] as $index => $placeholder ) {
				$arg = $args[ $index ] ?? '';
				if ( '%i' === $placeholder ) {
					$query = (string) preg_replace( '/%i/', $this->escape_identifier( (string) $arg ), $query, 1 );
					continue;
				}

				$value_args[] = $arg;
			}

			$args = $value_args;
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query string is assembled from fixed templates and escaped identifiers.
		$prepared = $wpdb->prepare( $query, ...$args );
		return is_string( $prepared ) && '' !== $prepared ? $prepared : null;
	}

	private function escape_identifier( string $identifier ): string {
		$sanitized = preg_replace( '/[^A-Za-z0-9_$.]/', '', $identifier );
		$value     = is_string( $sanitized ) && '' !== $sanitized ? $sanitized : 'invalid_identifier';
		return sprintf( '`%s`', $value );
	}
}
