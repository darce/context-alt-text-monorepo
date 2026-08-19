<?php

declare(strict_types=1);

namespace AltContext\Api;

require_once __DIR__ . '/class-abstract-recognition-proxy-controller.php';
require_once __DIR__ . '/class-recognition-data-source.php';
require_once __DIR__ . '/../sovereign/class-projection-query-exception.php';
require_once __DIR__ . '/../support/trait-detects-system-defined-labels.php';

use AltContext\Sovereign\Mappers\MemberResponseMapper;
use AltContext\Support\DetectsSystemDefinedLabels;
use AltContext\Sovereign\ProjectionQueryException;
use AltContext\Sovereign\Repositories\IdentityMembersRepository;
use AltContext\Sovereign\Repositories\IdentityMembersRepositoryInterface;
use AltContext\Sovereign\Repositories\SyncStateRepository;
use AltContext\Sovereign\Repositories\SyncStateRepositoryInterface;
use stdClass;
use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

use function absint;
use function array_keys;
use function count;
use function is_array;
use function is_string;
use function trim;
use function range;
use function rest_sanitize_boolean;
use function time;
use function wp_next_scheduled;
use function wp_schedule_single_event;

class MediaIdentitiesController extends AbstractRecognitionProxyController {
	use DetectsSystemDefinedLabels;
	private const DATA_SOURCE_LOCAL_PROJECTION = RecognitionDataSource::LOCAL_PROJECTION;
	private const DATA_SOURCE_BACKEND_PROXY = RecognitionDataSource::BACKEND_PROXY;
	private const DATA_SOURCE_ENDPOINT_ERROR = RecognitionDataSource::ENDPOINT_ERROR;
	private const DATA_SOURCE_UNAVAILABLE = RecognitionDataSource::UNAVAILABLE;
	private const REQUEST_CLASS_POST_SCAN_READ = 'post_scan_read';
	private IdentityMembersRepositoryInterface $members_repository;
	private SyncStateRepositoryInterface $sync_state_repository;
	private MemberResponseMapper $member_mapper;

	public function __construct(
		?IdentityMembersRepositoryInterface $members_repository = null,
		?SyncStateRepositoryInterface $sync_state_repository = null,
		?MemberResponseMapper $member_mapper = null
	) {
		$this->members_repository = $members_repository ?? new IdentityMembersRepository();
		$this->sync_state_repository = $sync_state_repository ?? new SyncStateRepository();
		$this->member_mapper = $member_mapper ?? new MemberResponseMapper();
	}

	public function register_routes(): void {
		register_rest_route(
			'acx/v1',
			'/recognition/media-identities',
			array(
				'methods'             => 'GET',
				'callback'            => array( $this, 'get_media_identities' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
				'args'                => array(
					'media_ids'     => array(
						'type'        => 'array',
						'required'    => true,
						'items'       => array( 'type' => 'integer' ),
						'description' => 'Attachment IDs to fetch detected identities for (max 100).',
					),
					'include_debug' => array(
						'type'        => 'string',
						'required'    => false,
						'description' => 'Include debug metrics in response.',
					),
				),
			)
		);
	}

	public function get_media_identities( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$tenant_id = $this->get_tenant_id();
		$media_ids = $request->get_param( 'media_ids' );
		if ( ! is_array( $media_ids ) || empty( $media_ids ) ) {
			return new WP_Error( 'missing_media_ids', 'Provide one or more media_ids to fetch identities.', array( 'status' => 400 ) );
		}

		$ids = array();
		foreach ( $media_ids as $media_id ) {
			$abs = absint( $media_id );
			if ( $abs > 0 ) {
				$ids[] = $abs;
			}
		}

		if ( empty( $ids ) || count( $ids ) > 100 ) {
			return new WP_Error( 'invalid_media_ids', 'Provide between 1 and 100 valid attachment IDs.', array( 'status' => 400 ) );
		}

		try {
			if ( $this->should_use_local_projection( $tenant_id ) ) {
				$rows = $this->members_repository->list_for_media_ids( $tenant_id, $ids );
				$payload = array(
					'identities_by_media' => $this->as_identities_map( $this->member_mapper->map_media_identities( $rows ) ),
					'data_source' => self::DATA_SOURCE_LOCAL_PROJECTION,
				);
				// Async heal only: the sovereign read must return immediately even offline.
				$this->maybe_schedule_stale_projection_heal( $tenant_id );
				return new WP_REST_Response( $payload, 200 );
			}
		} catch ( ProjectionQueryException $exception ) {
			return ProjectionQueryException::to_rest_error( 'get_media_identities' );
		}

		$query = array(
			'tenant_id' => $tenant_id,
			'media_ids' => $ids,
		);

		$include_debug = $request->get_param( 'include_debug' );
		if ( null !== $include_debug && true === rest_sanitize_boolean( $include_debug ) ) {
			$query['include_debug'] = 'true';
		}

		$response = $this->proxy_request( 'GET', '/recognition/media/identities', array(), $query, self::REQUEST_CLASS_POST_SCAN_READ );
		if ( $this->is_backend_overloaded( $response ) ) {
			return parent::backend_overloaded_response( $response );
		}
		// Refused 3xx: backend is reachable; report ENDPOINT_ERROR not UNAVAILABLE.
		if ( $this->is_proxy_redirect_refused( $response ) || $this->is_proxy_endpoint_error( $response ) ) {
			return $this->degraded_media_identities_response( self::DATA_SOURCE_ENDPOINT_ERROR );
		}
		if ( $this->is_proxy_transport_unreachable( $response ) ) {
			return $this->degraded_media_identities_response( self::DATA_SOURCE_UNAVAILABLE );
		}

		if ( $response instanceof WP_REST_Response && 200 === $response->get_status() ) {
			return $this->maybe_bootstrap_after_proxy_read( $tenant_id, $this->normalize_backend_media_identities_response( $response ) );
		}

		return $response;
	}

	private function normalize_backend_media_identities_response( WP_REST_Response $response ): WP_REST_Response|WP_Error {
		$data = $response->get_data();

		if ( ! is_array( $data ) ) {
			return new WP_Error(
				'invalid_media_identities_payload',
				'Media identities payload must be a JSON array or identities_by_media envelope.',
				array( 'status' => 502 )
			);
		}

		if ( isset( $data['identities_by_media'] ) ) {
			if ( ! is_array( $data['identities_by_media'] ) ) {
				return new WP_Error(
					'invalid_media_identities_payload',
					'Media identities envelope must include an identities_by_media object.',
					array( 'status' => 502 )
				);
			}

			return new WP_REST_Response(
				array(
					'identities_by_media' => $this->as_identities_map( $this->apply_label_authority_to_identities_map( $data['identities_by_media'] ) ),
					'data_source'        => self::DATA_SOURCE_BACKEND_PROXY,
				),
				200
			);
		}

		if ( ! $this->is_list_payload( $data ) ) {
			return new WP_Error(
				'invalid_media_identities_payload',
				'Media identities payload must be a JSON array or identities_by_media envelope.',
				array( 'status' => 502 )
			);
		}

		$grouped = array();
		foreach ( $data as $identity ) {
			if ( ! is_array( $identity ) ) {
				return new WP_Error(
					'invalid_media_identities_payload',
					'Media identities list items must be objects with a media_id.',
					array( 'status' => 502 )
				);
			}

			$media_id = absint( $identity['media_id'] ?? 0 );
			if ( $media_id <= 0 ) {
				return new WP_Error(
					'invalid_media_identities_payload',
					'Media identities list items must include a valid media_id.',
					array( 'status' => 502 )
				);
			}

			$media_key = (string) $media_id;
			if ( ! isset( $grouped[ $media_key ] ) ) {
				$grouped[ $media_key ] = array();
			}
			$grouped[ $media_key ][] = $this->apply_label_authority_to_identity( $identity );
		}

		return new WP_REST_Response(
			array(
				'identities_by_media' => $this->as_identities_map( $grouped ),
				'data_source'        => self::DATA_SOURCE_BACKEND_PROXY,
			),
			200
		);
	}

	/**
	 * Rows-first source selection ([DATA-14]): the projection rows are the
	 * ground truth, so a derived sync-state freshness marker must not veto
	 * the source of record. Staleness is healed asynchronously instead.
	 */
	private function should_use_local_projection( string $tenant_id ): bool {
		return $this->members_repository->has_projection_rows_for_tenant( $tenant_id );
	}

	/**
	 * BR-02: after a successful proxy read, converge the projection via the
	 * deduped async cron event only — never an inline pull. The successful
	 * proxy response must return immediately; blocking it on a background_sync
	 * pull (30s x3) exceeds the workbench client abort budget and withholds
	 * data the response already carries. This mirrors the sovereign local-read
	 * path ("return immediately even offline") and the ClusterProjectionSyncService
	 * newly-qualifying branch. The cron handler (Api::handle_bootstrap_sync)
	 * performs the actual convergence pull off the request path.
	 */
	private function maybe_bootstrap_after_proxy_read( string $tenant_id, WP_REST_Response|WP_Error $response ): WP_REST_Response|WP_Error {
		if ( ! ( $response instanceof WP_REST_Response ) ) {
			return $response;
		}

		if ( $response->get_status() < 200 || $response->get_status() >= 300 ) {
			return $response;
		}

		$this->schedule_bootstrap_sync_event( $tenant_id );

		return $response;
	}

	private function maybe_schedule_stale_projection_heal( string $tenant_id ): void {
		$updated_at = $this->sync_state_repository->get_last_updated( $tenant_id );
		if ( ! $this->is_projection_stale( $updated_at ) ) {
			return;
		}

		$this->schedule_bootstrap_sync_event( $tenant_id );
	}

	private function schedule_bootstrap_sync_event( string $tenant_id ): void {
		$args = array( $tenant_id );
		if ( false === wp_next_scheduled( RecognitionDataSource::BOOTSTRAP_SYNC_HOOK, $args ) ) {
			wp_schedule_single_event( time(), RecognitionDataSource::BOOTSTRAP_SYNC_HOOK, $args );
		}
	}

	/**
	 * BR-01: an empty identities_by_media must serialize as a JSON object ({}),
	 * not a JSON array ([]). The workbench guard (fetchMediaIdentities) rejects
	 * arrays, so an empty [] would throw client-side and collapse the honest
	 * degraded state (data_source) into an error the UI cannot render.
	 *
	 * @param array<array-key,mixed> $identities_by_media
	 * @return array<array-key,mixed>|stdClass
	 */
	private function as_identities_map( array $identities_by_media ): array|stdClass {
		return array() === $identities_by_media ? new stdClass() : $identities_by_media;
	}

	private function degraded_media_identities_response( string $data_source ): WP_REST_Response {
		return new WP_REST_Response(
			array(
				'identities_by_media' => new stdClass(),
				'data_source' => $data_source,
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

	/**
	 * @param array<array-key,mixed> $identities_by_media
	 * @return array<array-key,mixed>
	 */
	private function apply_label_authority_to_identities_map( array $identities_by_media ): array {
		$normalized = array();
		foreach ( $identities_by_media as $media_key => $identities ) {
			if ( ! is_array( $identities ) ) {
				$normalized[ $media_key ] = $identities;
				continue;
			}
			$mapped = array();
			foreach ( $identities as $identity ) {
				$mapped[] = is_array( $identity ) ? $this->apply_label_authority_to_identity( $identity ) : $identity;
			}
			$normalized[ $media_key ] = $mapped;
		}

		return $normalized;
	}

	/**
	 * @param array<string,mixed> $identity
	 * @return array<string,mixed>
	 */
	private function apply_label_authority_to_identity( array $identity ): array {
		return $this->member_mapper->apply_label_authority( $identity );
	}
}
