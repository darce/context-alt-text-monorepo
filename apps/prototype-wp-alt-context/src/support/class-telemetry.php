<?php
/**
 * Lightweight telemetry sink for plugin-side log lines (E15-11 Slice 3.2).
 *
 * Production calls PHP's error_log directly. Tests intercept by setting
 * $GLOBALS['__ac_error_log'] = [] before the call site fires; the helper
 * sees the array and appends to it instead of writing to stderr. This
 * matches the existing __ac_attachment_urls / __ac_attached_file capture
 * pattern used elsewhere in the test infrastructure.
 *
 * @package AltContext\Support
 */

declare(strict_types=1);

namespace AltContext\Support;

final class Telemetry {
	/**
	 * Emit a plugin-side log line. In tests where
	 * ``$GLOBALS['__ac_error_log']`` is an array, the message is captured
	 * there; otherwise the call delegates to PHP's ``error_log`` so
	 * production behaviour is unchanged.
	 */
	public static function log_line( string $message ): void {
		if ( isset( $GLOBALS['__ac_error_log'] ) && is_array( $GLOBALS['__ac_error_log'] ) ) {
			$GLOBALS['__ac_error_log'][] = $message;
			return;
		}
		if ( function_exists( 'error_log' ) ) {
			// phpcs:ignore WordPress.PHP.DevelopmentFunctions.error_log_error_log
			error_log( $message );
		}
	}
}
