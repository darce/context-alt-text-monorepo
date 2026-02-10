<?php

declare(strict_types=1);

namespace AltContext\Media;

use function absint;
use function add_action;
use function current_time;
use function do_action;
use function get_attached_file;
use function is_array;
use function is_string;
use function update_post_meta;

class AttachmentXmpMetricsPersistor {
	private ImageXmpWriter $xmpWriter;

	public function __construct( ImageXmpWriter $xmp_writer ) {
		$this->xmpWriter = $xmp_writer;
	}

	public function init(): void {
		add_action( 'acx_recognition_complete', array( $this, 'persist_for_attachment' ), 10, 2 );
	}

	/**
	 * @param int|string $attachment_id
	 */
	public function persist_for_attachment( $attachment_id, string $job_id = '' ): void {
		$id = absint( $attachment_id );
		if ( $id <= 0 ) {
			return;
		}

		$original_path = get_attached_file( $id, true );
		if ( ! is_string( $original_path ) || '' === $original_path ) {
			$this->record_result( $id, ImageXmpWriter::STATUS_SKIPPED, $job_id, 'Missing original attachment file path.' );
			return;
		}

		$status = $this->xmpWriter->write_for_attachment( $id, $original_path );
		if ( ImageXmpWriter::STATUS_FAILED === $status ) {
			do_action( 'acx_xmp_persist_failure', $id, $job_id, $original_path );
		}

		$this->record_result( $id, $status, $job_id, null );
	}

	/**
	 * @param int[] $attachment_ids
	 * @return array{processed:int,skipped:int,failed:int}
	 */
	public function embed_for_media_ids( array $attachment_ids ): array {
		$summary = array(
			'processed' => 0,
			'skipped'   => 0,
			'failed'    => 0,
		);

		$normalized_ids = array();
		foreach ( $attachment_ids as $attachment_id ) {
			$id = absint( $attachment_id );
			if ( $id > 0 ) {
				$normalized_ids[] = $id;
			}
		}

		$normalized_ids = array_values( array_unique( $normalized_ids ) );
		foreach ( $normalized_ids as $attachment_id ) {
			$original_path = get_attached_file( $attachment_id, true );
			if ( ! is_string( $original_path ) || '' === $original_path ) {
				++$summary['skipped'];
				$this->record_result( $attachment_id, ImageXmpWriter::STATUS_SKIPPED, '', 'Missing original attachment file path.' );
				continue;
			}

			$status = $this->xmpWriter->write_for_attachment( $attachment_id, $original_path );
			if ( ImageXmpWriter::STATUS_WRITTEN === $status ) {
				++$summary['processed'];
			}

			if ( ImageXmpWriter::STATUS_SKIPPED === $status ) {
				++$summary['skipped'];
			}

			if ( ImageXmpWriter::STATUS_FAILED === $status ) {
				++$summary['failed'];
				do_action( 'acx_xmp_persist_failure', $attachment_id, '', $original_path );
			}

			$this->record_result( $attachment_id, $status, '', null );
		}

		return $summary;
	}

	private function record_result( int $attachment_id, string $status, string $job_id, ?string $error ): void {
		$payload = array(
			'status'       => $status,
			'job_id'       => $job_id,
			'timestamp_gmt' => current_time( 'mysql', true ),
		);

		if ( is_string( $error ) && '' !== $error ) {
			$payload['error'] = $error;
		}

		update_post_meta( $attachment_id, 'acx_xmp_persist_last_result', $payload );
	}
}
