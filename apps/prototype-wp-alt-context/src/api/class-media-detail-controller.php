<?php

declare(strict_types=1);

namespace AltContext\Api;

use WP_REST_Request;
use WP_REST_Response;

use function absint;
use function array_filter;
use function array_map;
use function array_values;
use function explode;
use function get_post_meta;
use function get_post_mime_type;
use function get_post_modified_time;
use function is_array;
use function is_string;
use function wp_get_attachment_metadata;

class MediaDetailController {

	public function get_media_details( WP_REST_Request $request ): WP_REST_Response {
		$ids = $this->resolve_media_ids( $request );
		$details_by_media = array();

		foreach ( $ids as $media_id ) {
			$meta = wp_get_attachment_metadata( $media_id );
			$xmp_persist = get_post_meta( $media_id, 'acx_xmp_persist_last_result', true );

			$details_by_media[ (string) $media_id ] = array(
				'id'             => $media_id,
				'mimeType'       => get_post_mime_type( $media_id ),
				'updatedAt'      => get_post_modified_time( 'c', true, $media_id ),
				'dimensions'     => array(
					'width'  => is_array( $meta ) && isset( $meta['width'] ) ? (int) $meta['width'] : null,
					'height' => is_array( $meta ) && isset( $meta['height'] ) ? (int) $meta['height'] : null,
				),
				'xmpPersistence' => is_array( $xmp_persist ) ? $xmp_persist : null,
			);
		}

		return new WP_REST_Response(
			array(
				'details_by_media' => $details_by_media,
			),
			200
		);
	}

	/**
	 * @return array<int>
	 */
	private function resolve_media_ids( WP_REST_Request $request ): array {
		$raw_ids = $request->get_param( 'ids' );
		if ( ! is_array( $raw_ids ) ) {
			$raw_ids = $request->get_param( 'ids[]' );
		}

		if ( is_string( $raw_ids ) ) {
			$raw_ids = explode( ',', $raw_ids );
		}

		if ( ! is_array( $raw_ids ) ) {
			return array();
		}

		return array_values(
			array_filter(
				array_map( 'absint', $raw_ids ),
				static fn ( int $value ): bool => $value > 0
			)
		);
	}
}