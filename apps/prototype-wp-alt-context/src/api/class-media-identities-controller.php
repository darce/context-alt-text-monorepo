<?php

declare(strict_types=1);

namespace AltContext\Api;

use AltContext\Sovereign\Mappers\MemberResponseMapper;
use AltContext\Sovereign\Repositories\IdentityMembersRepository;
use AltContext\Sovereign\Repositories\IdentityMembersRepositoryInterface;
use AltContext\Sovereign\Repositories\SyncStateRepository;
use AltContext\Sovereign\Repositories\SyncStateRepositoryInterface;
use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

use function absint;
use function array_keys;
use function count;
use function is_array;
use function range;
use function rest_sanitize_boolean;

class MediaIdentitiesController extends AbstractRecognitionProxyController {
	private const DATA_SOURCE_LOCAL_PROJECTION = 'local_projection';
	private const DATA_SOURCE_BACKEND_PROXY = 'backend_proxy';
	private const DATA_SOURCE_UNAVAILABLE = 'unavailable';
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

		if ( $this->should_use_local_projection( $tenant_id ) ) {
			$rows = $this->members_repository->list_for_media_ids( $tenant_id, $ids );
			$payload = array(
				'identities_by_media' => $this->member_mapper->map_media_identities( $rows ),
				'data_source' => self::DATA_SOURCE_LOCAL_PROJECTION,
			);
			return new WP_REST_Response( $payload, 200 );
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
		if ( $this->is_proxy_unavailable( $response ) ) {
			return new WP_REST_Response(
				array(
					'identities_by_media' => array(),
					'data_source' => self::DATA_SOURCE_UNAVAILABLE,
				),
				200
			);
		}

		if ( $response instanceof WP_REST_Response && 200 === $response->get_status() ) {
			return $this->normalize_backend_media_identities_response( $response );
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
					'identities_by_media' => $data['identities_by_media'],
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
			$grouped[ $media_key ][] = $identity;
		}

		return new WP_REST_Response(
			array(
				'identities_by_media' => $grouped,
				'data_source'        => self::DATA_SOURCE_BACKEND_PROXY,
			),
			200
		);
	}

	private function should_use_local_projection( string $tenant_id ): bool {
		return $this->should_use_local_projection_gate( $this->sync_state_repository, $tenant_id )
			&& $this->members_repository->has_projection_rows_for_tenant( $tenant_id );
	}

	private function is_list_payload( array $data ): bool {
		if ( array() === $data ) {
			return true;
		}

		return array_keys( $data ) === range( 0, count( $data ) - 1 );
	}
}
