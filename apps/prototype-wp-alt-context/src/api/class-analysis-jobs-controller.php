<?php

declare(strict_types=1);

namespace AltContext\Api;

require_once __DIR__ . '/interface-analysis-jobs-host.php';
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

use AltContext\Sovereign\Repositories\BatchRunRepository;
use AltContext\Sovereign\Repositories\ClustersRepository;
use AltContext\Sovereign\Repositories\IdentityMembersRepository;
use AltContext\Sovereign\Repositories\SyncStateRepository;
use AltContext\Sovereign\Repositories\SyncStateRepositoryInterface;
use AltContext\Sovereign\Sync\SnapshotClient;
use AltContext\Sovereign\Sync\SyncPullJobFactory;
use AltContext\Sovereign\Sync\SyncPullJobInterface;
use AltContext\Support\BatchLimits;
use AltContext\Support\Telemetry;
use Throwable;
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
	private const BATCH_RUN_STATUS_STALE_SECONDS = 5;
	private const JOB_MEDIA_IDS_TRANSIENT_PREFIX = 'acx_job_media_ids_';
	private const JOB_BATCH_RUN_TRANSIENT_PREFIX = 'acx_job_batch_run_';
	private const PROJECTION_SYNC_TRANSIENT_PREFIX = 'acx_projection_sync_';
	private const JOB_TRACKING_TTL_SECONDS = 86400;
	private const PROJECTION_SYNC_SUCCESS_TTL_SECONDS = 300;
	private const PROJECTION_SYNC_RETRY_TTL_SECONDS = 5;
	private BatchRunRepository $batch_run_repository;
	private SyncStateRepositoryInterface $sync_state_repository;
	private ?SyncPullJobInterface $sync_pull_job;
	private ?SyncPullJobFactory $sync_pull_job_factory;

	public function __construct(
		?SyncStateRepositoryInterface $sync_state_repository = null,
		?SyncPullJobInterface $sync_pull_job = null,
		?SyncPullJobFactory $sync_pull_job_factory = null,
		?BatchRunRepository $batch_run_repository = null
	) {
		$this->sync_state_repository = $sync_state_repository ?? new SyncStateRepository();
		$this->sync_pull_job = $sync_pull_job;
		$this->sync_pull_job_factory = $sync_pull_job_factory;
		$this->batch_run_repository = $batch_run_repository ?? new BatchRunRepository();
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
		$batch_context      = $this->extract_batch_run_context( $request );
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
				$this->record_batch_run_failure( $batch_context, $requested_media_ids, $validated, array() );
				return $validated;
			}
			$media_items = $this->build_media_items( $media_ids );
		}

		$dispatched_media_ids = $this->extract_media_ids_from_analyze_payload( $media_items );
		$unreadable_media_ids = $this->diff_media_ids( $requested_media_ids, $dispatched_media_ids );

		if ( empty( $media_items ) ) {
			$error = new WP_Error( 'no_media_items', 'At least one media item is required', array( 'status' => 400 ) );
			$this->record_batch_run_failure( $batch_context, $requested_media_ids, $error, $unreadable_media_ids );
			return $error;
		}

		if ( 'multipart' === $transport ) {
			$multipart_result = $this->analyze_media_multipart( $media_items, $unreadable_media_ids );
			if ( is_wp_error( $multipart_result ) ) {
				$this->record_batch_run_failure( $batch_context, $requested_media_ids, $multipart_result, $unreadable_media_ids );
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
				$this->record_batch_run_success_from_response( $batch_context, $multipart_result, $media_items, $unreadable_media_ids );
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
				$this->record_batch_run_success( $batch_context, (string) ( $data['id'] ?? '' ), $this->extract_media_ids_from_analyze_payload( $media_items ), $unreadable_media_ids, $response );
			}
		} elseif ( is_wp_error( $response ) ) {
			$this->record_batch_run_failure( $batch_context, $requested_media_ids, $response, $unreadable_media_ids );
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
		$job_id = sanitize_text_field( (string) $request->get_param( 'job_id' ) );
		if ( '' === $job_id ) {
			return new WP_Error( 'missing_job_id', 'Job ID is required.', array( 'status' => 400 ) );
		}

		$response = $this->proxy_request(
			'GET',
			sprintf( '/recognition/jobs/%s', $job_id ),
			array(),
			array(
				'tenant_id' => $this->get_tenant_id(),
			),
			self::REQUEST_CLASS_POST_SCAN_READ
		);
		if ( $this->is_proxy_unavailable( $response ) ) {
			return $this->build_offline_job_status_response( $job_id );
		}

		if ( $response instanceof WP_REST_Response ) {
			$this->record_observed_job_status_from_response( $job_id, $response );
			$data = $response->get_data();
			if ( is_array( $data ) ) {
				$batch_run_id = $this->lookup_batch_run_id_for_job( $job_id );
				if ( '' !== $batch_run_id ) {
					$data['batch_run_id'] = $batch_run_id;
					$response->set_data( $data );
				}
				$this->maybe_trigger_projection_sync( $data );
			}
		}

		return $response;
	}

	private function record_observed_job_status_from_response( string $job_id, WP_REST_Response $response ): void {
		$data   = $response->get_data();
		$status = '';
		if ( is_array( $data ) ) {
			$status = sanitize_text_field( (string) ( $data['status'] ?? '' ) );
		}

		if ( '' === $status && 404 === $response->get_status() ) {
			$status = 'failed';
		}

		if ( '' === $status ) {
			return;
		}

		$this->batch_run_repository->record_observed_job_status( $this->get_tenant_id(), $job_id, $status );
	}

	public function get_recent_batch_runs( WP_REST_Request $request ): WP_REST_Response {
		$limit = max( 1, min( 10, absint( $request->get_param( 'limit' ) ) ) );
		if ( 0 === absint( $request->get_param( 'limit' ) ) ) {
			$limit = 5;
		}

		return new WP_REST_Response(
			array(
				'items' => $this->batch_run_repository->list_recent_runs( $this->get_tenant_id(), $limit ),
			),
			200
		);
	}

	public function get_batch_run_status( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$run_id = sanitize_text_field( (string) $request->get_param( 'run_id' ) );
		if ( '' === $run_id ) {
			return new WP_Error( 'missing_run_id', 'Batch run ID is required.', array( 'status' => 400 ) );
		}

		$this->refresh_stale_batch_run_children( $run_id );
		$computed = $this->batch_run_repository->get_status( $this->get_tenant_id(), $run_id );
		if ( null === $computed ) {
			return new WP_Error( 'batch_run_not_found', 'Batch run not found.', array( 'status' => 404 ) );
		}

		return new WP_REST_Response( $computed, 200 );
	}

	public function record_client_batch_failure( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$run_id = sanitize_text_field( (string) $request->get_param( 'run_id' ) );
		if ( '' === $run_id ) {
			return new WP_Error( 'missing_run_id', 'Batch run ID is required.', array( 'status' => 400 ) );
		}

		$media_ids = $this->extract_requested_media_ids( null, $request->get_param( 'media_ids' ) );
		if ( array() === $media_ids ) {
			return new WP_Error( 'missing_media_ids', 'Media IDs are required.', array( 'status' => 400 ) );
		}

		$this->batch_run_repository->record_batch_failure(
			$this->get_tenant_id(),
			$run_id,
			max( 0, absint( $request->get_param( 'batch_index' ) ) ),
			max( count( $media_ids ), absint( $request->get_param( 'submitted_total' ) ) ),
			$media_ids,
			new WP_Error( 'client_transport_error', 'Client could not submit this batch to WordPress.' ),
			array()
		);

		return new WP_REST_Response(
			array(
				'batch_run_id' => $run_id,
				'status'       => 'recorded',
			),
			202
		);
	}

	public function stream_job_progress( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$job_id = sanitize_text_field( (string) $request->get_param( 'job_id' ) );
		if ( '' === $job_id ) {
			return new WP_Error( 'missing_job_id', 'Job ID is required.', array( 'status' => 400 ) );
		}

		if ( function_exists( 'set_time_limit' ) ) {
			@set_time_limit( 0 );
		}
		if ( function_exists( 'ignore_user_abort' ) ) {
			@ignore_user_abort( true );
		}

		$this->prepare_stream_output_buffers();

		$last_completed = -1;
		$last_emit      = 0.0;
		$last_heartbeat = microtime( true );
		$last_phase     = null;

		while ( ! connection_aborted() ) {
			$response = $this->proxy_request(
				'GET',
				sprintf( '/recognition/jobs/%s', $job_id ),
				array(),
				array(
					'tenant_id' => $this->get_tenant_id(),
				)
			);

			if ( is_wp_error( $response ) ) {
				echo "event: error\n";
				echo 'data: ' . wp_json_encode( array( 'message' => $response->get_error_message() ) ) . "\n\n";
				@ob_flush();
				@flush();
				break;
			}

			if ( ! ( $response instanceof WP_REST_Response ) ) {
				echo "event: error\n";
				echo 'data: ' . wp_json_encode( array( 'message' => 'Unexpected response type.' ) ) . "\n\n";
				@ob_flush();
				@flush();
				break;
			}

			$status_code = $response->get_status();
			if ( 404 === $status_code ) {
				$this->record_observed_job_status_from_response( $job_id, $response );
				echo "event: error\n";
				echo 'data: ' . wp_json_encode( array( 'message' => 'Job not found.' ) ) . "\n\n";
				@ob_flush();
				@flush();
				break;
			}

			$data = $response->get_data();
			if ( ! is_array( $data ) ) {
				echo "event: error\n";
				echo 'data: ' . wp_json_encode( array( 'message' => 'Invalid job response.' ) ) . "\n\n";
				@ob_flush();
				@flush();
				break;
			}
			$this->maybe_trigger_projection_sync( $data );

			$progress   = is_array( $data['progress'] ?? null ) ? $data['progress'] : array();
			$completed  = absint( $progress['completed'] ?? 0 );
			$total      = absint( $progress['total'] ?? 0 );
			$status     = isset( $data['status'] ) ? sanitize_text_field( (string) $data['status'] ) : 'pending';
			$this->batch_run_repository->record_observed_job_status( $this->get_tenant_id(), $job_id, $status );
			$phase      = isset( $progress['phase'] ) ? sanitize_text_field( (string) $progress['phase'] ) : null;
			$job_type   = isset( $data['type'] ) ? sanitize_text_field( (string) $data['type'] ) : 'analyze';
			$event_type = 'scan_progress';
			if ( 'clustering' === $job_type ) {
				$event_type = 'clustering_progress';
			}
			$now         = microtime( true );
			$should_emit = (
				$completed !== $last_completed
				|| $phase !== $last_phase
				|| ( $now - $last_emit > 0.5 && $completed > 0 )
				|| ( $now - $last_heartbeat > 15 )
			);

			if ( $should_emit ) {
				$payload = $this->build_stream_progress_payload( $progress, $job_id, $event_type, $status );
				echo "event: progress\n";
				echo 'data: ' . wp_json_encode( $payload ) . "\n\n";
				$last_completed = $completed;
				$last_emit      = $now;
				$last_heartbeat = $now;
				$last_phase     = $phase;
				@ob_flush();
				@flush();
			}

			if ( in_array( $status, array( 'completed', 'failed' ), true ) ) {
				$done_payload = $this->build_stream_progress_payload( $progress, $job_id, $event_type, $status );
				echo "event: done\n";
				echo 'data: ' . wp_json_encode( $done_payload ) . "\n\n";
				@ob_flush();
				@flush();
				break;
			}

			usleep( 100000 );
		}

		$this->terminate_job_progress_stream();
	}

	protected function prepare_stream_output_buffers(): void {
		nocache_headers();
		header( 'Content-Type: text/event-stream' );
		header( 'Cache-Control: no-cache' );
		header( 'X-Accel-Buffering: no' );

		while ( ob_get_level() > 0 ) {
			ob_end_flush();
		}
		@ini_set( 'output_buffering', 'off' );
		@ini_set( 'zlib.output_compression', '0' );
	}

	protected function terminate_job_progress_stream(): never {
		exit;
	}

	public function cancel_job( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$job_id = sanitize_text_field( (string) $request->get_param( 'job_id' ) );

		if ( '' === $job_id ) {
			return new WP_Error( 'missing_job_id', 'Job ID is required.', array( 'status' => 400 ) );
		}

		return $this->proxy_request(
			'POST',
			sprintf( '/recognition/jobs/%s/cancel', $job_id ),
			array(),
			array(
				'tenant_id' => $this->get_tenant_id(),
			)
		);
	}

	public function acknowledge_projection( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$job_id = sanitize_text_field( (string) $request->get_param( 'job_id' ) );

		if ( '' === $job_id ) {
			return new WP_Error( 'missing_job_id', 'Job ID is required.', array( 'status' => 400 ) );
		}

		$body = $request->get_json_params();
		$snapshot_version = absint( $body['snapshot_version'] ?? 0 );
		if ( $snapshot_version <= 0 ) {
			return new WP_Error( 'invalid_snapshot_version', 'A positive snapshot_version is required.', array( 'status' => 400 ) );
		}

		$payload = array(
			'snapshot_version' => $snapshot_version,
		);

		$snapshot_generation_id = sanitize_text_field( (string) ( $body['snapshot_generation_id'] ?? '' ) );
		if ( '' !== $snapshot_generation_id ) {
			$payload['snapshot_generation_id'] = $snapshot_generation_id;
		}

		return $this->proxy_request(
			'POST',
			sprintf( '/recognition/jobs/%s/acknowledge-projection', $job_id ),
			$payload
		);
	}

	/**
	 * Build the SSE event payload for a single stream poll result.
	 *
	 * Extracted so the field-forwarding logic can be unit-tested independently
	 * of the streaming loop and its side-effects (headers, output flushing).
	 *
	 * @param array<string,mixed> $progress  The `progress` sub-array from the backend job response.
	 * @param string              $job_id    The job being streamed.
	 * @param string              $event_type  'scan_progress' or 'clustering_progress'.
	 * @param string              $status    Current job status string.
	 * @return array<string,mixed>
	 */
	protected function build_stream_progress_payload(
		array $progress,
		string $job_id,
		string $event_type,
		string $status
	): array {
		$completed = absint( $progress['completed'] ?? 0 );
		$total     = absint( $progress['total'] ?? 0 );
		$phase     = isset( $progress['phase'] ) && '' !== $progress['phase']
			? sanitize_text_field( (string) $progress['phase'] )
			: null;

		$payload = array(
			'type'      => $event_type,
			'job_id'    => $job_id,
			'status'    => $status,
			'completed' => $completed,
			'total'     => $total,
		);
		if ( null !== $phase ) {
			$payload['phase'] = $phase;
		}
		if ( isset( $progress['images_processed'] ) ) {
			$payload['images_processed'] = absint( $progress['images_processed'] );
		}
		if ( isset( $progress['faces_found'] ) ) {
			$payload['faces_found'] = absint( $progress['faces_found'] );
		}
		if ( isset( $progress['clusters_created'] ) ) {
			$payload['clusters_created'] = absint( $progress['clusters_created'] );
		}
		// Phase-2 checkpoint/retry metadata (finding 1165).
		if ( isset( $progress['retry_count'] ) ) {
			$payload['retry_count'] = absint( $progress['retry_count'] );
		}
		if ( isset( $progress['current_stage'] ) && '' !== $progress['current_stage'] ) {
			$payload['current_stage'] = sanitize_text_field( (string) $progress['current_stage'] );
		}
		if ( isset( $progress['last_successful_processed_identities'] ) ) {
			$payload['last_successful_processed_identities'] = absint( $progress['last_successful_processed_identities'] );
		}
		if ( isset( $progress['last_error_code'] ) && '' !== $progress['last_error_code'] ) {
			$payload['last_error_code'] = sanitize_text_field( (string) $progress['last_error_code'] );
		}

		$batch_run_id = $this->lookup_batch_run_id_for_job( $job_id );
		if ( '' !== $batch_run_id ) {
			$payload['batch_run_id'] = $batch_run_id;
		}

		return $payload;
	}

	private function build_offline_job_status_response( string $job_id ): WP_REST_Response {
		$now = gmdate( 'c' );
		return new WP_REST_Response(
			array(
				'id'          => $job_id,
				'type'        => 'analyze',
				'status'      => 'failed',
				'progress'    => array(
					'completed' => 0,
					'total'     => 0,
				),
				'started_at'  => $now,
				'finished_at' => $now,
				'message'     => 'Recognition backend unavailable.',
			),
			200
		);
	}

	/**
	 * Trigger a local projection pull once the backend reports a completed clustering job
	 * whose results have not yet been acknowledged locally.
	 *
	 * @param array<string,mixed> $job_payload
	 */
	private function maybe_trigger_projection_sync( array $job_payload ): void {
		$status           = sanitize_text_field( (string) ( $job_payload['status'] ?? '' ) );
		$snapshot_version = absint( $job_payload['snapshot_version'] ?? 0 );
		$acknowledged_at  = trim( (string) ( $job_payload['projection_acknowledged_at'] ?? '' ) );
		$job_id           = $this->projection_sync_job_id( $job_payload );

		if ( 'completed' !== $status || $snapshot_version <= 0 || '' !== $acknowledged_at || '' === $job_id ) {
			return;
		}

		$transient_key = $this->projection_sync_transient_key( $job_id, $snapshot_version );
		if ( false !== get_transient( $transient_key ) ) {
			return;
		}

		$sync_pull_job = $this->resolve_sync_pull_job();
		if ( null === $sync_pull_job ) {
			return;
		}

		$projection_payload = $this->build_inline_projection_payload( $job_payload, $job_id, $snapshot_version );

		try {
			$result = is_array( $projection_payload )
				? $sync_pull_job->perform_projection_payload( $this->get_tenant_id(), $projection_payload )
				: $sync_pull_job->perform_bypass_cooldown( $this->get_tenant_id() );
			$ttl    = $result->is_success()
				? self::PROJECTION_SYNC_SUCCESS_TTL_SECONDS
				: self::PROJECTION_SYNC_RETRY_TTL_SECONDS;
			set_transient( $transient_key, 1, $ttl );
		} catch ( Throwable $throwable ) {
			set_transient( $transient_key, 1, self::PROJECTION_SYNC_RETRY_TTL_SECONDS );
			// Job status remains readable even when the background projection retry fails.
		}
	}

	private function projection_sync_job_id( array $job_payload ): string {
		$job_id = trim( (string) ( $job_payload['source_job_id'] ?? $job_payload['id'] ?? '' ) );
		return sanitize_text_field( $job_id );
	}

	/**
	 * @param array<string,mixed> $job_payload
	 * @return array<string,mixed>|null
	 */
	private function build_inline_projection_payload( array $job_payload, string $job_id, int $snapshot_version ): ?array {
		$projection_payload = $job_payload['projection_payload'] ?? null;
		if ( ! is_array( $projection_payload ) ) {
			return null;
		}

		$payload_snapshot_version = absint( $projection_payload['snapshot_version'] ?? 0 );
		if ( $payload_snapshot_version <= 0 || $payload_snapshot_version !== $snapshot_version ) {
			return null;
		}

		$projection_payload['source_job_id'] = $job_id;
		return $projection_payload;
	}

	private function projection_sync_transient_key( string $job_id, int $snapshot_version ): string {
		return self::PROJECTION_SYNC_TRANSIENT_PREFIX . md5( $job_id . ':' . (string) $snapshot_version );
	}

	/**
	 * @return array{id:string,batch_index:int,submitted_total:int}|null
	 */
	private function extract_batch_run_context( WP_REST_Request $request ): ?array {
		$run_id = sanitize_text_field( (string) $request->get_param( 'batch_run_id' ) );
		if ( '' === $run_id ) {
			return null;
		}

		return array(
			'id'              => $run_id,
			'batch_index'     => max( 0, absint( $request->get_param( 'batch_index' ) ) ),
			'submitted_total' => max( 0, absint( $request->get_param( 'submitted_total' ) ) ),
		);
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

	/**
	 * @param array{id:string,batch_index:int,submitted_total:int}|null $batch_context
	 * @param array<int,array<string,mixed>> $media_items
	 * @param int[] $unreadable_media_ids
	 */
	private function record_batch_run_success_from_response( ?array $batch_context, WP_REST_Response $response, array $media_items, array $unreadable_media_ids ): void {
		$data = $response->get_data();
		if ( ! is_array( $data ) ) {
			return;
		}

		$this->record_batch_run_success(
			$batch_context,
			(string) ( $data['id'] ?? '' ),
			$this->extract_media_ids_from_analyze_payload( $media_items ),
			$unreadable_media_ids,
			$response
		);
	}

	/**
	 * @param array{id:string,batch_index:int,submitted_total:int}|null $batch_context
	 * @param int[] $media_ids
	 * @param int[] $unreadable_media_ids
	 */
	private function record_batch_run_success( ?array $batch_context, string $job_id, array $media_ids, array $unreadable_media_ids, WP_REST_Response $response ): void {
		if ( null === $batch_context || '' === $job_id ) {
			return;
		}

		$this->batch_run_repository->record_job_submission(
			$this->get_tenant_id(),
			$batch_context['id'],
			$batch_context['batch_index'],
			$batch_context['submitted_total'],
			$job_id,
			$media_ids,
			$unreadable_media_ids
		);

		$data = $response->get_data();
		if ( is_array( $data ) ) {
			$data['batch_run_id'] = $batch_context['id'];
			$response->set_data( $data );
		}

		set_transient( $this->job_batch_run_transient_key( $job_id ), $batch_context['id'], self::JOB_TRACKING_TTL_SECONDS );
	}

	/**
	 * @param array{id:string,batch_index:int,submitted_total:int}|null $batch_context
	 * @param int[] $media_ids
	 * @param int[] $unreadable_media_ids
	 */
	private function record_batch_run_failure( ?array $batch_context, array $media_ids, WP_Error $error, array $unreadable_media_ids ): void {
		if ( null === $batch_context ) {
			return;
		}

		$this->batch_run_repository->record_batch_failure(
			$this->get_tenant_id(),
			$batch_context['id'],
			$batch_context['batch_index'],
			$batch_context['submitted_total'],
			$media_ids,
			$error,
			$unreadable_media_ids
		);
	}

	private function lookup_batch_run_id_for_job( string $job_id ): string {
		$run_id = $this->batch_run_repository->lookup_run_id_for_job( $this->get_tenant_id(), $job_id );
		if ( '' !== $run_id ) {
			return $run_id;
		}

		$value = get_transient( $this->job_batch_run_transient_key( $job_id ) );
		return is_string( $value ) ? sanitize_text_field( $value ) : '';
	}

	private function job_batch_run_transient_key( string $job_id ): string {
		return self::JOB_BATCH_RUN_TRANSIENT_PREFIX . $job_id;
	}

	private function refresh_stale_batch_run_children( string $run_id ): void {
		$tenant_id = $this->get_tenant_id();
		$job_ids   = $this->batch_run_repository->get_stale_non_terminal_job_ids( $tenant_id, $run_id, self::BATCH_RUN_STATUS_STALE_SECONDS );

		foreach ( $job_ids as $job_id ) {
			$response = $this->proxy_request(
				'GET',
				sprintf( '/recognition/jobs/%s', $job_id ),
				array(),
				array(
					'tenant_id' => $tenant_id,
				),
				self::REQUEST_CLASS_POST_SCAN_READ
			);

			if ( ! ( $response instanceof WP_REST_Response ) ) {
				continue;
			}

			$this->record_observed_job_status_from_response( $job_id, $response );
			$data = $response->get_data();
			if ( ! is_array( $data ) ) {
				continue;
			}
		}
	}

	private function resolve_sync_pull_job(): ?SyncPullJobInterface {
		if ( null !== $this->sync_pull_job ) {
			return $this->sync_pull_job;
		}

		try {
			$factory = $this->sync_pull_job_factory ?? new SyncPullJobFactory(
				new ClustersRepository(),
				new IdentityMembersRepository(),
				$this->sync_state_repository,
				new SnapshotClient()
			);
			$this->sync_pull_job = $factory->create();
		} catch ( Throwable $throwable ) {
			return null;
		}

		return $this->sync_pull_job;
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
