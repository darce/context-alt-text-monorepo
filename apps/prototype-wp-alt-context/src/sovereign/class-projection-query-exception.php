<?php
/**
 * Thrown when a sovereign projection SQL query fails at the database layer.
 *
 * Callers must not collapse this into an empty result set (RLSE-05).
 *
 * @package AltContext\Sovereign
 */

declare(strict_types=1);

namespace AltContext\Sovereign;

/**
 * Typed failure for projection SELECT paths that hit a MySQL/wpdb error.
 */
class ProjectionQueryException extends \RuntimeException {
	/**
	 * Operator-facing REST error: stable code + generic message only (E21-14-BR-10).
	 * MySQL detail stays in Telemetry (logged at the guard), never on the wire.
	 */
	public static function to_rest_error( string $surface ): \WP_Error {
		return new \WP_Error(
			'acx_projection_query_failed',
			sprintf( 'Projection query failed on %s. See server logs for details.', $surface ),
			array( 'status' => 500 )
		);
	}
}
