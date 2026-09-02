<?php

declare(strict_types=1);

namespace AltContext\Settings;

use function get_option;
use function is_bool;
use function is_string;
use function strtolower;
use function update_option;

/**
 * Canonical store for the `acx_recognition_enabled` operator setting.
 *
 * Default ON: this plugin is installed to identify people. The WP option is
 * the only store; readers go through {@see enabled()} so stored '1'/'0'/
 * 'true'/'false' values normalise to bool.
 */
final class RecognitionPolicy {
	public const OPTION  = 'acx_recognition_enabled';
	public const DEFAULT = true;

	public static function enabled(): bool {
		return self::normalize( get_option( self::OPTION, self::DEFAULT ) );
	}

	public static function set( bool $value ): bool {
		update_option( self::OPTION, $value );
		$stored = get_option( self::OPTION, null );
		if ( null === $stored ) {
			return false;
		}

		return self::normalize( $stored ) === $value;
	}

	public static function normalize( mixed $value ): bool {
		if ( is_bool( $value ) ) {
			return $value;
		}

		if ( 1 === $value || '1' === $value ) {
			return true;
		}

		if ( 0 === $value || '0' === $value || '' === $value ) {
			return false;
		}

		if ( is_string( $value ) ) {
			$normalized = strtolower( $value );
			if ( 'true' === $normalized ) {
				return true;
			}
			if ( 'false' === $normalized ) {
				return false;
			}
		}

		return self::DEFAULT;
	}

	private function __construct() {}
}
