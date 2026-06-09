<?php

declare(strict_types=1);

namespace AltContext\Api;

require_once __DIR__ . '/interface-analysis-jobs-host.php';
require_once __DIR__ . '/services/class-batch-run-service.php';
require_once __DIR__ . '/services/class-projection-sync-service.php';
require_once __DIR__ . '/services/class-job-status-service.php';
require_once __DIR__ . '/services/class-job-progress-stream-service.php';
require_once __DIR__ . '/../sovereign/repositories/interface-sync-state-repository.php';
require_once __DIR__ . '/../sovereign/repositories/class-batch-run-repository.php';
require_once __DIR__ . '/../sovereign/repositories/class-sync-state-repository.php';
require_once __DIR__ . '/../sovereign/repositories/class-clusters-repository.php';
require_once __DIR__ . '/../sovereign/repositories/class-identity-members-repository.php';
require_once __DIR__ . '/../sovereign/sync/interface-snapshot-projector.php';
require_once __DIR__ . '/../sovereign/sync/class-snapshot-client.php';
require_once __DIR__ . '/../sovereign/sync/class-snapshot-projector.php';
require_once __DIR__ . '/../sovereign/sync/interface-sync-pull-job.php';
require_once __DIR__ . '/../sovereign/sync/class-sync-pull-job.php';
require_once __DIR__ . '/../sovereign/sync/class-sync-pull-result.php';
require_once __DIR__ . '/../sovereign/sync/class-sync-pull-job-factory.php';

use AltContext\Api\Services\BatchRunService;
use AltContext\Api\Services\JobProgressStreamService;
use AltContext\Api\Services\JobStatusService;
use AltContext\Api\Services\ProjectionSyncService;
use AltContext\Sovereign\Repositories\BatchRunRepository;
use AltContext\Sovereign\Repositories\SyncStateRepository;
use AltContext\Sovereign\Repositories\SyncStateRepositoryInterface;
use AltContext\Sovereign\Sync\SyncPullJobFactory;
use AltContext\Sovereign\Sync\SyncPullJobInterface;
use AltContext\Support\BatchLimits;
use AltContext\Support\Telemetry;
use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

use function absint;
use function get_current_user_id;
use function get_site_url;
use function get_transient;
use function gmdate;
use function in_array;
use function is_array;
use function is_wp_error;
use function md5;
use function nocache_headers;
use function sanitize_text_field;
use function set_transient;
use function sprintf;
use function trim;
use function wp_get_attachment_url;
use function wp_json_encode;

class AnalysisJobsController extends AbstractRecognitionProxyController implements AnalysisJobsHostInterface {
	use BatchLimits {
		get_current_tier_batch_limit as protected resolve_current_tier_batch_limit;
	}

	private const REQUEST_CLASS_POST_SCAN_READ = 'post_scan_read';
	private const JOB_MEDIA_IDS_TRANSIENT_PREFIX = 'acx_job_media_ids_';
	private const JOB_TRACKING_TTL_SECONDS = 86400;
	private BatchRunService $batch_run_service;
	private ProjectionSyncService $projection_sync_service;
	private JobStatusService $job_status_service;
	private JobProgressStreamService $job_progress_stream_service;

	public function __construct(
		?SyncStateRepositoryInterface $sync_state_repository = null,
		?SyncPullJobInterface $sync_pull_job = null,
		?SyncPullJobFactory $sync_pull_job_factory = null,
		?BatchRunRepository $batch_run_repository = null,
		?BatchRunService $batch_run_service = null,
		?ProjectionSyncService $projection_sync_service = null,
		?JobStatusService $job_status_service = null,
		?JobProgressStreamService $job_progress_stream_service = null
	) {
		$sync_state_repository = $sync_state_repository ?? new SyncStateRepository();
		$this->batch_run_service = $batch_run_service ?? new BatchRunService( $this, $batch_run_repository );
		$this->projection_sync_service = $projection_sync_service ?? new ProjectionSyncService(
			$this,
			$sync_state_repository,
			$sync_pull_job,
			$sync_pull_job_factory
		);
		$this->job_status_service = $job_status_service ?? new JobStatusService(
			$this,
			$this->batch_run_service,
			$this->projection_sync_service
		);
		$this->batch_run_service->wire_job_status_service( $this->job_status_service );
		$this->job_progress_stream_service = $job_progress_stream_service ?? new JobProgressStreamService(
			$this,
			$this->job_status_service,
			$this->batch_run_service,
			$this->projection_sync_service
		);
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
		string $body_kind = 'json'
	): WP_REST_Response|WP_Error {
		return $this->proxy_request( $method, $path, $body, $query, $request_class, $body_kind );
	}

	public function is_proxy_unavailable( WP_REST_Response|WP_Error $response ): bool {
		return parent::is_proxy_unavailable( $response );
	}

	public function get_retry_after_seconds( WP_REST_Response|WP_Error $response ): ?int {
		return parent::get_retry_after_seconds( $response );
	}

	public function backend_overloaded_response( WP_REST_Response|WP_Error $response ): WP_REST_Response {
		return parent::backend_overloaded_response( $response );
	}

	/**
	 * @param object $sync_state_repository
	 */
	public function should_use_local_projection_gate( $sync_state_repository, string $tenant_id ): bool {
		return parent::should_use_local_projection_gate( $sync_state_repository, $tenant_id );
	}

	public function get_proxy_policy(): RecognitionProxyPolicy {
		return parent::get_proxy_policy();
	}

	public function get_recognition_base_url(): string {
		return parent::get_recognition_base_url();
	}

	public function get_recognition_source(): string {
		return parent::get_recognition_source();
	}

	public function get_recognition_api_key(): string {
		return parent::get_recognition_api_key();
	}

	public function get_current_tier_batch_limit(): int {
		return $this->resolve_current_tier_batch_limit();
	}

	public function register_routes(): void {
		register_rest_route(
			'acx/v1',
			'/recognition/analyze',
			array(
				'methods'             => 'POST',
				'callback'            => array( $this, 'analyze_media' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
				'args'                => array(
					'media_ids'   => array(
						'type'              => 'array',
						'required'          => false,
						'items'             => array( 'type' => 'integer' ),
						'description'       => 'Array of attachment IDs to analyze.',
						'validate_callback' => array( $this, 'validate_media_ids' ),
					),
					'media_items' => array(
						'type'        => 'array',
						'required'    => false,
						'description' => 'Media item descriptors (media_id + media_url).',
					),
				),
			)
		);

		register_rest_route(
			'acx/v1',
			'/recognition/batch-runs',
			array(
				'methods'             => 'GET',
				'callback'            => array( $this, 'get_recent_batch_runs' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
			)
		);

		register_rest_route(
			'acx/v1',
			'/recognition/batch-runs/(?P<run_id>[a-f0-9-]+)',
			array(
				'methods'             => 'GET',
				'callback'            => array( $this, 'get_batch_run_status' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
			)
		);

		register_rest_route(
			'acx/v1',
			'/recognition/batch-runs/(?P<run_id>[a-f0-9-]+)/client-failures',
			array(
				'methods'             => 'POST',
				'callback'            => array( $this, 'record_client_batch_failure' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
			)
		);

		register_rest_route(
			'acx/v1',
			'/recognition/jobs/(?P<job_id>[a-f0-9-]+)',
			array(
				'methods'             => 'GET',
				'callback'            => array( $this, 'get_job_status' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
			)
		);

		register_rest_route(
			'acx/v1',
			'/recognition/jobs/(?P<job_id>[a-f0-9-]+)/stream',
			array(
				'methods'             => 'GET',
				'callback'            => array( $this, 'stream_job_progress' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
			)
		);

		register_rest_route(
			'acx/v1',
			'/recognition/jobs/(?P<job_id>[a-f0-9-]+)/cancel',
			array(
				'methods'             => 'POST',
				'callback'            => array( $this, 'cancel_job' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
			)
		);

		register_rest_route(
			'acx/v1',
			'/recognition/jobs/(?P<job_id>[a-f0-9-]+)/acknowledge-projection',
			array(
				'methods'             => 'POST',
				'callback'            => array( $this, 'acknowledge_projection' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
			)
		);
	}

	public function analyze_media( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$batch_context      = $this->batch_run_service->extract_batch_run_context( $request );
		$media_items_param = $request->get_param( 'media_items' );
		$media_ids         = $request->get_param( 'media_ids' );
		$media_items       = array();
		$requested_media_ids = $this->extract_requested_media_ids( $media_items_param, $media_ids );
		$unreadable_media_ids = array();

		// E15-11 Slice 2.2: 'multipart' (default) ships image bytes inline so
		// any WordPress install reaches the hosted recognition API without
		// publicly exposing its media library; 'url' keeps the legacy URL
		// path for managed-host installs whose media is publicly fetchable.
		$transport = (string) apply_filters( 'acx_recognition_transport', 'multipart' );
		if ( 'multipart' !== $transport && 'url' !== $transport ) {
			$transport = 'multipart';
		}
		// E15-11 Slice 3.2: log the resolved transport so operators can grep
		// for installs that fell back to URL transport unintentionally.
		Telemetry::log_line( sprintf( '[acx] acx_recognition_transport=%s', $transport ) );

		if ( is_array( $media_items_param ) && count( $media_items_param ) > 0 ) {
			$media_items = array_values(
				array_filter(
					array_map( array( $this, 'sanitize_media_item' ), $media_items_param ),
					static function ( array $item ): bool {
						return ! empty( $item['media_id'] ) && '' !== (string) $item['media_url'];
					}
				)
			);

			$max = $this->get_current_tier_batch_limit();
			if ( count( $media_items ) > $max ) {
				return new WP_Error(
					'too_many_media_items',
					sprintf( 'media_items supports at most %d items per request (received %d).', $max, count( $media_items ) ),
					array( 'status' => 400 )
				);
			}
		} elseif ( is_array( $media_ids ) && count( $media_ids ) > 0 ) {
			$validated = $this->validate_media_ids( $media_ids, $request, 'media_ids' );
			if ( is_wp_error( $validated ) ) {
				$this->batch_run_service->record_batch_run_failure( $batch_context, $requested_media_ids, $validated, array() );
				return $validated;
			}
			$media_items = $this->build_media_items( $media_ids );
		}

		$dispatched_media_ids = $this->extract_media_ids_from_analyze_payload( $media_items );
		$unreadable_media_ids = $this->diff_media_ids( $requested_media_ids, $dispatched_media_ids );

		if ( empty( $media_items ) ) {
			$error = new WP_Error( 'no_media_items', 'At least one media item is required', array( 'status' => 400 ) );
			$this->batch_run_service->record_batch_run_failure( $batch_context, $requested_media_ids, $error, $unreadable_media_ids );
			return $error;
		}

		if ( 'multipart' === $transport ) {
			$multipart_result = $this->analyze_media_multipart( $media_items, $unreadable_media_ids );
			if ( is_wp_error( $multipart_result ) ) {
				$this->batch_run_service->record_batch_run_failure( $batch_context, $requested_media_ids, $multipart_result, $unreadable_media_ids );
				// E15-11 Slice 3.2: surface dispatch failures (cap exceeded,
				// no readable files, proxy misconfig) in server logs so an
				// operator can correlate a stuck WP scan with the underlying
				// transport rejection.
				Telemetry::log_line(
					sprintf(
						'[acx] multipart dispatch failed: %s %s',
						$multipart_result->get_error_code(),
						$multipart_result->get_error_message()
					)
				);
			} else {
				$this->batch_run_service->record_batch_run_success_from_response( $batch_context, $multipart_result, $media_items, $unreadable_media_ids );
			}
			return $multipart_result;
		}

		$payload = array(
			'tenant_id'   => $this->get_tenant_id(),
			'site_url'    => get_site_url(),
			'media_items' => $media_items,
			'user_id'     => get_current_user_id(),
		);

		$response = $this->proxy_request( 'POST', '/recognition/analyze', $payload );
		if ( $response instanceof WP_REST_Response ) {
			$data = $response->get_data();
			if ( is_array( $data ) ) {
				$this->store_job_media_ids( (string) ( $data['id'] ?? '' ), $this->extract_media_ids_from_analyze_payload( $media_items ) );
				$this->batch_run_service->record_batch_run_success( $batch_context, (string) ( $data['id'] ?? '' ), $this->extract_media_ids_from_analyze_payload( $media_items ), $unreadable_media_ids, $response );
			}
		} elseif ( is_wp_error( $response ) ) {
			$this->batch_run_service->record_batch_run_failure( $batch_context, $requested_media_ids, $response, $unreadable_media_ids );
		}

		return $response;
	}

	/**
	 * Read each media item's bytes via get_attached_file and dispatch them
	 * inline to /recognition/analyze/multipart through the body_kind=multipart
	 * proxy path (E15-11 Slice 2.2).
	 *
	 * Items whose attachment file is missing on disk are skipped with an
	 * error log entry rather than failing the whole batch — matches the
	 * existing build_media_items policy of dropping unresolvable rows.
	 *
	 * @param array<int,array<string,mixed>> $media_items
	 */
	/**
	 * E15-11 Slice 2.3: multipart batch caps.
	 *
	 * Per the scope intake (#2337) the multipart route is sized for small
	 * predictable batches: ~5 images per submission and ~25 MiB total.
	 * Tier-based batch limits (BatchLimits trait) still apply on top of
	 * these caps; the smaller of (tier_limit, MULTIPART_MAX_IMAGES) wins
	 * for the multipart path. The byte cap is enforced plugin-side so a
	 * caller fails before the network round-trip; the recognition
	 * service's UploadSizeLimitMiddleware enforces the same bound at the
	 * server boundary as defense-in-depth.
	 */
	private const MULTIPART_MAX_IMAGES = 5;
	private const MULTIPART_MAX_BYTES  = 25 * 1024 * 1024;

	private function analyze_media_multipart( array $media_items, array &$unreadable_media_ids = array() ): WP_REST_Response|WP_Error {
		$tier_limit          = $this->get_current_tier_batch_limit();
		$effective_max_count = min( $tier_limit, self::MULTIPART_MAX_IMAGES );
		if ( count( $media_items ) > $effective_max_count ) {
			return new WP_Error(
				'too_many_multipart_images',
				sprintf(
					'multipart upload supports at most %d images per request (received %d).',
					$effective_max_count,
					count( $media_items )
				),
				array( 'status' => 400 )
			);
		}

		$multipart_body = array(
			'request' => wp_json_encode(
				array(
					'tenant_id' => $this->get_tenant_id(),
					'site_url'  => get_site_url(),
					'user_id'   => get_current_user_id(),
				)
			),
		);

		$dispatched_items = array();
		$total_bytes      = 0;
		foreach ( $media_items as $item ) {
			$media_id = (int) ( $item['media_id'] ?? 0 );
			if ( $media_id <= 0 ) {
				continue;
			}
			$path = get_attached_file( $media_id, true );
			if ( ! is_string( $path ) || '' === $path || ! is_readable( $path ) ) {
				$unreadable_media_ids[] = $media_id;
				Telemetry::log_line( sprintf( '[acx] skipping media_id=%d for multipart upload: file not readable', $media_id ) );
				continue;
			}
			$bytes = @file_get_contents( $path );
			if ( false === $bytes || '' === $bytes ) {
				$unreadable_media_ids[] = $media_id;
				Telemetry::log_line( sprintf( '[acx] skipping media_id=%d for multipart upload: empty file', $media_id ) );
				continue;
			}

			$total_bytes += strlen( $bytes );
			if ( $total_bytes > self::MULTIPART_MAX_BYTES ) {
				return new WP_Error(
					'multipart_payload_too_large',
					sprintf(
						'multipart upload exceeds %d-byte cap (currently %d bytes after media_id=%d).',
						self::MULTIPART_MAX_BYTES,
						$total_bytes,
						$media_id
					),
					array( 'status' => 413 )
				);
			}

			$multipart_body[ 'image_' . $media_id ] = array(
				'filename'     => basename( $path ),
				'content'      => $bytes,
				'content_type' => $this->resolve_image_mime_type( $path, $media_id ),
			);
			$dispatched_items[] = $item;
		}

		if ( empty( $dispatched_items ) ) {
			return new WP_Error(
				'no_media_items',
				'No readable image files for any requested media_id; multipart upload aborted.',
				array( 'status' => 400 )
			);
		}

		$response = $this->proxy_request(
			'POST',
			'/recognition/analyze/multipart',
			$multipart_body,
			array(),
			'auto',
			'multipart',
			self::MULTIPART_MAX_BYTES
		);

		if ( $response instanceof WP_REST_Response ) {
			$data = $response->get_data();
			if ( is_array( $data ) ) {
				$this->store_job_media_ids(
					(string) ( $data['id'] ?? '' ),
					$this->extract_media_ids_from_analyze_payload( $dispatched_items )
				);
			}
		}

		return $response;
	}

	/**
	 * Best-effort MIME detection for an attachment file. Falls back to
	 * application/octet-stream if WordPress can't resolve it.
	 */
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

	public function get_job_status( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->job_status_service->get_job_status( $request );
	}

	public function get_recent_batch_runs( WP_REST_Request $request ): WP_REST_Response {
		return $this->batch_run_service->get_recent_batch_runs( $request );
	}

	public function get_batch_run_status( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->batch_run_service->get_batch_run_status( $request );
	}

	public function record_client_batch_failure( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->batch_run_service->record_client_batch_failure( $request );
	}

	public function stream_job_progress( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->job_progress_stream_service->stream_job_progress( $request );
	}

	public function cancel_job( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->job_status_service->cancel_job( $request );
	}

	public function acknowledge_projection( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->job_status_service->acknowledge_projection( $request );
	}

	/**
	 * @param mixed $media_items_param
	 * @param mixed $media_ids
	 * @return int[]
	 */
	private function extract_requested_media_ids( $media_items_param, $media_ids ): array {
		if ( is_array( $media_items_param ) ) {
			return array_values(
				array_filter(
					array_map(
						static function ( $item ): int {
							return absint( is_array( $item ) ? ( $item['media_id'] ?? 0 ) : 0 );
						},
						$media_items_param
					)
				)
			);
		}

		if ( is_array( $media_ids ) ) {
			return array_values(
				array_filter(
					array_map( 'absint', $media_ids )
				)
			);
		}

		return array();
	}

	/**
	 * @param int[] $left
	 * @param int[] $right
	 * @return int[]
	 */
	private function diff_media_ids( array $left, array $right ): array {
		$right_lookup = array_fill_keys( $right, true );
		return array_values(
			array_filter(
				$left,
				static function ( int $media_id ) use ( $right_lookup ): bool {
					return ! isset( $right_lookup[ $media_id ] );
				}
			)
		);
	}

	public function validate_media_ids( $value, WP_REST_Request $request, string $param ): bool|WP_Error {
		if ( ! is_array( $value ) ) {
			return new WP_Error( 'invalid_media_ids', 'media_ids must be an array of attachment IDs.', array( 'status' => 400 ) );
		}

		$count = count( $value );
		if ( 0 === $count ) {
			return new WP_Error( 'missing_media_ids', 'Please provide one or more media IDs to analyze.', array( 'status' => 400 ) );
		}

		$max = $this->get_current_tier_batch_limit();
		if ( $count > $max ) {
			return new WP_Error(
				'too_many_media_ids',
				sprintf( 'media_ids supports at most %d items per request (received %d).', $max, $count ),
				array( 'status' => 400 )
			);
		}

		return true;
	}

	/**
	 * @param int[] $media_ids
	 * @return array<int,array<string,mixed>>
	 */
	private function build_media_items( array $media_ids ): array {
		$items = array();

		foreach ( $media_ids as $media_id ) {
			$id = absint( $media_id );
			if ( $id <= 0 ) {
				continue;
			}

			$url = wp_get_attachment_url( $id );
			if ( ! $url ) {
				continue;
			}

			$items[] = array(
				'media_id'  => $id,
				'media_url' => esc_url_raw( $url ),
			);
		}

		return $items;
	}

	/**
	 * @param array<string,mixed> $media_item
	 * @return array<string,mixed>
	 */
	private function sanitize_media_item( array $media_item ): array {
		return array(
			'media_id'  => absint( $media_item['media_id'] ?? 0 ),
			'media_url' => esc_url_raw( (string) ( $media_item['media_url'] ?? '' ) ),
		);
	}

	/**
	 * @param array<int,array<string,mixed>> $media_items
	 * @return int[]
	 */
	private function extract_media_ids_from_analyze_payload( array $media_items ): array {
		$media_ids = array();

		foreach ( $media_items as $media_item ) {
			$media_id = absint( $media_item['media_id'] ?? 0 );
			if ( $media_id > 0 ) {
				$media_ids[] = $media_id;
			}
		}

		return array_values( array_unique( $media_ids ) );
	}

	/**
	 * @param int[] $media_ids
	 */
	private function store_job_media_ids( string $job_id, array $media_ids ): void {
		if ( '' === $job_id || empty( $media_ids ) ) {
			return;
		}

		set_transient( $this->job_media_ids_transient_key( $job_id ), $media_ids, self::JOB_TRACKING_TTL_SECONDS );
	}

	private function job_media_ids_transient_key( string $job_id ): string {
		return self::JOB_MEDIA_IDS_TRANSIENT_PREFIX . $job_id;
	}
}
