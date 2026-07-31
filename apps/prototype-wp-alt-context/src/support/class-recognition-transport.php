<?php
/**
 * Credentialed recognition egress transport.
 *
 * Single chooser for loopback vs safe remote HTTP, with a hard never-follow-
 * redirects policy. Callers must not re-implement this split: forgetting
 * redirection => 0 at a call site walks X-API-Key / X-Tenant-ID onto any
 * public Location a compromised recognition host advertises (BR-137).
 *
 * @package AltContext\Support
 */

declare(strict_types=1);

namespace AltContext\Support;

require_once __DIR__ . '/class-loopback-host.php';

use WP_Error;

use function parse_url;
use function strtolower;
use function wp_remote_get;
use function wp_remote_request;
use function wp_safe_remote_get;
use function wp_safe_remote_request;

/**
 * Shared HTTP transport for credentialed recognition API calls.
 */
final class RecognitionTransport {
	/**
	 * Credentialed GET. Forces redirection => 0; non-loopback uses the safe
	 * transport so every hop is validated by wp_http_validate_url.
	 *
	 * @param array<string,mixed> $args
	 * @return array<string,mixed>|WP_Error
	 */
	public static function get( string $url, array $args ) {
		$args['redirection'] = 0;
		$host                = strtolower( (string) ( parse_url( $url, PHP_URL_HOST ) ?? '' ) );
		if ( LoopbackHost::is_loopback( $host ) ) {
			return wp_remote_get( $url, $args );
		}

		return wp_safe_remote_get( $url, $args );
	}

	/**
	 * Credentialed request (any method). Same loopback/safe split and
	 * never-follow-redirects policy as get().
	 *
	 * @param array<string,mixed> $args
	 * @return array<string,mixed>|WP_Error
	 */
	public static function request( string $url, array $args ) {
		$args['redirection'] = 0;
		$host                = strtolower( (string) ( parse_url( $url, PHP_URL_HOST ) ?? '' ) );
		if ( LoopbackHost::is_loopback( $host ) ) {
			return wp_remote_request( $url, $args );
		}

		return wp_safe_remote_request( $url, $args );
	}
}
