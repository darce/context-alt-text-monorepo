<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Sync;

interface SnapshotProjectorInterface {
	/**
	 * @param array<string,mixed> $snapshot
	 */
	public function project( string $tenant_id, array $snapshot ): void;

	/**
	 * @param array<string,mixed> $delta
	 */
	public function project_delta( string $tenant_id, array $delta ): void;
}
