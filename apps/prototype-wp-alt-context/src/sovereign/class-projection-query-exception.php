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
}
