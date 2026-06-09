<?php

declare(strict_types=1);

namespace AltContext\Api\Services;

use AltContext\Api\AnalysisJobsHostInterface;
use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

use function absint;
use function gmdate;
use function is_array;
use function is_wp_error;
use function sanitize_text_field;
use function sprintf;

class JobStatusService {
	private const REQUEST_CLASS_POST_SCAN_READ = 'post_scan_read';

	private AnalysisJobsHostInterface $host;
	private BatchRunService $batch_run_service;
	private ProjectionSyncService $projection_sync_service;

	public function __construct(
		AnalysisJobsHostInterface $host,
		BatchRunService $batch_run_service,
		ProjectionSyncService $projection_sync_service
	) {
		$this->host = $host;
		$this->batch_run_service = $batch_run_service;
		$this->projection_sync_service = $projection_sync_service;
	}

	public function get_job_status( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$job_id = sanitize_text_field( (string) $request->get_param( 'job_id' ) );
		if ( '' === $job_id ) {
			return new WP_Error( 'missing_job_id', 'Job ID is required.', array( 'status' => 400 ) );
		}

		$response = $this->host->proxy_recognition_request(
			'GET',
			sprintf( '/recognition/jobs/%s', $job_id ),
			array(),
			array(
				'tenant_id' => $this->host->get_tenant_id(),
			),
			self::REQUEST_CLASS_POST_SCAN_READ
		);
		if ( $this->host->is_proxy_unavailable( $response ) ) {
			return $this->build_offline_job_status_response( $job_id );
		}

		if ( $response instanceof WP_REST_Response ) {
			$this->record_observed_job_status_from_response( $job_id, $response );
			$data = $response->get_data();
			if ( is_array( $data ) ) {
				$batch_run_id = $this->batch_run_service->lookup_batch_run_id_for_job( $job_id );
				if ( '' !== $batch_run_id ) {
					$data['batch_run_id'] = $batch_run_id;
					$response->set_data( $data );
				}
				$this->projection_sync_service->maybe_trigger_projection_sync( $data );
			}
		}

		return $response;
	}

	public function cancel_job( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$job_id = sanitize_text_field( (string) $request->get_param( 'job_id' ) );

		if ( '' === $job_id ) {
			return new WP_Error( 'missing_job_id', 'Job ID is required.', array( 'status' => 400 ) );
		}

		return $this->host->proxy_recognition_request(
			'POST',
			sprintf( '/recognition/jobs/%s/cancel', $job_id ),
			array(),
			array(
				'tenant_id' => $this->host->get_tenant_id(),
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

		return $this->host->proxy_recognition_request(
			'POST',
			sprintf( '/recognition/jobs/%s/acknowledge-projection', $job_id ),
			$payload
		);
	}

	public function record_observed_job_status_from_response( string $job_id, WP_REST_Response $response ): void {
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

		$this->batch_run_service->record_observed_job_status( $job_id, $status );
	}

	public function build_offline_job_status_response( string $job_id ): WP_REST_Response {
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
}