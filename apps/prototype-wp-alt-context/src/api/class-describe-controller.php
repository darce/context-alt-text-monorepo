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
use function array_filter;
use function array_map;
use function array_values;
use function basename;
use function count;
use function file_get_contents;
use function get_attached_file;
use function is_array;
use function is_readable;
use function is_string;
use function is_wp_error;
use function pathinfo;
use function register_rest_route;
use function sanitize_text_field;
use function sprintf;
use function strtolower;
use function wp_check_filetype;
use function wp_json_encode;

use const PATHINFO_EXTENSION;

/**
 * E19-1 S6: WordPress `POST /acx/v1/recognition/describe`. A single-image
 * describe proxy that reuses the recognition auth/multipart/circuit transport
 * but targets the new backend `/scene/describe/multipart` route. Separate from
 * the wire-locked `/recognition/analyze` surface (PDS-26).
 */
class DescribeController extends AbstractRecognitionProxyController implements DescribeHostInterface {
	private const DESCRIBE_RUN_STREAM_MAX_HOLD_SECONDS = 25;
	private const DESCRIBE_RUN_MAX_MEDIA_IDS = 200;

	/**
	 * Overall serialized multipart body cap for a bulk describe run. The backend
	 * `/scene/describe/run` route is not behind the single-image
	 * UploadSizeLimitMiddleware, so bound the aggregate raw-bytes payload here to
	 * protect proxy memory (200 images × raw bytes + framing).
	 */
	private const DESCRIBE_RUN_MULTIPART_MAX_BYTES = 200 * 1024 * 1024;

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
		if ( is_wp_error( $media_ids ) ) {
			return $media_ids;
		}
		if ( array() === $media_ids ) {
			return new WP_Error( 'missing_media_ids', 'Please provide one or more media IDs to describe.', array( 'status' => 400 ) );
		}

		// The browser→WP contract is JSON { media_ids: int[] } — the browser has
		// no image bytes. WP loads each attachment's bytes and forwards a
		// multipart/form-data body to the backend: field `tenant_id`, field
		// `media_ids` (JSON int array as string), and one `image_<media_id>` file
		// part per id. The backend 422s if any media_id lacks an image part, so a
		// file we cannot read fails the whole run fast (400 naming the id) instead
		// of silently dropping it.
		$multipart_body = array(
			'tenant_id' => $this->get_tenant_id(),
			'media_ids' => wp_json_encode( array_values( $media_ids ) ),
		);

		foreach ( $media_ids as $media_id ) {
			$file_part = $this->load_media_file_part( $media_id );
			if ( is_wp_error( $file_part ) ) {
				return $file_part;
			}
			$multipart_body[ 'image_' . $media_id ] = $file_part;
		}

		return $this->proxy_recognition_request(
			'POST',
			'/scene/describe/run',
			$multipart_body,
			array(),
			'description',
			'multipart',
			self::DESCRIBE_RUN_MULTIPART_MAX_BYTES
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

		// The stream endpoint holds the connection open server-side for up to
		// DESCRIBE_RUN_STREAM_MAX_HOLD_SECONDS (SSE). The default 'auto'+GET class
		// resolves to `ui_read` (2s timeout + circuit breaker), which would time
		// out the hold and trip the shared recognition breaker. `background_sync`
		// (30s timeout, no breaker) tolerates the 25s hold. (S5-01)
		return $this->proxy_recognition_request(
			'GET',
			sprintf( '/scene/describe/run/%s/stream', $run_id ),
			array(),
			array(
				'tenant_id'        => $this->get_tenant_id(),
				'max_hold_seconds' => self::DESCRIBE_RUN_STREAM_MAX_HOLD_SECONDS,
			),
			'background_sync'
		);
	}

	public function get_describe_run_stream_max_hold_seconds(): int {
		return self::DESCRIBE_RUN_STREAM_MAX_HOLD_SECONDS;
	}

	/**
	 * Normalize the requested media IDs. Non-positive ids are filtered out. More
	 * than DESCRIBE_RUN_MAX_MEDIA_IDS valid ids returns a WP_Error rather than
	 * silently truncating the run to the first 200 — a silent slice would drop
	 * work the caller believes it queued. (S5-02)
	 *
	 * @return int[]|WP_Error
	 */
	private function normalize_media_ids( mixed $value ): array|WP_Error {
		if ( ! is_array( $value ) ) {
			return array();
		}

		$media_ids = array_values(
			array_filter(
				array_map( 'absint', $value ),
				static fn (int $media_id): bool => $media_id > 0
			)
		);

		if ( count( $media_ids ) > self::DESCRIBE_RUN_MAX_MEDIA_IDS ) {
			return new WP_Error(
				'too_many_media_ids',
				sprintf( 'Please describe at most %d media IDs per run.', self::DESCRIBE_RUN_MAX_MEDIA_IDS ),
				array( 'status' => 400 )
			);
		}

		return $media_ids;
	}

	/**
	 * Load a single attachment's bytes as a multipart file part for the bulk run
	 * body. Returns a WP_Error (400) naming the failing media_id when the file is
	 * missing, unreadable, or empty — the backend would otherwise 422 the whole
	 * run for a missing `image_<media_id>` part.
	 *
	 * @return array{filename:string,content:string,content_type:string}|WP_Error
	 */
	private function load_media_file_part( int $media_id ): array|WP_Error {
		$path = get_attached_file( $media_id, true );
		if ( ! is_string( $path ) || '' === $path || ! is_readable( $path ) ) {
			return new WP_Error(
				'describe_run_attachment_unreadable',
				sprintf( 'Attachment file for media_id=%d is missing or not readable.', $media_id ),
				array( 'status' => 400 )
			);
		}

		$bytes = @file_get_contents( $path );
		if ( false === $bytes || '' === $bytes ) {
			return new WP_Error(
				'describe_run_attachment_unreadable',
				sprintf( 'Attachment file for media_id=%d is empty or unreadable.', $media_id ),
				array( 'status' => 400 )
			);
		}

		return array(
			'filename'     => basename( $path ),
			'content'      => $bytes,
			'content_type' => $this->resolve_image_mime_type( $path, $media_id ),
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

	private function normalize_run_id( WP_REST_Request $request ): string {
		return sanitize_text_field( (string) $request->get_param( 'run_id' ) );
	}
}
