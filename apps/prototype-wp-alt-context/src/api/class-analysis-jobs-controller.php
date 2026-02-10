<?php

declare(strict_types=1);

namespace AltContext\Api;

use AltContext\Support\BatchLimits;
use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

use function absint;
use function do_action;
use function get_transient;
use function get_current_user_id;
use function get_site_url;
use function in_array;
use function is_array;
use function is_wp_error;
use function nocache_headers;
use function sanitize_text_field;
use function set_transient;
use function sprintf;
use function wp_get_attachment_url;
use function wp_json_encode;

class AnalysisJobsController extends AbstractRecognitionProxyController {
	use BatchLimits;

	private const JOB_MEDIA_IDS_TRANSIENT_PREFIX = 'acx_job_media_ids_';
	private const JOB_COMPLETION_TRANSIENT_PREFIX = 'acx_job_completion_emitted_';
	private const JOB_TRACKING_TTL_SECONDS = 86400;

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
	}

	public function analyze_media( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$media_items_param = $request->get_param( 'media_items' );
		$media_ids         = $request->get_param( 'media_ids' );
		$media_items       = array();

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
				return $validated;
			}
			$media_items = $this->build_media_items( $media_ids );
		}

		if ( empty( $media_items ) ) {
			return new WP_Error( 'no_media_items', 'At least one media item is required', array( 'status' => 400 ) );
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
			}
		}

		return $response;
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
			)
		);

		if ( $response instanceof WP_REST_Response ) {
			$data = $response->get_data();
			if ( is_array( $data ) ) {
				$this->maybe_dispatch_recognition_complete( $job_id, $data );
			}
		}

		return $response;
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

		nocache_headers();
		header( 'Content-Type: text/event-stream' );
		header( 'Cache-Control: no-cache' );
		header( 'X-Accel-Buffering: no' );

		while ( ob_get_level() > 0 ) {
			ob_end_flush();
		}
		@ini_set( 'output_buffering', 'off' );
		@ini_set( 'zlib.output_compression', '0' );

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

			$progress   = is_array( $data['progress'] ?? null ) ? $data['progress'] : array();
			$completed  = absint( $progress['completed'] ?? 0 );
			$total      = absint( $progress['total'] ?? 0 );
			$status     = isset( $data['status'] ) ? sanitize_text_field( (string) $data['status'] ) : 'pending';
			$phase      = isset( $progress['phase'] ) ? sanitize_text_field( (string) $progress['phase'] ) : null;
			$job_type   = isset( $data['type'] ) ? sanitize_text_field( (string) $data['type'] ) : 'analyze';
			$event_type = 'scan_progress';
			if ( 'clustering' === $job_type ) {
				$event_type = 'clustering_progress';
			}
			if ( 'completed' === $status ) {
				$this->maybe_dispatch_recognition_complete( $job_id, $data );
			}

			$now         = microtime( true );
			$should_emit = (
				$completed !== $last_completed
				|| $phase !== $last_phase
				|| ( $now - $last_emit > 0.5 && $completed > 0 )
				|| ( $now - $last_heartbeat > 15 )
			);

			if ( $should_emit ) {
				$payload = array(
					'type'      => $event_type,
					'job_id'    => $job_id,
					'status'    => $status,
					'completed' => $completed,
					'total'     => $total,
				);
				if ( null !== $phase && '' !== $phase ) {
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
				$done_payload = array(
					'type'      => $event_type,
					'job_id'    => $job_id,
					'status'    => $status,
					'completed' => $completed,
					'total'     => $total,
				);
				if ( null !== $phase && '' !== $phase ) {
					$done_payload['phase'] = $phase;
				}
				if ( isset( $progress['images_processed'] ) ) {
					$done_payload['images_processed'] = absint( $progress['images_processed'] );
				}
				if ( isset( $progress['faces_found'] ) ) {
					$done_payload['faces_found'] = absint( $progress['faces_found'] );
				}
				if ( isset( $progress['clusters_created'] ) ) {
					$done_payload['clusters_created'] = absint( $progress['clusters_created'] );
				}
				echo "event: done\n";
				echo 'data: ' . wp_json_encode( $done_payload ) . "\n\n";
				@ob_flush();
				@flush();
				break;
			}

			usleep( 100000 );
		}

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
	 * @param array<string,mixed> $job_data
	 */
	private function maybe_dispatch_recognition_complete( string $job_id, array $job_data ): void {
		$status = (string) ( $job_data['status'] ?? '' );
		if ( 'completed' !== $status || '' === $job_id || $this->has_emitted_completion( $job_id ) ) {
			return;
		}

		$media_ids = $this->extract_media_ids_from_job_data( $job_data );
		if ( empty( $media_ids ) ) {
			$media_ids = $this->load_stored_media_ids( $job_id );
		}

		if ( empty( $media_ids ) ) {
			return;
		}

		foreach ( $media_ids as $attachment_id ) {
			do_action( 'acx_recognition_complete', $attachment_id, $job_id );
		}

		$this->mark_completion_emitted( $job_id );
	}

	/**
	 * @param array<string,mixed> $job_data
	 * @return int[]
	 */
	private function extract_media_ids_from_job_data( array $job_data ): array {
		$media_ids = array();

		if ( isset( $job_data['media_ids'] ) && is_array( $job_data['media_ids'] ) ) {
			foreach ( $job_data['media_ids'] as $candidate ) {
				$media_id = absint( $candidate );
				if ( $media_id > 0 ) {
					$media_ids[] = $media_id;
				}
			}
		}

		if ( isset( $job_data['media_items'] ) && is_array( $job_data['media_items'] ) ) {
			foreach ( $job_data['media_items'] as $media_item ) {
				if ( ! is_array( $media_item ) ) {
					continue;
				}

				$media_id = absint( $media_item['media_id'] ?? 0 );
				if ( $media_id > 0 ) {
					$media_ids[] = $media_id;
				}
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

	/**
	 * @return int[]
	 */
	private function load_stored_media_ids( string $job_id ): array {
		if ( '' === $job_id ) {
			return array();
		}

		$stored = get_transient( $this->job_media_ids_transient_key( $job_id ) );
		if ( ! is_array( $stored ) ) {
			return array();
		}

		$media_ids = array();
		foreach ( $stored as $candidate ) {
			$media_id = absint( $candidate );
			if ( $media_id > 0 ) {
				$media_ids[] = $media_id;
			}
		}

		return array_values( array_unique( $media_ids ) );
	}

	private function has_emitted_completion( string $job_id ): bool {
		return true === (bool) get_transient( $this->completion_emitted_transient_key( $job_id ) );
	}

	private function mark_completion_emitted( string $job_id ): void {
		if ( '' === $job_id ) {
			return;
		}

		set_transient( $this->completion_emitted_transient_key( $job_id ), true, self::JOB_TRACKING_TTL_SECONDS );
	}

	private function job_media_ids_transient_key( string $job_id ): string {
		return self::JOB_MEDIA_IDS_TRANSIENT_PREFIX . $job_id;
	}

	private function completion_emitted_transient_key( string $job_id ): string {
		return self::JOB_COMPLETION_TRANSIENT_PREFIX . $job_id;
	}
}
