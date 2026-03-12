<?php

declare(strict_types=1);

namespace AltContext\Api;

require_once __DIR__ . '/../sovereign/sync/interface-sync-pull-job.php';

use AltContext\Sovereign\Sync\SyncPullJobInterface;
use AltContext\Sovereign\Sync\SyncPullResult;
use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

use function get_transient;
use function in_array;
use function is_array;
use function is_string;
use function register_rest_route;
use function set_transient;
use function trim;

class RetentionController extends AbstractRecognitionProxyController {
	private const STATUS_TRANSIENT_TTL_SECONDS = 60;
	private const ALLOWED_PURGE_SCOPES = array( 'disposed', 'all' );

	private ?SyncPullJobInterface $sync_pull_job;

	public function __construct( ?SyncPullJobInterface $sync_pull_job = null ) {
		$this->sync_pull_job = $sync_pull_job;
	}

	public function register_routes(): void {
		register_rest_route(
			'acx/v1',
			'/retention/status',
			array(
				'methods' => 'GET',
				'callback' => array( $this, 'get_status' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
			)
		);

		register_rest_route(
			'acx/v1',
			'/retention/policy',
			array(
				'methods' => 'PATCH',
				'callback' => array( $this, 'update_policy' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
				'args' => array(
					'retention_mode' => array(
						'type' => 'string',
						'required' => true,
					),
				),
			)
		);

		register_rest_route(
			'acx/v1',
			'/retention/export',
			array(
				'methods' => 'POST',
				'callback' => array( $this, 'trigger_export' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
			)
		);

		register_rest_route(
			'acx/v1',
			'/retention/purge',
			array(
				'methods' => 'POST',
				'callback' => array( $this, 'trigger_purge' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
				'args' => array(
					'confirm' => array(
						'type' => 'boolean',
						'required' => true,
					),
					'scope' => array(
						'type' => 'string',
						'required' => false,
					),
				),
			)
		);
	}

	public function get_status( WP_REST_Request $request ): WP_REST_Response {
		$tenant_id = $this->get_tenant_id();
		$cache_key = $this->status_cache_key( $tenant_id );
		$cached = get_transient( $cache_key );
		if ( is_array( $cached ) ) {
			return new WP_REST_Response( $cached, 200 );
		}

		$policy_response = $this->proxy_request( 'GET', '/retention/policy', array(), array(), 'ui_read' );
		$audit_response = $this->proxy_request( 'GET', '/retention/audit', array(), array( 'limit' => 5 ), 'ui_read' );

		if ( ! $this->is_successful_rest_response( $policy_response ) || ! $this->is_successful_rest_response( $audit_response ) ) {
			return new WP_REST_Response( $this->build_unavailable_status_payload(), 200 );
		}

		$policy = $policy_response->get_data();
		$audit_payload = $audit_response->get_data();
		if ( ! $this->is_valid_policy_payload( $policy ) || ! $this->is_valid_audit_payload( $audit_payload ) ) {
			return new WP_REST_Response( $this->build_unavailable_status_payload(), 200 );
		}

		$recent_audit_events = array_values( $audit_payload['items'] );

		$status = array(
			'available' => true,
			'policy' => $policy,
			'recent_audit_events' => $recent_audit_events,
		);

		set_transient( $cache_key, $status, self::STATUS_TRANSIENT_TTL_SECONDS );

		return new WP_REST_Response( $status, 200 );
	}

	public function update_policy( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$retention_mode = $this->normalize_string_param( $request->get_param( 'retention_mode' ) );
		if ( '' === $retention_mode ) {
			return new WP_Error( 'missing_retention_mode', 'Retention mode is required.', array( 'status' => 400 ) );
		}

		$response = $this->proxy_request(
			'PATCH',
			'/retention/policy',
			array( 'retention_mode' => $retention_mode ),
			array(),
			'mutation'
		);

		if ( ! $this->is_proxy_unavailable( $response ) && $response instanceof WP_REST_Response && $response->get_status() < 400 ) {
			$this->invalidate_status_cache();
		}

		return $response;
	}

	public function trigger_export( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$response = $this->proxy_request( 'POST', '/retention/export', array(), array(), 'mutation' );

		if ( ! $this->is_proxy_unavailable( $response ) && $response instanceof WP_REST_Response && $response->get_status() < 400 ) {
			$this->invalidate_status_cache();
		}

		return $response;
	}

	public function trigger_purge( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$confirmed = $this->is_confirmed( $request->get_param( 'confirm' ) );
		if ( ! $confirmed ) {
			return new WP_Error(
				'retention_purge_confirmation_required',
				'Purge confirmation is required.',
				array( 'status' => 400 )
			);
		}

		$scope = $this->normalize_string_param( $request->get_param( 'scope' ) );
		if ( '' === $scope ) {
			$scope = 'disposed';
		}

		if ( ! in_array( $scope, self::ALLOWED_PURGE_SCOPES, true ) ) {
			return new WP_Error( 'invalid_purge_scope', 'Purge scope is invalid.', array( 'status' => 400 ) );
		}

		$response = $this->proxy_request(
			'POST',
			'/retention/purge',
			array(
				'confirm' => true,
				'scope' => $scope,
			),
			array(),
			'mutation'
		);

		if ( $this->is_proxy_unavailable( $response ) || ! ( $response instanceof WP_REST_Response ) || $response->get_status() >= 400 ) {
			return $response;
		}

		$this->invalidate_status_cache();

		if ( ! ( $this->sync_pull_job instanceof SyncPullJobInterface ) ) {
			return new WP_Error(
				'retention_sync_refresh_unavailable',
				'Purge succeeded remotely, but local projection refresh is unavailable.',
				array(
					'status' => 503,
					'purge_response' => $response->get_data(),
				)
			);
		}

		$sync_result = $this->sync_pull_job->perform_bypass_cooldown( $this->get_tenant_id() );
		if ( ! $sync_result->is_success() ) {
			return new WP_Error(
				'retention_sync_refresh_failed',
				'Purge succeeded remotely, but local projection refresh failed.',
				array(
					'status' => 502,
					'purge_response' => $response->get_data(),
					'sync_status' => $sync_result->status(),
				)
			);
		}

		return $response;
	}

	private function build_unavailable_status_payload(): array {
		return array(
			'available' => false,
			'policy' => null,
			'recent_audit_events' => array(),
		);
	}

	private function invalidate_status_cache(): void {
		delete_transient( $this->status_cache_key( $this->get_tenant_id() ) );
	}

	private function status_cache_key( string $tenant_id ): string {
		return 'acx_retention_status_' . $tenant_id;
	}

	private function is_successful_rest_response( WP_REST_Response|WP_Error $response ): bool {
		return $response instanceof WP_REST_Response && $response->get_status() >= 200 && $response->get_status() < 300;
	}

	private function is_valid_policy_payload( mixed $payload ): bool {
		return is_array( $payload ) && is_string( $payload['retention_mode'] ?? null ) && '' !== trim( $payload['retention_mode'] );
	}

	private function is_valid_audit_payload( mixed $payload ): bool {
		return is_array( $payload ) && is_array( $payload['items'] ?? null );
	}

	private function normalize_string_param( mixed $value ): string {
		if ( ! is_string( $value ) ) {
			return '';
		}

		return trim( $value );
	}

	private function is_confirmed( mixed $value ): bool {
		if ( true === $value || 1 === $value || '1' === $value ) {
			return true;
		}

		if ( is_string( $value ) ) {
			$normalized = trim( $value );
			return in_array( $normalized, array( 'true', 'yes', 'on' ), true );
		}

		return false;
	}
}
