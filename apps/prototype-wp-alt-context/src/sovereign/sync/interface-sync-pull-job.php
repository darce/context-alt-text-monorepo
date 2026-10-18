<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Sync;

require_once __DIR__ . '/class-sync-pull-result.php';

interface SyncPullJobInterface {
	public function perform( string $tenant_id ): SyncPullResult;

	public function perform_bypass_cooldown( string $tenant_id ): SyncPullResult;

	/**
	 * @param array<string,mixed> $payload
	 */
	public function perform_projection_payload( string $tenant_id, array $payload ): SyncPullResult;
}
