<?php

declare(strict_types=1);

namespace AltContext\Api;

use function function_exists;
use function is_array;
use function is_string;
use function str_starts_with;
use function rest_url;

/**
 * Rewrites recognition-service blob paths to the WP REST proxy URL so the
 * browser can load them as `<img src>`.
 *
 * The recognition service emits relative paths like
 * `/recognition/blobs/<job_id>/<media_id>` for multipart-uploaded media
 * (the bytes live only on the recognition VM's filesystem; there is no
 * `wp-content/uploads/...` URL the browser could hit). Same-origin
 * resolution would 404 against the WP origin, and an absolute URL to the
 * recognition service would also fail because `<img>` requests can't
 * carry the API key. This rewriter swaps every such path to
 * `<rest_url>acx/v1/recognition/blobs/<job_id>/<media_id>` — a same-origin
 * URL the WP plugin's BlobsController proxies through with the API key.
 *
 * Pure helper: kept as static methods so it is unit-testable without
 * spinning up WordPress (rest_url is the only WP dep, and absent tests
 * fall through to the literal prefix path).
 */
class BlobUrlRewriter {
	private const RECOGNITION_BLOB_PREFIX = '/recognition/blobs/';

	/**
	 * Recursively rewrite `/recognition/blobs/<job>/<media>` strings inside
	 * a decoded JSON structure to absolute WP REST proxy URLs.
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
		$relative = 'acx/v1' . $value;
		if ( function_exists( 'rest_url' ) ) {
			return rest_url( $relative );
		}
		return '/' . $relative;
	}
}
