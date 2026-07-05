<?php

declare(strict_types=1);

namespace AltContext\Api;

require_once __DIR__ . '/interface-recognition-route-controller.php';
require_once __DIR__ . '/class-abstract-recognition-proxy-controller.php';
require_once __DIR__ . '/interface-describe-host.php';
require_once __DIR__ . '/services/class-describe-media-service.php';

use AltContext\Api\Services\DescribeMediaService;
use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

use function register_rest_route;

/**
 * E19-1 S6: WordPress `POST /acx/v1/recognition/describe`. A single-image
 * describe proxy that reuses the recognition auth/multipart/circuit transport
 * but targets the new backend `/scene/describe/multipart` route. Separate from
 * the wire-locked `/recognition/analyze` surface (PDS-26).
 */
class DescribeController extends AbstractRecognitionProxyController implements DescribeHostInterface {
	private DescribeMediaService $describe_media_service;

	public function __construct( ?DescribeMediaService $describe_media_service = null ) {
		$this->describe_media_service = $describe_media_service ?? new DescribeMediaService( $this );
	}

	public function get_tenant_id(): string {
		return parent::get_tenant_id();
	}

	/**
	 * @param array<string,mixed> $body
	 * @param array<string,mixed> $query
	 */
	public function proxy_recognition_request(
		string $method,
		string $path,
		array $body = array(),
		array $query = array(),
		string $request_class = 'auto',
		string $body_kind = 'json',
		?int $max_body_bytes = null
	): WP_REST_Response|WP_Error {
		return $this->proxy_request( $method, $path, $body, $query, $request_class, $body_kind, $max_body_bytes );
	}

	public function is_proxy_unavailable( WP_REST_Response|WP_Error $response ): bool {
		return parent::is_proxy_unavailable( $response );
	}

	public function register_routes(): void {
		register_rest_route(
			'acx/v1',
			'/recognition/describe',
			array(
				'methods'             => 'POST',
				'callback'            => array( $this, 'describe_media' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
				'args'                => array(
					'media_id' => array(
						'type'        => 'integer',
						'required'    => true,
						'description' => 'Attachment id to describe (single image).',
					),
					'write_alt' => array(
						'type'        => 'boolean',
						'required'    => false,
						'default'     => false,
						'description' => 'Persist the generated alt text to the attachment when policy allows.',
					),
					'force'     => array(
						'type'        => 'boolean',
						'required'    => false,
						'default'     => false,
						'description' => 'Overwrite existing attachment alt text when write_alt is true.',
					),
				),
			)
		);
	}

	public function describe_media( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->describe_media_service->describe_media( $request );
	}
}
