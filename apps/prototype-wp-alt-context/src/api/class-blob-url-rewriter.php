<?php

declare(strict_types=1);

namespace AltContext\Api;

use function add_query_arg;
use function array_merge;
use function ctype_digit;
use function rest_url;
use function str_contains;
use function str_ends_with;
use function str_starts_with;
use function wp_get_attachment_url;
use function wp_salt;
use const PHP_QUERY_RFC3986;

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
 * `token = HMAC-SHA256(wp_salt('auth'), "<route>:<job>:<media>:<expires>:<query>")`.
 * The matching `BlobsController::verify_blob_token` permission callback
 * recomputes the HMAC and compares it in constant time, only allowing the
 * fetch when the signature matches and `expires` is in the future.
 *
 * Pure helper: kept as static methods so it is unit-testable without
 * spinning up WordPress.
 */
class BlobUrlRewriter {
	private const RECOGNITION_BLOB_PREFIX       = '/recognition/blobs/';
	private const RECOGNITION_FACE_THUMB_PREFIX = '/recognition/face-thumbs/';
	private const FILE_SCHEME                   = 'file://';
	private const BLOB_SUFFIX                   = '.bin';
	private const TOKEN_TTL_SECONDS             = 3600;
	private const FACE_THUMB_QUERY_KEYS         = array( 'x', 'y', 'width', 'height' );
	// Keep this bound aligned with docs/agentic/contracts/clustering-api.md
	// "Face thumbnail crop contract" and the backend emitter/reader in
	// apps/prototype-description-service/recognition/interface_adapters/http/blob_url.py
	// and apps/prototype-description-service/recognition/interface_adapters/http/routers/blobs.py.
	private const FACE_THUMB_MAX_COMPONENT = 32768;

	/**
	 * Recursively rewrite blob strings inside a decoded JSON structure to
	 * absolute, signed WP REST proxy URLs.
	 *
	 * @param mixed $value Decoded JSON value (array, scalar, null).
	 * @return mixed The same shape with blob paths rewritten in place.
	 */
	public static function rewrite( $value ) {
		if ( \is_string( $value ) ) {
			return self::rewrite_string( $value );
		}
		if ( \is_array( $value ) ) {
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
		if ( str_starts_with( $value, self::FILE_SCHEME ) ) {
			$blob_path = self::rewrite_file_uri_to_blob_path( $value );
			if ( null === $blob_path ) {
				return '';
			}
			$value = $blob_path;
		}

		$route_kind = 'blobs';
		$prefix     = self::RECOGNITION_BLOB_PREFIX;
		if ( str_starts_with( $value, self::RECOGNITION_FACE_THUMB_PREFIX ) ) {
			$route_kind = 'face-thumbs';
			$prefix     = self::RECOGNITION_FACE_THUMB_PREFIX;
		} elseif ( ! str_starts_with( $value, self::RECOGNITION_BLOB_PREFIX ) ) {
			return $value;
		}
		$rest = \substr( $value, \strlen( $prefix ) );
		$query_args = array();
		$query_pos  = \strpos( $rest, '?' );
		if ( false !== $query_pos ) {
			$query_string = \substr( $rest, $query_pos + 1 );
			$rest         = \substr( $rest, 0, $query_pos );
			\parse_str( $query_string, $query_args );
		}
		if ( false === \strpos( $rest, '/' ) ) {
			return $value;
		}
		[ $job_id, $media_id ] = \explode( '/', $rest, 2 );
		if ( '' === $job_id || '' === $media_id ) {
			return $value;
		}
		if ( str_contains( $media_id, '/' ) ) {
			return $value;
		}
		$signature_args = array();
		if ( 'face-thumbs' === $route_kind ) {
			$signature_args = self::normalize_face_thumb_query_args( $query_args );
			if ( null === $signature_args ) {
				return $value;
			}
		}

		// Prefer the direct WP media URL when the recognition `media_id` matches
		// a real WP attachment. Bypasses the signed proxy entirely, so `<img>`
		// loads hit the same uploads URL that cluster-card thumbnails use and
		// avoid the recognition-service tenant-claim requirement on blob serve.
		if ( 'blobs' === $route_kind && ctype_digit( $media_id ) && \function_exists( 'wp_get_attachment_url' ) ) {
			$wp_url = wp_get_attachment_url( (int) $media_id );
			if ( \is_string( $wp_url ) && '' !== $wp_url ) {
				return $wp_url;
			}
		}

		$relative = 'acx/v1/recognition/' . $route_kind . '/' . $job_id . '/' . $media_id;
		$base_url = \function_exists( 'rest_url' ) ? rest_url( $relative ) : '/' . $relative;

		$expires = self::current_time() + self::TOKEN_TTL_SECONDS;
		$token   = self::sign( $job_id, $media_id, $expires, $route_kind, $signature_args );

		return add_query_arg(
			array_merge(
				$signature_args,
				array(
					'expires' => $expires,
					'token'   => $token,
				)
			),
			$base_url
		);
	}

	private static function rewrite_file_uri_to_blob_path( string $value ): ?string {
		$raw_path = \substr( $value, \strlen( self::FILE_SCHEME ) );
		if ( '' === $raw_path ) {
			return null;
		}

		$parts = \array_values(
			\array_filter(
				\explode( '/', $raw_path ),
				static fn ( string $part ): bool => '' !== $part
			)
		);
		if ( \count( $parts ) < 3 ) {
			return null;
		}

		$media_filename = $parts[ \count( $parts ) - 1 ];
		if ( ! str_ends_with( $media_filename, self::BLOB_SUFFIX ) ) {
			return null;
		}

		$job_id   = $parts[ \count( $parts ) - 2 ];
		$media_id = \substr( $media_filename, 0, -\strlen( self::BLOB_SUFFIX ) );
		if ( ! self::is_safe_route_segment( $job_id ) || ! self::is_safe_route_segment( $media_id ) ) {
			return null;
		}

		return self::RECOGNITION_BLOB_PREFIX . $job_id . '/' . $media_id;
	}

	private static function is_safe_route_segment( string $value ): bool {
		return 1 === \preg_match( '/^[A-Za-z0-9._-]+$/', $value );
	}

	/**
	 * Compute the HMAC for a (job, media, expires) capability tuple.
	 *
	 * Public so the controller permission callback can recompute the same
	 * signature and compare it in constant time.
	 */
	public static function sign(
		string $job_id,
		string $media_id,
		int $expires,
		string $route_kind = 'blobs',
		array $query_args = array()
	): string {
		$payload = \implode(
			':',
			array(
				$route_kind,
				$job_id,
				$media_id,
				(string) $expires,
				self::canonical_query_string( $query_args ),
			)
		);
		return \hash_hmac( 'sha256', $payload, self::secret() );
	}

	public static function normalize_face_thumb_query_args( array $query_args ): ?array {
		$normalized = array();
		foreach ( self::FACE_THUMB_QUERY_KEYS as $key ) {
			$value = $query_args[ $key ] ?? null;
			if ( ! \is_scalar( $value ) || '' === (string) $value || ! ctype_digit( (string) $value ) ) {
				return null;
			}
			$integer = (int) $value;
			if ( ( 'width' === $key || 'height' === $key ) && $integer <= 0 ) {
				return null;
			}
			if ( $integer > self::FACE_THUMB_MAX_COMPONENT ) {
				return null;
			}
			$normalized[ $key ] = $integer;
		}
		return $normalized;
	}

	private static function canonical_query_string( array $query_args ): string {
		if ( empty( $query_args ) ) {
			return '';
		}
		\ksort( $query_args );
		return \http_build_query( $query_args, '', '&', PHP_QUERY_RFC3986 );
	}

	private static function secret(): string {
		if ( \function_exists( 'wp_salt' ) ) {
			return wp_salt( 'auth' );
		}
		return 'acx-test-salt';
	}

	private static function current_time(): int {
		return \time();
	}
}
