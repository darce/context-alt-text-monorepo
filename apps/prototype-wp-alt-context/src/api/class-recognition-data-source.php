<?php

declare(strict_types=1);

namespace AltContext\Api;

/**
 * Canonical PHP vocabulary for recognition read-path provenance (sr-007, [REF-19]).
 *
 * Mirrors the TS DATA_SOURCE object (js/admin/api/recognition/types/dataSource.ts)
 * byte-for-byte; RecognitionDataSourceTest pins the parity. Also owns the
 * bootstrap-sync cron hook name so schedulers and the plugin-load handler
 * registration share a single declaration site.
 */
final class RecognitionDataSource {
	public const LOCAL_PROJECTION = 'local_projection';
	public const BACKEND_PROXY = 'backend_proxy';
	public const ENDPOINT_ERROR = 'endpoint_error';
	public const UNAVAILABLE = 'unavailable';

	public const BOOTSTRAP_SYNC_HOOK = 'acx_bootstrap_sync';

	private function __construct() {
	}
}
