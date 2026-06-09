<?php

declare(strict_types=1);

namespace AltContext\Api\Services;

use AltContext\Api\AnalysisJobsHostInterface;
use AltContext\Support\Telemetry;
use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

use function absint;
use function apply_filters;
use function array_filter;
use function array_map;
use function array_unique;
use function array_values;
use function basename;
use function count;
use function esc_url_raw;
use function get_attached_file;
use function get_current_user_id;
use function get_site_url;
use function is_array;
use function is_readable;
use function is_string;
use function is_wp_error;
use function pathinfo;
use function set_transient;
use function sprintf;
use function strlen;
use function wp_get_attachment_url;
use function wp_json_encode;

class AnalyzeMediaService {
	private const MULTIPART_MAX_IMAGES = 5;
	private const MULTIPART_MAX_BYTES  = 25 * 1024 * 1024;
	private const JOB_MEDIA_IDS_TRANSIENT_PREFIX = 'acx_job_media_ids_';
	private const JOB_TRACKING_TTL_SECONDS = 86400;

	private AnalysisJobsHostInterface $host;
	private BatchRunService $batch_run_service;

	public function __construct(
		AnalysisJobsHostInterface $host,
		BatchRunService $batch_run_service
	) {
		$this->host = $host;
		$this->batch_run_service = $batch_run_service;
	}

	/**
	 * @param callable $validate_media_ids bool|WP_Error validate_media_ids(mixed, WP_REST_Request, string)
	 */
	public function analyze_media( WP_REST_Request $request, callable $validate_media_ids ): WP_REST_Response|WP_Error {
		$batch_context       = $this->batch_run_service->extract_batch_run_context( $request );
		$media_items_param   = $request->get_param( 'media_items' );
		$media_ids           = $request->get_param( 'media_ids' );
		$media_items         = array();
		$requested_media_ids = $this->extract_requested_media_ids( $media_items_param, $media_ids );
		$unreadable_media_ids = array();

		$transport = (string) apply_filters( 'acx_recognition_transport', 'multipart' );
		if ( 'multipart' !== $transport && 'url' !== $transport ) {
			$transport = 'multipart';
		}
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

			$max = $this->host->get_current_tier_batch_limit();
			if ( count( $media_items ) > $max ) {
				return new WP_Error(
					'too_many_media_items',
					sprintf( 'media_items supports at most %d items per request (received %d).', $max, count( $media_items ) ),
					array( 'status' => 400 )
				);
			}
		} elseif ( is_array( $media_ids ) && count( $media_ids ) > 0 ) {
			$validated = $validate_media_ids( $media_ids, $request, 'media_ids' );
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
			'tenant_id'   => $this->host->get_tenant_id(),
			'site_url'    => get_site_url(),
			'media_items' => $media_items,
			'user_id'     => get_current_user_id(),
		);

		$response = $this->host->proxy_recognition_request( 'POST', '/recognition/analyze', $payload );
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
	 * @param array<int,array<string,mixed>> $media_items
	 * @param int[] $unreadable_media_ids
	 */
	private function analyze_media_multipart( array $media_items, array &$unreadable_media_ids = array() ): WP_REST_Response|WP_Error {
		$tier_limit          = $this->host->get_current_tier_batch_limit();
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
					'tenant_id' => $this->host->get_tenant_id(),
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

		$response = $this->host->proxy_recognition_request(
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
