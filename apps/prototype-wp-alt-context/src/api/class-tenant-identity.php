<?php

declare(strict_types=1);

namespace AltContext\Api;

use function get_site_url;
use function hexdec;
use function sha1;
use function sprintf;
use function strtolower;
use function substr;
use function untrailingslashit;

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

	private function __construct() {}
}
