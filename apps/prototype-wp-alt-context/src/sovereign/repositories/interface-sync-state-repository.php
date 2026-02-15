<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Repositories;

interface SyncStateRepositoryInterface {
	public function upsert_snapshot_version( string $tenant_id, int $snapshot_version ): void;

	public function get_snapshot_version( string $tenant_id ): int;

	public function get_last_updated( string $tenant_id ): ?string;
}
