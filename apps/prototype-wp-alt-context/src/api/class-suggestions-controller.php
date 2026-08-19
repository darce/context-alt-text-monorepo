<?php

declare(strict_types=1);

namespace AltContext\Api;

require_once __DIR__ . '/class-abstract-recognition-proxy-controller.php';
require_once __DIR__ . '/class-recognition-data-source.php';
require_once __DIR__ . '/../sovereign/class-projection-query-exception.php';
require_once __DIR__ . '/../sovereign/repositories/class-clusters-read-repository.php';

use AltContext\Sovereign\ProjectionQueryException;
use AltContext\Sovereign\Repositories\ClustersReadRepository;
use stdClass;
use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

use function absint;
use function array_keys;
use function array_slice;
use function array_values;
use function count;
use function is_array;
use function is_int;
use function is_numeric;
use function is_object;
use function is_string;
use function range;
use function sanitize_text_field;
use function sprintf;
use function usort;

class SuggestionsController extends AbstractRecognitionProxyController {
	private const DATA_SOURCE_BACKEND_PROXY = RecognitionDataSource::BACKEND_PROXY;
	private const DATA_SOURCE_ENDPOINT_ERROR = RecognitionDataSource::ENDPOINT_ERROR;
	private const DATA_SOURCE_UNAVAILABLE = RecognitionDataSource::UNAVAILABLE;
	private const REQUEST_CLASS_POST_SCAN_READ = 'post_scan_read';
	private const ROSTER_CANDIDATES_TOP_K_MIN = 1;
	private const ROSTER_CANDIDATES_TOP_K_MAX = 50;
	/** Coupled to recognition.application.suggestions.roster_candidates.MAX_ROSTER_CANDIDATES_TOP_K (roster_candidates.py:19). */
	private const ROSTER_CANDIDATES_PYTHON_WINDOW = 50;
	private const INVALID_TOP_K_CODE = 'invalid_top_k';
	private const INVALID_TOP_K_MESSAGE = 'top_k must be an integer between 1 and 50.';

	private ?ClustersReadRepository $clusters_read_repository;

	public function __construct( ?ClustersReadRepository $clusters_read_repository = null ) {
		$this->clusters_read_repository = $clusters_read_repository;
	}

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
						'minimum'     => self::ROSTER_CANDIDATES_TOP_K_MIN,
						'maximum'     => self::ROSTER_CANDIDATES_TOP_K_MAX,
						'description' => sprintf(
							'People-grain cap (%d-%d) applied after PHP collapses upstream cluster rows to one row per roster person. Not forwarded upstream: PHP always requests the full %d-row cluster-grain window.',
							self::ROSTER_CANDIDATES_TOP_K_MIN,
							self::ROSTER_CANDIDATES_TOP_K_MAX,
							self::ROSTER_CANDIDATES_PYTHON_WINDOW
						),
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

	private function validate_roster_candidates_top_k( $value ): bool|WP_Error {
		if ( ! is_numeric( $value ) ) {
			return $this->invalid_top_k_error();
		}
		$int = (int) $value;
		if ( $int >= self::ROSTER_CANDIDATES_TOP_K_MIN
			&& $int <= self::ROSTER_CANDIDATES_TOP_K_MAX
			&& (float) $value === (float) $int ) {
			return true;
		}
		return $this->invalid_top_k_error();
	}

	private function invalid_top_k_error(): WP_Error {
		return new WP_Error( self::INVALID_TOP_K_CODE, self::INVALID_TOP_K_MESSAGE, array( 'status' => 400 ) );
	}

	public function get_roster_candidates( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$cluster_id = sanitize_text_field( (string) $request->get_param( 'cluster_id' ) );

		if ( '' === $cluster_id ) {
			return new WP_Error( 'missing_cluster_id', 'Cluster ID is required.', array( 'status' => 400 ) );
		}

		$raw_top_k = $request->get_param( 'top_k' );
		if ( null === $raw_top_k || '' === $raw_top_k ) {
			$raw_top_k = 10;
		}
		$valid_top_k = $this->validate_roster_candidates_top_k( $raw_top_k );
		if ( $valid_top_k instanceof WP_Error ) {
			return $valid_top_k;
		}
		$top_k = (int) $raw_top_k;

		$query = array(
			'tenant_id' => $this->get_tenant_id(),
			// Cluster-grain window: fetch the Python max so a person split across
			// N clusters cannot starve later people before PHP collapses + slices.
			'top_k'     => self::ROSTER_CANDIDATES_PYTHON_WINDOW,
		);

		$response = $this->proxy_request(
			'GET',
			sprintf( '/recognition/clusters/%s/roster-candidates', $cluster_id ),
			array(),
			$query,
			self::REQUEST_CLASS_POST_SCAN_READ
		);
		if ( $this->is_backend_overloaded( $response ) ) {
			return parent::backend_overloaded_response( $response );
		}
		if ( $this->is_proxy_redirect_refused( $response ) || $this->is_proxy_endpoint_error( $response, 400 ) ) {
			return new WP_Error(
				'recognition_endpoint_error',
				'Recognition roster-candidates endpoint is unavailable.',
				array( 'status' => 502 )
			);
		}
		if ( $this->is_proxy_transport_unreachable( $response ) ) {
			return new WP_Error(
				'recognition_unavailable',
				'Recognition service is unreachable.',
				array( 'status' => 503 )
			);
		}

		if ( $response instanceof WP_REST_Response ) {
			$data = $response->get_data();
			if ( is_array( $data ) ) {
				try {
					$response->set_data( $this->attach_roster_entry_ids( $data, $top_k ) );
				} catch ( ProjectionQueryException $exception ) {
					return ProjectionQueryException::to_rest_error( 'get_roster_candidates' );
				}
			}
		}

		return $response;
	}

	/**
	 * Map python labelled cluster_id → local acx_persons.id. Collapse to one row
	 * per roster_entry_id (max similarity wins, keep that row's band + name).
	 * Re-sort committable first, then similarity DESC, cluster_id ASC, then
	 * slice people-grain top_k. Unmapped rows keep roster_entry_id null
	 * (uncommittable) and do not occupy top_k slots ahead of committable rows.
	 * Never invents total/limit.
	 *
	 * @param array<string,mixed> $payload
	 * @return array<string,mixed>
	 */
	private function attach_roster_entry_ids( array $payload, int $top_k ): array {
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

		$lookup            = $this->clusters_read_repository()->lookup_person_ids_for_clusters(
			$this->get_tenant_id(),
			array_values( $cluster_ids )
		);
		$person_by_cluster = array();
		$name_by_cluster   = array();
		foreach ( $lookup as $row ) {
			$uuid = sanitize_text_field( (string) ( $row['cluster_uuid'] ?? '' ) );
			if ( '' === $uuid ) {
				continue;
			}
			$person_by_cluster[ $uuid ] = $row['person_id'] ?? null;
			if ( isset( $row['name'] ) && is_string( $row['name'] ) && '' !== $row['name'] ) {
				$name_by_cluster[ $uuid ] = $row['name'];
			}
		}

		$collapsed        = array();
		$index_by_person  = array();
		foreach ( $candidates as $candidate ) {
			if ( ! is_array( $candidate ) ) {
				continue;
			}
			$uuid                         = sanitize_text_field( (string) ( $candidate['cluster_id'] ?? '' ) );
			$person_id                    = $person_by_cluster[ $uuid ] ?? null;
			$person_id                    = is_int( $person_id ) ? $person_id : null;
			$candidate['roster_entry_id'] = $person_id;
			if ( isset( $name_by_cluster[ $uuid ] ) ) {
				$candidate['name'] = $name_by_cluster[ $uuid ];
			}
			if ( null !== $person_id && isset( $index_by_person[ $person_id ] ) ) {
				$existing_idx = $index_by_person[ $person_id ];
				$existing_sim = (float) ( $collapsed[ $existing_idx ]['similarity'] ?? -INF );
				$incoming_sim = (float) ( $candidate['similarity'] ?? -INF );
				if ( $incoming_sim > $existing_sim ) {
					$collapsed[ $existing_idx ] = $candidate;
				}
				continue;
			}
			if ( null !== $person_id ) {
				$index_by_person[ $person_id ] = count( $collapsed );
			}
			$collapsed[] = $candidate;
		}

		usort(
			$collapsed,
			static function ( array $left, array $right ): int {
				$left_null  = null === ( $left['roster_entry_id'] ?? null );
				$right_null = null === ( $right['roster_entry_id'] ?? null );
				if ( $left_null !== $right_null ) {
					return $left_null ? 1 : -1;
				}
				$sim = ( (float) ( $right['similarity'] ?? 0 ) ) <=> ( (float) ( $left['similarity'] ?? 0 ) );
				if ( 0 !== $sim ) {
					return $sim;
				}
				return ( (string) ( $left['cluster_id'] ?? '' ) ) <=> ( (string) ( $right['cluster_id'] ?? '' ) );
			}
		);

		$payload['candidates'] = array_slice( $collapsed, 0, $top_k );
		return $payload;
	}

	private function clusters_read_repository(): ClustersReadRepository {
		if ( null === $this->clusters_read_repository ) {
			global $wpdb;
			$table = ( isset( $wpdb ) && is_object( $wpdb ) && isset( $wpdb->prefix ) && is_string( $wpdb->prefix ) )
				? $wpdb->prefix . 'acx_clusters'
				: 'wp_acx_clusters';
			$this->clusters_read_repository = new ClustersReadRepository( $table );
		}
		return $this->clusters_read_repository;
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
