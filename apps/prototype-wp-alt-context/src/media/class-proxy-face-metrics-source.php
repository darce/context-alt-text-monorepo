<?php

declare(strict_types=1);

namespace AltContext\Media;

require_once __DIR__ . '/interface-face-metrics-source.php';

use AltContext\Api\MediaIdentitiesController;
use WP_REST_Request;
use WP_REST_Response;

use function absint;
use function array_filter;
use function array_map;
use function array_values;
use function is_array;

class ProxyFaceMetricsSource implements FaceMetricsSourceInterface {
	private MediaIdentitiesController $mediaIdentitiesController;

	public function __construct( ?MediaIdentitiesController $media_identities_controller = null ) {
		$this->mediaIdentitiesController = $media_identities_controller ?? new MediaIdentitiesController();
	}

	/**
	 * @return array<int,array<string,mixed>>
	 */
	public function get_identities_for_attachment( int $attachment_id ): array {
		if ( $attachment_id <= 0 ) {
			return array();
		}

		$request = new WP_REST_Request( 'GET', '/acx/v1/recognition/media-identities' );
		$request->set_param( 'media_ids', array( $attachment_id ) );
		$request->set_param( 'include_debug', 'true' );

		$response = $this->mediaIdentitiesController->get_media_identities( $request );
		if ( ! ( $response instanceof WP_REST_Response ) || 200 !== $response->get_status() ) {
			return array();
		}

		$data = $response->get_data();
		if ( ! is_array( $data ) || ! is_array( $data['identities_by_media'] ?? null ) ) {
			return array();
		}

		$identities = $data['identities_by_media'][ (string) $attachment_id ] ?? array();
		if ( ! is_array( $identities ) ) {
			return array();
		}

		return array_values(
			array_filter(
				array_map(
					static function ( $identity ): array {
						return is_array( $identity ) ? $identity : array();
					},
					$identities
				),
				static function ( array $identity ): bool {
					$media_id = absint( $identity['media_id'] ?? 0 );
					return $media_id > 0;
				}
			)
		);
	}
}
