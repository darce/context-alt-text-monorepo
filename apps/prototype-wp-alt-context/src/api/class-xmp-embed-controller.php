<?php

declare(strict_types=1);

namespace AltContext\Api;

use AltContext\Media\AttachmentXmpMetricsPersistor;
use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

use function absint;
use function current_user_can;
use function is_array;
use function register_rest_route;
use function rest_ensure_response;

class XmpEmbedController {
	private AttachmentXmpMetricsPersistor $persistor;

	public function __construct( AttachmentXmpMetricsPersistor $persistor ) {
		$this->persistor = $persistor;
	}

	public function register_routes(): void {
		register_rest_route(
			'acx/v1',
			'/recognition/xmp/embed',
			array(
				'methods'             => 'POST',
				'callback'            => array( $this, 'embed_media' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
				'args'                => array(
					'media_ids' => array(
						'type'        => 'array',
						'required'    => true,
						'items'       => array( 'type' => 'integer' ),
						'description' => 'Attachment IDs to persist XMP metrics for.',
					),
				),
			)
		);
	}

	public function can_manage_recognition(): bool {
		return current_user_can( 'manage_options' );
	}

	public function embed_media( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$media_ids = $request->get_param( 'media_ids' );
		if ( ! is_array( $media_ids ) || empty( $media_ids ) ) {
			return new WP_Error( 'missing_media_ids', 'Provide one or more media_ids for XMP embedding.', array( 'status' => 400 ) );
		}

		$normalized_ids = array();
		foreach ( $media_ids as $media_id ) {
			$id = absint( $media_id );
			if ( $id > 0 ) {
				$normalized_ids[] = $id;
			}
		}

		if ( empty( $normalized_ids ) ) {
			return new WP_Error( 'invalid_media_ids', 'Provide one or more valid attachment IDs.', array( 'status' => 400 ) );
		}

		$result = $this->persistor->embed_for_media_ids( $normalized_ids );

		return rest_ensure_response( $result );
	}
}
