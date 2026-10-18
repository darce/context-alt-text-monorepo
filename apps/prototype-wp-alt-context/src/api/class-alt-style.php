<?php

declare(strict_types=1);

namespace AltContext\Api;

use function get_option;
use function in_array;
use function is_string;

/**
 * ALTQ-1: canonical values for the `acx_alt_style` operator setting.
 *
 * Controls where a describe result's surfaces land on write: `alt_only`
 * (default — current behavior, short draft to `_wp_attachment_image_alt`
 * only) or `alt_plus_description` (short draft to the alt field AND the
 * optional backend `alt_text_long` to the attachment description /
 * `post_content`). Centralized per sr-007 so no consumer scatters magic
 * string comparisons; mirrors the {@see ProbeOutcome} constants idiom.
 */
final class AltStyle {
	public const OPTION_NAME = 'acx_alt_style';

	public const ALT_ONLY             = 'alt_only';
	public const ALT_PLUS_DESCRIPTION = 'alt_plus_description';

	public const ALL = array( self::ALT_ONLY, self::ALT_PLUS_DESCRIPTION );

	public static function is_valid( mixed $value ): bool {
		return is_string( $value ) && in_array( $value, self::ALL, true );
	}

	/**
	 * Invalid or missing stored values degrade to the safe default
	 * (current behavior): ALT_ONLY.
	 */
	public static function normalize( mixed $value ): string {
		return self::is_valid( $value ) ? $value : self::ALT_ONLY;
	}

	public static function current(): string {
		return self::normalize( get_option( self::OPTION_NAME, self::ALT_ONLY ) );
	}

	private function __construct() {}
}
