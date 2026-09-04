<?php

declare(strict_types=1);

namespace AltContext\PublicSite;

/**
 * Canonical public-demo REST error vocabulary (sr-007).
 */
final class PublicDemoErrorCode {
	public const DISABLED              = 'acx_public_demo_disabled';
	public const INVALID_NONCE         = 'acx_public_demo_invalid_nonce';
	public const MEDIA_NOT_ALLOWED     = 'acx_public_demo_media_not_allowed';
	public const CLIENT_UNAVAILABLE    = 'acx_public_demo_client_unavailable';
	public const RATE_LIMITED          = 'acx_public_demo_rate_limited';
	public const DAILY_CAP_REACHED     = 'acx_public_demo_daily_cap_reached';
	public const BUSY                  = 'acx_public_demo_busy';
	public const STATE_UNAVAILABLE     = 'acx_public_demo_state_unavailable';
	public const RUN_NOT_AVAILABLE     = 'acx_public_demo_run_not_available';
	public const INVALID_PIPELINE_DATA = 'acx_public_demo_invalid_pipeline_data';
	public const PIPELINE_FAILED       = 'acx_public_demo_pipeline_failed';
	public const PARTIAL_FAILURE       = 'acx_public_demo_partial_failure';

	private function __construct() {
	}
}
