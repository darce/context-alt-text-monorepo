<?php

declare(strict_types=1);

namespace AltContext\Api\Services;

require_once __DIR__ . '/../../support/class-telemetry.php';

use AltContext\Api\DescribeHostInterface;
use AltContext\Support\Telemetry;
use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

use function absint;
use function array_filter;
use function array_key_exists;
use function array_slice;
use function array_values;
use function basename;
use function get_attached_file;
use function get_post;
use function get_post_meta;
use function is_array;
use function is_numeric;
use function is_object;
use function is_readable;
use function is_string;
use function is_wp_error;
use function pathinfo;
use function sprintf;
use function strlen;
use function substr;
use function strtolower;
use function trim;
use function wp_get_object_terms;
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

		// Reject oversize on a cheap stat before loading the whole file into
		// memory; the post-read strlen check below still guards the exact size.
		$stat_size = @filesize( $path );
		if ( is_int( $stat_size ) && $stat_size > self::MULTIPART_MAX_BYTES ) {
			return $this->payload_too_large_error( $media_id, $stat_size );
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
			return $this->payload_too_large_error( $media_id, strlen( $bytes ) );
		}

		$multipart_body = array(
			'request' => wp_json_encode(
				array(
					'tenant_id' => $this->host->get_tenant_id(),
					'media_id'  => $media_id,
					'context_pack' => $this->build_context_pack( $media_id, $path ),
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
			'description',
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

	private function payload_too_large_error( int $media_id, int $size_bytes ): WP_Error {
		return new WP_Error(
			'describe_payload_too_large',
			sprintf(
				'Image for media_id=%d is %d bytes, exceeding the %d-byte cap.',
				$media_id,
				$size_bytes,
				self::MULTIPART_MAX_BYTES
			),
			array( 'status' => 413 )
		);
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
	 * @return array<string,mixed>
	 */
	private function build_context_pack( int $media_id, string $path ): array {
		$attachment = get_post( $media_id );
		$parent     = $this->get_public_parent_post( $attachment );
		$context    = array(
			'attachment' => $this->non_empty_fields(
				array(
					'title'       => $this->bounded_string( is_object( $attachment ) && isset( $attachment->post_title ) ? $attachment->post_title : null, 160 ),
					'caption'     => $this->bounded_string( is_object( $attachment ) && isset( $attachment->post_excerpt ) ? $attachment->post_excerpt : null, 500 ),
					'description' => $this->bounded_string( is_object( $attachment ) && isset( $attachment->post_content ) ? $attachment->post_content : null, 1000 ),
					'alt_text'    => $this->bounded_string( get_post_meta( $media_id, '_wp_attachment_image_alt', true ), 500 ),
					'filename'    => $this->bounded_string( basename( $path ), 255 ),
				)
			),
		);

		if ( null !== $parent ) {
			$context['post'] = $this->non_empty_fields(
				array(
					'title'     => $this->bounded_string( $parent->post_title ?? null, 200 ),
					'excerpt'   => $this->bounded_string( $parent->post_excerpt ?? null, 1000 ),
					'post_type' => $this->bounded_string( $parent->post_type ?? null, 64 ),
					'status'    => $this->bounded_string( $parent->post_status ?? null, 32 ),
				)
			);

			if ( isset( $parent->ID ) ) {
				$terms = $this->collect_taxonomy_terms( (int) $parent->ID );
				if ( array() !== $terms ) {
					$context['taxonomy_terms'] = $terms;
				}

				if ( 'product' === (string) ( $parent->post_type ?? '' ) ) {
					$context['product'] = $this->non_empty_fields(
						array(
							'name'  => $this->bounded_string( $parent->post_title ?? null, 200 ),
							'sku'   => $this->bounded_string( get_post_meta( (int) $parent->ID, '_sku', true ), 120 ),
							'price' => $this->bounded_string( get_post_meta( (int) $parent->ID, '_price', true ), 64 ),
						)
					);
				}
			}
		}

		return array_filter(
			$context,
			static fn ( mixed $value ): bool => is_array( $value ) ? array() !== $value : null !== $value
		);
	}

	private function get_public_parent_post( mixed $attachment ): ?object {
		$parent_id = is_object( $attachment ) && isset( $attachment->post_parent ) ? absint( $attachment->post_parent ) : 0;
		if ( $parent_id <= 0 ) {
			return null;
		}

		$parent = get_post( $parent_id );
		if ( ! is_object( $parent ) || 'publish' !== (string) ( $parent->post_status ?? '' ) ) {
			return null;
		}

		return $parent;
	}

	/**
	 * @return array<int,array<string,string>>
	 */
	private function collect_taxonomy_terms( int $object_id ): array {
		$terms = array();
		foreach ( array( 'category', 'post_tag', 'product_cat', 'product_tag' ) as $taxonomy ) {
			$result = wp_get_object_terms( $object_id, $taxonomy );
			if ( is_wp_error( $result ) || ! is_array( $result ) ) {
				continue;
			}

			foreach ( $result as $term ) {
				if ( ! is_object( $term ) || ! isset( $term->name, $term->taxonomy ) ) {
					continue;
				}

				$terms[] = $this->non_empty_fields(
					array(
						'taxonomy' => $this->bounded_string( $term->taxonomy, 64 ),
						'name'     => $this->bounded_string( $term->name, 120 ),
						'slug'     => $this->bounded_string( $term->slug ?? null, 120 ),
					)
				);
			}
		}

		return array_slice( array_values( array_filter( $terms ) ), 0, 20 );
	}

	/**
	 * @param array<string,?string> $fields
	 * @return array<string,string>
	 */
	private function non_empty_fields( array $fields ): array {
		return array_filter(
			$fields,
			static fn ( ?string $value ): bool => null !== $value && '' !== $value
		);
	}

	private function bounded_string( mixed $value, int $max_length ): ?string {
		if ( ! is_string( $value ) && ! is_numeric( $value ) ) {
			return null;
		}

		$value = trim( (string) $value );
		if ( '' === $value ) {
			return null;
		}

		return substr( $value, 0, $max_length );
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
