<?php

declare(strict_types=1);

namespace AltContext\Api;

require_once __DIR__ . '/class-abstract-recognition-proxy-controller.php';
require_once __DIR__ . '/class-blob-url-rewriter.php';

use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

use function add_action;
use function add_filter;
use function esc_url_raw;
use function hash_equals;
use function header;
use function is_wp_error;
use function nocache_headers;
use function register_rest_route;
use function remove_filter;
use function rest_get_server;
use function sprintf;
use function sanitize_text_field;
use function status_header;
use function str_contains;
use function time;
use function untrailingslashit;
use function wp_unslash;
use function wp_remote_get;
use function wp_remote_retrieve_body;
use function wp_remote_retrieve_header;
use function wp_remote_retrieve_response_code;

/**
 * Streaming proxy for recognition-service blob bytes.
 *
 * The browser cannot fetch the recognition service directly: API keys are
 * stored server-side, `<img>` requests can't carry an `Authorization`
 * header, and the recognition service runs on a different origin. This
 * controller exposes
 * `GET /wp-json/acx/v1/recognition/blobs/{job_id}/{media_id}` and proxies
 * the bytes through the existing recognition transport (which adds the
 * X-API-Key + X-Tenant-ID headers). The matching wire-format rewriter
 * (`BlobUrlRewriter`) ensures every `*media_url` field that the
 * recognition service emits as a `/recognition/blobs/...` path lands in
 * the browser as a fetchable WP REST URL.
 *
 * Returns binary bytes via WP's `rest_pre_serve_request` hook because
 * `WP_REST_Response` JSON-encodes the body field. The hook short-circuits
 * the response after writing the upstream Content-Type and bytes.
 */
class BlobsController extends AbstractRecognitionProxyController {
	private const ALLOWED_CONTENT_TYPES = array(
		'image/jpeg',
		'image/png',
		'image/gif',
		'image/webp',
		'application/octet-stream',
	);

	private const ROUTE_PREFIX = '/wp-json/acx/v1/recognition/blobs/';

	public function register_routes(): void {
		register_rest_route(
			'acx/v1',
			'/recognition/blobs/(?P<job_id>[A-Za-z0-9._-]+)/(?P<media_id>[A-Za-z0-9._-]+)',
			array(
				'methods'             => 'GET',
				'callback'            => array( $this, 'serve_blob' ),
				'permission_callback' => array( $this, 'verify_blob_token' ),
			)
		);

		// `<img>` requests can't carry an X-WP-Nonce header. WP REST's
		// rest_cookie_check_errors fires on rest_authentication_errors
		// before the route's permission_callback and rejects every
		// cookie-authed request without a nonce as 403
		// rest_cookie_invalid_nonce — short-circuiting our HMAC token
		// check. Clear that error specifically for the blob route so
		// verify_blob_token can run. Priority 200 runs after the cookie
		// check (priority 100); the bypass is scoped to the blob route
		// path so the rest of WP REST stays nonce-protected.
		add_filter( 'rest_authentication_errors', array( self::class, 'maybe_bypass_nonce_for_blob_route' ), 200 );
	}

	/**
	 * Replace a `rest_cookie_invalid_nonce` error with `null` (auth ok)
	 * when the request URI targets the blob proxy route. Returns the
	 * upstream value untouched in every other case.
	 *
	 * @param mixed $errors Prior auth result from upstream filters.
	 * @return mixed
	 */
	public static function maybe_bypass_nonce_for_blob_route( $errors ) {
		if ( ! ( $errors instanceof WP_Error ) ) {
			return $errors;
		}
		if ( 'rest_cookie_invalid_nonce' !== $errors->get_error_code() ) {
			return $errors;
		}
		$request_uri = isset( $_SERVER['REQUEST_URI'] )
			? sanitize_text_field( wp_unslash( (string) $_SERVER['REQUEST_URI'] ) )
			: '';
		if ( '' === $request_uri ) {
			return $errors;
		}
		if ( str_contains( $request_uri, self::ROUTE_PREFIX ) ) {
			return null;
		}
		return $errors;
	}

	/**
	 * Permission gate for the blob proxy. Validates the HMAC capability
	 * token minted by `BlobUrlRewriter::sign` against the request's
	 * job_id, media_id, and expires query args.
	 *
	 * `<img src>` requests cannot carry the `X-WP-Nonce` header, so the
	 * standard cookie+nonce REST permission check fails for thumbnails
	 * embedded in admin pages. The signed URL is the capability that
	 * authorizes this specific GET; no session check is required because
	 * the token is unforgeable without `wp_salt('auth')`, which is server
	 * side only.
	 */
	public function verify_blob_token( WP_REST_Request $request ): bool|WP_Error {
		$job_id   = (string) $request->get_param( 'job_id' );
		$media_id = (string) $request->get_param( 'media_id' );
		$expires  = (int) $request->get_param( 'expires' );
		$token    = (string) $request->get_param( 'token' );

		if ( '' === $token || $expires <= 0 ) {
			return new WP_Error(
				'recognition_blob_token_missing',
				'Missing or invalid blob token.',
				array( 'status' => 401 )
			);
		}
		if ( $expires < time() ) {
			return new WP_Error(
				'recognition_blob_token_expired',
				'Blob token has expired.',
				array( 'status' => 401 )
			);
		}

		$expected = BlobUrlRewriter::sign( $job_id, $media_id, $expires );
		if ( ! hash_equals( $expected, $token ) ) {
			return new WP_Error(
				'recognition_blob_token_invalid',
				'Blob token signature does not match.',
				array( 'status' => 401 )
			);
		}

		return true;
	}

	public function serve_blob( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$job_id   = (string) $request->get_param( 'job_id' );
		$media_id = (string) $request->get_param( 'media_id' );

		$base_url = $this->get_recognition_base_url();
		if ( '' === $base_url ) {
			return new WP_Error(
				'recognition_not_configured',
				'Recognition service URL is missing.',
				array( 'status' => 500 )
			);
		}

		$api_key = $this->get_recognition_api_key();
		if ( '' === $api_key ) {
			return new WP_Error(
				'recognition_api_key_missing',
				'Recognition API key is not configured.',
				array( 'status' => 500 )
			);
		}

		$url      = esc_url_raw(
			untrailingslashit( $base_url ) . sprintf( '/recognition/blobs/%s/%s', $job_id, $media_id )
		);
		$response = wp_remote_get(
			$url,
			array(
				'headers' => array(
					'X-API-Key'   => $api_key,
					'X-Tenant-ID' => $this->get_tenant_id(),
				),
				'timeout' => 10,
			)
		);

		if ( is_wp_error( $response ) ) {
			return new WP_Error(
				'recognition_blob_unavailable',
				$response->get_error_message(),
				array( 'status' => 502 )
			);
		}

		$status       = (int) wp_remote_retrieve_response_code( $response );
		$content_type = (string) wp_remote_retrieve_header( $response, 'content-type' );
		$body         = wp_remote_retrieve_body( $response );

		if ( $status >= 400 ) {
			return new WP_Error(
				'recognition_blob_error',
				sprintf( 'Recognition service returned %d for blob.', $status ),
				array( 'status' => $status )
			);
		}

		$safe_type = $this->normalize_content_type( $content_type );

		add_action(
			'rest_pre_serve_request',
			static function ( bool $served ) use ( $body, $safe_type ): bool {
				if ( $served ) {
					return $served;
				}
				remove_filter( 'rest_pre_echo_response', '__return_null' );
				nocache_headers();
				status_header( 200 );
				header( 'Content-Type: ' . $safe_type );
				header( 'Content-Length: ' . (string) strlen( $body ) );
				echo $body; // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped -- binary image bytes.
				return true;
			},
			10,
			1
		);

		// The hook above writes the actual body. Returning an empty
		// WP_REST_Response keeps the WP REST machinery happy without
		// adding a JSON envelope on top of the bytes.
		$placeholder = new WP_REST_Response( null, 200 );
		$placeholder->header( 'Content-Type', $safe_type );
		return $placeholder;
	}

	private function normalize_content_type( string $value ): string {
		$lower = strtolower( trim( $value ) );
		if ( '' === $lower ) {
			return 'application/octet-stream';
		}
		// Strip charset/parameter trailer.
		$semi = strpos( $lower, ';' );
		if ( false !== $semi ) {
			$lower = substr( $lower, 0, $semi );
		}
		$lower = trim( $lower );
		if ( in_array( $lower, self::ALLOWED_CONTENT_TYPES, true ) ) {
			return $lower;
		}
		return 'application/octet-stream';
	}
}
