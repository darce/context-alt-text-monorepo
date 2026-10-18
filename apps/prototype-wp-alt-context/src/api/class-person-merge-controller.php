<?php

declare(strict_types=1);

namespace AltContext\Api;

require_once __DIR__ . '/services/class-person-merge-service.php';
require_once __DIR__ . '/class-tenant-identity.php';

use AltContext\Api\Services\PersonMergeService;
use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

class PersonMergeController {
	private PersonMergeService $service;

	public function __construct( ?PersonMergeService $service = null ) {
		$this->service = $service ?? new PersonMergeService();
	}

	public function register_routes( callable $permission ): void {
		foreach ( array( '/preview' => 'preview', '' => 'commit', '/undo' => 'undo' ) as $suffix => $method ) {
			register_rest_route( 'acx/v1', '/roster/persons/merge' . $suffix, array(
				'methods' => 'POST',
				'callback' => array( $this, $method ),
				'permission_callback' => $permission,
			) );
		}
	}

	public function preview( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->dispatch( $request, 'preview' );
	}

	public function commit( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->dispatch( $request, 'commit' );
	}

	public function undo( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$token = $request->get_param( 'undo_token' );
		if ( ! is_string( $token ) || ! preg_match( PersonMergeService::UNDO_TOKEN_PATTERN, $token ) ) {
			return new WP_Error( 'invalid_undo_token', 'A valid undo token is required.', array( 'status' => 400 ) );
		}
		return $this->response( $this->service->undo( TenantIdentity::resolve()['value'] ?? '', $token ) );
	}

	private function dispatch( WP_REST_Request $request, string $method ): WP_REST_Response|WP_Error {
		$ids = array();
		foreach ( array( 'survivor_id', 'loser_id' ) as $key ) {
			$value = $request->get_param( $key );
			if ( ( ! is_int( $value ) && ! is_string( $value ) ) || ! preg_match( '/^[1-9][0-9]*$/D', (string) $value ) || false === filter_var( $value, FILTER_VALIDATE_INT ) ) {
				return new WP_Error( 'invalid_person_ids', 'Positive integer person IDs are required.', array( 'status' => 400 ) );
			}
			$ids[] = (int) $value;
		}
		if ( $ids[0] === $ids[1] ) {
			return new WP_Error( 'invalid_person_ids', 'Person IDs must differ.', array( 'status' => 400 ) );
		}
		return $this->response( $this->service->$method( TenantIdentity::resolve()['value'] ?? '', $ids[0], $ids[1] ) );
	}

	private function response( array|WP_Error $result ): WP_REST_Response|WP_Error {
		return is_wp_error( $result ) ? $result : new WP_REST_Response( $result, 200 );
	}
}
