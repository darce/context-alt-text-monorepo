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
use function is_array;
use function rest_sanitize_boolean;
use function trim;

class MediaIdentitiesController extends AbstractRecognitionProxyController {
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

		$response = $this->proxy_request( 'GET', '/recognition/media/identities', array(), $query );

		if ( $response instanceof WP_REST_Response && 200 === $response->get_status() ) {
			$data = $response->get_data();
			if ( is_array( $data ) ) {
				$grouped = array();
				foreach ( $data as $identity ) {
					if ( isset( $identity['media_id'] ) ) {
						$media_key = (string) $identity['media_id'];
						if ( ! isset( $grouped[ $media_key ] ) ) {
							$grouped[ $media_key ] = array();
						}
						$grouped[ $media_key ][] = $identity;
					}
				}
				return new WP_REST_Response( array( 'identities_by_media' => $grouped ), 200 );
			}
		}

		return $response;
	}

	private function should_use_local_projection( string $tenant_id ): bool {
		return $this->should_use_local_projection_gate( $this->sync_state_repository, $tenant_id );
	}
}
