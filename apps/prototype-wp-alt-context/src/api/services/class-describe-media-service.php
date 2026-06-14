<?php

declare(strict_types=1);

namespace AltContext\Api\Services;

use AltContext\Api\DescribeHostInterface;
use AltContext\Support\Telemetry;
use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

use function absint;
use function array_key_exists;
use function basename;
use function get_attached_file;
use function get_post;
use function get_site_url;
use function is_array;
use function is_object;
use function is_readable;
use function is_string;
use function is_wp_error;
use function pathinfo;
use function sprintf;
use function strlen;
use function strtolower;
use function wp_json_encode;

use const PATHINFO_EXTENSION;

/**
 * E19-1 S6: resolve one WordPress attachment, read its bytes, attach inert
 * wp_context, and dispatch a single-image multipart request to the backend
 * `/scene/describe/multipart` route. The backend `VisualFactsResponse` is
 * passed through unchanged; a malformed upstream envelope is rejected with an
 * explicit `502 invalid_description_envelope` (rg-015 — never fabricate
 * `cached`/`data_source`/provenance fields, never add list-pagination fields).
 */
class DescribeMediaService {
	private const MULTIPART_MAX_BYTES = 25 * 1024 * 1024;

	/**
	 * The 15 provenance-bearing fields the backend contract guarantees. The
	 * proxy validates the upstream payload carries every one before passing it
	 * through — a missing field means the boundary contract was violated.
	 *
	 * @var string[]
	 */
	private const REQUIRED_RESPONSE_FIELDS = array(
		'tenant_id',
		'media_id',
		'image_hash',
		'context_hash',
		'adapter',
		'model_id',
		'model_version',
		'prompt_or_task_version',
		'visual_facts',
		'alt_text_draft',
		'context_used',
		'provider_disclosure',
		'cached',
		'duration_ms',
		'retention_class',
	);

	private DescribeHostInterface $host;

	public function __construct( DescribeHostInterface $host ) {
		$this->host = $host;
	}

	public function describe_media( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$media_id = absint( $request->get_param( 'media_id' ) );
		if ( $media_id <= 0 ) {
			return new WP_Error(
				'describe_invalid_media_id',
				'A positive media_id is required.',
				array( 'status' => 400 )
			);
		}

		$path = get_attached_file( $media_id, true );
		if ( ! is_string( $path ) || '' === $path || ! is_readable( $path ) ) {
			return new WP_Error(
				'describe_attachment_unreadable',
				sprintf( 'Attachment file for media_id=%d is missing or not readable.', $media_id ),
				array( 'status' => 404 )
			);
		}

		$bytes = @file_get_contents( $path );
		if ( false === $bytes || '' === $bytes ) {
			return new WP_Error(
				'describe_attachment_unreadable',
				sprintf( 'Attachment file for media_id=%d is empty or unreadable.', $media_id ),
				array( 'status' => 404 )
			);
		}

		if ( strlen( $bytes ) > self::MULTIPART_MAX_BYTES ) {
			return new WP_Error(
				'describe_payload_too_large',
				sprintf(
					'Image for media_id=%d is %d bytes, exceeding the %d-byte cap.',
					$media_id,
					strlen( $bytes ),
					self::MULTIPART_MAX_BYTES
				),
				array( 'status' => 413 )
			);
		}

		$multipart_body = array(
			'request' => wp_json_encode(
				array(
					'tenant_id' => $this->host->get_tenant_id(),
					'media_id'  => $media_id,
					'context'   => $this->build_wp_context( $media_id, $path ),
				)
			),
			'image_' . $media_id => array(
				'filename'     => basename( $path ),
				'content'      => $bytes,
				'content_type' => $this->resolve_image_mime_type( $path, $media_id ),
			),
		);

		$response = $this->host->proxy_recognition_request(
			'POST',
			'/scene/describe/multipart',
			$multipart_body,
			array(),
			'auto',
			'multipart',
			self::MULTIPART_MAX_BYTES
		);

		if ( is_wp_error( $response ) ) {
			return $response;
		}

		return $this->validate_description_envelope( $response, $media_id );
	}

	/**
	 * rg-015: pass the backend payload through verbatim on success, but never
	 * fabricate a description envelope when the upstream shape is wrong. Upstream
	 * 4xx/5xx errors are forwarded unchanged; a 2xx body that omits any required
	 * provenance field is an explicit boundary violation (502).
	 */
	private function validate_description_envelope( WP_REST_Response $response, int $media_id ): WP_REST_Response|WP_Error {
		if ( $response->get_status() >= 400 ) {
			return $response;
		}

		$data = $response->get_data();
		if ( ! is_array( $data ) ) {
			return $this->invalid_envelope_error( $media_id, 'response body was not a JSON object' );
		}

		foreach ( self::REQUIRED_RESPONSE_FIELDS as $field ) {
			if ( ! array_key_exists( $field, $data ) ) {
				return $this->invalid_envelope_error( $media_id, sprintf( "missing required field '%s'", $field ) );
			}
		}

		return $response;
	}

	private function invalid_envelope_error( int $media_id, string $reason ): WP_Error {
		Telemetry::log_line(
			sprintf( '[acx] describe media_id=%d invalid backend envelope: %s', $media_id, $reason )
		);
		return new WP_Error(
			'invalid_description_envelope',
			sprintf( 'Backend describe response for media_id=%d was malformed: %s.', $media_id, $reason ),
			array( 'status' => 502 )
		);
	}

	/**
	 * Inert Phase-1 WordPress context (the seeded adapter is not scored on it).
	 * Sent as the backend envelope's single `context` field — the backend
	 * `DescribeImageEnvelope` is `extra='forbid'`, so site_url/title/etc. travel
	 * inside `context`, never as extra top-level keys.
	 *
	 * @return array<string,string>
	 */
	private function build_wp_context( int $media_id, string $path ): array {
		$post        = get_post( $media_id );
		$title       = is_object( $post ) && isset( $post->post_title ) ? (string) $post->post_title : '';
		$caption     = is_object( $post ) && isset( $post->post_excerpt ) ? (string) $post->post_excerpt : '';
		$description = is_object( $post ) && isset( $post->post_content ) ? (string) $post->post_content : '';

		return array(
			'site_url'    => get_site_url(),
			'title'       => $title,
			'caption'     => $caption,
			'description' => $description,
			'filename'    => basename( $path ),
		);
	}

	private function resolve_image_mime_type( string $path, int $media_id ): string {
		if ( function_exists( 'wp_check_filetype' ) ) {
			$detected = wp_check_filetype( $path );
			if ( is_array( $detected ) && ! empty( $detected['type'] ) ) {
				return (string) $detected['type'];
			}
		}
		if ( isset( $GLOBALS['__ac_attachment_mimes'][ $media_id ] ) ) {
			return (string) $GLOBALS['__ac_attachment_mimes'][ $media_id ];
		}
		$extension = strtolower( pathinfo( $path, PATHINFO_EXTENSION ) );
		switch ( $extension ) {
			case 'jpg':
			case 'jpeg':
				return 'image/jpeg';
			case 'png':
				return 'image/png';
			case 'webp':
				return 'image/webp';
			default:
				return 'application/octet-stream';
		}
	}
}
