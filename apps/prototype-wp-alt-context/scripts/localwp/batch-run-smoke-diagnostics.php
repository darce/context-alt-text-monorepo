<?php

declare(strict_types=1);

function acx_batch_run_timeout_message_base(): string {
	return 'BatchRun did not reach a terminal state before timeout.';
}

function acx_format_batch_run_timeout_message( array $child_job_statuses ): string {
	$message = acx_batch_run_timeout_message_base();
	if ( array() === $child_job_statuses ) {
		return $message;
	}

	$parts = array();
	foreach ( $child_job_statuses as $job_status ) {
		if ( ! is_array( $job_status ) ) {
			continue;
		}

		$job_id = trim( (string) ( $job_status['job_id'] ?? '' ) );
		if ( '' === $job_id ) {
			$job_id = 'unknown-job';
		}

		$status = trim( (string) ( $job_status['status'] ?? 'unknown' ) );
		if ( '' === $status ) {
			$status = 'unknown';
		}

		$message_detail = trim( (string) ( $job_status['message'] ?? '' ) );
		$parts[] = '' !== $message_detail
			? sprintf( '%s=%s (%s)', $job_id, $status, $message_detail )
			: sprintf( '%s=%s', $job_id, $status );
	}

	if ( array() === $parts ) {
		return $message;
	}

	return $message . ' Child jobs: ' . implode( ', ', $parts ) . '.';
}
