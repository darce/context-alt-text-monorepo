<?php

declare(strict_types=1);

namespace AltContext\Api\Services;

use AltContext\Api\AnalysisJobsHostInterface;
use AltContext\Sovereign\Repositories\BatchRunRepository;
use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

use function absint;
use function array_filter;
use function array_map;
use function count;
use function get_transient;
use function is_array;
use function is_string;
use function is_wp_error;
use function max;
use function sanitize_text_field;
use function set_transient;
use function sprintf;

class BatchRunService {
	private const REQUEST_CLASS_POST_SCAN_READ = 'post_scan_read';
	private const BATCH_RUN_STATUS_STALE_SECONDS = 5;
	private const JOB_BATCH_RUN_TRANSIENT_PREFIX = 'acx_job_batch_run_';
	private const JOB_TRACKING_TTL_SECONDS = 86400;

	private AnalysisJobsHostInterface $host;
	private BatchRunRepository $batch_run_repository;
	private ?JobStatusService $job_status_service = null;

	public function __construct(
		AnalysisJobsHostInterface $host,
		?BatchRunRepository $batch_run_repository = null
	) {
		$this->host = $host;
		$this->batch_run_repository = $batch_run_repository ?? new BatchRunRepository();
	}

	public function wire_job_status_service( JobStatusService $job_status_service ): void {
		$this->job_status_service = $job_status_service;
	}

	public function get_recent_batch_runs( WP_REST_Request $request ): WP_REST_Response {
		$limit = max( 1, min( 10, absint( $request->get_param( 'limit' ) ) ) );
		if ( 0 === absint( $request->get_param( 'limit' ) ) ) {
			$limit = 5;
		}

		return new WP_REST_Response(
			array(
				'items' => $this->batch_run_repository->list_recent_runs( $this->host->get_tenant_id(), $limit ),
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
		$computed = $this->batch_run_repository->get_status( $this->host->get_tenant_id(), $run_id );
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
			$this->host->get_tenant_id(),
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

	/**
	 * @return array{id:string,batch_index:int,submitted_total:int}|null
	 */
	public function extract_batch_run_context( WP_REST_Request $request ): ?array {
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
	 * @param array{id:string,batch_index:int,submitted_total:int}|null $batch_context
	 * @param array<int,array<string,mixed>> $media_items
	 * @param int[] $unreadable_media_ids
	 */
	public function record_batch_run_success_from_response( ?array $batch_context, WP_REST_Response $response, array $media_items, array $unreadable_media_ids ): void {
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
	public function record_batch_run_success( ?array $batch_context, string $job_id, array $media_ids, array $unreadable_media_ids, WP_REST_Response $response ): void {
		if ( null === $batch_context || '' === $job_id ) {
			return;
		}

		$this->batch_run_repository->record_job_submission(
			$this->host->get_tenant_id(),
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
	public function record_batch_run_failure( ?array $batch_context, array $media_ids, WP_Error $error, array $unreadable_media_ids ): void {
		if ( null === $batch_context ) {
			return;
		}

		$this->batch_run_repository->record_batch_failure(
			$this->host->get_tenant_id(),
			$batch_context['id'],
			$batch_context['batch_index'],
			$batch_context['submitted_total'],
			$media_ids,
			$error,
			$unreadable_media_ids
		);
	}

	public function lookup_batch_run_id_for_job( string $job_id ): string {
		$run_id = $this->batch_run_repository->lookup_run_id_for_job( $this->host->get_tenant_id(), $job_id );
		if ( '' !== $run_id ) {
			return $run_id;
		}

		$value = get_transient( $this->job_batch_run_transient_key( $job_id ) );
		return is_string( $value ) ? sanitize_text_field( $value ) : '';
	}

	public function record_observed_job_status( string $job_id, string $status ): void {
		if ( '' === $status ) {
			return;
		}

		$this->batch_run_repository->record_observed_job_status( $this->host->get_tenant_id(), $job_id, $status );
	}

	private function refresh_stale_batch_run_children( string $run_id ): void {
		$tenant_id = $this->host->get_tenant_id();
		$job_ids   = $this->batch_run_repository->get_stale_non_terminal_job_ids( $tenant_id, $run_id, self::BATCH_RUN_STATUS_STALE_SECONDS );

		foreach ( $job_ids as $job_id ) {
			$response = $this->host->proxy_recognition_request(
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

			if ( null !== $this->job_status_service ) {
				$this->job_status_service->record_observed_job_status_from_response( $job_id, $response );
			}
			$data = $response->get_data();
			if ( ! is_array( $data ) ) {
				continue;
			}
		}
	}

	private function job_batch_run_transient_key( string $job_id ): string {
		return self::JOB_BATCH_RUN_TRANSIENT_PREFIX . $job_id;
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
}