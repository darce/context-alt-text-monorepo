<?php

declare(strict_types=1);

namespace AltContext\Tests\Stubs;

use AltContext\Sovereign\Sync\SyncPullResult;
use AltContext\Sovereign\Sync\TargetedSyncPullJobInterface;

/**
 * Recording TargetedSyncPullJobInterface spy for Api::handle_bootstrap_sync.
 */
final class TargetedSpySyncPullJob implements TargetedSyncPullJobInterface {
	/** @var list<string> */
	public array $performCalls = array();

	/** @var list<string> */
	public array $bypassCalls = array();

	/** @var list<array{tenant_id:string,cluster_ids:list<string>}> */
	public array $targetedCalls = array();

	public function perform( string $tenant_id ): SyncPullResult {
		$this->performCalls[] = $tenant_id;
		return SyncPullResult::ok();
	}

	public function perform_bypass_cooldown( string $tenant_id ): SyncPullResult {
		$this->bypassCalls[] = $tenant_id;
		return SyncPullResult::ok();
	}

	public function perform_projection_payload( string $tenant_id, array $payload ): SyncPullResult {
		return SyncPullResult::ok();
	}

	/**
	 * @param string[] $cluster_ids
	 */
	public function perform_targeted_snapshot( string $tenant_id, array $cluster_ids ): SyncPullResult {
		$this->targetedCalls[] = array(
			'tenant_id' => $tenant_id,
			'cluster_ids' => $cluster_ids,
		);
		return SyncPullResult::ok();
	}
}
