<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Sync;

require_once __DIR__ . '/interface-sync-pull-job.php';
require_once __DIR__ . '/class-sync-pull-result.php';

interface TargetedSyncPullJobInterface extends SyncPullJobInterface {
	/**
	 * Repair a bounded set of clusters from the backend targeted snapshot endpoint.
	 *
	 * @param string[] $cluster_ids
	 */
	public function perform_targeted_snapshot( string $tenant_id, array $cluster_ids ): SyncPullResult;
}
