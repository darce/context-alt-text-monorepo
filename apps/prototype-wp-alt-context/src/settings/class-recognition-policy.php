<?php

declare(strict_types=1);

namespace AltContext\Settings;

use function add_option;
use function get_option;
use function is_string;
use function strtolower;
use function update_option;

/**
 * Canonical store for the `acx_recognition_enabled` operator setting.
 *
 * Default ON: this plugin is installed to identify people. The WP option is
 * the only store; readers go through {@see enabled()}. Persist only the
 * strings '1' / '0' — never a PHP bool. Core `update_option()` no-ops when
 * the incoming value === `get_option()` whose default is false, so writing
 * `false` on a fresh install never inserts a row (Trac r56788).
 *
 * Unknown stored values fail closed to false. DEFAULT applies only when the
 * option row is missing (`get_option( OPTION, null ) === null`).
 */
final class RecognitionPolicy {
	public const OPTION  = 'acx_recognition_enabled';
	public const DEFAULT = true;

	public static function enabled(): bool {
		$stored = get_option( self::OPTION, null );
		if ( null === $stored ) {
			return self::DEFAULT;
		}

		return self::normalize( $stored );
	}

	public static function set( bool $value ): bool {
		$stored_value = $value ? '1' : '0';
		if ( null === get_option( self::OPTION, null ) ) {
			add_option( self::OPTION, $stored_value );
		} else {
			update_option( self::OPTION, $stored_value );
		}

		$stored = get_option( self::OPTION, null );
		if ( null === $stored ) {
			return false;
		}

		return self::normalize( $stored ) === $value;
	}

	public static function normalize( mixed $value ): bool {
		if ( true === $value || 1 === $value || '1' === $value ) {
			return true;
		}

		if ( is_string( $value ) && 'true' === strtolower( $value ) ) {
			return true;
		}

		return false;
	}

	private function __construct() {}
}
