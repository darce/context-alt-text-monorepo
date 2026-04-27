<?php

declare(strict_types=1);

namespace AltContext\Api;

use function add_query_arg;
use function ctype_digit;
use function explode;
use function function_exists;
use function hash_hmac;
use function is_array;
use function is_string;
use function str_starts_with;
use function rest_url;
use function time;
use function wp_get_attachment_url;
use function wp_salt;

/**
 * Rewrites recognition-service blob paths to a signed WP REST proxy URL so
 * the browser can load them as `<img src>`.
 *
 * The recognition service emits relative paths like
 * `/recognition/blobs/<job_id>/<media_id>` for multipart-uploaded media.
 * Same-origin resolution would 404 against the WP origin, and an absolute
 * URL to the recognition service would also fail because `<img>` requests
 * can't carry the API key.
 *
 * `<img>` requests also can't carry the WP REST `X-WP-Nonce` header, so we
 * cannot guard the proxy route with the standard cookie+nonce permission
 * callback. Instead, this rewriter mints a self-authenticating capability
 * URL: the rewritten URL carries `expires` + `token` query args, where
 * `token = HMAC-SHA256(wp_salt('auth'), "<job>:<media>:<expires>")`. The
 * matching `BlobsController::verify_blob_token` permission callback
 * recomputes the HMAC and compares it in constant time, only allowing the
 * fetch when the signature matches and `expires` is in the future.
 *
 * Pure helper: kept as static methods so it is unit-testable without
 * spinning up WordPress.
 */
class BlobUrlRewriter {
	private const RECOGNITION_BLOB_PREFIX = '/recognition/blobs/';
	private const TOKEN_TTL_SECONDS       = 3600;

	/**
	 * Recursively rewrite `/recognition/blobs/<job>/<media>` strings inside
	 * a decoded JSON structure to absolute, signed WP REST proxy URLs.
	 *
	 * @param mixed $value Decoded JSON value (array, scalar, null).
	 * @return mixed The same shape with blob paths rewritten in place.
	 */
	public static function rewrite( $value ) {
		if ( is_string( $value ) ) {
			return self::rewrite_string( $value );
		}
		if ( is_array( $value ) ) {
			foreach ( $value as $k => $v ) {
				$value[ $k ] = self::rewrite( $v );
			}
			return $value;
		}
		return $value;
	}

	/**
	 * Rewrite a single string value if it is a recognition blob path.
	 *
	 * Public so callers (or tests) can apply the transform to a known
	 * field without walking a structure.
	 */
	public static function rewrite_string( string $value ): string {
		if ( ! str_starts_with( $value, self::RECOGNITION_BLOB_PREFIX ) ) {
			return $value;
		}
		$rest = substr( $value, strlen( self::RECOGNITION_BLOB_PREFIX ) );
		if ( false === strpos( $rest, '/' ) ) {
			return $value;
		}
		[ $job_id, $media_id ] = explode( '/', $rest, 2 );
		if ( '' === $job_id || '' === $media_id ) {
			return $value;
		}

		// Prefer the direct WP media URL when the recognition `media_id` matches
		// a real WP attachment. Bypasses the signed proxy entirely, so `<img>`
		// loads hit the same uploads URL that cluster-card thumbnails use and
		// avoid the recognition-service tenant-claim requirement on blob serve.
		if ( ctype_digit( $media_id ) && function_exists( 'wp_get_attachment_url' ) ) {
			$wp_url = wp_get_attachment_url( (int) $media_id );
			if ( is_string( $wp_url ) && '' !== $wp_url ) {
				return $wp_url;
			}
		}

		$relative = 'acx/v1' . $value;
		$base_url = function_exists( 'rest_url' ) ? rest_url( $relative ) : '/' . $relative;

		$expires = self::current_time() + self::TOKEN_TTL_SECONDS;
		$token   = self::sign( $job_id, $media_id, $expires );

		return add_query_arg(
			array(
				'expires' => $expires,
				'token'   => $token,
			),
			$base_url
		);
	}

	/**
	 * Compute the HMAC for a (job, media, expires) capability tuple.
	 *
	 * Public so the controller permission callback can recompute the same
	 * signature and compare it in constant time.
	 */
	public static function sign( string $job_id, string $media_id, int $expires ): string {
		return hash_hmac( 'sha256', $job_id . ':' . $media_id . ':' . $expires, self::secret() );
	}

	private static function secret(): string {
		if ( function_exists( 'wp_salt' ) ) {
			return wp_salt( 'auth' );
		}
		// Test fallback: deterministic so unit tests can recompute signatures.
		return 'acx-test-salt';
	}

	private static function current_time(): int {
		return time();
	}
}
