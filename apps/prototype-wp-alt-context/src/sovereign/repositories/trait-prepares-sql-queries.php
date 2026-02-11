<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Repositories;

use function do_action;
use function function_exists;
use function is_object;
use function is_string;
use function method_exists;
use function preg_match_all;
use function preg_replace;
use function sprintf;
use function strpos;

trait PreparesSqlQueries {
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

	private function log_empty_tenant_id_guard( string $method ): void {
		if ( function_exists( 'do_action' ) ) {
			do_action(
				'acx_sovereign_warning',
				'empty_tenant_id',
				array(
					'method' => $method,
				)
			);
		}

		if ( function_exists( '_doing_it_wrong' ) ) {
			_doing_it_wrong( __METHOD__, 'Tenant ID must be non-empty for sovereign projection operations.', '4.13.1' );
		}
	}
}
