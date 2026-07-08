<?php

declare(strict_types=1);

namespace AltContext\Api;

require_once __DIR__ . '/interface-recognition-route-controller.php';
require_once __DIR__ . '/class-abstract-recognition-proxy-controller.php';
require_once __DIR__ . '/interface-describe-host.php';
require_once __DIR__ . '/services/class-description-candidate-service.php';
require_once __DIR__ . '/services/class-describe-media-service.php';
require_once __DIR__ . '/services/class-description-history-service.php';

use AltContext\Api\Services\DescriptionCandidateService;
use AltContext\Api\Services\DescriptionHistoryService;
use AltContext\Api\Services\DescribeMediaService;
use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

use function absint;
use function array_map;
use function array_values;
use function count;
use function is_array;
use function register_rest_route;
use function sanitize_text_field;
use function sprintf;

/**
 * E19-1 S6: WordPress `POST /acx/v1/recognition/describe`. A single-image
 * describe proxy that reuses the recognition auth/multipart/circuit transport
 * but targets the new backend `/scene/describe/multipart` route. Separate from
 * the wire-locked `/recognition/analyze` surface (PDS-26).
 */
class DescribeController extends AbstractRecognitionProxyController implements DescribeHostInterface {
	private const DESCRIBE_RUN_STREAM_MAX_HOLD_SECONDS = 25;

	private DescribeMediaService $describe_media_service;
	private DescriptionCandidateService $description_candidate_service;
	private DescriptionHistoryService $description_history_service;

	public function __construct( ?DescribeMediaService $describe_media_service = null, ?DescriptionCandidateService $description_candidate_service = null, ?DescriptionHistoryService $description_history_service = null ) {
		$this->describe_media_service = $describe_media_service ?? new DescribeMediaService( $this );
		$this->description_candidate_service = $description_candidate_service ?? new DescriptionCandidateService();
		$this->description_history_service = $description_history_service ?? new DescriptionHistoryService();
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
		register_rest_route(
			'acx/v1',
			'/recognition/describe/candidates',
			array(
				'methods'             => 'GET',
				'callback'            => array( $this, 'list_description_candidates' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
				'args'                => array(
					'limit'  => array(
						'type'        => 'integer',
						'required'    => false,
						'default'     => 50,
						'description' => 'Maximum candidate rows to return.',
					),
					'offset' => array(
						'type'        => 'integer',
						'required'    => false,
						'default'     => 0,
						'description' => 'Candidate offset after filtering.',
					),
				),
			)
		);

		register_rest_route(
			'acx/v1',
			'/recognition/describe/history',
			array(
				'methods'             => 'GET',
				'callback'            => array( $this, 'get_description_history' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
				'args'                => array(
					'limit' => array(
						'type'        => 'integer',
						'default'     => 50,
						'description' => 'Maximum number of description history rows to return.',
					),
					'offset' => array(
						'type'        => 'integer',
						'default'     => 0,
						'description' => 'Description history row offset.',
					),
				),
			)
		);

		register_rest_route(
			'acx/v1',
			'/recognition/describe/history/(?P<media_id>\d+)/correction',
			array(
				'methods'             => 'POST',
				'callback'            => array( $this, 'correct_description_history_item' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
				'args'                => array(
					'media_id' => array(
						'type'        => 'integer',
						'required'    => true,
						'description' => 'Attachment id to correct.',
					),
					'alt_text' => array(
						'type'        => 'string',
						'required'    => true,
						'description' => 'Human-corrected alt text.',
					),
				),
			)
		);

		register_rest_route(
			'acx/v1',
			'/recognition/describe/runs',
			array(
				'methods'             => 'POST',
				'callback'            => array( $this, 'submit_describe_run' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
				'args'                => array(
					'media_ids' => array(
						'type'        => 'array',
						'required'    => true,
						'items'       => array( 'type' => 'integer' ),
						'description' => 'Attachment ids to describe in bulk.',
					),
				),
			)
		);

		register_rest_route(
			'acx/v1',
			'/recognition/describe/runs/(?P<run_id>[a-f0-9-]+)',
			array(
				'methods'             => 'GET',
				'callback'            => array( $this, 'get_describe_run_status' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
			)
		);

		register_rest_route(
			'acx/v1',
			'/recognition/describe/runs/(?P<run_id>[a-f0-9-]+)/cancel',
			array(
				'methods'             => 'POST',
				'callback'            => array( $this, 'cancel_describe_run' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
			)
		);

		register_rest_route(
			'acx/v1',
			'/recognition/describe/runs/(?P<run_id>[a-f0-9-]+)/stream',
			array(
				'methods'             => 'GET',
				'callback'            => array( $this, 'stream_describe_run_progress' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
			)
		);
	}

	public function describe_media( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->describe_media_service->describe_media( $request );
	}

	public function list_description_candidates( WP_REST_Request $request ): WP_REST_Response {
		return new WP_REST_Response(
			$this->description_candidate_service->list_missing_alt_candidates(
				(int) $request->get_param( 'limit' ),
				(int) $request->get_param( 'offset' )
			),
			200
		);
	}

	public function get_description_history( WP_REST_Request $request ): WP_REST_Response {
		return new WP_REST_Response(
			$this->description_history_service->list_history(
				absint( $request->get_param( 'limit' ) ?? 50 ),
				absint( $request->get_param( 'offset' ) ?? 0 )
			)
		);
	}

	public function correct_description_history_item( WP_REST_Request $request ): WP_REST_Response {
		return new WP_REST_Response(
			$this->description_history_service->record_correction(
				absint( $request->get_param( 'media_id' ) ),
				(string) $request->get_param( 'alt_text' )
			)
		);
	}

	public function submit_describe_run( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$media_ids = $this->normalize_media_ids( $request->get_param( 'media_ids' ) );
		if ( array() === $media_ids ) {
			return new WP_Error( 'missing_media_ids', 'Please provide one or more media IDs to describe.', array( 'status' => 400 ) );
		}

		return $this->proxy_recognition_request(
			'POST',
			'/scene/describe/run',
			array(
				'tenant_id'  => $this->get_tenant_id(),
				'media_ids' => $media_ids,
			)
		);
	}

	public function get_describe_run_status( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$run_id = $this->normalize_run_id( $request );
		if ( '' === $run_id ) {
			return new WP_Error( 'missing_run_id', 'Run ID is required.', array( 'status' => 400 ) );
		}

		return $this->proxy_recognition_request(
			'GET',
			sprintf( '/scene/describe/run/%s', $run_id ),
			array(),
			array( 'tenant_id' => $this->get_tenant_id() )
		);
	}

	public function cancel_describe_run( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$run_id = $this->normalize_run_id( $request );
		if ( '' === $run_id ) {
			return new WP_Error( 'missing_run_id', 'Run ID is required.', array( 'status' => 400 ) );
		}

		return $this->proxy_recognition_request(
			'DELETE',
			sprintf( '/scene/describe/run/%s', $run_id ),
			array(),
			array( 'tenant_id' => $this->get_tenant_id() )
		);
	}

	public function stream_describe_run_progress( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$run_id = $this->normalize_run_id( $request );
		if ( '' === $run_id ) {
			return new WP_Error( 'missing_run_id', 'Run ID is required.', array( 'status' => 400 ) );
		}

		return $this->proxy_recognition_request(
			'GET',
			sprintf( '/scene/describe/run/%s/stream', $run_id ),
			array(),
			array(
				'tenant_id'        => $this->get_tenant_id(),
				'max_hold_seconds' => self::DESCRIBE_RUN_STREAM_MAX_HOLD_SECONDS,
			)
		);
	}

	public function get_describe_run_stream_max_hold_seconds(): int {
		return self::DESCRIBE_RUN_STREAM_MAX_HOLD_SECONDS;
	}

	/**
	 * @return int[]
	 */
	private function normalize_media_ids( mixed $value ): array {
		if ( ! is_array( $value ) ) {
			return array();
		}

		$media_ids = array_values(
			array_filter(
				array_map( 'absint', $value ),
				static fn (int $media_id): bool => $media_id > 0
			)
		);

		return count( $media_ids ) > 200 ? array_slice( $media_ids, 0, 200 ) : $media_ids;
	}

	private function normalize_run_id( WP_REST_Request $request ): string {
		return sanitize_text_field( (string) $request->get_param( 'run_id' ) );
	}
}
