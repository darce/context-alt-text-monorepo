<?php

declare(strict_types=1);

namespace AltContext\Api;

use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

use function absint;
use function sanitize_text_field;
use function sprintf;

class SuggestionsController extends AbstractRecognitionProxyController {
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
	}

	public function get_identity_suggestions( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$identity_id = sanitize_text_field( (string) $request->get_param( 'identity_id' ) );

		if ( '' === $identity_id ) {
			return new WP_Error( 'missing_identity_id', 'Identity ID is required.', array( 'status' => 400 ) );
		}

		$query = array(
			'tenant_id' => $this->get_tenant_id(),
			'top_k'     => absint( $request->get_param( 'top_k' ) ?? 5 ),
			'threshold' => (float) ( $request->get_param( 'threshold' ) ?? 0.6 ),
		);

		return $this->proxy_request(
			'GET',
			sprintf( '/recognition/identities/%s/suggestions', $identity_id ),
			array(),
			$query
		);
	}

	public function get_pending_suggestions( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$query = array(
			'tenant_id' => $this->get_tenant_id(),
			'limit'     => absint( $request->get_param( 'limit' ) ?? 10 ),
			'offset'    => absint( $request->get_param( 'offset' ) ?? 0 ),
		);

		return $this->proxy_request(
			'GET',
			'/recognition/suggestions',
			array(),
			$query
		);
	}

	public function get_pending_merge_suggestions( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$query = array(
			'tenant_id' => $this->get_tenant_id(),
			'limit'     => absint( $request->get_param( 'limit' ) ?? 10 ),
			'offset'    => absint( $request->get_param( 'offset' ) ?? 0 ),
		);

		return $this->proxy_request(
			'GET',
			'/recognition/suggestions/merge',
			array(),
			$query
		);
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
}
