<?php

declare(strict_types=1);

require_once __DIR__ . '/batch-run-smoke-args.php';

if ( ! defined( 'WP_CLI' ) || ! WP_CLI ) {
	fwrite( STDERR, "This script must be run via WP-CLI.\n" );
	exit( 1 );
}

$args = is_array( $args ?? null ) ? $args : array();

try {
	$smoke_args = acx_parse_batch_run_smoke_args( $args );
} catch ( RuntimeException $exception ) {
	fwrite( STDERR, $exception->getMessage() . "\n" );
	exit( 1 );
}

$limit = $smoke_args['limit'];
$batch_size = $smoke_args['batch_size'];
$timeout_seconds = $smoke_args['timeout_seconds'];
$poll_interval_ms = $smoke_args['poll_interval_ms'];

function acx_collect_batch_run_child_job_statuses( array $job_ids ): array {
	$statuses = array();

	foreach ( $job_ids as $job_id ) {
		$job_id = trim( (string) $job_id );
		if ( '' === $job_id ) {
			continue;
		}

		$request = new WP_REST_Request( 'GET', '/acx/v1/recognition/jobs/' . $job_id );
		$response = rest_do_request( $request );

		if ( is_wp_error( $response ) ) {
			$statuses[ $job_id ] = array(
				'status'  => 'unavailable',
				'message' => $response->get_error_message(),
			);
			continue;
		}

		$status_code = (int) $response->get_status();
		$data        = $response->get_data();

		if ( $status_code >= 200 && $status_code < 300 && is_array( $data ) ) {
			$status_payload = array(
				'status' => trim( (string) ( $data['status'] ?? 'unknown' ) ),
			);

			$message = trim( (string) ( $data['message'] ?? '' ) );
			if ( '' !== $message ) {
				$status_payload['message'] = $message;
			}

			$statuses[ $job_id ] = $status_payload;
			continue;
		}

		$statuses[ $job_id ] = array(
			'status'      => 'unavailable',
			'http_status' => $status_code,
			'message'     => is_array( $data ) ? trim( (string) ( $data['message'] ?? 'Job status lookup failed.' ) ) : 'Job status lookup failed.',
		);
	}

	return $statuses;
}

function acx_format_batch_run_timeout_message( array $child_job_statuses ): string {
	if ( array() === $child_job_statuses ) {
		return 'BatchRun did not reach a terminal state before timeout.';
	}

	$parts = array();
	foreach ( $child_job_statuses as $job_id => $job_status ) {
		$status = trim( (string) ( $job_status['status'] ?? 'unknown' ) );
		if ( '' === $status ) {
			$status = 'unknown';
		}

		$message = trim( (string) ( $job_status['message'] ?? '' ) );
		$parts[] = '' !== $message
			? sprintf( '%s=%s (%s)', $job_id, $status, $message )
			: sprintf( '%s=%s', $job_id, $status );
	}

	return 'BatchRun did not reach a terminal state before timeout. Child jobs: ' . implode( ', ', $parts ) . '.';
}

$admin_ids = get_users(
	array(
		'role'   => 'administrator',
		'number' => 1,
		'fields' => 'ids',
	)
);

if ( empty( $admin_ids ) ) {
	fwrite( STDERR, "No administrator user found for REST dispatch.\n" );
	exit( 1 );
}

wp_set_current_user( (int) $admin_ids[0] );

$recognition_source = trim( (string) get_option( 'acx_recognition_source', '' ) );
if ( '' === $recognition_source && defined( 'ACX_RECOGNITION_SOURCE' ) && is_string( ACX_RECOGNITION_SOURCE ) ) {
	$recognition_source = trim( ACX_RECOGNITION_SOURCE );
}

if ( 'local' !== $recognition_source ) {
	fwrite( STDERR, sprintf( "Recognition source must be local for this smoke; current value: %s\n", '' === $recognition_source ? '<empty>' : $recognition_source ) );
	exit( 1 );
}

$media_ids = get_posts(
	array(
		'post_type'      => 'attachment',
		'post_status'    => 'inherit',
		'post_mime_type' => 'image',
		'fields'         => 'ids',
		'posts_per_page' => $limit,
		'orderby'        => 'ID',
		'order'          => 'ASC',
	)
);

if ( ! is_array( $media_ids ) || count( $media_ids ) < $limit ) {
	fwrite( STDERR, sprintf( "Need at least %d image attachments; found %d.\n", $limit, is_array( $media_ids ) ? count( $media_ids ) : 0 ) );
	exit( 1 );
}

$media_ids = array_map( 'intval', array_slice( $media_ids, 0, $limit ) );
$batch_run_id = wp_generate_uuid4();
$dispatched_jobs = array();
$dispatch_failures = array();

foreach ( array_chunk( $media_ids, $batch_size ) as $batch_index => $batch_media_ids ) {
	$request = new WP_REST_Request( 'POST', '/acx/v1/recognition/analyze' );
	$request->set_body_params(
		array(
			'media_ids'       => $batch_media_ids,
			'batch_run_id'    => $batch_run_id,
			'batch_index'     => $batch_index,
			'submitted_total' => count( $media_ids ),
		)
	);

	$response = rest_do_request( $request );
	if ( is_wp_error( $response ) ) {
		$dispatch_failures[] = array(
			'batch_index'   => $batch_index,
			'media_ids'     => $batch_media_ids,
			'error_code'    => $response->get_error_code(),
			'error_message' => $response->get_error_message(),
		);
		continue;
	}

	$status = (int) $response->get_status();
	$data = $response->get_data();

	if ( $status < 200 || $status >= 300 || ! is_array( $data ) || '' === (string) ( $data['id'] ?? '' ) ) {
		$dispatch_failures[] = array(
			'batch_index'   => $batch_index,
			'media_ids'     => $batch_media_ids,
			'error_code'    => is_array( $data ) ? (string) ( $data['code'] ?? 'http_error' ) : 'http_error',
			'error_message' => is_array( $data ) ? (string) ( $data['message'] ?? 'Analyze request failed.' ) : 'Analyze request failed.',
			'http_status'   => $status,
		);
		continue;
	}

	$dispatched_jobs[] = (string) $data['id'];
}

$deadline = microtime( true ) + $timeout_seconds;
$batch_run_status = null;

do {
	$status_request = new WP_REST_Request( 'GET', '/acx/v1/recognition/batch-runs/' . $batch_run_id );
	$status_response = rest_do_request( $status_request );

	if ( ! is_wp_error( $status_response ) ) {
		$status_code = (int) $status_response->get_status();
		$status_data = $status_response->get_data();
		if ( $status_code >= 200 && $status_code < 300 && is_array( $status_data ) ) {
			$batch_run_status = $status_data;
			if ( ! empty( $batch_run_status['terminal_state'] ) ) {
				break;
			}
		}
	}

	usleep( $poll_interval_ms * 1000 );
} while ( microtime( true ) < $deadline );

if ( ! is_array( $batch_run_status ) ) {
	fwrite( STDERR, "BatchRun status could not be loaded.\n" );
	exit( 1 );
}

$completed_total = (int) ( $batch_run_status['completed_total'] ?? 0 );
$failed_total = (int) ( $batch_run_status['failed_total'] ?? 0 );
$cancelled_total = (int) ( $batch_run_status['cancelled_total'] ?? 0 );
$reconciled_total = $completed_total + $failed_total + $cancelled_total;
$child_job_statuses = empty( $batch_run_status['terminal_state'] )
	? acx_collect_batch_run_child_job_statuses( $dispatched_jobs )
	: array();

$payload = array(
	'site_url'          => get_site_url(),
	'recognition_source'=> $recognition_source,
	'batch_run_id'      => $batch_run_id,
	'limit'             => $limit,
	'batch_size'        => $batch_size,
	'submitted_total'   => count( $media_ids ),
	'accepted_total'    => (int) ( $batch_run_status['accepted_total'] ?? 0 ),
	'completed_total'   => $completed_total,
	'failed_total'      => $failed_total,
	'cancelled_total'   => $cancelled_total,
	'terminal_state'    => (bool) ( $batch_run_status['terminal_state'] ?? false ),
	'reconciled'        => $reconciled_total === count( $media_ids ),
	'child_job_ids'     => array_values( array_map( 'strval', is_array( $batch_run_status['child_job_ids'] ?? null ) ? $batch_run_status['child_job_ids'] : array() ) ),
	'child_job_statuses'=> $child_job_statuses,
	'failed_batches'    => is_array( $batch_run_status['failed_batches'] ?? null ) ? $batch_run_status['failed_batches'] : array(),
	'unreadable_media_ids' => is_array( $batch_run_status['unreadable_media_ids'] ?? null ) ? $batch_run_status['unreadable_media_ids'] : array(),
	'dispatch_failures' => $dispatch_failures,
	'dispatched_jobs'   => $dispatched_jobs,
	'timeout_seconds'   => $timeout_seconds,
	'poll_interval_ms'  => $poll_interval_ms,
);

echo wp_json_encode( $payload, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES ) . PHP_EOL;

if ( empty( $batch_run_status['terminal_state'] ) ) {
	fwrite( STDERR, acx_format_batch_run_timeout_message( $child_job_statuses ) . "\n" );
	exit( 2 );
}

if ( $reconciled_total !== count( $media_ids ) ) {
	fwrite( STDERR, sprintf( "BatchRun totals did not reconcile: %d of %d terminal.\n", $reconciled_total, count( $media_ids ) ) );
	exit( 3 );
}