<?php

declare(strict_types=1);

namespace AltContext\Api;

require_once __DIR__ . '/class-abstract-recognition-proxy-controller.php';
require_once __DIR__ . '/class-recognition-data-source.php';

use stdClass;
use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

use function absint;
use function array_fill;
use function array_keys;
use function array_values;
use function count;
use function implode;
use function is_array;
use function range;
use function sanitize_text_field;
use function sprintf;

class SuggestionsController extends AbstractRecognitionProxyController {
	private const DATA_SOURCE_BACKEND_PROXY = RecognitionDataSource::BACKEND_PROXY;
	private const DATA_SOURCE_ENDPOINT_ERROR = RecognitionDataSource::ENDPOINT_ERROR;
	private const DATA_SOURCE_UNAVAILABLE = RecognitionDataSource::UNAVAILABLE;
	private const REQUEST_CLASS_POST_SCAN_READ = 'post_scan_read';

	public function register_routes(): void {
		register_rest_route(
			'acx/v1',
			'/recognition/identities/(?P<identity_id>[a-f0-9-]+)/suggestions',
			array(
				'methods'             => 'GET',
				'callback'            => array( $this, 'get_identity_suggestions' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
			)
		);

		register_rest_route(
			'acx/v1',
			'/recognition/identities/suggestions',
			array(
				'methods'             => 'GET',
				'callback'            => array( $this, 'get_identities_suggestions' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
				'args'                => array(
					'identity_ids' => array(
						// 'array' would trigger rest_sanitize_array -> wp_parse_list, splitting
						// the comma-joined scalar so add_query_arg emits identity_ids[0]=...,
						// which binds nothing on the FastAPI side. Must stay 'string'.
						'type'        => 'string',
						'required'    => true,
						'description' => 'Comma-joined identity UUIDs (max 100), forwarded unchanged.',
					),
					'top_k'        => array(
						'type'        => 'integer',
						'default'     => 1,
						'description' => 'Maximum suggestions per identity.',
					),
				),
			)
		);

		register_rest_route(
			'acx/v1',
			'/recognition/suggestions',
			array(
				'methods'             => 'GET',
				'callback'            => array( $this, 'get_pending_suggestions' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
				'args'                => array(
					'limit'  => array(
						'type'        => 'integer',
						'default'     => 10,
						'description' => 'Maximum number of suggestions to return.',
					),
					'offset' => array(
						'type'        => 'integer',
						'default'     => 0,
						'description' => 'Number of suggestions to skip.',
					),
				),
			)
		);

		register_rest_route(
			'acx/v1',
			'/recognition/suggestions/merge',
			array(
				'methods'             => 'GET',
				'callback'            => array( $this, 'get_pending_merge_suggestions' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
				'args'                => array(
					'limit'  => array(
						'type'        => 'integer',
						'default'     => 10,
						'description' => 'Maximum number of merge suggestions to return.',
					),
					'offset' => array(
						'type'        => 'integer',
						'default'     => 0,
						'description' => 'Number of merge suggestions to skip.',
					),
				),
			)
		);

		register_rest_route(
			'acx/v1',
			'/recognition/suggestions/(?P<suggestion_id>[a-f0-9-]+)/accept',
			array(
				'methods'             => 'POST',
				'callback'            => array( $this, 'accept_suggestion' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
			)
		);

		register_rest_route(
			'acx/v1',
			'/recognition/suggestions/merge/(?P<suggestion_id>[a-f0-9-]+)/accept',
			array(
				'methods'             => 'POST',
				'callback'            => array( $this, 'accept_merge_suggestion' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
			)
		);

		register_rest_route(
			'acx/v1',
			'/recognition/suggestions/(?P<suggestion_id>[a-f0-9-]+)/reject',
			array(
				'methods'             => 'POST',
				'callback'            => array( $this, 'reject_suggestion' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
			)
		);

		register_rest_route(
			'acx/v1',
			'/recognition/suggestions/merge/(?P<suggestion_id>[a-f0-9-]+)/reject',
			array(
				'methods'             => 'POST',
				'callback'            => array( $this, 'reject_merge_suggestion' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
			)
		);

		register_rest_route(
			'acx/v1',
			'/recognition/suggestions/name',
			array(
				'methods'             => 'GET',
				'callback'            => array( $this, 'list_name_suggestions' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
				'args'                => array(
					'min_confidence' => array(
						'type'    => 'number',
						'default' => 0.0,
					),
					'limit'          => array(
						'type'    => 'integer',
						'default' => 25,
					),
					'offset'         => array(
						'type'    => 'integer',
						'default' => 0,
					),
				),
			)
		);

		register_rest_route(
			'acx/v1',
			'/recognition/suggestions/name/(?P<suggestion_id>[a-f0-9-]+)/accept',
			array(
				'methods'             => 'POST',
				'callback'            => array( $this, 'accept_name_suggestion' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
			)
		);

		register_rest_route(
			'acx/v1',
			'/recognition/suggestions/name/(?P<suggestion_id>[a-f0-9-]+)/reject',
			array(
				'methods'             => 'POST',
				'callback'            => array( $this, 'reject_name_suggestion' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
			)
		);

		register_rest_route(
			'acx/v1',
			'/recognition/clusters/(?P<cluster_id>[a-f0-9-]+)/roster-candidates',
			array(
				'methods'             => 'GET',
				'callback'            => array( $this, 'get_roster_candidates' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
				'args'                => array(
					'top_k' => array(
						'type'        => 'integer',
						'default'     => 10,
						'description' => 'Maximum ranked candidates to return (service max 50).',
					),
				),
			)
		);

		register_rest_route(
			'acx/v1',
			'/recognition/suggestions/bulk-accept',
			array(
				'methods'             => 'POST',
				'callback'            => array( $this, 'bulk_accept_suggestions' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
				'args'                => array(
					'suggestion_type' => array(
						'type'     => 'string',
						'required' => true,
					),
					'min_confidence'  => array(
						'type'    => 'number',
						'default' => 0.0,
					),
				),
			)
		);
	}

	public function get_identity_suggestions( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$identity_id = sanitize_text_field( (string) $request->get_param( 'identity_id' ) );

		if ( '' === $identity_id ) {
			return new WP_Error( 'missing_identity_id', 'Identity ID is required.', array( 'status' => 400 ) );
		}

		// No 'threshold': the recognition route accepts only min_confidence, so the
		// old param never bound (UXP-3 0b-5 dead-param removal).
		$query = array(
			'tenant_id' => $this->get_tenant_id(),
			'top_k'     => absint( $request->get_param( 'top_k' ) ?? 5 ),
		);

		$response = $this->proxy_request(
			'GET',
			sprintf( '/recognition/identities/%s/suggestions', $identity_id ),
			array(),
			$query
		);
		if ( $this->is_backend_overloaded( $response ) ) {
			return parent::backend_overloaded_response( $response );
		}
		// BR-08: the offline path must carry data_source so the UI can tell
		// "backend unreachable/erroring" from "genuinely no matches". matches is a
		// list for a single identity, so its empty shape stays [].
		// A refused 3xx is reachable-but-bad (ENDPOINT_ERROR), not UNAVAILABLE.
		if ( $this->is_proxy_redirect_refused( $response ) || $this->is_proxy_endpoint_error( $response ) ) {
			return new WP_REST_Response(
				array(
					'matches' => array(),
					'data_source' => self::DATA_SOURCE_ENDPOINT_ERROR,
				),
				200
			);
		}
		if ( $this->is_proxy_transport_unreachable( $response ) ) {
			return new WP_REST_Response(
				array(
					'matches' => array(),
					'data_source' => self::DATA_SOURCE_UNAVAILABLE,
				),
				200
			);
		}

		return $response;
	}

	public function get_identities_suggestions( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$identity_ids = sanitize_text_field( (string) $request->get_param( 'identity_ids' ) );

		if ( '' === $identity_ids ) {
			return new WP_Error( 'missing_identity_ids', 'Identity IDs are required.', array( 'status' => 400 ) );
		}

		$query = array(
			'tenant_id'    => $this->get_tenant_id(),
			// Forwarded as the unchanged comma-joined scalar; FastAPI validates
			// each id and rejects over-limit lists (>100) with 400.
			'identity_ids' => $identity_ids,
			'top_k'        => absint( $request->get_param( 'top_k' ) ?? 1 ),
		);

		$response = $this->proxy_request(
			'GET',
			'/recognition/identities/suggestions',
			array(),
			$query
		);
		if ( $this->is_backend_overloaded( $response ) ) {
			return parent::backend_overloaded_response( $response );
		}
		// BR-08: keyed-by-id envelope — empty mapping serializes as {} not [] — and
		// the offline path must carry data_source so the UI distinguishes
		// unreachable/erroring from a genuine empty result.
		// A refused 3xx is reachable-but-bad (ENDPOINT_ERROR), not UNAVAILABLE.
		if ( $this->is_proxy_redirect_refused( $response ) || $this->is_proxy_endpoint_error( $response ) ) {
			return new WP_REST_Response(
				array(
					'matches' => new stdClass(),
					'data_source' => self::DATA_SOURCE_ENDPOINT_ERROR,
				),
				200
			);
		}
		if ( $this->is_proxy_transport_unreachable( $response ) ) {
			return new WP_REST_Response(
				array(
					'matches' => new stdClass(),
					'data_source' => self::DATA_SOURCE_UNAVAILABLE,
				),
				200
			);
		}

		return $response;
	}

	public function get_roster_candidates( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$cluster_id = sanitize_text_field( (string) $request->get_param( 'cluster_id' ) );

		if ( '' === $cluster_id ) {
			return new WP_Error( 'missing_cluster_id', 'Cluster ID is required.', array( 'status' => 400 ) );
		}

		$query = array(
			'tenant_id' => $this->get_tenant_id(),
			'top_k'     => absint( $request->get_param( 'top_k' ) ?? 10 ),
		);

		$response = $this->proxy_request(
			'GET',
			sprintf( '/recognition/clusters/%s/roster-candidates', $cluster_id ),
			array(),
			$query
		);
		if ( $this->is_backend_overloaded( $response ) ) {
			return parent::backend_overloaded_response( $response );
		}
		if ( $this->is_proxy_redirect_refused( $response ) || $this->is_proxy_endpoint_error( $response ) ) {
			return new WP_REST_Response(
				array(
					'candidates'  => array(),
					'data_source' => self::DATA_SOURCE_ENDPOINT_ERROR,
				),
				200
			);
		}
		if ( $this->is_proxy_transport_unreachable( $response ) ) {
			return new WP_REST_Response(
				array(
					'candidates'  => array(),
					'data_source' => self::DATA_SOURCE_UNAVAILABLE,
				),
				200
			);
		}

		if ( $response instanceof WP_REST_Response ) {
			$data = $response->get_data();
			if ( is_array( $data ) ) {
				$response->set_data( $this->attach_roster_entry_ids( $data ) );
			}
		}

		return $response;
	}

	/**
	 * Map python labelled cluster_id → local acx_persons.id. Never invents total/limit.
	 *
	 * @param array<string,mixed> $payload
	 * @return array<string,mixed>
	 */
	private function attach_roster_entry_ids( array $payload ): array {
		$candidates = $payload['candidates'] ?? null;
		if ( ! is_array( $candidates ) || array() === $candidates ) {
			return $payload;
		}

		$cluster_ids = array();
		foreach ( $candidates as $candidate ) {
			if ( ! is_array( $candidate ) ) {
				continue;
			}
			$uuid = sanitize_text_field( (string) ( $candidate['cluster_id'] ?? '' ) );
			if ( '' !== $uuid ) {
				$cluster_ids[ $uuid ] = $uuid;
			}
		}

		$person_by_cluster = $this->lookup_person_ids_for_clusters( array_values( $cluster_ids ) );
		foreach ( $candidates as $index => $candidate ) {
			if ( ! is_array( $candidate ) ) {
				continue;
			}
			$uuid = sanitize_text_field( (string) ( $candidate['cluster_id'] ?? '' ) );
			$person_id = $person_by_cluster[ $uuid ] ?? null;
			$candidates[ $index ]['roster_entry_id'] = null !== $person_id ? (int) $person_id : null;
		}
		$payload['candidates'] = $candidates;
		return $payload;
	}

	/**
	 * @param list<string> $cluster_ids
	 * @return array<string,int>
	 */
	private function lookup_person_ids_for_clusters( array $cluster_ids ): array {
		if ( array() === $cluster_ids ) {
			return array();
		}

		global $wpdb;
		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'get_results' ) ) {
			return array();
		}

		$table        = $wpdb->prefix . 'acx_clusters';
		$placeholders = implode( ',', array_fill( 0, count( $cluster_ids ), '%s' ) );
		$sql          = $wpdb->prepare(
			"SELECT cluster_uuid, person_id FROM %i WHERE cluster_uuid IN ({$placeholders})",
			$table,
			...$cluster_ids
		);
		$rows = $wpdb->get_results( $sql, ARRAY_A );
		if ( ! is_array( $rows ) ) {
			return array();
		}

		$mapped = array();
		foreach ( $rows as $row ) {
			if ( ! is_array( $row ) ) {
				continue;
			}
			$uuid = sanitize_text_field( (string) ( $row['cluster_uuid'] ?? '' ) );
			if ( '' === $uuid || ! isset( $row['person_id'] ) || '' === (string) $row['person_id'] ) {
				continue;
			}
			$mapped[ $uuid ] = (int) $row['person_id'];
		}
		return $mapped;
	}

	public function get_pending_suggestions( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$query = array(
			'tenant_id' => $this->get_tenant_id(),
			'limit'     => absint( $request->get_param( 'limit' ) ?? 10 ),
			'offset'    => absint( $request->get_param( 'offset' ) ?? 0 ),
		);

		$response = $this->proxy_request(
			'GET',
			'/recognition/suggestions',
			array(),
			$query,
			self::REQUEST_CLASS_POST_SCAN_READ
		);
		if ( $this->is_backend_overloaded( $response ) ) {
			return parent::backend_overloaded_response( $response );
		}
		if ( $this->is_proxy_redirect_refused( $response ) ) {
			return $this->empty_pending_suggestions_response( (int) $query['limit'], (int) $query['offset'], self::DATA_SOURCE_ENDPOINT_ERROR );
		}
		if ( is_wp_error( $response ) ) {
			return $this->empty_pending_suggestions_response( (int) $query['limit'], (int) $query['offset'] );
		}
		if ( $response instanceof WP_REST_Response && $response->get_status() >= 500 ) {
			return $this->empty_pending_suggestions_response( (int) $query['limit'], (int) $query['offset'], self::DATA_SOURCE_ENDPOINT_ERROR );
		}

		return $this->normalize_pending_suggestions_response( $response, (int) $query['limit'], (int) $query['offset'] );
	}

	public function get_pending_merge_suggestions( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$query = array(
			'tenant_id' => $this->get_tenant_id(),
			'limit'     => absint( $request->get_param( 'limit' ) ?? 10 ),
			'offset'    => absint( $request->get_param( 'offset' ) ?? 0 ),
		);

		$response = $this->proxy_request(
			'GET',
			'/recognition/suggestions/merge',
			array(),
			$query,
			self::REQUEST_CLASS_POST_SCAN_READ
		);
		if ( $this->is_backend_overloaded( $response ) ) {
			return parent::backend_overloaded_response( $response );
		}
		if ( $this->is_proxy_redirect_refused( $response ) ) {
			return $this->empty_pending_suggestions_response( (int) $query['limit'], (int) $query['offset'], self::DATA_SOURCE_ENDPOINT_ERROR );
		}
		if ( is_wp_error( $response ) ) {
			return $this->empty_pending_suggestions_response( (int) $query['limit'], (int) $query['offset'] );
		}
		if ( $response instanceof WP_REST_Response && $response->get_status() >= 500 ) {
			return $this->empty_pending_suggestions_response( (int) $query['limit'], (int) $query['offset'], self::DATA_SOURCE_ENDPOINT_ERROR );
		}

		return $this->normalize_pending_suggestions_response( $response, (int) $query['limit'], (int) $query['offset'] );
	}

	public function accept_suggestion( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$suggestion_id = sanitize_text_field( (string) $request->get_param( 'suggestion_id' ) );

		if ( '' === $suggestion_id ) {
			return new WP_Error( 'missing_suggestion_id', 'Suggestion ID is required.', array( 'status' => 400 ) );
		}

		$payload = array(
			'tenant_id' => $this->get_tenant_id(),
		);

		return $this->proxy_request(
			'POST',
			sprintf( '/recognition/suggestions/%s/accept', $suggestion_id ),
			$payload
		);
	}

	public function accept_merge_suggestion( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$suggestion_id = sanitize_text_field( (string) $request->get_param( 'suggestion_id' ) );

		if ( '' === $suggestion_id ) {
			return new WP_Error( 'missing_suggestion_id', 'Suggestion ID is required.', array( 'status' => 400 ) );
		}

		$payload = array(
			'tenant_id' => $this->get_tenant_id(),
		);

		return $this->proxy_request(
			'POST',
			sprintf( '/recognition/suggestions/merge/%s/accept', $suggestion_id ),
			$payload
		);
	}

	public function reject_suggestion( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$suggestion_id = sanitize_text_field( (string) $request->get_param( 'suggestion_id' ) );

		if ( '' === $suggestion_id ) {
			return new WP_Error( 'missing_suggestion_id', 'Suggestion ID is required.', array( 'status' => 400 ) );
		}

		$payload = array(
			'tenant_id' => $this->get_tenant_id(),
		);

		return $this->proxy_request(
			'POST',
			sprintf( '/recognition/suggestions/%s/reject', $suggestion_id ),
			$payload
		);
	}

	public function reject_merge_suggestion( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$suggestion_id = sanitize_text_field( (string) $request->get_param( 'suggestion_id' ) );

		if ( '' === $suggestion_id ) {
			return new WP_Error( 'missing_suggestion_id', 'Suggestion ID is required.', array( 'status' => 400 ) );
		}

		$payload = array(
			'tenant_id' => $this->get_tenant_id(),
		);

		return $this->proxy_request(
			'POST',
			sprintf( '/recognition/suggestions/merge/%s/reject', $suggestion_id ),
			$payload
		);
	}

	public function list_name_suggestions( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$query = array(
			'tenant_id'      => $this->get_tenant_id(),
			'min_confidence' => (float) ( $request->get_param( 'min_confidence' ) ?? 0.0 ),
			'limit'          => absint( $request->get_param( 'limit' ) ?? 25 ),
			'offset'         => absint( $request->get_param( 'offset' ) ?? 0 ),
		);

		$response = $this->proxy_request(
			'GET',
			'/recognition/suggestions/name',
			array(),
			$query,
			self::REQUEST_CLASS_POST_SCAN_READ
		);
		if ( $this->is_backend_overloaded( $response ) ) {
			return parent::backend_overloaded_response( $response );
		}
		// A refused 3xx is reachable-but-bad (ENDPOINT_ERROR), not UNAVAILABLE.
		// Keep the pre-existing is_proxy_unavailable mapping for transport
		// errors and 5xx (UNAVAILABLE) — only the 3xx case is reclassified.
		if ( $this->is_proxy_redirect_refused( $response ) ) {
			return $this->empty_pending_name_suggestions_response( (int) $query['limit'], (int) $query['offset'], self::DATA_SOURCE_ENDPOINT_ERROR );
		}
		if ( $this->is_proxy_unavailable( $response ) ) {
			return $this->empty_pending_name_suggestions_response( (int) $query['limit'], (int) $query['offset'] );
		}

		return $this->normalize_pending_name_suggestions_response( $response, (int) $query['limit'], (int) $query['offset'] );
	}

	public function accept_name_suggestion( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$suggestion_id = sanitize_text_field( (string) $request->get_param( 'suggestion_id' ) );

		if ( '' === $suggestion_id ) {
			return new WP_Error( 'missing_suggestion_id', 'Suggestion ID is required.', array( 'status' => 400 ) );
		}

		$payload = array(
			'tenant_id' => $this->get_tenant_id(),
		);

		return $this->proxy_request(
			'POST',
			sprintf( '/recognition/suggestions/name/%s/accept', $suggestion_id ),
			$payload
		);
	}

	public function reject_name_suggestion( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$suggestion_id = sanitize_text_field( (string) $request->get_param( 'suggestion_id' ) );

		if ( '' === $suggestion_id ) {
			return new WP_Error( 'missing_suggestion_id', 'Suggestion ID is required.', array( 'status' => 400 ) );
		}

		$payload = array(
			'tenant_id' => $this->get_tenant_id(),
		);

		return $this->proxy_request(
			'POST',
			sprintf( '/recognition/suggestions/name/%s/reject', $suggestion_id ),
			$payload
		);
	}

	public function bulk_accept_suggestions( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$suggestion_type = sanitize_text_field( (string) ( $request->get_param( 'suggestion_type' ) ?? '' ) );
		if ( '' === $suggestion_type ) {
			return new WP_Error( 'missing_suggestion_type', 'Suggestion type is required.', array( 'status' => 400 ) );
		}

		$payload = array(
			'tenant_id'       => $this->get_tenant_id(),
			'suggestion_type' => $suggestion_type,
			'min_confidence'  => (float) ( $request->get_param( 'min_confidence' ) ?? 0.0 ),
		);

		$response = $this->proxy_request(
			'POST',
			'/recognition/suggestions/bulk-accept',
			$payload
		);
		if ( $this->is_backend_overloaded( $response ) ) {
			return parent::backend_overloaded_response( $response );
		}
		// BR-08: carry data_source on the offline path so a no-op bulk-accept
		// caused by an unreachable/erroring backend is distinguishable from a
		// genuine "nothing to accept" result.
		// A refused 3xx is reachable-but-bad (ENDPOINT_ERROR), not UNAVAILABLE.
		if ( $this->is_proxy_redirect_refused( $response ) || $this->is_proxy_endpoint_error( $response ) ) {
			return new WP_REST_Response(
				array(
					'accepted_count' => 0,
					'skipped_count'  => 0,
					'data_source'    => self::DATA_SOURCE_ENDPOINT_ERROR,
				),
				200
			);
		}
		if ( $this->is_proxy_transport_unreachable( $response ) ) {
			return new WP_REST_Response(
				array(
					'accepted_count' => 0,
					'skipped_count'  => 0,
					'data_source'    => self::DATA_SOURCE_UNAVAILABLE,
				),
				200
			);
		}

		return $response;
	}
	private function empty_pending_suggestions_response( int $limit, int $offset, string $data_source = self::DATA_SOURCE_UNAVAILABLE ): WP_REST_Response {
		// COR-3 (rg-015): no authoritative total exists for a single bare page; omit it
		// rather than claim a fabricated count. Consumers count loaded suggestions.
		return new WP_REST_Response(
			array(
				'suggestions' => array(),
				'limit'       => $limit,
				'offset'      => $offset,
				'data_source' => $data_source,
			),
			200
		);
	}

	private function empty_pending_name_suggestions_response( int $limit, int $offset, string $data_source = self::DATA_SOURCE_UNAVAILABLE ): WP_REST_Response {
		return new WP_REST_Response(
			array(
				'suggestions' => array(),
				'limit'       => $limit,
				'offset'      => $offset,
				'data_source' => $data_source,
			),
			200
		);
	}

	private function normalize_pending_suggestions_response( WP_REST_Response|WP_Error $response, int $limit, int $offset ): WP_REST_Response|WP_Error {
		if ( ! $response instanceof WP_REST_Response || 200 !== $response->get_status() ) {
			return $response;
		}

		$data = $response->get_data();
		if ( ! is_array( $data ) ) {
			return $response;
		}

		if ( ! $this->is_list_payload( $data ) ) {
			return new WP_Error(
				'invalid_suggestions_payload',
				'Suggestions payload must be a JSON array.',
				array( 'status' => 502 )
			);
		}

		return new WP_REST_Response(
			array(
				'suggestions' => $data,
				'limit'       => $limit,
				'offset'      => $offset,
				'data_source' => self::DATA_SOURCE_BACKEND_PROXY,
			),
			200
		);
	}

	private function normalize_pending_name_suggestions_response( WP_REST_Response|WP_Error $response, int $limit, int $offset ): WP_REST_Response|WP_Error {
		if ( ! $response instanceof WP_REST_Response || 200 !== $response->get_status() ) {
			return $response;
		}

		$data = $response->get_data();
		if ( ! is_array( $data ) ) {
			return $response;
		}

		if ( ! $this->is_list_payload( $data ) ) {
			return new WP_Error(
				'invalid_name_suggestions_payload',
				'Name suggestions payload must be a JSON array.',
				array( 'status' => 502 )
			);
		}

		return new WP_REST_Response(
			array(
				'suggestions' => $data,
				'limit'       => $limit,
				'offset'      => $offset,
				'data_source' => self::DATA_SOURCE_BACKEND_PROXY,
			),
			200
		);
	}

	private function is_list_payload( array $data ): bool {
		if ( array() === $data ) {
			return true;
		}

		return array_keys( $data ) === range( 0, count( $data ) - 1 );
	}
}
