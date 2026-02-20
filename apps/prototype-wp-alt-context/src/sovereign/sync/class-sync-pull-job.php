<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Sync;

use Throwable;

use function is_array;
use function is_wp_error;
use function get_transient;
use function md5;
use function set_transient;

class SyncPullJob implements SyncPullJobInterface {
	private const SYNC_COOLDOWN_SECONDS = 30;
	private const COOLDOWN_TRANSIENT_PREFIX = 'acx_sync_cooldown_';

	private SnapshotClient $client;
	private SnapshotProjectorInterface $projector;

	public function __construct( SnapshotClient $client, SnapshotProjectorInterface $projector ) {
		$this->client = $client;
		$this->projector = $projector;
	}

	public function perform( string $tenant_id ): bool {
		$transient_key = self::COOLDOWN_TRANSIENT_PREFIX . md5( $tenant_id );
		if ( false !== get_transient( $transient_key ) ) {
			return false;
		}

		return $this->do_sync( $tenant_id, $transient_key );
	}

	public function perform_bypass_cooldown( string $tenant_id ): bool {
		$transient_key = self::COOLDOWN_TRANSIENT_PREFIX . md5( $tenant_id );
		return $this->do_sync( $tenant_id, $transient_key );
	}

	private function do_sync( string $tenant_id, string $transient_key ): bool {
		$snapshot = $this->client->fetch_snapshot( $tenant_id );
		if ( is_wp_error( $snapshot ) ) {
			set_transient( $transient_key, 1, self::SYNC_COOLDOWN_SECONDS );
			return false;
		}

		if ( ! is_array( $snapshot ) ) {
			set_transient( $transient_key, 1, self::SYNC_COOLDOWN_SECONDS );
			return false;
		}

		try {
			$this->projector->project( $tenant_id, $snapshot );
			return true;
		} catch ( Throwable $throwable ) {
			set_transient( $transient_key, 1, self::SYNC_COOLDOWN_SECONDS );
			return false;
		}
	}
}
