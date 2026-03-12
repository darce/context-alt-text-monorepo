<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Sync;

require_once __DIR__ . '/../repositories/interface-sync-state-repository.php';
require_once __DIR__ . '/class-sync-pull-result.php';
require_once __DIR__ . '/interface-snapshot-client.php';

use AltContext\Sovereign\Repositories\SyncStateRepositoryInterface;
use RuntimeException;
use Throwable;

use function do_action;
use function esc_html;
use function is_wp_error;
use function get_transient;
use function md5;
use function sanitize_text_field;
use function set_transient;

class SyncPullJob implements SyncPullJobInterface {
	/** Cooldown after failed sync attempts to prevent rapid retry loops. */
	private const SYNC_COOLDOWN_SECONDS = 30;
	/** Tenant-specific cooldown key prefix used by perform() and bypass path writes. */
	private const COOLDOWN_TRANSIENT_PREFIX = 'acx_sync_cooldown_';

	private SnapshotClientInterface $client;
	private SnapshotProjectorInterface $projector;
	private SyncStateRepositoryInterface $sync_state_repository;

	public function __construct(
		SnapshotClientInterface $client,
		SnapshotProjectorInterface $projector,
		SyncStateRepositoryInterface $sync_state_repository
	) {
		$this->client = $client;
		$this->projector = $projector;
		$this->sync_state_repository = $sync_state_repository;
	}

	/**
	 * Run sync with cooldown gate.
	 *
	 * Returns SyncPullResult::skipped() immediately when a cooldown transient is active for the tenant.
	 */
	public function perform( string $tenant_id ): SyncPullResult {
		$transient_key = self::COOLDOWN_TRANSIENT_PREFIX . md5( $tenant_id );
		if ( false !== get_transient( $transient_key ) ) {
			return SyncPullResult::skipped();
		}

		return $this->do_sync( $tenant_id, $transient_key );
	}

	/**
	 * Run sync without checking cooldown.
	 *
	 * Used by explicit user-triggered sync actions; failures still set cooldown.
	 */
	public function perform_bypass_cooldown( string $tenant_id ): SyncPullResult {
		$transient_key = self::COOLDOWN_TRANSIENT_PREFIX . md5( $tenant_id );
		return $this->do_sync( $tenant_id, $transient_key );
	}

	private function do_sync( string $tenant_id, string $transient_key ): SyncPullResult {
		$snapshot = $this->client->fetch_snapshot( $tenant_id );
		if ( is_wp_error( $snapshot ) ) {
			$this->sync_state_repository->set_last_sync_result( $tenant_id, SyncPullResult::UNREACHABLE );
			set_transient( $transient_key, 1, self::SYNC_COOLDOWN_SECONDS );
			return SyncPullResult::unreachable();
		}

		try {
			$this->projector->project( $tenant_id, $snapshot );
		} catch ( Throwable $throwable ) {
			$this->sync_state_repository->set_last_sync_result( $tenant_id, SyncPullResult::FAILED );
			set_transient( $transient_key, 1, self::SYNC_COOLDOWN_SECONDS );
			do_action(
				'acx_sync_pull_failed',
				array(
					'tenant_id' => $tenant_id,
					'context' => 'projection_failed',
					'message' => $throwable->getMessage(),
				)
			);
			return SyncPullResult::failed();
		}

		$this->sync_state_repository->set_last_sync_result( $tenant_id, SyncPullResult::OK );

		try {
			$this->maybe_acknowledge_projection( $snapshot );
		} catch ( Throwable $throwable ) {
			do_action(
				'acx_sync_pull_failed',
				array(
					'tenant_id' => $tenant_id,
					'context' => 'projection_acknowledgement_failed',
					'message' => $throwable->getMessage(),
				)
			);
		}

		return SyncPullResult::ok();
	}

	/**
	 * Projection acknowledgement is coordination metadata only.
	 *
	 * A failed acknowledgement must not mark the sync itself as failed after the
	 * snapshot has already been projected locally.
	 *
	 * @param array<string,mixed> $snapshot
	 * @throws RuntimeException When the backend acknowledgement returns a WP_Error.
	 */
	private function maybe_acknowledge_projection( array $snapshot ): void {
		$snapshot_version = isset( $snapshot['snapshot_version'] ) ? (int) $snapshot['snapshot_version'] : 0;
		$source_job_id    = isset( $snapshot['source_job_id'] ) ? trim( (string) $snapshot['source_job_id'] ) : '';
		$snapshot_generation_id = isset( $snapshot['snapshot_generation_id'] ) ? trim( (string) $snapshot['snapshot_generation_id'] ) : '';
		if ( $snapshot_version <= 0 || '' === $source_job_id ) {
			return;
		}

		$response = $this->client->acknowledge_projection(
			$source_job_id,
			$snapshot_version,
			'' !== $snapshot_generation_id ? $snapshot_generation_id : null
		);
		if ( is_wp_error( $response ) ) {
			throw new RuntimeException( esc_html( sanitize_text_field( $response->get_error_message() ) ) );
		}
	}
}
