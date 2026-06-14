<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Sync;

require_once __DIR__ . '/../repositories/interface-sync-state-repository.php';
require_once __DIR__ . '/class-sync-pull-result.php';
require_once __DIR__ . '/class-snapshot-client.php';
require_once __DIR__ . '/interface-targeted-sync-pull-job.php';

use AltContext\Sovereign\Repositories\SyncStateRepositoryInterface;
use RuntimeException;
use Throwable;

use function do_action;
use function esc_html;
use function is_wp_error;
use function array_filter;
use function array_map;
use function array_unique;
use function array_values;
use function get_transient;
use function md5;
use function sanitize_text_field;
use function set_transient;
use function trim;

class SyncPullJob implements TargetedSyncPullJobInterface {
	/** Cooldown after projection or auth failures. */
	private const FAILED_SYNC_COOLDOWN_SECONDS = 30;
	/** Short cooldown after transient connectivity failures to speed recovery. */
	private const UNREACHABLE_SYNC_COOLDOWN_SECONDS = 5;
	/** Tenant-specific cooldown key prefix used by perform() and bypass path writes. */
	private const COOLDOWN_TRANSIENT_PREFIX = 'acx_sync_cooldown_';

	private SnapshotClient $client;
	private SnapshotProjectorInterface $projector;
	private SyncStateRepositoryInterface $sync_state_repository;

	public function __construct(
		SnapshotClient $client,
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

	/**
	 * Apply a completed job-status projection payload without re-fetching snapshot state.
	 *
	 * @param array<string,mixed> $payload
	 */
	public function perform_projection_payload( string $tenant_id, array $payload ): SyncPullResult {
		$transient_key = self::COOLDOWN_TRANSIENT_PREFIX . md5( $tenant_id );

		try {
			$this->projector->project_delta( $tenant_id, $payload );
		} catch ( Throwable $throwable ) {
			$this->sync_state_repository->set_last_sync_result( $tenant_id, SyncPullResult::FAILED );
			set_transient( $transient_key, 1, self::FAILED_SYNC_COOLDOWN_SECONDS );
			do_action(
				'acx_sync_pull_failed',
				array(
					'tenant_id' => $tenant_id,
					'context' => 'inline_projection_failed',
					'message' => $throwable->getMessage(),
				)
			);
			return SyncPullResult::failed();
		}

		$this->sync_state_repository->set_last_sync_result( $tenant_id, SyncPullResult::OK );

		try {
			$this->maybe_acknowledge_projection( $payload );
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
	 * @param string[] $cluster_ids
	 */
	public function perform_targeted_snapshot( string $tenant_id, array $cluster_ids ): SyncPullResult {
		$normalized_cluster_ids = array_values(
			array_unique(
				array_filter(
					array_map(
						static function ( $cluster_id ): string {
							return sanitize_text_field( trim( (string) $cluster_id ) );
						},
						$cluster_ids
					),
					static function ( string $cluster_id ): bool {
						return '' !== $cluster_id;
					}
				)
			)
		);

		if ( empty( $normalized_cluster_ids ) ) {
			return SyncPullResult::skipped();
		}

		$snapshot = $this->client->fetch_targeted_snapshot( $tenant_id, $normalized_cluster_ids );
		if ( is_wp_error( $snapshot ) ) {
			$this->sync_state_repository->set_last_sync_result( $tenant_id, SyncPullResult::UNREACHABLE );
			do_action(
				'acx_sync_pull_failed',
				array(
					'tenant_id' => $tenant_id,
					'context' => 'targeted_snapshot_fetch_failed',
					'message' => $snapshot->get_error_message(),
				)
			);
			return SyncPullResult::unreachable();
		}

		try {
			$this->projector->project_delta( $tenant_id, $snapshot );
		} catch ( Throwable $throwable ) {
			$this->sync_state_repository->set_last_sync_result( $tenant_id, SyncPullResult::FAILED );
			do_action(
				'acx_sync_pull_failed',
				array(
					'tenant_id' => $tenant_id,
					'context' => 'targeted_projection_failed',
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
					'context' => 'targeted_projection_acknowledgement_failed',
					'message' => $throwable->getMessage(),
				)
			);
		}

		return SyncPullResult::ok();
	}

	private function do_sync( string $tenant_id, string $transient_key ): SyncPullResult {
		$last_snapshot_version = max( 0, $this->sync_state_repository->get_snapshot_version( $tenant_id ) );
		$delta_result          = $this->try_delta_sync( $tenant_id, $last_snapshot_version );
		if ( $delta_result instanceof SyncPullResult ) {
			return $delta_result;
		}

		$snapshot = $this->client->fetch_snapshot( $tenant_id );
		if ( is_wp_error( $snapshot ) ) {
			$this->sync_state_repository->set_last_sync_result( $tenant_id, SyncPullResult::UNREACHABLE );
			set_transient( $transient_key, 1, self::UNREACHABLE_SYNC_COOLDOWN_SECONDS );
			return SyncPullResult::unreachable();
		}

		try {
			$this->projector->project( $tenant_id, $snapshot );
		} catch ( Throwable $throwable ) {
			$this->sync_state_repository->set_last_sync_result( $tenant_id, SyncPullResult::FAILED );
			set_transient( $transient_key, 1, self::FAILED_SYNC_COOLDOWN_SECONDS );
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
	 * Attempt delta projection first when the tenant already has a local snapshot version.
	 *
	 * Returns `null` to signal snapshot fallback.
	 */
	private function try_delta_sync( string $tenant_id, int $since_version ): ?SyncPullResult {
		$delta = $this->client->fetch_delta( $tenant_id, $since_version );
		if ( is_wp_error( $delta ) ) {
			do_action(
				'acx_sync_pull_failed',
				array(
					'tenant_id' => $tenant_id,
					'context' => 'delta_fetch_failed',
					'message' => $delta->get_error_message(),
				)
			);
			return null;
		}

		if ( true === ( $delta['fallback_to_snapshot'] ?? false ) ) {
			return null;
		}

		try {
			$this->projector->project_delta( $tenant_id, $delta );
		} catch ( Throwable $throwable ) {
			do_action(
				'acx_sync_pull_failed',
				array(
					'tenant_id' => $tenant_id,
					'context' => 'delta_projection_failed',
					'message' => $throwable->getMessage(),
				)
			);
			return null;
		}

		$this->sync_state_repository->set_last_sync_result( $tenant_id, SyncPullResult::OK );
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
