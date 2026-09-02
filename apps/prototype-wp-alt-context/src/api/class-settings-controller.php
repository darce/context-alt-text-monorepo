<?php

declare(strict_types=1);

namespace AltContext\Api;

require_once __DIR__ . '/class-alt-style.php';
require_once __DIR__ . '/../settings/class-recognition-policy.php';
require_once __DIR__ . '/class-probe-outcome.php';
require_once __DIR__ . '/class-recognition-endpoint-resolver.php';
require_once __DIR__ . '/class-tenant-identity.php';
require_once __DIR__ . '/services/class-description-budget-service.php';
require_once __DIR__ . '/services/class-tenant-local-rekey-service.php';
require_once __DIR__ . '/../support/class-loopback-host.php';
require_once __DIR__ . '/../support/class-recognition-transport.php';

use AltContext\Api\Services\DescriptionBudgetService;
use AltContext\Api\Services\TenantLocalRekeyService;
use AltContext\Settings\RecognitionPolicy;
use AltContext\Support\LoopbackHost;
use AltContext\Support\RecognitionTransport;

use WP_Error;
use WP_REST_Request;
use WP_REST_Response;
use function apply_filters;
use function array_key_exists;
use function current_user_can;
use function defined;
use function get_option;
use function in_array;
use function intval;
use function is_array;
use function is_bool;
use function is_int;
use function is_numeric;
use function is_string;
use function is_wp_error;
use function json_decode;
use function parse_url;
use function register_rest_route;
use function rtrim;
use function stripos;
use function strtolower;
use function substr;
use function trim;
use function update_option;
use function wp_is_uuid;
use function wp_remote_retrieve_body;
use function wp_remote_retrieve_headers;
use function wp_remote_retrieve_response_code;

/**
 * REST controller for recognition API configuration.
 *
 * GET  /acx/v1/settings          — read current config with source detection
 * POST /acx/v1/settings          — save URL and/or API key to WP options
 * POST /acx/v1/settings/test     — probe the authenticated recognition pool
 *                                  endpoint and classify the response into one
 *                                  of ten canonical {@see ProbeOutcome} codes
 */
class SettingsController {
	/**
	 * Wire vocabulary for POST /settings `result` [sr-007].
	 * Mirrored by TypeScript `SettingsSaveResult` in settingsApi.ts.
	 * Happy-path stays `{ saved, result: 'ok' }` byte-compatible with existing clients.
	 */
	public const SAVE_RESULT_OK      = 'ok';
	public const SAVE_RESULT_PARTIAL = 'partial';
	public const SAVE_RESULT_ERROR   = 'error';

	private RecognitionEndpointResolver $endpoint_resolver;

	private DescriptionBudgetService $description_budget_service;

	public function __construct(
		?RecognitionEndpointResolver $endpoint_resolver = null,
		?DescriptionBudgetService $description_budget_service = null
	) {
		$this->endpoint_resolver          = $endpoint_resolver ?? new RecognitionEndpointResolver();
		$this->description_budget_service = $description_budget_service ?? new DescriptionBudgetService();
	}

	public function register_routes(): void {
		register_rest_route(
			'acx/v1',
			'/settings',
			array(
				array(
					'methods'             => 'GET',
					'callback'            => array( $this, 'get_settings' ),
					'permission_callback' => array( $this, 'can_manage_settings' ),
				),
				array(
					'methods'             => 'POST',
					'callback'            => array( $this, 'save_settings' ),
					'permission_callback' => array( $this, 'can_manage_settings' ),
				),
			)
		);

		register_rest_route(
			'acx/v1',
			'/settings/test',
			array(
				'methods'             => 'POST',
				'callback'            => array( $this, 'test_connection' ),
				'permission_callback' => array( $this, 'can_manage_settings' ),
			)
		);
	}

	public function can_manage_settings(): bool {
		return current_user_can( 'manage_options' );
	}

	public function get_settings( WP_REST_Request $request ): WP_REST_Response {
		$snapshot          = $this->endpoint_resolver->resolve_settings_snapshot();
		$key_resolution    = $this->resolve_key_source();
		$tenant_resolution = TenantIdentity::resolve();

		return new WP_REST_Response(
			array(
				'url'                       => $snapshot['service_url'],
				'url_source'                => $snapshot['service_url_source'],
				// BR-138: service_url_rejection_* → url_rejection_* (same rename as url/url_source).
				'url_rejection_reason'      => $snapshot['service_url_rejection_reason'],
				'url_rejection_source'      => $snapshot['service_url_rejection_source'],
				'url_rejection_value'       => $snapshot['service_url_rejection_value'],
				'effective_target_url'      => $snapshot['effective_target_url'],
				'effective_target_mode'     => $snapshot['effective_target_mode'],
				'recognition_source'        => $snapshot['recognition_source'],
				'recognition_source_source' => $snapshot['recognition_source_source'],
				'api_key_set'               => '' !== $key_resolution['value'],
				'api_key_last4'             => $this->mask_key( $key_resolution['value'] ),
				'key_source'                => $key_resolution['source'],
				'tenant_id'                 => $tenant_resolution['value'],
				'tenant_id_source'          => $tenant_resolution['source'],
				'tenant_paired'             => TenantIdentity::is_paired(),
				'alt_style'                 => AltStyle::current(),
				'recognition_enabled'       => RecognitionPolicy::enabled(),
				'description_budget'        => $this->get_description_budget_payload(),
			),
			200
		);
	}

	public function save_settings( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$body   = $request->get_json_params();
		$body   = is_array( $body ) ? $body : array();
		$saved  = array();
		$failed = array();

		if ( isset( $body['url'] ) && is_string( $body['url'] ) ) {
			$url = trim( $body['url'] );
			if ( '' !== $url && ! $this->is_valid_url( $url ) ) {
				return new WP_Error(
					'invalid_url',
					'The recognition API URL must be HTTPS (HTTP is allowed only for loopback development hosts).',
					array( 'status' => 400 )
				);
			}
			// R23-BR-14: do not trust update_option's return (false on no-op *and*
			// failure). Read back and compare against the intended value; a no-op
			// re-save still matches. option_matches_intended() verifies effect, not
			// bytes in storage — see its docblock [R23-BR-35].
			update_option( 'acx_recognition_url', $url );
			if ( $this->option_matches_intended( 'acx_recognition_url', $url ) ) {
				$saved[] = 'url';
			} else {
				$failed[] = 'url';
			}
		}

		// RECOG-1: the product no longer writes acx_recognition_source or
		// acx_recognition_local_url. Local remains a dev-only code hatch reachable
		// via the ACX_RECOGNITION_SOURCE / ACX_RECOGNITION_LOCAL_URL constants (or
		// their filters), never the Settings surface.

		if ( isset( $body['api_key'] ) && is_string( $body['api_key'] ) ) {
			$key = trim( $body['api_key'] );
			update_option( 'acx_recognition_api_key', $key );
			if ( $this->option_matches_intended( 'acx_recognition_api_key', $key ) ) {
				$saved[] = 'api_key';
			} else {
				$failed[] = 'api_key';
			}
		}

		if ( isset( $body['alt_style'] ) ) {
			// ALTQ-1: gate for writing the optional backend alt_text_long to the
			// attachment description on describe writes.
			if ( ! AltStyle::is_valid( $body['alt_style'] ) ) {
				return new WP_Error(
					'invalid_alt_style',
					'alt_style must be one of: alt_only, alt_plus_description.',
					array( 'status' => 400 )
				);
			}
			$alt_style = $body['alt_style'];
			update_option( AltStyle::OPTION_NAME, $alt_style );
			if ( $this->option_matches_intended( AltStyle::OPTION_NAME, $alt_style ) ) {
				$saved[] = 'alt_style';
			} else {
				$failed[] = 'alt_style';
			}
		}

		if ( array_key_exists( 'recognition_enabled', $body ) ) {
			if ( ! is_bool( $body['recognition_enabled'] ) ) {
				return new WP_Error(
					'invalid_recognition_enabled',
					'recognition_enabled must be a boolean.',
					array( 'status' => 400 )
				);
			}
			$recognition_enabled = $body['recognition_enabled'];
			RecognitionPolicy::set( $recognition_enabled );
			if ( $this->option_matches_intended( RecognitionPolicy::OPTION, $recognition_enabled ) ) {
				$saved[] = 'recognition_enabled';
			} else {
				$failed[] = 'recognition_enabled';
			}
		}

		if ( isset( $body['description_budget'] ) && is_array( $body['description_budget'] ) ) {
			$max_attempts = $body['description_budget']['max_attempts'] ?? null;
			if ( ! is_int( $max_attempts ) && ! is_numeric( $max_attempts ) ) {
				return new WP_Error(
					'invalid_description_budget',
					'Description budget max attempts must be an integer greater than or equal to -1.',
					array( 'status' => 400 )
				);
			}

			$max_attempts = (int) $max_attempts;
			if ( $max_attempts < -1 ) {
				return new WP_Error(
					'invalid_description_budget',
					'Description budget max attempts must be greater than or equal to -1.',
					array( 'status' => 400 )
				);
			}

			update_option( 'acx_description_budget_max_attempts', $max_attempts );
			// Int options may reappear as numeric strings after a cold options
			// load from the DB; option_matches_intended models that coerce.
			if ( $this->option_matches_intended( 'acx_description_budget_max_attempts', $max_attempts ) ) {
				$saved[] = 'description_budget';
			} else {
				$failed[] = 'description_budget';
			}
		}

		// Happy path stays { saved, result: 'ok' } — no extra keys [byte-compat].
		// Non-ok names the fields that did not land so the operator can act.
		$result = self::SAVE_RESULT_OK;
		if ( array() !== $failed ) {
			$result = array() === $saved
				? self::SAVE_RESULT_ERROR
				: self::SAVE_RESULT_PARTIAL;
		}

		$payload = array(
			'saved'  => $saved,
			'result' => $result,
		);
		if ( array() !== $failed ) {
			$payload['failed'] = $failed;
		}

		return new WP_REST_Response( $payload, 200 );
	}

	/**
	 * True when a read of the option now yields the intended value.
	 *
	 * update_option returns false for both storage failure and no-op (value
	 * already equal), so its return cannot be trusted and a read-back is
	 * required [R23-BR-14].
	 *
	 * What this verifies is effect, not bytes-in-storage [R23-BR-35]. get_option
	 * applies pre_option_{$option} / option_{$option} / default_option_{$option},
	 * so this compares the intended value against the *filtered* read — which is
	 * deliberate: every consumer of these keys also reads through get_option
	 * (see class-recognition-endpoint-resolver.php and
	 * class-abstract-recognition-proxy-controller.php), so the filtered value is
	 * what the site will actually use. A filter that diverges the read means the
	 * operator's value is not in effect, and reporting it as saved would be the
	 * false success R23-BR-14 removed. Verifying an unfiltered $wpdb read here
	 * would reintroduce exactly that.
	 *
	 * Consequence to keep in mind: a false return does not distinguish "did not
	 * persist" from "persisted but a filter overrides the read". Both are
	 * correctly not-saved; neither is separately reported.
	 *
	 * Integer options are compared via numeric coerce so a DB-reloaded string
	 * form does not false-fail a successful write.
	 *
	 * @param string $option   Option name.
	 * @param mixed  $intended Value that should be in effect.
	 */
	private function option_matches_intended( string $option, $intended ): bool {
		// null default: missing option is distinguishable from stored empty string.
		$stored = get_option( $option, null );
		if ( is_int( $intended ) ) {
			return is_numeric( $stored ) && (int) $stored === $intended;
		}
		if ( is_bool( $intended ) ) {
			// Missing option is not a successful bool write, even when DEFAULT
			// would make enabled() true. Coerce stored WP '1'/'0'/'' forms.
			if ( null === $stored ) {
				return false;
			}

			return RecognitionPolicy::normalize( $stored ) === $intended;
		}

		return $stored === $intended;
	}

	/**
	 * @return array<string,mixed>
	 */
	private function get_description_budget_payload(): array {
		return array(
			'max_attempts'  => (int) get_option( 'acx_description_budget_max_attempts', -1 ),
			'usage'         => $this->description_budget_service->usage_summary(),
			'recent_errors' => $this->description_budget_service->recent_errors( 5 ),
		);
	}

	public function test_connection( WP_REST_Request $request ): WP_REST_Response {
		// RECOG-1: the keyless local `/health` liveness probe and the
		// probe_target=local dispatch are retired. Test always exercises the
		// authenticated service probe against the effective target (the dev hatch,
		// if active, routes the effective target to local and is probed with a key).
		$snapshot = $this->endpoint_resolver->resolve_settings_snapshot();
		$url      = $snapshot['effective_target_url'];

		if ( '' === $url ) {
			return new WP_REST_Response(
				array(
					'outcome'     => ProbeOutcome::NOT_CONFIGURED,
					'probe_mode'  => 'service_auth',
					'probed_url'  => '',
				),
				200
			);
		}

		$key_resolution = $this->resolve_key_source();
		$headers        = array(
			'X-Tenant-ID' => TenantIdentity::resolve()['value'],
		);
		if ( '' !== $key_resolution['value'] ) {
			$headers['X-API-Key'] = $key_resolution['value'];
		}

		$health_url = rtrim( $url, '/' ) . '/health/detailed';
		// BR-131/BR-137: RecognitionTransport chooses safe vs loopback transport
		// and forces redirection => 0 so X-API-Key cannot walk on 3xx.
		$response = RecognitionTransport::get(
			$health_url,
			array(
				'headers' => $headers,
				'timeout' => 10,
			)
		);

		$payload = $this->build_probe_payload( $response );
		$payload['probe_mode'] = 'service_auth';
		$payload['probed_url'] = $health_url;

		// A mismatched key (403 -> TENANT_MISMATCH) is a first-time / paired-elsewhere pairing signal,
		// not a terminal error: attempt pairing so a never-paired auto-derived site can auto-adopt and
		// recover in a single "Check health" click. Every other non-CONNECTED outcome is terminal.
		$probe_outcome    = $payload['outcome'] ?? null;
		$pairing_eligible = in_array( $probe_outcome, array( ProbeOutcome::CONNECTED, ProbeOutcome::TENANT_MISMATCH ), true );
		if ( ! $pairing_eligible ) {
			return new WP_REST_Response( $payload, 200 );
		}

		$confirm_pairing = $this->request_confirms_tenant_pairing( $request );
		$pairing         = $this->attempt_tenant_pairing(
			base_url: $url,
			headers: $headers,
			confirm_pairing: $confirm_pairing,
		);
		$pairing_outcome = $pairing['outcome'] ?? null;
		$pairing_errors  = array( ProbeOutcome::NETWORK_ERROR, ProbeOutcome::SERVER_ERROR );
		if ( in_array( $pairing_outcome, $pairing_errors, true ) ) {
			$detail = is_string( $pairing['detail'] ?? null ) ? $pairing['detail'] : 'Tenant pairing failed.';
			// Isolate the pairing failure into pairing_error; the probe's own detail (e.g. the mismatch
			// reason) must survive so the banner still reports the underlying probe outcome as-is.
			unset( $pairing['outcome'], $pairing['status_code'], $pairing['detail'] );
			$payload                  = array_merge( $payload, $pairing );
			$payload['pairing_error'] = $detail;

			return new WP_REST_Response( $payload, 200 );
		}

		$payload = array_merge( $payload, $pairing );

		// Recovery from a mismatch: adoption just re-pointed this site at the key's canonical tenant,
		// so re-probe /health/detailed EXACTLY ONCE with the adopted identity to reach green in the same
		// request. Strictly bounded -- one pairing attempt + one re-probe, never a retry loop. If the
		// re-probe still fails, its outcome is returned as-is. A conflict (paired elsewhere) does not
		// adopt, so it skips the re-probe and surfaces TENANT_PAIRING_CONFLICT to the banner.
		$adopted = true === ( $pairing['tenant_paired'] ?? false );
		if ( $adopted && ProbeOutcome::TENANT_MISMATCH === $probe_outcome ) {
			$reprobe_headers                = $headers;
			$reprobe_headers['X-Tenant-ID'] = TenantIdentity::resolve()['value'];
			$reprobe_response = RecognitionTransport::get(
				$health_url,
				array(
					'headers' => $reprobe_headers,
					'timeout' => 10,
				)
			);

			$reprobe_payload               = $this->build_probe_payload( $reprobe_response );
			$reprobe_payload['probe_mode'] = 'service_auth';
			$reprobe_payload['probed_url'] = $health_url;
			$payload                       = array_merge( $reprobe_payload, $pairing );
		}

		return new WP_REST_Response( $payload, 200 );
	}

	/**
	 * @param array<string, string> $headers
	 * @return array<string, mixed>
	 */
	private function attempt_tenant_pairing( string $base_url, array $headers, bool $confirm_pairing ): array {
		$whoami_url = rtrim( $base_url, '/' ) . '/recognition/tenant/whoami';
		$response   = RecognitionTransport::get(
			$whoami_url,
			array(
				'headers' => $headers,
				'timeout' => 10,
			)
		);

		if ( is_wp_error( $response ) ) {
			return array(
				'outcome' => ProbeOutcome::NETWORK_ERROR,
				'detail'  => (string) $response->get_error_message(),
			);
		}

		$status_code = (int) wp_remote_retrieve_response_code( $response );
		if ( $status_code < 200 || $status_code >= 300 ) {
			$body    = wp_remote_retrieve_body( $response );
			$decoded = json_decode( $body, true );
			$detail  = is_array( $decoded ) && isset( $decoded['detail'] ) && is_string( $decoded['detail'] )
				? $decoded['detail']
				: 'Tenant pairing lookup failed.';
			return array(
				'outcome'     => ProbeOutcome::SERVER_ERROR,
				'status_code' => $status_code,
				'detail'      => $detail,
			);
		}

		$body = json_decode( wp_remote_retrieve_body( $response ), true );
		if ( ! is_array( $body ) || ! isset( $body['tenant_id'] ) || ! is_string( $body['tenant_id'] ) ) {
			return array(
				'outcome' => ProbeOutcome::SERVER_ERROR,
				'detail'  => 'Tenant pairing response missing tenant_id.',
			);
		}

		$key_tenant_id = strtolower( trim( $body['tenant_id'] ) );
		if ( ! wp_is_uuid( $key_tenant_id ) ) {
			return array(
				'outcome' => ProbeOutcome::SERVER_ERROR,
				'detail'  => 'Tenant pairing response returned a malformed tenant_id.',
			);
		}

		$current_resolution = TenantIdentity::resolve();
		$current_tenant_id  = strtolower( $current_resolution['value'] );

		if ( $current_tenant_id === $key_tenant_id ) {
			// R23-BR-15: adopt throws RuntimeException on storage failure (distinct
			// from InvalidArgumentException for a malformed UUID). Surface as a
			// pairing error — do not claim tenant_paired when the option did not land.
			try {
				TenantIdentity::adopt_paired_tenant( $key_tenant_id );
			} catch ( \RuntimeException $e ) {
				return array(
					'outcome' => ProbeOutcome::SERVER_ERROR,
					'detail'  => $e->getMessage(),
				);
			}
			return array(
				'tenant_paired'    => true,
				'tenant_id'        => $key_tenant_id,
				'tenant_id_source' => 'option',
			);
		}

		// First-time pairing: a never-paired, un-pinned auto-derived identity adopts the API key's
		// canonical tenant outright -- the key claim is the single service-side authority. resolve()
		// persists the derived id on first call, so "option unset" is unreachable; detect the bootstrap
		// identity by value instead. Only an already-paired site (or a deliberately pinned/persisted id)
		// whose key now maps elsewhere requires the explicit conflict-confirm dance.
		$auto_adoptable = ! TenantIdentity::is_paired()
			&& TenantIdentity::is_auto_derived_identity( $current_tenant_id );

		if ( ! $auto_adoptable && ! $confirm_pairing ) {
			return array(
				'outcome'             => ProbeOutcome::TENANT_PAIRING_CONFLICT,
				'persisted_tenant_id' => $current_tenant_id,
				'key_tenant_id'       => $key_tenant_id,
			);
		}

		// R23-BR-28: adopt+verify the tenant-id option (and only then the paired
		// flag, inside adopt_paired_tenant) BEFORE rekeying local rows / writing
		// the resync_required marker. Prior order rekeyed first; if adopt then
		// failed, durable rows already advertised the new tenant while pairing
		// was incomplete. option_matches_intended() is option-scoped (save_settings
		// path) and does not fit table-row rekey verification — adopt_paired_tenant
		// already performs the option read-back; rekey verifies via row count
		// read-back before its marker [sr-007].
		//
		// Call sites of adopt_paired_tenant (both in this method):
		// 1. matching-tenant path above — try/catch RuntimeException → SERVER_ERROR
		// 2. this rekey / auto-adopt path — same catch shape
		// Call site of reconcile_identity_change: only here. Wrapped so a rekey
		// throw after a successful adopt surfaces as SERVER_ERROR (not a 500),
		// with tenant_paired already true so the operator sees identity landed
		// and rekey needs retry (extra keys only on this non-success path).
		try {
			TenantIdentity::adopt_paired_tenant( $key_tenant_id );
		} catch ( \RuntimeException $e ) {
			return array(
				'outcome' => ProbeOutcome::SERVER_ERROR,
				'detail'  => $e->getMessage(),
			);
		}

		$rekey_service = new TenantLocalRekeyService();
		try {
			$rekey_result = $rekey_service->reconcile_identity_change( $current_tenant_id, $key_tenant_id );
		} catch ( \RuntimeException $e ) {
			return array(
				'outcome'        => ProbeOutcome::SERVER_ERROR,
				'detail'         => $e->getMessage(),
				'tenant_paired'  => true,
				'tenant_id'      => $key_tenant_id,
				'rekey_failed'   => true,
			);
		}

		return array(
			'tenant_paired'       => true,
			'tenant_id'           => $key_tenant_id,
			'tenant_id_source'    => 'option',
			'rekey_strategy'      => $rekey_result['strategy'],
			'rekey_updated_rows'  => $rekey_result['updated_rows'],
		);
	}

	private function request_confirms_tenant_pairing( WP_REST_Request $request ): bool {
		$body = $request->get_json_params();
		if ( ! is_array( $body ) ) {
			return false;
		}

		return ! empty( $body['confirm_tenant_pairing'] );
	}

	/**
	 * Build the full /settings/test response payload from the raw wp_remote_get
	 * result. The wire contract is `{outcome, status_code?, retry_after_seconds?,
	 * detail?, body?}`. Consumers derive a boolean "connected" from
	 * `outcome === 'connected'`; the controller never emits that field itself.
	 *
	 * @param WP_Error|array<string, mixed> $response
	 * @return array<string, mixed>
	 */
	private function build_probe_payload( WP_Error|array $response ): array {
		if ( is_wp_error( $response ) ) {
			$message = (string) $response->get_error_message();
			$outcome = $this->is_tls_failure( $message )
				? ProbeOutcome::TLS_ERROR
				: ProbeOutcome::NETWORK_ERROR;
			$payload = array( 'outcome' => $outcome );
			if ( '' !== $message ) {
				$payload['detail'] = $message;
			}
			return $payload;
		}

		$status_code = (int) wp_remote_retrieve_response_code( $response );
		$body        = wp_remote_retrieve_body( $response );
		$decoded     = json_decode( $body, true );
		$detail      = is_array( $decoded ) && isset( $decoded['detail'] ) && is_string( $decoded['detail'] )
			? $decoded['detail']
			: null;

		$outcome = $this->classify_http_status( $status_code, $detail );
		$payload = array(
			'outcome'     => $outcome,
			'status_code' => $status_code,
			'body'        => null !== $decoded ? $decoded : $body,
		);
		if ( null !== $detail ) {
			$payload['detail'] = $detail;
		}
		if ( ProbeOutcome::RATE_LIMITED === $outcome ) {
			$retry_after = $this->parse_retry_after( $this->retrieve_retry_after_header( $response ) );
			if ( null !== $retry_after ) {
				$payload['retry_after_seconds'] = $retry_after;
			}
		}
		return $payload;
	}

	/**
	 * @param array<string, mixed> $response
	 */
	private function retrieve_retry_after_header( array $response ): mixed {
		$headers = wp_remote_retrieve_headers( $response );
		if ( is_array( $headers ) ) {
			return $headers['Retry-After']
				?? $headers['retry-after']
				?? null;
		}
		if ( $headers instanceof \ArrayAccess ) {
			if ( isset( $headers['Retry-After'] ) ) {
				return $headers['Retry-After'];
			}
			if ( isset( $headers['retry-after'] ) ) {
				return $headers['retry-after'];
			}
		}
		return null;
	}

	private function classify_http_status( int $status_code, ?string $detail ): string {
		if ( $status_code >= 200 && $status_code < 300 ) {
			return ProbeOutcome::CONNECTED;
		}
		if ( 401 === $status_code ) {
			if ( 'api key expired' === $detail ) {
				return ProbeOutcome::EXPIRED;
			}
			if ( 'api key revoked' === $detail ) {
				return ProbeOutcome::REVOKED;
			}
			return ProbeOutcome::INVALID_KEY;
		}
		if ( 403 === $status_code ) {
			if ( 'tenant mismatch' === $detail ) {
				return ProbeOutcome::TENANT_MISMATCH;
			}
			return ProbeOutcome::INVALID_KEY;
		}
		if ( 429 === $status_code ) {
			return ProbeOutcome::RATE_LIMITED;
		}
		if ( $status_code >= 500 ) {
			return ProbeOutcome::SERVER_ERROR;
		}
		return ProbeOutcome::SERVER_ERROR;
	}

	private function is_tls_failure( string $message ): bool {
		if ( '' === $message ) {
			return false;
		}
		foreach ( array( 'certificate', 'SSL', 'TLS' ) as $keyword ) {
			if ( false !== stripos( $message, $keyword ) ) {
				return true;
			}
		}
		return false;
	}

	/**
	 * Parse a Retry-After header value, treating it as integer delta-seconds
	 * per RFC 7231 §7.1.3 — the form emitted by the recognition service's
	 * enforce_rate_limit dependency (E15-1 Slice 1). HTTP-date form is not
	 * supported; a non-numeric value falls back to null and the UI renders a
	 * generic "wait a few seconds" hint.
	 */
	private function parse_retry_after( mixed $raw ): ?int {
		if ( is_array( $raw ) ) {
			$raw = $raw[0] ?? null;
		}
		if ( ! is_string( $raw ) ) {
			return null;
		}
		$trimmed = trim( $raw );
		if ( '' === $trimmed ) {
			return null;
		}
		$parsed = intval( $trimmed );
		if ( $parsed <= 0 ) {
			return null;
		}
		return $parsed;
	}

	/**
	 * Resolve the recognition API key and its source.
	 *
	 * @return array{value: string, source: string}
	 */
	private function resolve_key_source(): array {
		// E15-12-RR-01: code-managed sources (constant, filter) MUST win over
		// operator-saved options. The pre-fix order resolved option before
		// filter, mirroring the BR-07 URL bug: a stale saved key kept routing
		// recognition auth even after an operator wired a filter to inject a
		// deploy-time key, and the key field surfaced as option-owned/editable
		// instead of code-managed/read-only. Precedence is now: constant ->
		// filter -> option -> default, matching resolve_url_source() and the
		// documented selector contract.
		$constant = $this->get_constant_value( 'ACX_RECOGNITION_API_KEY' );
		if ( '' !== $constant ) {
			return array( 'value' => $constant, 'source' => 'constant' );
		}

		$filter = trim( (string) apply_filters( 'acx_recognition_api_key', '' ) );
		if ( '' !== $filter ) {
			return array( 'value' => $filter, 'source' => 'filter' );
		}

		$option = trim( (string) get_option( 'acx_recognition_api_key', '' ) );
		if ( '' !== $option ) {
			return array( 'value' => $option, 'source' => 'option' );
		}

		return array( 'value' => '', 'source' => 'default' );
	}

	private function get_constant_value( string $name ): string {
		if ( defined( $name ) && is_string( constant( $name ) ) ) {
			return trim( constant( $name ) );
		}
		return '';
	}

	private function mask_key( string $key ): string {
		if ( strlen( $key ) <= 4 ) {
			return '' === $key ? '' : '****';
		}
		return '****' . substr( $key, -4 );
	}

	/**
	 * BR-131: require https for saved service URLs. Permit http only for
	 * loopback hosts (LocalWP / local description-service hatch). Rejects
	 * http://attacker.invalid while keeping http://localhost:8000.
	 */
	private function is_valid_url( string $url ): bool {
		$parts = parse_url( $url );
		if ( false === $parts || ! is_array( $parts ) ) {
			return false;
		}
		if ( ! isset( $parts['scheme'], $parts['host'] ) ) {
			return false;
		}

		$scheme = strtolower( (string) $parts['scheme'] );
		$host   = strtolower( (string) $parts['host'] );
		if ( '' === $host ) {
			return false;
		}

		if ( 'https' === $scheme ) {
			return true;
		}

		return 'http' === $scheme && LoopbackHost::is_loopback( $host );
	}
}
