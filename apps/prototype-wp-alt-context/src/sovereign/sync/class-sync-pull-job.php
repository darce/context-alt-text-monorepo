<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Sync;

use function is_array;
use function is_wp_error;

class SyncPullJob implements SyncPullJobInterface {
	private SnapshotClient $client;
	private SnapshotProjectorInterface $projector;

	public function __construct( SnapshotClient $client, SnapshotProjectorInterface $projector ) {
		$this->client = $client;
		$this->projector = $projector;
	}

	public function perform( string $tenant_id ): bool {
		$snapshot = $this->client->fetch_snapshot( $tenant_id );
		if ( is_wp_error( $snapshot ) ) {
			return false;
		}

		if ( ! is_array( $snapshot ) ) {
			return false;
		}

		$this->projector->project( $tenant_id, $snapshot );
		return true;
	}
}
