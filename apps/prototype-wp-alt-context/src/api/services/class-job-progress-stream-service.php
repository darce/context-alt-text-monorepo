<?php

declare(strict_types=1);

namespace AltContext\Api\Services;

use AltContext\Api\AnalysisJobsHostInterface;
use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

use function absint;
use function connection_aborted;
use function in_array;
use function is_array;
use function is_wp_error;
use function microtime;
use function nocache_headers;
use function ob_end_flush;
use function ob_flush;
use function ob_get_level;
use function sanitize_text_field;
use function sprintf;
use function usleep;
use function wp_json_encode;

class JobProgressStreamService {
	private AnalysisJobsHostInterface $host;
	private JobStatusService $job_status_service;
	private BatchRunService $batch_run_service;
	private ProjectionSyncService $projection_sync_service;

	public function __construct(
		AnalysisJobsHostInterface $host,
		JobStatusService $job_status_service,
		BatchRunService $batch_run_service,
		ProjectionSyncService $projection_sync_service
	) {
		$this->host = $host;
		$this->job_status_service = $job_status_service;
		$this->batch_run_service = $batch_run_service;
		$this->projection_sync_service = $projection_sync_service;
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
			$response = $this->host->proxy_recognition_request(
				'GET',
				sprintf( '/recognition/jobs/%s', $job_id ),
				array(),
				array(
					'tenant_id' => $this->host->get_tenant_id(),
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
				$this->job_status_service->record_observed_job_status_from_response( $job_id, $response );
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
			$this->projection_sync_service->maybe_trigger_projection_sync( $data );

			$progress   = is_array( $data['progress'] ?? null ) ? $data['progress'] : array();
			$completed  = absint( $progress['completed'] ?? 0 );
			$total      = absint( $progress['total'] ?? 0 );
			$status     = isset( $data['status'] ) ? sanitize_text_field( (string) $data['status'] ) : 'pending';
			$this->job_status_service->record_observed_job_status_from_response( $job_id, $response );
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

	/**
	 * @param array<string,mixed> $progress
	 * @return array<string,mixed>
	 */
	public function build_stream_progress_payload(
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

		$batch_run_id = $this->batch_run_service->lookup_batch_run_id_for_job( $job_id );
		if ( '' !== $batch_run_id ) {
			$payload['batch_run_id'] = $batch_run_id;
		}

		return $payload;
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
}