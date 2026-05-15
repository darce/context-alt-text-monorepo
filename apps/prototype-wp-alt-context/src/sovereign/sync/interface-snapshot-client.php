<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Sync;

use WP_Error;
use WP_REST_Response;

interface SnapshotClientInterface {
	public function fetch_snapshot( string $tenant_id ): array|WP_Error;

	public function fetch_delta( string $tenant_id, int $since_version ): array|WP_Error;

	/**
	 * @param string[] $cluster_ids
	 */
	public function fetch_targeted_snapshot( string $tenant_id, array $cluster_ids ): array|WP_Error;

	public function acknowledge_projection( string $job_id, int $snapshot_version, ?string $snapshot_generation_id = null ): WP_REST_Response|WP_Error;
}
