<?php

declare(strict_types=1);

namespace AltContext\Api;

/**
 * Canonical outcome codes for the Settings page "Test Connection" probe.
 *
 * These ten string values are the wire contract between SettingsController
 * and the React SettingsPage, mirrored bit-for-bit by the TypeScript
 * `TestConnectionOutcome` object in `settingsApi.ts`.
 *
 * Nine post-HTTP outcomes map 1:1 onto the auth decisions emitted by
 * `_require_auth_impl` in the recognition service (plus transport failure
 * classifications). `NOT_CONFIGURED` is a local precondition, evaluated
 * before any HTTP request is attempted.
 */
final class ProbeOutcome {
	public const CONNECTED       = 'connected';
	public const NOT_CONFIGURED  = 'not_configured';
	public const INVALID_KEY     = 'invalid_key';
	public const EXPIRED         = 'expired';
	public const REVOKED         = 'revoked';
	public const TENANT_MISMATCH = 'tenant_mismatch';
	public const RATE_LIMITED    = 'rate_limited';
	public const SERVER_ERROR    = 'server_error';
	public const NETWORK_ERROR   = 'network_error';
	public const TLS_ERROR               = 'tls_error';
	public const TENANT_PAIRING_CONFLICT = 'tenant_pairing_conflict';

	private function __construct() {}
}
