<?php

declare(strict_types=1);

namespace AltContext\Api;

use AltContext\Support\BatchLimits;
use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

use function absint;
use function add_query_arg;
use function apply_filters;
use function current_user_can;
use function esc_url_raw;
use function get_current_user_id;
use function get_option;
use function get_site_url;
use function is_array;
use function is_wp_error;
use function min;
use function nocache_headers;
use function sanitize_key;
use function sanitize_text_field;
use function sprintf;
use function untrailingslashit;
use function wp_get_attachment_url;
use function wp_json_encode;
use function wp_remote_request;
use function wp_remote_retrieve_body;
use function wp_remote_retrieve_response_code;
use function rest_sanitize_boolean;

class RecognitionController {
	use BatchLimits;

	private string $recognition_base_url;
	private string $api_key;

	public function __construct() {
		$this->recognition_base_url = (string) get_option( 'alt_context_recognition_url', 'http://localhost:8000' );
		$this->api_key             = (string) get_option( 'alt_context_recognition_api_key', '' );
	}

	public function register_routes(): void {
		register_rest_route(
			'acx/v1',
			'/recognition/analyze',
			[
				'methods'             => 'POST',
				'callback'            => [ $this, 'analyze_media' ],
				'permission_callback' => [ $this, 'can_manage_recognition' ],
				'args'                => [
					'media_ids'   => [
						'type'              => 'array',
						'required'          => false,
						'items'             => [ 'type' => 'integer' ],
						'description'       => 'Array of attachment IDs to analyze.',
						'validate_callback' => [ $this, 'validate_media_ids' ],
					],
					'media_items' => [
						'type'        => 'array',
						'required'    => false,
						'description' => 'Media item descriptors (media_id + media_url).',
					],
				],
			]
		);

		register_rest_route(
			'acx/v1',
			'/recognition/jobs/(?P<job_id>[a-f0-9-]+)',
			[
				'methods'             => 'GET',
				'callback'            => [ $this, 'get_job_status' ],
				'permission_callback' => [ $this, 'can_manage_recognition' ],
			]
		);

		register_rest_route(
			'acx/v1',
			'/recognition/jobs/(?P<job_id>[a-f0-9-]+)/stream',
			[
				'methods'             => 'GET',
				'callback'            => [ $this, 'stream_job_progress' ],
				'permission_callback' => [ $this, 'can_manage_recognition' ],
			]
		);

		register_rest_route(
			'acx/v1',
			'/recognition/jobs/(?P<job_id>[a-f0-9-]+)/cancel',
			[
				'methods'             => 'POST',
				'callback'            => [ $this, 'cancel_job' ],
				'permission_callback' => [ $this, 'can_manage_recognition' ],
			]
		);

		register_rest_route(
			'acx/v1',
			'/recognition/cluster',
			[
				'methods'             => 'POST',
				'callback'            => [ $this, 'cluster_media' ],
				'permission_callback' => [ $this, 'can_manage_recognition' ],
			]
		);

		register_rest_route(
			'acx/v1',
			'/recognition/clusters',
			[
				'methods'             => 'GET',
				'callback'            => [ $this, 'list_clusters' ],
				'permission_callback' => [ $this, 'can_manage_recognition' ],
			]
		);

		register_rest_route(
			'acx/v1',
			'/recognition/clusters/top-unlabeled',
			[
				'methods'             => 'GET',
				'callback'            => [ $this, 'list_top_unlabeled_clusters' ],
				'permission_callback' => [ $this, 'can_manage_recognition' ],
			]
		);

		register_rest_route(
			'acx/v1',
			'/recognition/clusters/events',
			[
				'methods'             => 'GET',
				'callback'            => [ $this, 'stream_cluster_events' ],
				'permission_callback' => [ $this, 'can_manage_recognition' ],
			]
		);

		register_rest_route(
			'acx/v1',
			'/recognition/clusters/labels',
			[
				'methods'             => 'GET',
				'callback'            => [ $this, 'list_cluster_labels' ],
				'permission_callback' => [ $this, 'can_manage_recognition' ],
			]
		);

		register_rest_route(
			'acx/v1',
			'/recognition/training-stage',
			[
				'methods'             => 'GET',
				'callback'            => [ $this, 'get_training_stage' ],
				'permission_callback' => [ $this, 'can_manage_recognition' ],
			]
		);

		register_rest_route(
			'acx/v1',
			'/recognition/clusters/reassign',
			[
				'methods'             => 'POST',
				'callback'            => [ $this, 'reassign_cluster_identity' ],
				'permission_callback' => [ $this, 'can_manage_recognition' ],
			]
		);

		register_rest_route(
			'acx/v1',
			'/recognition/clusters/(?P<cluster_id>[a-f0-9-]+)',
			[
				'methods'             => 'GET',
				'callback'            => [ $this, 'get_cluster_detail' ],
				'permission_callback' => [ $this, 'can_manage_recognition' ],
			]
		);

		register_rest_route(
			'acx/v1',
			'/recognition/clusters/(?P<cluster_id>[a-f0-9-]+)',
			[
				'methods'             => 'PATCH',
				'callback'            => [ $this, 'update_cluster_label' ],
				'permission_callback' => [ $this, 'can_manage_recognition' ],
			]
		);

		register_rest_route(
			'acx/v1',
			'/recognition/clusters/(?P<cluster_id>[a-f0-9-]+)/members',
			[
				'methods'             => 'GET',
				'callback'            => [ $this, 'get_cluster_members' ],
				'permission_callback' => [ $this, 'can_manage_recognition' ],
			]
		);

		register_rest_route(
			'acx/v1',
			'/recognition/clusters/(?P<cluster_id>[a-f0-9-]+)/dismiss',
			[
				'methods'             => 'POST',
				'callback'            => [ $this, 'dismiss_cluster' ],
				'permission_callback' => [ $this, 'can_manage_recognition' ],
			]
		);

		register_rest_route(
			'acx/v1',
			'/recognition/clusters/(?P<cluster_id>[a-f0-9-]+)/dismiss',
			[
				'methods'             => 'DELETE',
				'callback'            => [ $this, 'undismiss_cluster' ],
				'permission_callback' => [ $this, 'can_manage_recognition' ],
			]
		);

		register_rest_route(
			'acx/v1',
			'/recognition/clusters/(?P<source_id>[a-f0-9-]+)/merge',
			[
				'methods'             => 'POST',
				'callback'            => [ $this, 'merge_cluster' ],
				'permission_callback' => [ $this, 'can_manage_recognition' ],
			]
		);

		register_rest_route(
			'acx/v1',
			'/recognition/clusters/(?P<cluster_id>[a-f0-9-]+)/split',
			[
				'methods'             => 'POST',
				'callback'            => [ $this, 'split_cluster' ],
				'permission_callback' => [ $this, 'can_manage_recognition' ],
			]
		);

		register_rest_route(
			'acx/v1',
			'/recognition/clusters/create-for-identity',
			[
				'methods'             => 'POST',
				'callback'            => [ $this, 'create_cluster_for_identity' ],
				'permission_callback' => [ $this, 'can_manage_recognition' ],
			]
		);

		register_rest_route(
			'acx/v1',
			'/recognition/clusters/recover-orphans',
			[
				'methods'             => 'POST',
				'callback'            => [ $this, 'recover_orphan_identities' ],
				'permission_callback' => [ $this, 'can_manage_recognition' ],
			]
		);

		register_rest_route(
			'acx/v1',
			'/recognition/media-identities',
			[
				'methods'             => 'GET',
				'callback'            => [ $this, 'get_media_identities' ],
				'permission_callback' => [ $this, 'can_manage_recognition' ],
				'args'                => [
				 'media_ids' => [
					 'type'        => 'array',
					 'required'    => true,
					 'items'       => [ 'type' => 'integer' ],
					 'description' => 'Attachment IDs to fetch detected identities for (max 100).',
				 ],
				 'include_debug' => [
					 'type'        => 'string',
					 'required'    => false,
					 'description' => 'Include debug metrics in response.',
				 ],
				],
			]
		);

		register_rest_route(
			'acx/v1',
			'/recognition/identities/(?P<identity_id>[a-f0-9-]+)/suggestions',
			[
				'methods'             => 'GET',
				'callback'            => [ $this, 'get_identity_suggestions' ],
				'permission_callback' => [ $this, 'can_manage_recognition' ],
			]
		);

		register_rest_route(
			'acx/v1',
			'/recognition/clusters/revert-merge',
			[
				'methods'             => 'POST',
				'callback'            => [ $this, 'revert_merge_cluster' ],
				'permission_callback' => [ $this, 'can_manage_recognition' ],
			]
		);

		register_rest_route(
			'acx/v1',
			'/recognition/suggestions',
			[
				'methods'             => 'GET',
				'callback'            => [ $this, 'get_pending_suggestions' ],
				'permission_callback' => [ $this, 'can_manage_recognition' ],
				'args'                => [
					'limit'  => [
						'type'        => 'integer',
						'default'     => 10,
						'description' => 'Maximum number of suggestions to return.',
					],
					'offset' => [
						'type'        => 'integer',
						'default'     => 0,
						'description' => 'Number of suggestions to skip.',
					],
				],
			]
		);

		register_rest_route(
			'acx/v1',
			'/recognition/suggestions/merge',
			[
				'methods'             => 'GET',
				'callback'            => [ $this, 'get_pending_merge_suggestions' ],
				'permission_callback' => [ $this, 'can_manage_recognition' ],
				'args'                => [
					'limit'  => [
						'type'        => 'integer',
						'default'     => 10,
						'description' => 'Maximum number of merge suggestions to return.',
					],
					'offset' => [
						'type'        => 'integer',
						'default'     => 0,
						'description' => 'Number of merge suggestions to skip.',
					],
				],
			]
		);

		register_rest_route(
			'acx/v1',
			'/recognition/suggestions/(?P<suggestion_id>[a-f0-9-]+)/accept',
			[
				'methods'             => 'POST',
				'callback'            => [ $this, 'accept_suggestion' ],
				'permission_callback' => [ $this, 'can_manage_recognition' ],
			]
		);

		register_rest_route(
			'acx/v1',
			'/recognition/suggestions/merge/(?P<suggestion_id>[a-f0-9-]+)/accept',
			[
				'methods'             => 'POST',
				'callback'            => [ $this, 'accept_merge_suggestion' ],
				'permission_callback' => [ $this, 'can_manage_recognition' ],
			]
		);

		register_rest_route(
			'acx/v1',
			'/recognition/suggestions/(?P<suggestion_id>[a-f0-9-]+)/reject',
			[
				'methods'             => 'POST',
				'callback'            => [ $this, 'reject_suggestion' ],
				'permission_callback' => [ $this, 'can_manage_recognition' ],
			]
		);

		register_rest_route(
			'acx/v1',
			'/recognition/suggestions/merge/(?P<suggestion_id>[a-f0-9-]+)/reject',
			[
				'methods'             => 'POST',
				'callback'            => [ $this, 'reject_merge_suggestion' ],
				'permission_callback' => [ $this, 'can_manage_recognition' ],
			]
		);
	}

	public function can_manage_recognition(): bool {
		return current_user_can( 'manage_options' );
	}

	public function analyze_media( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$media_items_param = $request->get_param( 'media_items' );
		$media_ids         = $request->get_param( 'media_ids' );
		$media_items       = array();

		if ( is_array( $media_items_param ) && count( $media_items_param ) > 0 ) {
			$media_items = array_values(
				array_filter(
					array_map( [ $this, 'sanitize_media_item' ], $media_items_param ),
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
					[ 'status' => 400 ]
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
			return new WP_Error( 'no_media_items', 'At least one media item is required', [ 'status' => 400 ] );
		}

		$payload = [
			'tenant_id'   => $this->get_tenant_id(),
			'site_url'    => get_site_url(),
			'media_items' => $media_items,
			'user_id'     => get_current_user_id(),
		];

		return $this->proxy_request( 'POST', '/recognition/analyze', $payload );
	}

	public function get_job_status( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$job_id = sanitize_text_field( (string) $request->get_param( 'job_id' ) );
		if ( '' === $job_id ) {
			return new WP_Error( 'missing_job_id', 'Job ID is required.', [ 'status' => 400 ] );
		}

		return $this->proxy_request(
			'GET',
			sprintf( '/recognition/jobs/%s', $job_id ),
			[],
			[
				'tenant_id' => $this->get_tenant_id(),
			]
		);
	}

	public function stream_job_progress( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$job_id = sanitize_text_field( (string) $request->get_param( 'job_id' ) );
		if ( '' === $job_id ) {
			return new WP_Error( 'missing_job_id', 'Job ID is required.', [ 'status' => 400 ] );
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
				[],
				[
					'tenant_id' => $this->get_tenant_id(),
				]
			);

			if ( is_wp_error( $response ) ) {
				echo "event: error\n";
				echo 'data: ' . wp_json_encode( [ 'message' => $response->get_error_message() ] ) . "\n\n";
				@ob_flush();
				@flush();
				break;
			}

			if ( ! ( $response instanceof WP_REST_Response ) ) {
				echo "event: error\n";
				echo 'data: ' . wp_json_encode( [ 'message' => 'Unexpected response type.' ] ) . "\n\n";
				@ob_flush();
				@flush();
				break;
			}

			$status_code = $response->get_status();
			if ( 404 === $status_code ) {
				echo "event: error\n";
				echo 'data: ' . wp_json_encode( [ 'message' => 'Job not found.' ] ) . "\n\n";
				@ob_flush();
				@flush();
				break;
			}

			$data = $response->get_data();
			if ( ! is_array( $data ) ) {
				echo "event: error\n";
				echo 'data: ' . wp_json_encode( [ 'message' => 'Invalid job response.' ] ) . "\n\n";
				@ob_flush();
				@flush();
				break;
			}

			$progress  = is_array( $data['progress'] ?? null ) ? $data['progress'] : [];
			$completed = absint( $progress['completed'] ?? 0 );
			$total     = absint( $progress['total'] ?? 0 );
			$status    = isset( $data['status'] ) ? sanitize_text_field( (string) $data['status'] ) : 'pending';
			$phase     = isset( $progress['phase'] ) ? sanitize_text_field( (string) $progress['phase'] ) : null;
			$job_type  = isset( $data['type'] ) ? sanitize_text_field( (string) $data['type'] ) : 'analyze';
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
				$payload = [
					'type'      => $event_type,
					'job_id'    => $job_id,
					'status'    => $status,
					'completed' => $completed,
					'total'     => $total,
				];
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

			if ( in_array( $status, [ 'completed', 'failed' ], true ) ) {
				$done_payload = [
					'type'      => $event_type,
					'job_id'    => $job_id,
					'status'    => $status,
					'completed' => $completed,
					'total'     => $total,
				];
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
			return new WP_Error( 'missing_job_id', 'Job ID is required.', [ 'status' => 400 ] );
		}

		return $this->proxy_request(
			'POST',
			sprintf( '/recognition/jobs/%s/cancel', $job_id ),
			[],
			[
				'tenant_id' => $this->get_tenant_id(),
			]
		);
	}

	public function cluster_media( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$mode = sanitize_text_field( (string) ( $request->get_param( 'mode' ) ?? 'async' ) );
		if ( ! in_array( $mode, [ 'sync', 'async' ], true ) ) {
			return new WP_Error( 'invalid_mode', 'Mode must be sync or async.', [ 'status' => 400 ] );
		}

		$body = [
			'tenant_id' => $this->get_tenant_id(),
			'mode'      => $mode,
		];

		// Use the hybrid clustering endpoint which runs Chinese Whispers for unmatched identities
		return $this->proxy_request( 'POST', '/recognition/clustering/jobs', $body );
	}

	public function recover_orphan_identities( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$payload = [
			'tenant_id' => $this->get_tenant_id(),
		];

		return $this->proxy_request( 'POST', '/recognition/clusters/recover-orphans', $payload );
	}

	public function list_clusters( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$limit  = absint( $request->get_param( 'limit' ) ?? 50 );
		$limit  = min( $limit, 500 );
		$search = sanitize_text_field( (string) $request->get_param( 'search' ) );

		$query = [
			'tenant_id' => $this->get_tenant_id(),
			'limit'     => $limit,
			'offset'    => absint( $request->get_param( 'offset' ) ?? 0 ),
		];

		if ( 'true' === $request->get_param( 'labeled_only' ) ) {
			$query['labeled_only'] = 'true';
		}

		if ( '' !== $search ) {
			$query['search'] = $search;
		}

		return $this->proxy_request( 'GET', '/recognition/clusters', [], $query );
	}

	public function list_top_unlabeled_clusters( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$query = [
			'tenant_id' => $this->get_tenant_id(),
			'limit'     => absint( $request->get_param( 'limit' ) ?? 10 ),
		];

		$response = $this->proxy_request( 'GET', '/recognition/clusters/top-unlabeled', [], $query );
		if ( ! ( $response instanceof WP_REST_Response ) ) {
			return $response;
		}

		if ( 200 !== $response->get_status() ) {
			return $response;
		}

		$data = $response->get_data();
		if ( ! is_array( $data ) ) {
			return $response;
		}

		foreach ( $data as $cluster_index => $cluster ) {
			if ( ! is_array( $cluster ) ) {
				continue;
			}
			if ( ! isset( $cluster['representatives'] ) || ! is_array( $cluster['representatives'] ) ) {
				continue;
			}

			foreach ( $cluster['representatives'] as $rep_index => $rep ) {
				if ( ! is_array( $rep ) ) {
					continue;
				}

				$thumb_url = $rep['thumb_url'] ?? null;
				if ( ( ! is_string( $thumb_url ) || '' === $thumb_url ) && isset( $rep['thumbnail_url'] ) ) {
					$legacy_thumb = $rep['thumbnail_url'];
					if ( is_string( $legacy_thumb ) && '' !== $legacy_thumb ) {
						$thumb_url = $legacy_thumb;
					}
				}

				if ( ( ! is_string( $thumb_url ) || '' === $thumb_url ) && isset( $rep['media_id'] ) ) {
					$media_id = absint( $rep['media_id'] );
					if ( $media_id > 0 ) {
						$fallback_url = wp_get_attachment_url( $media_id );
						if ( is_string( $fallback_url ) && '' !== $fallback_url ) {
							$thumb_url = $fallback_url;
						}
					}
				}

				$cluster['representatives'][ $rep_index ]['thumb_url'] = is_string( $thumb_url ) && '' !== $thumb_url ? $thumb_url : null;
			}

			$data[ $cluster_index ] = $cluster;
		}

		$response->set_data( $data );
		return $response;
	}

	public function stream_cluster_events( WP_REST_Request $request ): WP_REST_Response|WP_Error {
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

		$last_ping = microtime( true );
		$tenant_id = $this->get_tenant_id();

		echo ": connected\n\n";
		@ob_flush();
		@flush();

		while ( ! connection_aborted() ) {
			$now = microtime( true );
			if ( $now - $last_ping >= 15 ) {
				echo "event: ping\n";
				echo 'data: ' . wp_json_encode(
					[
						'event_type' => 'heartbeat',
						'timestamp'  => gmdate( 'c' ),
						'tenant_id'  => $tenant_id,
					]
				) . "\n\n";
				@ob_flush();
				@flush();
				$last_ping = $now;
			}
			usleep( 250000 );
		}

		exit;
	}

	public function list_cluster_labels( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$query = [
			'tenant_id' => $this->get_tenant_id(),
		];

		return $this->proxy_request( 'GET', '/recognition/clusters/labels', [], $query );
	}

	public function get_training_stage( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$query = [
			'tenant_id' => $this->get_tenant_id(),
		];

		return $this->proxy_request( 'GET', '/recognition/training-stage', [], $query );
	}

	public function reassign_cluster_identity( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$identity_id = sanitize_text_field( (string) $request->get_param( 'identity_id' ) );
		if ( '' === $identity_id ) {
			return new WP_Error( 'missing_identity_id', 'Identity ID is required.', [ 'status' => 400 ] );
		}

		$target = $request->get_param( 'target_cluster_id' );
		$payload = [
			'tenant_id'         => $this->get_tenant_id(),
			'identity_id'       => $identity_id,
			'target_cluster_id' => $target ? sanitize_text_field( (string) $target ) : null,
			'user_id'           => get_current_user_id(),
		];
		$block_from_cluster = $request->get_param( 'block_from_cluster' );
		if ( null !== $block_from_cluster ) {
			$payload['block_from_cluster'] = rest_sanitize_boolean( $block_from_cluster );
		}

		return $this->proxy_request( 'POST', '/recognition/clusters/reassign', $payload );
	}

	public function get_cluster_detail( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$cluster_id = sanitize_text_field( (string) $request->get_param( 'cluster_id' ) );
		if ( '' === $cluster_id ) {
			return new WP_Error( 'missing_cluster_id', 'Cluster ID is required.', [ 'status' => 400 ] );
		}

		return $this->proxy_request(
			'GET',
			sprintf( '/recognition/clusters/%s', $cluster_id ),
			[],
			[ 'tenant_id' => $this->get_tenant_id() ]
		);
	}

	public function get_cluster_members( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$cluster_id = sanitize_text_field( (string) $request->get_param( 'cluster_id' ) );
		if ( '' === $cluster_id ) {
			return new WP_Error( 'missing_cluster_id', 'Cluster ID is required.', [ 'status' => 400 ] );
		}

		return $this->proxy_request(
			'GET',
			sprintf( '/recognition/clusters/%s/members', $cluster_id ),
			[],
			[ 'tenant_id' => $this->get_tenant_id() ]
		);
	}

	public function update_cluster_label( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$cluster_id = sanitize_text_field( (string) $request->get_param( 'cluster_id' ) );
		$label      = sanitize_text_field( (string) $request->get_param( 'label' ) );

		if ( '' === $cluster_id ) {
			return new WP_Error( 'missing_cluster_id', 'Cluster ID is required.', [ 'status' => 400 ] );
		}

		if ( '' === $label ) {
			return new WP_Error( 'missing_label', 'Label cannot be empty.', [ 'status' => 400 ] );
		}

		$payload = [
			'tenant_id' => $this->get_tenant_id(),
			'label'     => $label,
		];

		return $this->proxy_request( 'PATCH', sprintf( '/recognition/clusters/%s', $cluster_id ), $payload );
	}

	public function dismiss_cluster( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$cluster_id = sanitize_text_field( (string) $request->get_param( 'cluster_id' ) );
		if ( '' === $cluster_id ) {
			return new WP_Error( 'missing_cluster_id', 'Cluster ID is required.', [ 'status' => 400 ] );
		}

		return $this->proxy_request(
			'POST',
			sprintf( '/recognition/clusters/%s/dismiss', $cluster_id ),
			[],
			[ 'tenant_id' => $this->get_tenant_id() ]
		);
	}

	public function undismiss_cluster( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$cluster_id = sanitize_text_field( (string) $request->get_param( 'cluster_id' ) );
		if ( '' === $cluster_id ) {
			return new WP_Error( 'missing_cluster_id', 'Cluster ID is required.', [ 'status' => 400 ] );
		}

		return $this->proxy_request(
			'DELETE',
			sprintf( '/recognition/clusters/%s/dismiss', $cluster_id ),
			[],
			[ 'tenant_id' => $this->get_tenant_id() ]
		);
	}

	public function merge_cluster( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$source_id         = sanitize_text_field( (string) $request->get_param( 'source_id' ) );
		$target_cluster_id = sanitize_text_field( (string) $request->get_param( 'target_cluster_id' ) );
		$target_label      = sanitize_text_field( (string) $request->get_param( 'target_label' ) );

		if ( '' === $source_id ) {
			return new WP_Error( 'missing_source_id', 'Source cluster ID is required.', [ 'status' => 400 ] );
		}

		if ( '' === $target_cluster_id ) {
			return new WP_Error( 'missing_target_cluster_id', 'Target cluster ID is required.', [ 'status' => 400 ] );
		}

		$payload = [
			'tenant_id'         => $this->get_tenant_id(),
			'target_cluster_id' => $target_cluster_id,
		];

		if ( '' !== $target_label ) {
			$payload['target_label'] = $target_label;
		}

		return $this->proxy_request( 'POST', sprintf( '/recognition/clusters/%s/merge', $source_id ), $payload );
	}

	public function split_cluster( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$cluster_id = sanitize_text_field( (string) $request->get_param( 'cluster_id' ) );

		if ( '' === $cluster_id ) {
			return new WP_Error( 'missing_cluster_id', 'Cluster ID is required.', [ 'status' => 400 ] );
		}

		$n_clusters = absint( $request->get_param( 'n_clusters' ) ?? 0 );

		$payload = [
			'tenant_id'  => $this->get_tenant_id(),
			'n_clusters' => $n_clusters,
		];
		$anchor_identity_id = sanitize_text_field( (string) $request->get_param( 'anchor_identity_id' ) );
		if ( '' !== $anchor_identity_id ) {
			$payload['anchor_identity_id'] = $anchor_identity_id;
		}
		$split_mode = sanitize_text_field( (string) $request->get_param( 'split_mode' ) );
		if ( '' !== $split_mode ) {
			$payload['split_mode'] = $split_mode;
		}

		return $this->proxy_request( 'POST', sprintf( '/recognition/clusters/%s/split', $cluster_id ), $payload );
	}

	public function create_cluster_for_identity( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$identity_id = sanitize_text_field( (string) $request->get_param( 'identity_id' ) );
		$label       = sanitize_text_field( (string) $request->get_param( 'label' ) );

		if ( '' === $identity_id ) {
			return new WP_Error( 'missing_identity_id', 'Identity ID is required.', [ 'status' => 400 ] );
		}

		if ( '' === $label ) {
			return new WP_Error( 'missing_label', 'Label is required.', [ 'status' => 400 ] );
		}

		$payload = [
			'tenant_id'   => $this->get_tenant_id(),
			'identity_id' => $identity_id,
			'label'       => $label,
			'user_id'     => get_current_user_id(),
		];

		return $this->proxy_request( 'POST', '/recognition/clusters/create-for-identity', $payload );
	}

	public function get_media_identities( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$media_ids = $request->get_param( 'media_ids' );
		if ( ! is_array( $media_ids ) || empty( $media_ids ) ) {
			return new WP_Error( 'missing_media_ids', 'Provide one or more media_ids to fetch identities.', [ 'status' => 400 ] );
		}

		$ids = array();
		foreach ( $media_ids as $media_id ) {
			$abs = absint( $media_id );
			if ( $abs > 0 ) {
				$ids[] = $abs;
			}
		}

		if ( empty( $ids ) || count( $ids ) > 100 ) {
			return new WP_Error( 'invalid_media_ids', 'Provide between 1 and 100 valid attachment IDs.', [ 'status' => 400 ] );
		}

		$query = [
			'tenant_id' => $this->get_tenant_id(),
			'media_ids' => $ids,
		];

		// Forward include_debug param for development environments
		$include_debug = $request->get_param( 'include_debug' );
		if ( $include_debug ) {
			$query['include_debug'] = 'true';
		}

		$response = $this->proxy_request( 'GET', '/recognition/media/identities', [], $query );

		// Transform flat array response into identities_by_media format expected by frontend
		if ( $response instanceof WP_REST_Response && $response->get_status() === 200 ) {
			$data = $response->get_data();
			if ( is_array( $data ) ) {
				$grouped = [];
				foreach ( $data as $identity ) {
					if ( isset( $identity['media_id'] ) ) {
						$media_key = (string) $identity['media_id'];
						if ( ! isset( $grouped[ $media_key ] ) ) {
							$grouped[ $media_key ] = [];
						}
						$grouped[ $media_key ][] = $identity;
					}
				}
				return new WP_REST_Response( [ 'identities_by_media' => $grouped ], 200 );
			}
		}

		return $response;
	}

	public function get_identity_suggestions( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$identity_id = sanitize_text_field( (string) $request->get_param( 'identity_id' ) );

		if ( '' === $identity_id ) {
			return new WP_Error( 'missing_identity_id', 'Identity ID is required.', [ 'status' => 400 ] );
		}

		$query = [
			'tenant_id' => $this->get_tenant_id(),
			'top_k'     => absint( $request->get_param( 'top_k' ) ?? 5 ),
			'threshold' => (float) ( $request->get_param( 'threshold' ) ?? 0.6 ),
		];

		return $this->proxy_request(
			'GET',
			sprintf( '/recognition/identities/%s/suggestions', $identity_id ),
			[],
			$query
		);
	}

	public function revert_merge_cluster( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$target_cluster_id  = sanitize_text_field( (string) $request->get_param( 'target_cluster_id' ) );
		$moved_identity_ids = $request->get_param( 'moved_identity_ids' );
		$source_label       = $request->get_param( 'source_label' );

		if ( '' === $target_cluster_id ) {
			return new WP_Error( 'missing_target_cluster_id', 'Target cluster ID is required.', [ 'status' => 400 ] );
		}

		if ( ! is_array( $moved_identity_ids ) || empty( $moved_identity_ids ) ) {
			return new WP_Error( 'missing_moved_identity_ids', 'Provide one or more identity IDs to revert.', [ 'status' => 400 ] );
		}

		$sanitized_ids = array_map(
			static function ( $value ): string {
				return sanitize_text_field( (string) $value );
			},
			$moved_identity_ids
		);

		$payload = [
			'tenant_id'          => $this->get_tenant_id(),
			'target_cluster_id'  => $target_cluster_id,
			'moved_identity_ids' => $sanitized_ids,
			'source_label'       => $source_label ? sanitize_text_field( (string) $source_label ) : null,
			'user_id'            => get_current_user_id(),
		];

		return $this->proxy_request( 'POST', '/recognition/clusters/revert-merge', $payload );
	}

	public function get_pending_suggestions( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$query = [
			'tenant_id' => $this->get_tenant_id(),
			'limit'     => absint( $request->get_param( 'limit' ) ?? 10 ),
			'offset'    => absint( $request->get_param( 'offset' ) ?? 0 ),
		];

		return $this->proxy_request(
			'GET',
			'/recognition/suggestions',
			[],
			$query
		);
	}

	public function get_pending_merge_suggestions( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$query = [
			'tenant_id' => $this->get_tenant_id(),
			'limit'     => absint( $request->get_param( 'limit' ) ?? 10 ),
			'offset'    => absint( $request->get_param( 'offset' ) ?? 0 ),
		];

		return $this->proxy_request(
			'GET',
			'/recognition/suggestions/merge',
			[],
			$query
		);
	}

	public function accept_suggestion( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$suggestion_id = sanitize_text_field( (string) $request->get_param( 'suggestion_id' ) );

		if ( '' === $suggestion_id ) {
			return new WP_Error( 'missing_suggestion_id', 'Suggestion ID is required.', [ 'status' => 400 ] );
		}

		$payload = [
			'tenant_id' => $this->get_tenant_id(),
		];

		return $this->proxy_request(
			'POST',
			sprintf( '/recognition/suggestions/%s/accept', $suggestion_id ),
			$payload
		);
	}

	public function accept_merge_suggestion( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$suggestion_id = sanitize_text_field( (string) $request->get_param( 'suggestion_id' ) );

		if ( '' === $suggestion_id ) {
			return new WP_Error( 'missing_suggestion_id', 'Suggestion ID is required.', [ 'status' => 400 ] );
		}

		$payload = [
			'tenant_id' => $this->get_tenant_id(),
		];

		return $this->proxy_request(
			'POST',
			sprintf( '/recognition/suggestions/merge/%s/accept', $suggestion_id ),
			$payload
		);
	}

	public function reject_suggestion( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$suggestion_id = sanitize_text_field( (string) $request->get_param( 'suggestion_id' ) );

		if ( '' === $suggestion_id ) {
			return new WP_Error( 'missing_suggestion_id', 'Suggestion ID is required.', [ 'status' => 400 ] );
		}

		$payload = [
			'tenant_id' => $this->get_tenant_id(),
		];

		return $this->proxy_request(
			'POST',
			sprintf( '/recognition/suggestions/%s/reject', $suggestion_id ),
			$payload
		);
	}

	public function reject_merge_suggestion( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$suggestion_id = sanitize_text_field( (string) $request->get_param( 'suggestion_id' ) );

		if ( '' === $suggestion_id ) {
			return new WP_Error( 'missing_suggestion_id', 'Suggestion ID is required.', [ 'status' => 400 ] );
		}

		$payload = [
			'tenant_id' => $this->get_tenant_id(),
		];

		return $this->proxy_request(
			'POST',
			sprintf( '/recognition/suggestions/merge/%s/reject', $suggestion_id ),
			$payload
		);
	}

	public function validate_media_ids( $value, WP_REST_Request $request, string $param ): bool|WP_Error {
		if ( ! is_array( $value ) ) {
			return new WP_Error( 'invalid_media_ids', 'media_ids must be an array of attachment IDs.', [ 'status' => 400 ] );
		}

		$count = count( $value );
		if ( 0 === $count ) {
			return new WP_Error( 'missing_media_ids', 'Please provide one or more media IDs to analyze.', [ 'status' => 400 ] );
		}

		$max = $this->get_current_tier_batch_limit();
		if ( $count > $max ) {
			return new WP_Error(
				'too_many_media_ids',
				sprintf( 'media_ids supports at most %d items per request (received %d).', $max, $count ),
				[ 'status' => 400 ]
			);
		}

		return true;
	}

	private function proxy_request( string $method, string $path, array $body = [], array $query = [] ): WP_REST_Response|WP_Error {
		if ( '' === $this->recognition_base_url ) {
			return new WP_Error( 'recognition_not_configured', 'Recognition service URL is missing.', [ 'status' => 500 ] );
		}

		$base_url = untrailingslashit( $this->recognition_base_url );
		$url      = esc_url_raw( $base_url . $path );

		if ( ! empty( $query ) ) {
			$url = esc_url_raw( add_query_arg( $query, $url ) );
		}

		$headers = [
			'Content-Type' => 'application/json',
			'X-Tenant-ID'  => $this->get_tenant_id(),
		];

		if ( '' !== $this->api_key ) {
			$headers['X-API-Key'] = $this->api_key;
		}

		$options = [
			'headers' => $headers,
			'timeout' => in_array( $method, [ 'POST', 'PUT', 'PATCH' ], true ) ? 60 : 30,
			'body'    => ! empty( $body ) && 'GET' !== $method ? wp_json_encode( $body ) : null,
		];

		// Retry with exponential backoff for transient failures
		$max_retries    = 3;
		$base_delay_ms  = 500;
		$last_error     = null;

		for ( $attempt = 0; $attempt < $max_retries; $attempt++ ) {
			$response = wp_remote_request( $url, array_merge( $options, [ 'method' => $method ] ) );

			if ( is_wp_error( $response ) ) {
				$last_error = $response;
				// Retry on connection errors
				if ( $attempt < $max_retries - 1 ) {
					$delay_ms = $base_delay_ms * ( 2 ** $attempt ); // 500ms, 1000ms, 2000ms
					usleep( $delay_ms * 1000 );
					continue;
				}
				return $response;
			}

			$status = wp_remote_retrieve_response_code( $response );

			// Retry on 5xx server errors (not 4xx client errors)
			if ( $status >= 500 && $attempt < $max_retries - 1 ) {
				$delay_ms = $base_delay_ms * ( 2 ** $attempt );
				usleep( $delay_ms * 1000 );
				continue;
			}

			$response_body = wp_remote_retrieve_body( $response );
			return new WP_REST_Response( json_decode( $response_body, true ), $status );
		}

		// Should not reach here, but return last error if we do
		return $last_error ?? new WP_Error( 'proxy_failed', 'Request failed after retries.', [ 'status' => 502 ] );
	}

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

	private function sanitize_media_item( array $media_item ): array {
		return [
			'media_id'  => absint( $media_item['media_id'] ?? 0 ),
			'media_url' => esc_url_raw( (string) ( $media_item['media_url'] ?? '' ) ),
		];
	}

	private function get_tenant_id(): string {
		return md5( (string) get_site_url() );
	}
}
