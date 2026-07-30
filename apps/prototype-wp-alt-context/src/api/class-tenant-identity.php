<?php

declare(strict_types=1);

namespace AltContext\Api;

use AltContext\Support\Telemetry;
use function apply_filters;
use function defined;
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
 * Canonical tenant identity resolution for the plugin.
 */
final class TenantIdentity {
	public const OPTION_KEY        = 'acx_recognition_tenant_id';
	public const PAIRED_OPTION_KEY = 'acx_recognition_tenant_paired';

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

		$derived = self::derive_site_url_tenant_id();
		if ( '' === $option ) {
			update_option( self::OPTION_KEY, $derived );
		}

		return array(
			'value'  => $derived,
			'source' => 'derived',
		);
	}

	public static function is_paired(): bool {
		return (bool) get_option( self::PAIRED_OPTION_KEY, false );
	}

	/**
	 * Persist the operator-paired tenant id and the paired flag.
	 *
	 * R23-BR-15: verify both option writes via read-back. update_option returns
	 * false on both failure and no-op (re-pairing the already-stored id / flag)
	 * — only read-back distinguishes them. Never set the paired flag on an
	 * unverified identity write: is_paired() true with an empty OPTION_KEY lets
	 * resolve() auto-derive and persist a URL-derived id while advertising a
	 * paired identity. If the paired-flag write fails after a verified tenant-id
	 * write, leave the tenant id in place (safe state: is_paired() is false).
	 *
	 * @throws \InvalidArgumentException When $tenant_id is not a UUID.
	 * @throws \RuntimeException         When the tenant-id option or paired flag
	 *                                   does not hold the intended value after
	 *                                   the write attempt.
	 */
	public static function adopt_paired_tenant( string $tenant_id ): void {
		$normalized = strtolower( trim( $tenant_id ) );
		if ( ! self::is_valid_tenant_uuid( $normalized ) ) {
			throw new \InvalidArgumentException( 'Paired tenant id must be a UUID.' );
		}

		update_option( self::OPTION_KEY, $normalized );
		// Custom option: sanitize_option is identity; compare the intended UUID.
		// No-op re-pair (option already $normalized) still passes read-back.
		$stored = get_option( self::OPTION_KEY, null );
		if ( ! is_string( $stored ) || strtolower( trim( $stored ) ) !== $normalized ) {
			throw new \RuntimeException(
				'Could not persist the paired tenant id; pairing was not completed.'
			);
		}

		update_option( self::PAIRED_OPTION_KEY, true );
		// Truthy read-back: harness stores boolean true; a real DB cold-reload
		// returns '1'. Strict === true would false-fail production. No-op re-pair
		// (flag already set) still passes because the stored value is truthy.
		$paired = get_option( self::PAIRED_OPTION_KEY, false );
		if ( ! $paired ) {
			throw new \RuntimeException(
				'Could not persist the paired flag; pairing was not completed.'
			);
		}
	}

	/**
	 * True when the given tenant id is exactly the one this site would auto-derive
	 * from its URL (i.e. an un-pinned bootstrap identity, not an operator/pairing choice).
	 */
	public static function is_auto_derived_identity( string $tenant_id ): bool {
		return strtolower( trim( $tenant_id ) ) === self::derive_site_url_tenant_id();
	}

	/**
	 * One-time bootstrap derivation from the WordPress site URL.
	 */
	private static function derive_site_url_tenant_id(): string {
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

	private static function get_constant_value( string $name ): string {
		if ( ! defined( $name ) ) {
			return '';
		}

		$value = constant( $name );
		if ( ! is_string( $value ) ) {
			self::log_invalid_override( 'constant', var_export( $value, true ) );
			return '';
		}

		return trim( $value );
	}

	private static function is_valid_tenant_uuid( string $value ): bool {
		return wp_is_uuid( strtolower( trim( $value ) ) );
	}

	private static function log_invalid_override( string $level, string $value ): void {
		Telemetry::log_line(
			sprintf(
				'Alt Context: ignoring malformed %s tenant id override: %s',
				$level,
				$value
			)
		);
	}

	private function __construct() {}
}
