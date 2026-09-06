<?php

declare(strict_types=1);

namespace AltContext\Api;

require_once __DIR__ . '/class-describe-controller.php';
require_once __DIR__ . '/interface-recognition-route-controller.php';
require_once __DIR__ . '/../public/class-public-demo-error-code.php';

use AltContext\PublicSite\PublicDemoErrorCode;
use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

use function absint;
use function add_option;
use function apply_filters;
use function array_filter;
use function array_key_exists;
use function array_map;
use function array_merge;
use function array_unique;
use function array_values;
use function ceil;
use function delete_transient;
use function filter_var;
use function get_option;
use function get_transient;
use function gmdate;
use function hash;
use function hash_equals;
use function in_array;
use function is_array;
use function is_int;
use function is_numeric;
use function is_string;
use function is_wp_error;
use function max;
use function min;
use function register_rest_route;
use function sanitize_text_field;
use function serialize;
use function set_transient;
use function strlen;
use function time;
use function trim;
use function update_option;
use function wp_verify_nonce;
use function wp_cache_delete;
use function wp_generate_uuid4;

use const FILTER_VALIDATE_IP;

/**
 * Narrow anonymous adapter over the existing describe-run pipeline.
 *
 * The public boundary accepts one attachment ID from an operator-curated
 * allowlist. It never accepts bytes or URLs. Enable/configure it explicitly:
 *
 *   wp option update acx_public_demo_enabled 1
 *   wp option update acx_public_demo_media_ids '[41,42]' --format=json
 *   wp option update acx_public_demo_daily_cap 50
 *
 * Fail-fast limits form a cost/stability bulkhead around the paid describe
 * pipeline: three requests per IP per minute, a daily site cap, and exactly
 * one in-flight public run.
 */
final class PublicDemoDescribeController implements RecognitionRouteControllerInterface {
	private const INFLIGHT_OPTION       = 'acx_public_demo_inflight';
	private const INFLIGHT_TTL_SECONDS  = 600;
	private const RATE_TTL_SECONDS      = 120;
	private const IDEMPOTENCY_TTL_SECONDS = 900;
	private const IDEMPOTENCY_KEY_MAX_LENGTH = 128;
	private const IDEMPOTENCY_TRANSIENT_PREFIX = 'acx_public_demo_idempotency_';
	private const IDEMPOTENCY_LOCK_PREFIX = 'acx_public_demo_idempotency_lock_';
	private const DEFAULT_RATE_PER_MIN  = 3;
	private const DEFAULT_DAILY_CAP     = 50;
	private const DEFAULT_GPU_WARMUP_TIMEOUT_SECONDS = 510;
	private const DEFAULT_INFERENCE_TIMEOUT_SECONDS  = 180;
	private const TERMINAL_STATUSES     = array( 'completed', 'completed_with_errors', 'failed', 'cancelled' );
	private const LIVE_STATUSES         = array( 'pending', 'running' );
	private const PHASES                = array( 'queued', 'warming', 'describing', 'complete', 'failed', 'cancelled' );
	private const GPU_STATES            = array( 'unknown', 'stopped', 'starting', 'warming', 'ready', 'degraded' );

	private DescribeController $pipeline;
	private ?string $inflight_token = null;

	public function __construct( ?DescribeController $pipeline = null ) {
		$this->pipeline = $pipeline ?? new DescribeController();
	}

	public function register_routes(): void {
		register_rest_route(
			'acx/v1',
			'/public/demo/describe',
			array(
				'methods'             => 'POST',
				'callback'            => array( $this, 'submit' ),
				'permission_callback' => array( $this, 'check_public_permission' ),
				'args'                => array(
					'media_id' => array(
						'type'        => 'integer',
						'required'    => true,
						'description' => 'One attachment ID from the configured public demo allowlist.',
					),
					'idempotency_key' => array(
						'type'        => 'string',
						'required'    => false,
						'description' => 'Client-generated key for retrying one user-initiated trigger.',
					),
				),
			)
		);

		register_rest_route(
			'acx/v1',
			'/public/demo/describe/runs/(?P<run_id>[^/]+)',
			array(
				'methods'             => 'GET',
				'callback'            => array( $this, 'status' ),
				'permission_callback' => array( $this, 'check_public_permission' ),
			)
		);
	}

	public function check_public_permission( WP_REST_Request $request ): bool|WP_Error {
		$enabled = get_option( 'acx_public_demo_enabled', false );
		if ( true !== $enabled && 1 !== $enabled && '1' !== $enabled ) {
			return new WP_Error(
				PublicDemoErrorCode::DISABLED,
				'The public description demo is not enabled.',
				array( 'status' => 403 )
			);
		}

		$nonce = $request->get_header( 'X-WP-Nonce' );
		if ( '' === $nonce || ! wp_verify_nonce( $nonce, 'wp_rest' ) ) {
			return new WP_Error(
				PublicDemoErrorCode::INVALID_NONCE,
				'This demo page token is missing or expired. Refresh the page and try again.',
				array( 'status' => 403 )
			);
		}

		return true;
	}

	public function submit( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$media_id = absint( $request->get_param( 'media_id' ) );
		if ( ! in_array( $media_id, $this->allowlisted_media_ids(), true ) ) {
			return new WP_Error(
				PublicDemoErrorCode::MEDIA_NOT_ALLOWED,
				'That image is not available in this demo.',
				array( 'status' => 403 )
			);
		}

		$client_key = $this->client_rate_key();
		if ( is_wp_error( $client_key ) ) {
			return $client_key;
		}

		$idempotency_key = $this->request_idempotency_key( $request );
		$idempotency_key_name = $this->idempotency_transient_key( $client_key, $idempotency_key );
		$idempotency_lock_name = self::IDEMPOTENCY_LOCK_PREFIX . hash( 'sha256', $idempotency_key_name );
		$idempotency_lock = $this->acquire_lock( $idempotency_lock_name, 5 );
		if ( false === $idempotency_lock ) {
			return $this->limited_response( PublicDemoErrorCode::STATE_UNAVAILABLE, 'The demo is temporarily busy. Please retry.', 1 );
		}

		try {
			$existing = get_transient( $idempotency_key_name );
			if ( is_array( $existing ) && (int) ( $existing['expires_at'] ?? 0 ) > time() ) {
				if ( $media_id !== absint( $existing['media_id'] ?? 0 ) ) {
					return new WP_Error(
						PublicDemoErrorCode::IDEMPOTENCY_CONFLICT,
						'That retry key is already associated with another demo image.',
						array( 'status' => 409 )
					);
				}
				$existing_response = $this->idempotency_response( $existing );
				if ( $existing_response instanceof WP_REST_Response ) {
					return $existing_response;
				}
				// A durable pending reservation means another request may have
				// accepted paid work but not yet written its run ID. Fail closed;
				// never spend a second run while that uncertainty is live.
				return $this->limited_response( PublicDemoErrorCode::STATE_UNAVAILABLE, 'The demo is temporarily busy. Please retry.', 5 );
			}

			$rate_result = $this->consume_rate_token( $client_key );
			if ( $rate_result instanceof WP_REST_Response ) {
				return $rate_result;
			}

			if ( ! $this->acquire_inflight_bulkhead( $media_id ) ) {
				return $this->limited_response(
					PublicDemoErrorCode::BUSY,
					'Another description is already running. Please try again shortly.',
					5
				);
			}

			$daily_result = $this->reserve_daily_capacity();
			if ( $daily_result instanceof WP_REST_Response ) {
				$this->release_inflight_bulkhead();
				return $daily_result;
			}

			// Reserve the key before dispatch. The pending record survives a PHP
			// crash and makes a retry fail closed instead of creating duplicate paid
			// work. The same transient is immediately updated with the run ID below.
			$pending = array(
				'media_id'  => $media_id,
				'run_id'    => 'pending',
				'expires_at' => time() + self::IDEMPOTENCY_TTL_SECONDS,
			);
			if ( ! set_transient( $idempotency_key_name, $pending, self::IDEMPOTENCY_TTL_SECONDS ) ) {
				$this->release_inflight_bulkhead();
				return $this->limited_response( PublicDemoErrorCode::STATE_UNAVAILABLE, 'The demo state is temporarily unavailable. Please retry.', 5 );
			}

			$pipeline_request = new WP_REST_Request( 'POST', '/acx/v1/recognition/describe/runs' );
			$pipeline_request->set_param( 'media_ids', array( $media_id ) );
			$pipeline_request->set_param( 'idempotency_key', $idempotency_key );
			// Persist uncertainty before dispatch: a timeout or worker death can
			// hide backend acceptance and must never turn into an expired free slot.
			if ( ! $this->mark_submission_started() ) {
				return $this->limited_response( PublicDemoErrorCode::STATE_UNAVAILABLE, 'The demo is temporarily busy. Please retry.', 5 );
			}
			$response = $this->pipeline->submit_describe_run( $pipeline_request );

			if ( $response instanceof WP_Error || $response->get_status() >= 400 ) {
				$error_data = $response instanceof WP_Error ? $response->get_error_data() : $response->get_data();
				$accepted_run_id = is_array( $error_data ) && is_string( $error_data['run_id'] ?? null )
					? sanitize_text_field( $error_data['run_id'] ) : '';
				if ( '' !== $accepted_run_id ) {
					// Tracking persistence may fail after acceptance. Keep the run ID
					// in the idempotency record so a retry cannot dispatch twice.
					$this->bind_inflight_run( $accepted_run_id );
					$this->store_idempotency_mapping( $idempotency_key_name, $media_id, $accepted_run_id );
				} elseif ( $response instanceof WP_Error && in_array( $response->get_error_code(), array(
					'missing_media_ids',
					'too_many_media_ids',
					'describe_run_attachment_unreadable',
					'describe_run_payload_too_large',
				), true ) ) {
					// These local validation failures precede the transport call.
					// Unrecognized errors (including HTTP errors) remain uncertain.
					delete_transient( $idempotency_key_name );
					$this->release_inflight_bulkhead();
				}
				return $this->translated_pipeline_error( $response );
			}

			$data   = $response->get_data();
			$run_id = is_array( $data ) && is_string( $data['run_id'] ?? null )
				? sanitize_text_field( $data['run_id'] )
				: '';
			if ( '' === $run_id || ! $this->bind_inflight_run( $run_id ) ) {
				return new WP_Error(
					PublicDemoErrorCode::INVALID_PIPELINE_DATA,
					'The description started but its status could not be tracked safely.',
					array( 'status' => 502 )
				);
			}

			$public_response = $this->public_envelope_response( $response, true );
			if ( $public_response instanceof WP_Error ) {
				$this->store_idempotency_mapping( $idempotency_key_name, $media_id, $run_id );
				return $public_response;
			}
			if ( ! $this->store_idempotency_mapping( $idempotency_key_name, $media_id, $run_id, $public_response ) ) {
				// The run is accepted and the bulkhead remains held. Do not report a
				// retryable success when the durable dedupe record could not be written.
				return $this->limited_response( PublicDemoErrorCode::STATE_UNAVAILABLE, 'The demo state is temporarily unavailable. Please retry.', 5 );
			}

			return $public_response;
		} finally {
			$this->release_lock( $idempotency_lock_name, $idempotency_lock );
		}
	}

	public function status( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$run_id   = sanitize_text_field( (string) $request->get_param( 'run_id' ) );
		$inflight = get_option( self::INFLIGHT_OPTION, false );
		if ( '' === $run_id || ! is_array( $inflight ) || ! is_string( $inflight['run_id'] ?? null ) || ! hash_equals( $inflight['run_id'], $run_id ) ) {
			return new WP_Error(
				PublicDemoErrorCode::RUN_NOT_AVAILABLE,
				'That public demo run is not available.',
				array( 'status' => 403 )
			);
		}

		$pipeline_request = new WP_REST_Request( 'GET', '/acx/v1/recognition/describe/runs/' . $run_id );
		$pipeline_request->set_param( 'run_id', $run_id );
		$response = $this->pipeline->get_describe_run_status( $pipeline_request );
		if ( $response instanceof WP_Error || $response->get_status() >= 400 ) {
			return $this->translated_pipeline_error( $response );
		}

		$data   = $response->get_data();
		$current_inflight = get_option( self::INFLIGHT_OPTION, false );
		$response_run_id = is_array( $data ) && is_string( $data['run_id'] ?? null ) ? $data['run_id'] : '';
		$current_run_id = is_array( $current_inflight ) && is_string( $current_inflight['run_id'] ?? null )
			? $current_inflight['run_id']
			: '';
		$lease_token = is_string( $inflight['token'] ?? null ) ? $inflight['token'] : '';
		$current_token = is_array( $current_inflight ) && is_string( $current_inflight['token'] ?? null )
			? $current_inflight['token']
			: '';
		if (
			'' === $response_run_id
			|| '' === $current_run_id
			|| '' === $lease_token
			|| '' === $current_token
			|| ! hash_equals( $run_id, $response_run_id )
			|| ! hash_equals( $run_id, $current_run_id )
			|| ! hash_equals( $lease_token, $current_token )
		) {
			return $this->invalid_pipeline_response();
		}

		$public_response = $this->public_envelope_response( $response, false );
		if ( $public_response instanceof WP_Error ) {
			return $public_response;
		}

		$status = $public_response->get_data()['status'];
		if ( 'completed' === $status ) {
			$description = $this->public_description( $pipeline_request, absint( $inflight['media_id'] ?? 0 ), $run_id, $lease_token );
			if ( $description instanceof WP_Error ) {
				return $description;
			}
			$public_response = $this->public_envelope_response( $response, false, $description );
			if ( $public_response instanceof WP_Error ) {
				return $public_response;
			}
		}

		if ( in_array( $status, self::TERMINAL_STATUSES, true ) ) {
			$this->release_inflight_bulkhead( $run_id, $lease_token );
		}

		return $public_response;
	}

	/** @return list<int> */
	private function allowlisted_media_ids(): array {
		$configured = get_option( 'acx_public_demo_media_ids', array() );
		if ( ! is_array( $configured ) ) {
			return array();
		}

		$ids = array_map( 'absint', $configured );
		$ids = array_values( array_filter( $ids ) );
		return array_values( array_unique( $ids ) );
	}

	private function client_rate_key(): string|WP_Error {
		// Deliberately trust only the direct peer address. Forwarded headers are
		// attacker-controlled unless a deployment-specific trusted-proxy layer
		// normalizes them before WordPress.
		// phpcs:ignore WordPress.Security.ValidatedSanitizedInput.InputNotSanitized -- validated as an IP immediately below; transforming it would change rate-limit identity.
		$address = is_string( $_SERVER['REMOTE_ADDR'] ?? null ) ? (string) $_SERVER['REMOTE_ADDR'] : '';
		if ( false === filter_var( $address, FILTER_VALIDATE_IP ) ) {
			return new WP_Error(
				PublicDemoErrorCode::CLIENT_UNAVAILABLE,
				'The demo could not identify this client safely.',
				array( 'status' => 403 )
			);
		}

		return hash( 'sha256', $address );
	}

	private function request_idempotency_key( WP_REST_Request $request ): string {
		$raw = $request->get_param( 'idempotency_key' );
		if ( ! is_string( $raw ) || '' === trim( $raw ) ) {
			$raw = $request->get_header( 'Idempotency-Key' );
		}
		$normalized = is_string( $raw ) ? trim( sanitize_text_field( $raw ) ) : '';
		if ( '' === $normalized ) {
			// Keep direct PHP callers backwards-compatible; the browser always
			// supplies an explicit key for retry-safe public submissions.
			return wp_generate_uuid4();
		}
		if ( strlen( $normalized ) > self::IDEMPOTENCY_KEY_MAX_LENGTH ) {
			return hash( 'sha256', $normalized );
		}

		return $normalized;
	}

	private function idempotency_transient_key( string $client_key, string $idempotency_key ): string {
		return self::IDEMPOTENCY_TRANSIENT_PREFIX . hash( 'sha256', $client_key . ':' . $idempotency_key );
	}

	/** @param array<string,mixed> $entry */
	private function idempotency_response( array $entry ): ?WP_REST_Response {
		$run_id = is_string( $entry['run_id'] ?? null ) ? sanitize_text_field( $entry['run_id'] ) : '';
		if ( '' === $run_id || 'pending' === $run_id ) {
			return null;
		}
		if ( is_array( $entry['response'] ?? null ) ) {
			return new WP_REST_Response(
				$entry['response'],
				max( 200, (int) ( $entry['response_status'] ?? 202 ) )
			);
		}

		// An accepted response can lose its final mapping write or report a
		// post-acceptance tracking error. Returning a minimal valid envelope keeps
		// retries on the same run without inventing a second paid submission.
		return new WP_REST_Response(
			array(
				'run_id'           => $run_id,
				'status'           => 'running',
				'phase'            => 'describing',
				'gpu_state'        => null,
				'progress'         => array( 'done' => 0, 'total' => 1 ),
				'deadline_seconds' => $this->public_deadline_seconds(),
			),
			202
		);
	}

	private function store_idempotency_mapping(
		string $transient_key,
		int $media_id,
		string $run_id,
		?WP_REST_Response $response = null
	): bool {
		$mapping = array(
			'media_id'   => $media_id,
			'run_id'     => $run_id,
			'expires_at' => time() + self::IDEMPOTENCY_TTL_SECONDS,
		);
		if ( $response instanceof WP_REST_Response ) {
			$mapping['response'] = $response->get_data();
			$mapping['response_status'] = $response->get_status();
		}

		return set_transient( $transient_key, $mapping, self::IDEMPOTENCY_TTL_SECONDS );
	}

	private function consume_rate_token( string $client_key ): bool|WP_REST_Response {
		$lock_key = 'acx_public_demo_rate_lock_' . $client_key;
		$lock_token = $this->acquire_lock( $lock_key, 5 );
		if ( false === $lock_token ) {
			return $this->limited_response( PublicDemoErrorCode::STATE_UNAVAILABLE, 'The demo is temporarily busy. Please retry.', 1 );
		}

		try {
			$now     = time();
			$rate    = max( 1, (int) apply_filters( 'acx_public_demo_rate_per_minute', self::DEFAULT_RATE_PER_MIN ) );
			$key     = 'acx_public_demo_rate_' . $client_key;
			$bucket  = get_transient( $key );
			$tokens  = is_array( $bucket ) ? (float) ( $bucket['tokens'] ?? $rate ) : (float) $rate;
			$updated = is_array( $bucket ) ? (int) ( $bucket['updated'] ?? $now ) : $now;
			$tokens  = min( (float) $rate, $tokens + max( 0, $now - $updated ) * ( $rate / 60 ) );

			if ( $tokens < 1.0 ) {
				$retry_after = max( 1, (int) ceil( ( 1.0 - $tokens ) / ( $rate / 60 ) ) );
				return $this->limited_response( PublicDemoErrorCode::RATE_LIMITED, 'Too many demo requests. Please wait and try again.', $retry_after );
			}

			if ( ! set_transient( $key, array( 'tokens' => $tokens - 1.0, 'updated' => $now ), self::RATE_TTL_SECONDS ) ) {
				return $this->limited_response( PublicDemoErrorCode::STATE_UNAVAILABLE, 'The demo rate limiter is unavailable. Please retry.', 5 );
			}
		} finally {
			$this->release_lock( $lock_key, $lock_token );
		}

		return true;
	}

	private function acquire_inflight_bulkhead( int $media_id ): bool {
		$token = wp_generate_uuid4();
		$value = array(
			'media_id'  => $media_id,
			'run_id'    => 'pending',
			'token'     => $token,
			'expires_at' => time() + self::INFLIGHT_TTL_SECONDS,
		);
		if ( add_option( self::INFLIGHT_OPTION, $value, '', false ) ) {
			$this->inflight_token = $token;
			return true;
		}

		$guard = $this->acquire_lock( self::INFLIGHT_OPTION . '_reconcile', 5 );
		if ( false === $guard ) {
			return false;
		}

		try {
			$current = get_option( self::INFLIGHT_OPTION, false );
			if ( false === $current ) {
				$acquired = add_option( self::INFLIGHT_OPTION, $value, '', false );
				$this->inflight_token = $acquired ? $token : null;
				return $acquired;
			}
			if ( ! is_array( $current ) || (int) ( $current['expires_at'] ?? 0 ) >= time() ) {
				return false;
			}

			$run_id = is_string( $current['run_id'] ?? null ) ? $current['run_id'] : '';
			if ( 'pending' === $run_id ) {
				if ( ! empty( $current['submission_started'] ) ) {
					// No run ID is available to reconcile an uncertain dispatch.
					// An operator must verify backend quiescence before clearing it.
					return false;
				}
				// A submitter can die before dispatch. Replace that expired lease
				// while holding the reconciliation guard. Fence the
				// write against the exact expired owner snapshot: a renewed or replaced
				// lease must never be overwritten by this recovery attempt.
				if ( ! is_string( $current['token'] ?? null ) || '' === $current['token'] ) {
					return false;
				}
				$observed = get_option( self::INFLIGHT_OPTION, false );
				if (
					$current !== $observed
					|| ! is_array( $observed )
					|| ! is_string( $observed['token'] ?? null )
					|| ! hash_equals( $current['token'], $observed['token'] )
					|| (int) ( $observed['expires_at'] ?? 0 ) >= time()
				) {
					return false;
				}
				$acquired = $this->update_inflight_lease( $current, $value );
				$this->inflight_token = $acquired ? $token : null;
				return $acquired;
			}
			if ( '' === $run_id ) {
				return false;
			}
			$state = $this->reconcile_backend_run( $run_id );
			if ( 'terminal' !== $state && 'unknown' !== $state ) {
				$this->renew_inflight_lease( $current, $run_id );
				return false;
			}

			if ( get_option( self::INFLIGHT_OPTION, false ) !== $current ) {
				return false;
			}
			if ( ! $this->delete_inflight_lease( $current ) ) {
				return false;
			}
			$acquired = add_option( self::INFLIGHT_OPTION, $value, '', false );
			$this->inflight_token = $acquired ? $token : null;
			return $acquired;
		} finally {
			$this->release_lock( self::INFLIGHT_OPTION . '_reconcile', $guard );
		}
	}

	/** @param array<string,mixed> $expected */
	private function renew_inflight_lease( array $expected, string $run_id ): void {
		$current = get_option( self::INFLIGHT_OPTION, false );
		if ( $current !== $expected || ! is_string( $current['token'] ?? null ) ) {
			return;
		}
		$current['expires_at'] = time() + self::INFLIGHT_TTL_SECONDS;
		$current['run_id'] = $run_id;
		$this->update_inflight_lease( $expected, $current );
	}

	private function mark_submission_started(): bool {
		$current = get_option( self::INFLIGHT_OPTION, false );
		if (
			null === $this->inflight_token
			|| ! is_array( $current )
			|| 'pending' !== ( $current['run_id'] ?? null )
			|| ! is_string( $current['token'] ?? null )
			|| ! hash_equals( $current['token'], $this->inflight_token )
		) {
			return false;
		}
		$started = $current;
		$started['submission_started'] = true;
		return $this->update_inflight_lease( $current, $started );
	}

	private function reconcile_backend_run( string $run_id ): string {
		$request = new WP_REST_Request( 'GET', '/acx/v1/recognition/describe/runs/' . $run_id );
		$request->set_param( 'run_id', $run_id );
		$response = $this->pipeline->get_describe_run_status( $request );
		if ( $response instanceof WP_Error ) {
			$data = $response->get_error_data();
			return is_array( $data ) && 404 === (int) ( $data['status'] ?? 0 ) ? 'unknown' : 'indeterminate';
		}
		if ( 404 === $response->get_status() ) {
			return 'unknown';
		}
		if ( $response->get_status() >= 400 ) {
			return 'indeterminate';
		}
		$data = $response->get_data();
		$response_run_id = is_array( $data ) && is_string( $data['run_id'] ?? null ) ? $data['run_id'] : '';
		if ( '' === $response_run_id || ! hash_equals( $run_id, $response_run_id ) ) {
			return 'indeterminate';
		}
		$validated = $this->public_envelope_response( $response, false );
		if ( $validated instanceof WP_Error ) {
			return 'indeterminate';
		}
		$status = $validated->get_data()['status'];
		if ( in_array( $status, self::TERMINAL_STATUSES, true ) ) {
			return 'terminal';
		}
		return in_array( $status, self::LIVE_STATUSES, true ) ? 'live' : 'indeterminate';
	}

	private function bind_inflight_run( string $run_id ): bool {
		// Acceptance must be recorded even while another submit holds the
		// reconciliation guard. The snapshot CAS fences this write against
		// replacement; guard contention must not discard the accepted run ID.
		$current = get_option( self::INFLIGHT_OPTION, false );
		if (
			null === $this->inflight_token
			|| ! is_array( $current )
			|| 'pending' !== ( $current['run_id'] ?? null )
			|| ! is_string( $current['token'] ?? null )
			|| ! hash_equals( $current['token'], $this->inflight_token )
		) {
			return false;
		}

		$bound = array(
			'run_id'    => $run_id,
			'media_id'  => absint( $current['media_id'] ?? 0 ),
			'token'     => $current['token'],
			'expires_at' => time() + self::INFLIGHT_TTL_SECONDS,
		);
		return $this->update_inflight_lease( $current, $bound );
	}

	private function release_inflight_bulkhead( ?string $expected_run_id = null, ?string $expected_token = null ): void {
		$current = get_option( self::INFLIGHT_OPTION, false );
		$expected_token = $expected_token ?? $this->inflight_token;
		if ( ! is_array( $current ) || null === $expected_token ) {
			return;
		}
		if ( null !== $expected_run_id && ( ! is_string( $current['run_id'] ?? null ) || ! hash_equals( $current['run_id'], $expected_run_id ) ) ) {
			return;
		}
		if ( ! is_string( $current['token'] ?? null ) || ! hash_equals( $current['token'], $expected_token ) ) {
			return;
		}
		$this->delete_inflight_lease( $current );
	}

	/**
	 * @param array<string,mixed> $expected
	 * @param array<string,mixed> $replacement
	 */
	private function update_inflight_lease( array $expected, array $replacement ): bool {
		global $wpdb;

		// Fence the write itself. The reconciliation guard can expire while a
		// request is paused; a prior ownership read cannot protect a later write.
		$updated = $wpdb->query(
			$wpdb->prepare(
				"UPDATE {$wpdb->options} SET option_value = %s WHERE option_name = %s AND BINARY option_value = %s",
				serialize( $replacement ),
				self::INFLIGHT_OPTION,
				serialize( $expected )
			)
		);
		wp_cache_delete( self::INFLIGHT_OPTION, 'options' );
		return 1 === $updated;
	}

	/** @param array<string,mixed> $expected */
	private function delete_inflight_lease( array $expected ): bool {
		global $wpdb;

		// Compare the complete owner snapshot in the DELETE itself. An option
		// read followed by delete_option() can erase a concurrently replaced or
		// renewed lease, even after checking its token immediately beforehand.
		$wpdb->query(
			$wpdb->prepare(
				"DELETE FROM {$wpdb->options} WHERE option_name = %s AND BINARY option_value = %s",
				self::INFLIGHT_OPTION,
				serialize( $expected )
			)
		);
		// This option is always non-autoloaded. Invalidate even on a compare
		// miss so a stale cached owner cannot hide the database's replacement.
		wp_cache_delete( self::INFLIGHT_OPTION, 'options' );
		return 1 === $deleted;
	}

	private function reserve_daily_capacity(): bool|WP_REST_Response {
		$date        = gmdate( 'Ymd' );
		$count_key   = 'acx_public_demo_daily_usage';
		$lock_key    = 'acx_public_demo_daily_lock';
		$retry_after = max( 1, 86400 - ( time() % 86400 ) );
		$lock_token = $this->acquire_lock( $lock_key, 5 );
		if ( false === $lock_token ) {
			return $this->limited_response( PublicDemoErrorCode::STATE_UNAVAILABLE, 'The demo usage counter is temporarily unavailable.', 1 );
		}

		try {
			$cap   = max( 0, absint( get_option( 'acx_public_demo_daily_cap', self::DEFAULT_DAILY_CAP ) ) );
			$usage = get_option( $count_key, array() );
			$count = is_array( $usage ) && $date === ( $usage['date'] ?? null ) ? max( 0, absint( $usage['count'] ?? 0 ) ) : 0;
			if ( $count >= $cap ) {
				return $this->limited_response( PublicDemoErrorCode::DAILY_CAP_REACHED, 'Today\'s demo limit has been reached. Please return tomorrow.', $retry_after );
			}

			$next = array( 'date' => $date, 'count' => $count + 1 );
			update_option( $count_key, $next, false );
			if ( $next !== get_option( $count_key, array() ) ) {
				return $this->limited_response( PublicDemoErrorCode::STATE_UNAVAILABLE, 'The demo usage counter could not be updated safely.', 5 );
			}
		} finally {
			$this->release_lock( $lock_key, $lock_token );
		}

		return true;
	}

	/** @param array<string,mixed> $extra */
	private function acquire_lock( string $option, int $ttl, string $run_id = '', array $extra = array() ): string|false {
		$token = wp_generate_uuid4();
		$value = array_merge( $extra, array( 'run_id' => $run_id, 'token' => $token, 'expires_at' => time() + $ttl ) );
		if ( add_option( $option, $value, '', false ) ) {
			return $token;
		}

		$current = get_option( $option, false );
		if ( ! is_array( $current ) || (int) ( $current['expires_at'] ?? 0 ) >= time() ) {
			return false;
		}

		// WordPress options do not expose a conditional add-with-TTL. Replace an
		// expired record only when its complete snapshot still matches; a newer
		// owner then makes this compare-and-set fail instead of being deleted.
		global $wpdb;
		$updated = $wpdb->query(
			$wpdb->prepare(
				"UPDATE {$wpdb->options} SET option_value = %s WHERE option_name = %s AND BINARY option_value = %s",
				serialize( $value ),
				$option,
				serialize( $current )
			)
		);
		wp_cache_delete( $option, 'options' );
		return 1 === $updated ? $token : false;
	}

	private function release_lock( string $option, string $token ): void {
		global $wpdb;

		$current = get_option( $option, false );
		if ( ! is_array( $current ) || ! is_string( $current['token'] ?? null ) || ! hash_equals( $current['token'], $token ) ) {
			return;
		}

		// The ownership check belongs in the DELETE itself. If this request was
		// paused until its TTL elapsed and another owner acquired the lock, the
		// stale release affects zero rows and cannot remove the newer lock.
		$wpdb->query(
			$wpdb->prepare(
				"DELETE FROM {$wpdb->options} WHERE option_name = %s AND BINARY option_value = %s",
				$option,
				serialize( $current )
			)
		);
		wp_cache_delete( $option, 'options' );
	}

	private function public_description( WP_REST_Request $pipeline_request, int $media_id, string $expected_run_id, string $expected_token ): string|WP_Error {
		$items_response = $this->pipeline->get_describe_run_items( $pipeline_request );
		if ( ! $items_response instanceof WP_REST_Response || $items_response->get_status() >= 400 ) {
			return $this->invalid_pipeline_response();
		}

		$items_data = $items_response->get_data();
		$items_run_id = is_array( $items_data ) && is_string( $items_data['run_id'] ?? null ) ? $items_data['run_id'] : '';
		$current = get_option( self::INFLIGHT_OPTION, false );
		$current_run_id = is_array( $current ) && is_string( $current['run_id'] ?? null ) ? $current['run_id'] : '';
		$current_token = is_array( $current ) && is_string( $current['token'] ?? null ) ? $current['token'] : '';
		if (
			'' === $items_run_id
			|| '' === $current_run_id
			|| '' === $current_token
			|| ! hash_equals( $expected_run_id, $items_run_id )
			|| ! hash_equals( $expected_run_id, $current_run_id )
			|| ! hash_equals( $expected_token, $current_token )
		) {
			return $this->invalid_pipeline_response();
		}
		$items      = is_array( $items_data ) && is_array( $items_data['items'] ?? null ) ? $items_data['items'] : array();
		foreach ( $items as $item ) {
			if ( ! is_array( $item ) || $media_id !== absint( $item['media_id'] ?? 0 ) ) {
				continue;
			}
			$description = is_string( $item['alt_text_draft'] ?? null ) ? trim( $item['alt_text_draft'] ) : '';
			if ( '' === $description ) {
				continue;
			}
			return $description;
		}

		return '';
	}

	private function public_envelope_response( WP_REST_Response $upstream, bool $include_deadline, string $description = '' ): WP_REST_Response|WP_Error {
		$data = $upstream->get_data();
		if ( ! is_array( $data ) ) {
			return $this->invalid_pipeline_response();
		}
		$run_id = is_string( $data['run_id'] ?? null ) ? sanitize_text_field( $data['run_id'] ) : '';
		$status = is_string( $data['status'] ?? null ) ? $data['status'] : '';
		$phase = is_string( $data['phase'] ?? null ) ? $data['phase'] : '';
		$has_gpu_state = array_key_exists( 'gpu_state', $data );
		$gpu_state = $has_gpu_state ? $data['gpu_state'] : null;
		$completed = $data['completed'] ?? null;
		$failed = $data['failed'] ?? null;
		$skipped = $data['skipped'] ?? null;
		$total = $data['total'] ?? null;
		if (
			'' === $run_id
			|| ! in_array( $status, array_merge( self::LIVE_STATUSES, self::TERMINAL_STATUSES ), true )
			|| ! in_array( $phase, self::PHASES, true )
			|| ( $has_gpu_state && null !== $gpu_state && ( ! is_string( $gpu_state ) || ! in_array( $gpu_state, self::GPU_STATES, true ) ) )
			|| ! is_int( $completed ) || ! is_int( $failed ) || ! is_int( $skipped ) || ! is_int( $total )
			|| ! $this->status_matches_phase( $status, $phase )
		) {
			return $this->invalid_pipeline_response();
		}
		if ( $completed < 0 || $failed < 0 || $skipped < 0 || $total < 0 ) {
			return $this->invalid_pipeline_response();
		}

		$done = $completed + $failed + $skipped;
		$total = (int) $total;
		if ( $done > $total ) {
			return $this->invalid_pipeline_response();
		}
		if (
			( in_array( $status, array( 'completed', 'completed_with_errors' ), true ) && $done !== $total )
			|| ( 'completed' === $status && 0 !== $failed )
		) {
			return $this->invalid_pipeline_response();
		}

		$public = array(
			'run_id' => $run_id,
			'status' => $status,
			'phase' => $phase,
		);
		if ( $has_gpu_state ) {
			$public['gpu_state'] = $gpu_state;
		}
		$public['progress'] = array( 'done' => $done, 'total' => $total );
		if ( $include_deadline ) {
			$public['deadline_seconds'] = $this->public_deadline_seconds();
		}
		if ( 'completed' === $status && '' !== $description ) {
			$public['description'] = $description;
		}
		if ( 'completed_with_errors' === $status ) {
			$public['error'] = array(
				'code' => PublicDemoErrorCode::PARTIAL_FAILURE,
				'message' => 'The description did not complete successfully. Please try another image.',
			);
		} elseif ( in_array( $status, array( 'failed', 'cancelled' ), true ) ) {
			$public['error'] = array(
				'code' => PublicDemoErrorCode::PIPELINE_FAILED,
				'message' => 'The image could not be described. Please try again later.',
			);
		}

		return new WP_REST_Response( $public, $upstream->get_status() );
	}

	private function status_matches_phase( string $status, string $phase ): bool {
		if ( 'pending' === $status ) {
			return 'queued' === $phase;
		}
		if ( 'running' === $status ) {
			return in_array( $phase, array( 'warming', 'describing' ), true );
		}
		$terminal_phases = array(
			'completed' => 'complete',
			'completed_with_errors' => 'complete',
			'failed' => 'failed',
			'cancelled' => 'cancelled',
		);
		return ( $terminal_phases[ $status ] ?? '' ) === $phase;
	}

	private function public_deadline_seconds(): int {
		if ( ! defined( 'ACX_GPU_WARMUP_TIMEOUT_SECONDS' ) && function_exists( 'acx_define_env_constant' ) ) {
			\acx_define_env_constant(
				'ACX_GPU_WARMUP_TIMEOUT_SECONDS',
				array( 'ACX_GPU_WARMUP_TIMEOUT_SECONDS' ),
				static fn ( string $value ): int => is_numeric( $value )
					? max( 1, (int) $value )
					: self::DEFAULT_GPU_WARMUP_TIMEOUT_SECONDS
			);
		}
		$warmup = defined( 'ACX_GPU_WARMUP_TIMEOUT_SECONDS' )
			? max( 1, (int) constant( 'ACX_GPU_WARMUP_TIMEOUT_SECONDS' ) )
			: self::DEFAULT_GPU_WARMUP_TIMEOUT_SECONDS;
		$inference = max( 1, (int) apply_filters( 'acx_proxy_timeout_description_seconds', self::DEFAULT_INFERENCE_TIMEOUT_SECONDS ) );
		return $warmup + $inference;
	}

	private function invalid_pipeline_response(): WP_Error {
		return new WP_Error(
			PublicDemoErrorCode::INVALID_RESPONSE,
			'The description service returned an invalid response. Please try again later.',
			array( 'status' => 502 )
		);
	}

	private function translated_pipeline_error( WP_REST_Response|WP_Error $upstream ): WP_Error {
		$status = 502;
		if ( $upstream instanceof WP_REST_Response ) {
			$status = $upstream->get_status() >= 500 ? 503 : 502;
		} else {
			$data = $upstream->get_error_data();
			if ( is_array( $data ) && (int) ( $data['status'] ?? 0 ) >= 500 ) {
				$status = 503;
			}
		}
		return new WP_Error(
			PublicDemoErrorCode::PIPELINE_FAILED,
			'The description service is temporarily unavailable. Please try again later.',
			array( 'status' => $status )
		);
	}

	private function limited_response( string $code, string $message, int $retry_after ): WP_REST_Response {
		return new WP_REST_Response(
			array(
				'code'    => $code,
				'message' => $message,
				'data'    => array( 'status' => 429 ),
			),
			429,
			array( 'Retry-After' => (string) max( 1, $retry_after ) )
		);
	}
}
