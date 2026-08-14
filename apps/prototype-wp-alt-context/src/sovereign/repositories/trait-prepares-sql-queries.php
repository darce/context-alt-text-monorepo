<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Repositories;

require_once __DIR__ . '/../class-projection-query-exception.php';
require_once __DIR__ . '/../../support/class-telemetry.php';

use AltContext\Sovereign\ProjectionQueryException;
use AltContext\Support\Telemetry;

use function do_action;
use function esc_html;
use function function_exists;
use function is_object;
use function is_string;
use function method_exists;
use function preg_match_all;
use function preg_replace;
use function property_exists;
use function sprintf;
use function strpos;
use function trim;

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

	private function prepare_projection_read_query( string $query, array $args ): string {
		$prepared = $this->prepare_query( $query, $args );
		if ( null === $prepared ) {
			$message = 'Projection query failed [prepare_query]: wpdb could not prepare query';
			Telemetry::log_line( $message );
			// phpcs:ignore WordPress.Security.EscapeOutput.ExceptionNotEscaped -- Internal diagnostic message; never rendered as output.
			throw new ProjectionQueryException( $message );
		}

		return $prepared;
	}

	private function clear_query_error(): void {
		global $wpdb;

		if ( isset( $wpdb ) && is_object( $wpdb ) ) {
			$wpdb->last_error = '';
		}
	}

	private function escape_identifier( string $identifier ): string {
		$sanitized = preg_replace( '/[^A-Za-z0-9_$.]/', '', $identifier );
		$value     = is_string( $sanitized ) && '' !== $sanitized ? $sanitized : 'invalid_identifier';
		return sprintf( '`%s`', $value );
	}

	/**
	 * Fail loud when a projection read fails (RLSE-05 / OBS-08 / AGT-10).
	 *
	 * Keys off $wpdb->last_error and, when $null_is_failure is true, a null
	 * result (get_results / COUNT get_var). get_row and existence get_var may
	 * legitimately return null — pass $null_is_failure = false for those.
	 *
	 * @param mixed $result Query result from get_results/get_var/get_row.
	 * @throws ProjectionQueryException On MySQL error or non-executing query.
	 */
	private function guard_query_error( string $query_label, $result = null, bool $null_is_failure = false ): void {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) ) {
			return;
		}

		$error = '';
		if ( property_exists( $wpdb, 'last_error' ) || isset( $wpdb->last_error ) ) {
			$raw   = $wpdb->last_error;
			$error = is_string( $raw ) ? trim( $raw ) : '';
		}

		if ( '' === $error && ! ( $null_is_failure && null === $result ) ) {
			return;
		}

		if ( '' !== $error ) {
			$message = sprintf( 'Projection query failed [%s]: %s', $query_label, $error );
		} else {
			$message = sprintf(
				'Projection query failed [%s]: query did not execute (wpdb not ready or query filtered)',
				$query_label
			);
		}

		Telemetry::log_line( $message );
		$wpdb->last_error = '';

		// phpcs:ignore WordPress.Security.EscapeOutput.ExceptionNotEscaped -- Internal diagnostic message; never rendered as output.
		throw new ProjectionQueryException( $message );
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
			_doing_it_wrong( esc_html( $method ), 'Tenant ID must be non-empty for sovereign projection operations.', '4.13.1' );
		}
	}
}
