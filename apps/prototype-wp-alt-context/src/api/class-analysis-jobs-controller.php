<?php

declare(strict_types=1);

namespace AltContext\Api;

require_once __DIR__ . '/class-abstract-recognition-proxy-controller.php';
require_once __DIR__ . '/../settings/class-recognition-policy.php';
require_once __DIR__ . '/../support/trait-batch-limits.php';
require_once __DIR__ . '/interface-analysis-jobs-host.php';
require_once __DIR__ . '/services/class-batch-run-service.php';
require_once __DIR__ . '/services/class-projection-sync-service.php';
require_once __DIR__ . '/services/class-job-status-service.php';
require_once __DIR__ . '/services/class-job-progress-stream-service.php';
require_once __DIR__ . '/services/class-analyze-media-service.php';
require_once __DIR__ . '/../sovereign/repositories/interface-sync-state-repository.php';
require_once __DIR__ . '/../sovereign/repositories/class-batch-run-repository.php';
require_once __DIR__ . '/../sovereign/repositories/class-sync-state-repository.php';
require_once __DIR__ . '/../sovereign/sync/interface-sync-pull-job.php';
require_once __DIR__ . '/../sovereign/sync/class-sync-pull-job.php';
require_once __DIR__ . '/../sovereign/sync/class-sync-pull-result.php';
require_once __DIR__ . '/../sovereign/sync/class-sync-pull-job-factory.php';

use AltContext\Api\Services\AnalyzeMediaService;
use AltContext\Api\Services\BatchRunService;
use AltContext\Api\Services\JobProgressStreamService;
use AltContext\Api\Services\JobStatusService;
use AltContext\Api\Services\ProjectionSyncService;
use AltContext\Settings\RecognitionPolicy;
use AltContext\Sovereign\Repositories\BatchRunRepository;
use AltContext\Sovereign\Repositories\SyncStateRepository;
use AltContext\Sovereign\Repositories\SyncStateRepositoryInterface;
use AltContext\Sovereign\Sync\SyncPullJobFactory;
use AltContext\Sovereign\Sync\SyncPullJobInterface;
use AltContext\Support\BatchLimits;
use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

use function __;
use function absint;
use function count;
use function is_array;
use function is_wp_error;
use function sprintf;

class AnalysisJobsController extends AbstractRecognitionProxyController implements AnalysisJobsHostInterface {
	use BatchLimits {
		get_current_tier_batch_limit as protected resolve_current_tier_batch_limit;
	}

	private BatchRunService $batch_run_service;
	private ProjectionSyncService $projection_sync_service;
	private JobStatusService $job_status_service;
	private JobProgressStreamService $job_progress_stream_service;
	private AnalyzeMediaService $analyze_media_service;

	public function __construct(
		?SyncStateRepositoryInterface $sync_state_repository = null,
		?SyncPullJobInterface $sync_pull_job = null,
		?SyncPullJobFactory $sync_pull_job_factory = null,
		?BatchRunRepository $batch_run_repository = null,
		?BatchRunService $batch_run_service = null,
		?ProjectionSyncService $projection_sync_service = null,
		?JobStatusService $job_status_service = null,
		?JobProgressStreamService $job_progress_stream_service = null,
		?AnalyzeMediaService $analyze_media_service = null
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
		$this->job_progress_stream_service = $job_progress_stream_service ?? new JobProgressStreamService(
			$this,
			$this->job_status_service,
			$this->batch_run_service,
			$this->projection_sync_service
		);
		$this->analyze_media_service = $analyze_media_service ?? new AnalyzeMediaService(
			$this,
			$this->batch_run_service
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
		string $body_kind = 'json',
		?int $max_body_bytes = null
	): WP_REST_Response|WP_Error {
		return $this->proxy_request( $method, $path, $body, $query, $request_class, $body_kind, $max_body_bytes );
	}

	public function is_proxy_unavailable( WP_REST_Response|WP_Error $response ): bool {
		return parent::is_proxy_unavailable( $response );
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
		if ( ! RecognitionPolicy::enabled() ) {
			return new WP_Error(
				'recognition_disabled',
				__( 'People identification is turned off in Settings.', 'alt-context' ),
				array( 'status' => 409 )
			);
		}

		return $this->analyze_media_service->analyze_media( $request, array( $this, 'validate_media_ids' ) );
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
}
