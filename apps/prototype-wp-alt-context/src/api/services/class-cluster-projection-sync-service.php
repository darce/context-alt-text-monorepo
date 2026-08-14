<?php

declare(strict_types=1);

namespace AltContext\Api\Services;

require_once __DIR__ . '/../../sovereign/class-projection-query-exception.php';
require_once __DIR__ . '/../../support/class-telemetry.php';

use AltContext\Api\ClustersHostInterface;
use AltContext\Sovereign\ProjectionQueryException;
use AltContext\Sovereign\Repositories\ClustersRepository;
use AltContext\Sovereign\Repositories\ClustersRepositoryInterface;
use AltContext\Sovereign\Repositories\IdentityMembersRepository;
use AltContext\Sovereign\Repositories\IdentityMembersRepositoryInterface;
use AltContext\Sovereign\Repositories\SyncStateRepositoryInterface;
use AltContext\Sovereign\Sync\SnapshotClient;
use AltContext\Sovereign\Sync\SyncPullJobFactory;
use AltContext\Sovereign\Sync\SyncPullJobInterface;
use AltContext\Support\Telemetry;
use Throwable;
use WP_Error;
use WP_REST_Response;

use function array_unique;
use function array_values;
use function do_action;
use function is_array;
use function is_numeric;
use function sanitize_text_field;
use function time;
use function trim;
use function wp_next_scheduled;
use function wp_schedule_single_event;

class ClusterProjectionSyncService {
	private ClustersHostInterface $host;
	private string $bootstrap_sync_hook;
	private ClustersRepositoryInterface $clusters_repository;
	private IdentityMembersRepositoryInterface $members_repository;
	private SyncStateRepositoryInterface $sync_state_repository;
	private ?SyncPullJobInterface $sync_pull_job;
	private ?SyncPullJobFactory $sync_pull_job_factory;

	public function __construct(
		ClustersHostInterface $host,
		string $bootstrap_sync_hook,
		?ClustersRepositoryInterface $clusters_repository = null,
		?IdentityMembersRepositoryInterface $members_repository = null,
		?SyncStateRepositoryInterface $sync_state_repository = null,
		?SyncPullJobInterface $sync_pull_job = null,
		?SyncPullJobFactory $sync_pull_job_factory = null
	) {
		$this->host = $host;
		$this->bootstrap_sync_hook = $bootstrap_sync_hook;
		$this->clusters_repository = $clusters_repository ?? new ClustersRepository();
		$this->members_repository = $members_repository ?? new IdentityMembersRepository();
		$this->sync_state_repository = $sync_state_repository;
		$this->sync_pull_job = $sync_pull_job;
		$this->sync_pull_job_factory = $sync_pull_job_factory;
	}

	/**
	 * Rows-first qualification ([DATA-14], [API-09] additive): a read qualifies
	 * for the local projection when the sync-state gate passes OR projection
	 * rows exist for the tenant. The E15-35 wipe class (sync-state row lost
	 * while rows survive) therefore no longer flips reads to the remote proxy.
	 */
	public function should_use_local_projection( string $tenant_id ): bool {
		if ( $this->host->host_should_use_local_projection_gate( $this->sync_state_repository, $tenant_id ) ) {
			$updated_at = $this->sync_state_repository->get_last_updated( $tenant_id );
			if ( $this->host->host_is_projection_stale( $updated_at ) ) {
				// BR-03: heal async, never inline. The prior inline perform() blocked
				// the read on an offline/degraded backend and ignored its result, so a
				// failed refresh left no cron fallback and the projection never healed.
				// Serve local immediately; the deduped cron event converges off-path,
				// matching the newly-qualifying branch and MediaIdentitiesController.
				$this->schedule_bootstrap_sync_event( $tenant_id );
			}

			return true;
		}

		try {
			if ( ! $this->clusters_repository->has_projection_rows_for_tenant( $tenant_id ) ) {
				return false;
			}
		} catch ( ProjectionQueryException $exception ) {
			Telemetry::log_line( sprintf( 'Local projection availability check failed: %s', $exception->getMessage() ) );
			return false;
		}

		// Newly-qualifying state (gate fails, rows present): serve local and
		// heal async via one deduped single event. Never pull inline here —
		// this is exactly the state that must keep serving with the machine
		// offline, and an inline pull would hold the read for the proxy timeout.
		$this->schedule_bootstrap_sync_event( $tenant_id );

		return true;
	}

	public function maybe_bootstrap_after_proxy_read( string $tenant_id, WP_REST_Response|WP_Error $response ): WP_REST_Response|WP_Error {
		if ( ! ( $response instanceof WP_REST_Response ) ) {
			return $response;
		}

		if ( $response->get_status() < 200 || $response->get_status() >= 300 ) {
			return $response;
		}

		// BR-04/BR-02: converge via the deduped async cron event only. The prior
		// inline perform_bypass_cooldown blocked the successful proxy response,
		// coalesced nothing (bypassing the cooldown thundering-herds concurrent
		// reads), and was not throw-guarded (a throwing pull turned a 200 into a
		// 500). The cron handler performs the bypass pull off the request path.
		$this->schedule_bootstrap_sync_event( $tenant_id );

		return $response;
	}

	private function schedule_bootstrap_sync_event( string $tenant_id ): void {
		$args = array( $tenant_id );
		if ( false === wp_next_scheduled( $this->bootstrap_sync_hook, $args ) ) {
			wp_schedule_single_event( time(), $this->bootstrap_sync_hook, $args );
		}
	}

	public function perform_bootstrap_sync( string $tenant_id ): void {
		$sync_pull_job = $this->resolve_sync_pull_job();
		$normalized_tenant_id = trim( $tenant_id );
		if ( '' === $normalized_tenant_id || null === $sync_pull_job ) {
			return;
		}

		$sync_pull_job->perform_bypass_cooldown( $normalized_tenant_id );
	}

	/**
	 * @param array<int,array<string,mixed>> $clusters
	 * @param array<string,array<int,array<string,mixed>>> $members_by_cluster
	 * @return string[]
	 */
	public function find_clusters_missing_projected_members( array $clusters, array $members_by_cluster ): array {
		$cluster_ids = array();
		foreach ( $clusters as $cluster ) {
			if ( ! is_array( $cluster ) ) {
				continue;
			}

			$cluster_id = sanitize_text_field( (string) ( $cluster['cluster_uuid'] ?? '' ) );
			if ( '' === $cluster_id || ! $this->cluster_row_should_have_members( $cluster ) ) {
				continue;
			}

			if ( empty( $members_by_cluster[ $cluster_id ] ) ) {
				$cluster_ids[] = $cluster_id;
			}
		}

		return array_values( array_unique( $cluster_ids ) );
	}

	/**
	 * @param array<string,mixed> $cluster_row
	 */
	public function cluster_row_should_have_members( array $cluster_row ): bool {
		if ( ! isset( $cluster_row['identity_count'] ) || ! is_numeric( $cluster_row['identity_count'] ) ) {
			return false;
		}

		return (int) $cluster_row['identity_count'] > 0;
	}

	/**
	 * BR-07: never pull synchronously on the read path. The prior
	 * perform_targeted_snapshot blocked the sovereign read for the full
	 * targeted-snapshot timeout budget whenever the backend was offline/degraded
	 * — exactly the state rows-first routing must keep serving through. Schedule
	 * the deduped async bootstrap heal and serve the current projection; missing
	 * members converge off the request path. Returns false so callers do not
	 * re-read (nothing was repaired synchronously).
	 *
	 * @param string[] $cluster_ids
	 */
	public function repair_targeted_projection( string $tenant_id, array $cluster_ids ): bool {
		if ( empty( $cluster_ids ) ) {
			return false;
		}

		$this->schedule_bootstrap_sync_event( $tenant_id );

		return false;
	}

	private function resolve_sync_pull_job(): ?SyncPullJobInterface {
		if ( null !== $this->sync_pull_job ) {
			return $this->sync_pull_job;
		}

		try {
			$factory = $this->sync_pull_job_factory ?? new SyncPullJobFactory(
				$this->clusters_repository,
				$this->members_repository,
				$this->sync_state_repository,
				new SnapshotClient()
			);
			$this->sync_pull_job = $factory->create();
		} catch ( Throwable $e ) {
			do_action(
				'acx_recognition_composition_failed',
				array(
					'message' => $e->getMessage(),
					'controller' => __CLASS__,
					'context' => 'clusters_lazy_sync_pull_job',
				)
			);
			return null;
		}

		return $this->sync_pull_job;
	}
}
