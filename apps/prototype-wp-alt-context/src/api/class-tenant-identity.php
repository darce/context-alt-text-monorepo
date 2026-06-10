<?php

declare(strict_types=1);

namespace AltContext\Api;

use function apply_filters;
use function defined;
use function error_log;
use function get_option;
use function get_site_url;
use function hexdec;
use function sha1;
use function sprintf;
use function strtolower;
use function substr;
use function trim;
use function untrailingslashit;
use function update_option;
use function wp_is_uuid;

/**
 * Canonical tenant-id derivation for the plugin.
 *
 * The recognition service keys every row on a per-site UUID derived from the
 * WordPress site URL. `AbstractRecognitionProxyController` used to inline this
 * derivation, so the `X-Tenant-ID` header sent with every recognition call
 * matched exactly one site. The Settings probe must produce the same value or
 * its outcome diverges from real request behavior, so both call sites now
 * delegate here.
 */
final class TenantIdentity {
	public const OPTION_KEY = 'acx_recognition_tenant_id';

	/**
	 * @return array{value: string, source: string}
	 */
	public static function resolve(): array {
		$constant = self::get_constant_value( 'ACX_RECOGNITION_TENANT_ID' );
		if ( '' !== $constant ) {
			if ( self::is_valid_tenant_uuid( $constant ) ) {
				return array(
					'value'  => strtolower( $constant ),
					'source' => 'constant',
				);
			}

			self::log_invalid_override( 'constant', $constant );
		}

		$filter = trim( (string) apply_filters( 'acx_recognition_tenant_id', '' ) );
		if ( '' !== $filter ) {
			if ( self::is_valid_tenant_uuid( $filter ) ) {
				return array(
					'value'  => strtolower( $filter ),
					'source' => 'filter',
				);
			}

			self::log_invalid_override( 'filter', $filter );
		}

		$option = trim( (string) get_option( self::OPTION_KEY, '' ) );
		if ( '' !== $option ) {
			if ( self::is_valid_tenant_uuid( $option ) ) {
				return array(
					'value'  => strtolower( $option ),
					'source' => 'option',
				);
			}

			self::log_invalid_override( 'option', $option );
		}

		$derived = self::derive_from_site_url();
		if ( '' === $option ) {
			update_option( self::OPTION_KEY, $derived );
		}

		return array(
			'value'  => $derived,
			'source' => 'derived',
		);
	}

	public static function derive_from_site_url(): string {
		$site_url  = untrailingslashit( strtolower( (string) get_site_url() ) );
		$hash      = sha1( 'acx-site-tenant:' . $site_url );
		$time_hi   = ( hexdec( substr( $hash, 12, 4 ) ) & 0x0fff ) | 0x5000;
		$clock_seq = ( hexdec( substr( $hash, 16, 4 ) ) & 0x3fff ) | 0x8000;

		return sprintf(
			'%s-%s-%04x-%04x-%s',
			substr( $hash, 0, 8 ),
			substr( $hash, 8, 4 ),
			$time_hi,
			$clock_seq,
			substr( $hash, 20, 12 )
		);
	}

	public static function is_paired(): bool {
		return false;
	}

	private static function get_constant_value( string $name ): string {
		if ( defined( $name ) && is_string( constant( $name ) ) ) {
			return trim( constant( $name ) );
		}

		return '';
	}

	private static function is_valid_tenant_uuid( string $value ): bool {
		return wp_is_uuid( strtolower( trim( $value ) ) );
	}

	private static function log_invalid_override( string $level, string $value ): void {
		error_log(
			sprintf(
				'Alt Context: ignoring malformed %s tenant id override: %s',
				$level,
				$value
			)
		);
	}

	private function __construct() {}
}