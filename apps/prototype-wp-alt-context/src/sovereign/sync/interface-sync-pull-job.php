<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Sync;

interface SyncPullJobInterface {
	public function perform( string $tenant_id ): bool;
}
