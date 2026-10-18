<?php
/**
 * Shared loopback-host predicate for recognition URL gates and egress.
 *
 * Single source of truth for the http-loopback allowlist used by endpoint
 * resolution, settings validation, and credentialed outbound transport.
 * Do not widen the set without an explicit security review — this is a
 * pure extraction of the previous private copies (BR-139).
 *
 * @package AltContext\Support
 */

declare(strict_types=1);

namespace AltContext\Support;

use function in_array;
use function str_ends_with;
use function str_starts_with;
use function substr;

/**
 * Predicate: is this host an explicit loopback development target?
 */
final class LoopbackHost {
	/**
	 * Accept only the loopback names the local hatch already uses:
	 * localhost, 127.0.0.1, and ::1 (with optional IPv6 brackets).
	 */
	public static function is_loopback( string $host ): bool {
		if ( str_starts_with( $host, '[' ) && str_ends_with( $host, ']' ) ) {
			$host = substr( $host, 1, -1 );
		}

		return in_array( $host, array( 'localhost', '127.0.0.1', '::1' ), true );
	}
}
