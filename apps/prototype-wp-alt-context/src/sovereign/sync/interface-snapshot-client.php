<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Sync;

use WP_Error;
use WP_REST_Response;

interface SnapshotClientInterface {
	public function fetch_snapshot( string $tenant_id ): array|WP_Error;

	public function acknowledge_projection( string $job_id, int $snapshot_version ): WP_REST_Response|WP_Error;
}
