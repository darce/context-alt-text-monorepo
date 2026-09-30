<?php

declare(strict_types=1);

namespace AltContext\Api;

require_once __DIR__ . '/class-abstract-recognition-proxy-controller.php';
require_once __DIR__ . '/class-proxy-routes.php';
require_once __DIR__ . '/../sovereign/sync/interface-sync-pull-job.php';

use AltContext\Sovereign\Sync\SyncPullJobInterface;
use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

use function get_transient;
use function gmdate;
use function in_array;
use function is_array;
use function is_int;
use function is_string;
use function preg_match;
use function register_rest_route;
use function rest_sanitize_boolean;
use function sanitize_key;
use function set_transient;
use function str_contains;
use function strtolower;
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
			'/retention/policy/preset',
			array(
				'methods' => 'POST',
				'callback' => array( $this, 'apply_preset' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
				'args' => array(
					'preset' => array(
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
			'/retention/export/(?P<job_id>[a-f0-9-]{36})/status',
			array(
				'methods' => 'GET',
				'callback' => array( $this, 'get_export_job_status' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
				'args' => array(
					'job_id' => array(
						'type' => 'string',
						'required' => true,
					),
				),
			)
		);

		register_rest_route(
			'acx/v1',
			'/retention/export/(?P<job_id>[a-f0-9-]{36})/data',
			array(
				'methods' => 'GET',
				'callback' => array( $this, 'get_export_job_data' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
				'args' => array(
					'job_id' => array(
						'type' => 'string',
						'required' => true,
					),
				),
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

		register_rest_route(
			'acx/v1',
			'/retention/import',
			array(
				'methods' => 'POST',
				'callback' => array( $this, 'trigger_import' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
			)
		);

		register_rest_route(
			'acx/v1',
			'/retention/audit',
			array(
				'methods' => 'GET',
				'callback' => array( $this, 'list_audit_events' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
				'args' => array(
					'limit' => array(
						'type' => 'integer',
						'required' => false,
					),
					'offset' => array(
						'type' => 'integer',
						'required' => false,
					),
					'event_type' => array(
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

		$policy_response = $this->proxy_request( 'GET', ProxyRoutes::GET_RETENTION_POLICY_PATH, array(), array(), 'ui_read' );
		$audit_response = $this->proxy_request( 'GET', ProxyRoutes::GET_RETENTION_AUDIT_PATH, array(), array( 'limit' => 5 ), 'ui_read' );

		if ( ! $this->is_successful_rest_response( $policy_response ) || ! $this->is_successful_rest_response( $audit_response ) ) {
			$failed = ! $this->is_successful_rest_response( $policy_response )
				? $policy_response
				: $audit_response;

			return new WP_REST_Response( $this->build_unavailable_status_payload( $failed ), 200 );
		}

		$policy = $policy_response->get_data();
		$audit_payload = $audit_response->get_data();
		if ( ! $this->is_valid_policy_payload( $policy ) || ! $this->is_valid_audit_payload( $audit_payload ) ) {
			$mismatch = ! $this->is_valid_policy_payload( $policy )
				? $policy_response
				: $audit_response;

			return new WP_REST_Response( $this->build_unavailable_status_payload( $mismatch, true ), 200 );
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
			ProxyRoutes::PATCH_RETENTION_POLICY_PATH,
			array( 'retention_mode' => $retention_mode ),
			array(),
			'mutation'
		);

		if ( ! $this->is_proxy_unavailable( $response ) && $response instanceof WP_REST_Response && $response->get_status() < 400 ) {
			$this->invalidate_status_cache();
		}

		return $response;
	}

	public function apply_preset( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$preset = $this->normalize_string_param( $request->get_param( 'preset' ) );
		if ( '' === $preset ) {
			return new WP_Error( 'missing_preset', 'Retention preset name is required.', array( 'status' => 400 ) );
		}

		$response = $this->proxy_request(
			'POST',
			ProxyRoutes::POST_RETENTION_POLICY_PRESET_PATH,
			array( 'preset' => $preset ),
			array(),
			'mutation'
		);

		if ( ! $this->is_proxy_unavailable( $response ) && $response instanceof WP_REST_Response && $response->get_status() < 400 ) {
			$this->invalidate_status_cache();
		}

		return $response;
	}

	public function trigger_export( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$response = $this->proxy_request( 'POST', ProxyRoutes::POST_RETENTION_EXPORT_PATH, array(), array(), 'mutation' );

		if ( ! $this->is_proxy_unavailable( $response ) && $response instanceof WP_REST_Response && $response->get_status() < 400 ) {
			$this->invalidate_status_cache();
		}

		return $response;
	}

	public function get_export_job_status( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$job_id = sanitize_key( $request->get_param( 'job_id' ) );
		return $this->proxy_request( 'GET', ProxyRoutes::export_job_status_path( $job_id ), array(), array(), 'ui_read' );
	}

	public function get_export_job_data( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$job_id = sanitize_key( $request->get_param( 'job_id' ) );
		return $this->proxy_request( 'GET', ProxyRoutes::export_job_data_path( $job_id ), array(), array(), 'ui_read' );
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
			ProxyRoutes::POST_RETENTION_PURGE_PATH,
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

	public function trigger_import( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$body = $request->get_json_params();
		if ( ! is_array( $body ) || ! isset( $body['data'] ) || ! is_array( $body['data'] ) ) {
			return new WP_Error(
				'retention_import_invalid_body',
				'Import request must include a "data" object.',
				array( 'status' => 400 )
			);
		}

		$response = $this->proxy_request(
			'POST',
			ProxyRoutes::POST_RETENTION_IMPORT_PATH,
			array( 'data' => $body['data'] ),
			array(),
			'mutation'
		);

		if ( ! $this->is_proxy_unavailable( $response ) && $response instanceof WP_REST_Response && $response->get_status() < 400 ) {
			$this->invalidate_status_cache();
		}

		return $response;
	}

	public function list_audit_events( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$query_params = array();

		$limit = $request->get_param( 'limit' );
		if ( null !== $limit ) {
			$query_params['limit'] = (int) $limit;
		}

		$offset = $request->get_param( 'offset' );
		if ( null !== $offset ) {
			$query_params['offset'] = (int) $offset;
		}

		$event_type = $this->normalize_string_param( $request->get_param( 'event_type' ) );
		if ( '' !== $event_type ) {
			$query_params['event_type'] = $event_type;
		}

		return $this->proxy_request( 'GET', ProxyRoutes::GET_RETENTION_AUDIT_PATH, array(), $query_params, 'ui_read' );
	}

	/**
	 * @return array{
	 *   available: bool,
	 *   policy: null,
	 *   recent_audit_events: array<int, mixed>,
	 *   unavailable: array{
	 *     reason: string,
	 *     service: string,
	 *     http_status: int|null,
	 *     retry_after_seconds: int|null,
	 *     checked_at: string
	 *   }
	 * }
	 */
	private function build_unavailable_status_payload( WP_REST_Response|WP_Error $response, bool $contract_mismatch = false ): array {
		return array(
			'available' => false,
			'policy' => null,
			'recent_audit_events' => array(),
			'unavailable' => $this->build_unavailable_envelope( $response, 'recognition', $contract_mismatch ),
		);
	}

	/**
	 * Typed unavailable object for retention status failures.
	 *
	 * `checked_at` is the time the plugin observed the failure (gmdate UTC).
	 * proxy_request and its WP_Error data do not carry a failed-attempt timestamp.
	 *
	 * @return array{
	 *   reason: string,
	 *   service: string,
	 *   http_status: int|null,
	 *   retry_after_seconds: int|null,
	 *   checked_at: string
	 * }
	 */
	private function build_unavailable_envelope( WP_REST_Response|WP_Error $response, string $service, bool $contract_mismatch = false ): array {
		return array(
			'reason' => $this->map_unavailable_reason( $response, $contract_mismatch ),
			'service' => $service,
			'http_status' => $this->proxy_http_status( $response ),
			'retry_after_seconds' => $this->unavailable_retry_after_seconds( $response ),
			'checked_at' => gmdate( 'Y-m-d\TH:i:s\Z' ),
		);
	}

	private function map_unavailable_reason( WP_REST_Response|WP_Error $response, bool $contract_mismatch ): string {
		if ( $contract_mismatch ) {
			return 'contract_mismatch';
		}

		$service_reason = $this->service_unavailable_reason( $response );
		if ( null !== $service_reason ) {
			return $service_reason;
		}

		if ( $response instanceof WP_Error ) {
			$code = $response->get_error_code();
			if ( 'recognition_not_configured' === $code ) {
				return 'not_configured';
			}
			if ( 'recognition_api_key_missing' === $code ) {
				return 'api_key_missing';
			}
			if ( 'recognition_circuit_open' === $code ) {
				return 'circuit_open';
			}
			if ( $this->is_timeout_proxy_error( $response ) ) {
				return 'timeout';
			}
		}

		$status = $this->proxy_http_status( $response );
		if ( null !== $status && $status >= 400 && $status < 500 ) {
			return 'upstream_4xx';
		}

		return 'upstream_5xx';
	}

	private function service_unavailable_reason( WP_REST_Response|WP_Error $response ): ?string {
		$payload = $this->unavailable_reason_source_payload( $response );
		if ( null === $payload ) {
			return null;
		}

		foreach ( $this->unavailable_reason_candidates( $payload ) as $candidate ) {
			$normalized = $this->normalize_service_unavailable_reason( $candidate );
			if ( null !== $normalized ) {
				return $normalized;
			}
		}

		return null;
	}

	/**
	 * @return array<string, mixed>|null
	 */
	private function unavailable_reason_source_payload( WP_REST_Response|WP_Error $response ): ?array {
		if ( $response instanceof WP_REST_Response ) {
			$data = $response->get_data();

			return is_array( $data ) ? $data : null;
		}

		$data = $response->get_error_data();

		return is_array( $data ) ? $data : null;
	}

	/**
	 * @param array<string, mixed> $payload
	 * @return list<mixed>
	 */
	private function unavailable_reason_candidates( array $payload ): array {
		$candidates = array();
		$unavailable = $payload['unavailable'] ?? null;
		if ( is_array( $unavailable ) ) {
			$candidates[] = $unavailable['reason'] ?? null;
		}

		$candidates[] = $payload['reason'] ?? null;

		$detail = $payload['detail'] ?? null;
		if ( is_array( $detail ) ) {
			$nested_unavailable = $detail['unavailable'] ?? null;
			if ( is_array( $nested_unavailable ) ) {
				$candidates[] = $nested_unavailable['reason'] ?? null;
			}
			$candidates[] = $detail['reason'] ?? null;
		}

		return $candidates;
	}

	private function normalize_service_unavailable_reason( mixed $reason ): ?string {
		if ( ! is_string( $reason ) ) {
			return null;
		}

		$normalized = strtolower( trim( $reason ) );
		if ( 1 !== preg_match( '/^[a-z][a-z0-9_]{0,62}$/', $normalized ) ) {
			return null;
		}

		return $normalized;
	}

	private function proxy_http_status( WP_REST_Response|WP_Error $response ): ?int {
		if ( $response instanceof WP_REST_Response ) {
			$status = $response->get_status();

			return $status > 0 ? $status : null;
		}

		$data = $response->get_error_data();
		if ( ! is_array( $data ) ) {
			return null;
		}

		$status = $data['status'] ?? $data['http_status'] ?? null;
		if ( is_int( $status ) && $status > 0 ) {
			return $status;
		}

		return null;
	}

	private function unavailable_retry_after_seconds( WP_REST_Response|WP_Error $response ): ?int {
		if ( $response instanceof WP_REST_Response ) {
			return $this->get_retry_after_seconds( $response );
		}

		$data = $response->get_error_data();
		if ( ! is_array( $data ) ) {
			return null;
		}

		$raw = $data['retry_after_seconds'] ?? $data['retry_after'] ?? null;
		if ( is_int( $raw ) && $raw > 0 ) {
			return $raw;
		}

		return null;
	}

	private function is_timeout_proxy_error( WP_Error $response ): bool {
		$code = strtolower( $response->get_error_code() );
		if ( str_contains( $code, 'timeout' ) || str_contains( $code, 'timed_out' ) ) {
			return true;
		}

		$message = strtolower( $response->get_error_message() );

		return str_contains( $message, 'timed out' ) || str_contains( $message, 'timeout' );
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

		return sanitize_key( trim( $value ) );
	}

	private function is_confirmed( mixed $value ): bool {
		return true === rest_sanitize_boolean( $value );
	}
}
