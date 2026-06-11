<?php

declare(strict_types=1);

namespace AltContext\Api\Services;

use AltContext\Api\ClustersHostInterface;
use AltContext\Sovereign\Repositories\ClustersRepository;
use AltContext\Sovereign\Repositories\ClustersRepositoryInterface;
use AltContext\Sovereign\Repositories\IdentityMembersRepository;
use AltContext\Sovereign\Repositories\IdentityMembersRepositoryInterface;
use AltContext\Sovereign\Repositories\SyncStateRepositoryInterface;
use AltContext\Sovereign\Sync\SnapshotClient;
use AltContext\Sovereign\Sync\SyncPullJobFactory;
use AltContext\Sovereign\Sync\SyncPullJobInterface;
use AltContext\Sovereign\Sync\TargetedSyncPullJobInterface;
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

	public function should_use_local_projection( string $tenant_id ): bool {
		$has_projection = $this->host->host_should_use_local_projection_gate( $this->sync_state_repository, $tenant_id );
		if ( ! $has_projection ) {
			return false;
		}

		$updated_at    = $this->sync_state_repository->get_last_updated( $tenant_id );
		$sync_pull_job = $this->resolve_sync_pull_job();
		if ( $this->host->host_is_projection_stale( $updated_at ) && null !== $sync_pull_job ) {
			try {
				$sync_pull_job->perform( $tenant_id );
			} catch ( Throwable $e ) {
				do_action(
					'acx_sync_pull_failed',
					array(
						'tenant_id' => $tenant_id,
						'context' => 'stale_projection_read',
						'message' => $e->getMessage(),
					)
				);
			}
		}

		return true;
	}

	public function maybe_bootstrap_after_proxy_read( string $tenant_id, WP_REST_Response|WP_Error $response ): WP_REST_Response|WP_Error {
		if ( ! ( $response instanceof WP_REST_Response ) ) {
			return $response;
		}

		if ( $response->get_status() < 200 || $response->get_status() >= 300 ) {
			return $response;
		}

		$sync_pull_job = $this->resolve_sync_pull_job();
		if ( null === $sync_pull_job ) {
			return $response;
		}

		$inline_result = $sync_pull_job->perform_bypass_cooldown( $tenant_id );
		if ( ! $inline_result->is_success() ) {
			$args = array( $tenant_id );
			if ( false === wp_next_scheduled( $this->bootstrap_sync_hook, $args ) ) {
				wp_schedule_single_event( time(), $this->bootstrap_sync_hook, $args );
			}
		}

		return $response;
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
	 * @param string[] $cluster_ids
	 */
	public function repair_targeted_projection( string $tenant_id, array $cluster_ids ): bool {
		$sync_pull_job = $this->resolve_sync_pull_job();
		if ( ! ( $sync_pull_job instanceof TargetedSyncPullJobInterface ) ) {
			return false;
		}

		try {
			$result = $sync_pull_job->perform_targeted_snapshot( $tenant_id, $cluster_ids );
			return $result->is_success();
		} catch ( Throwable $throwable ) {
			do_action(
				'acx_sync_pull_failed',
				array(
					'tenant_id' => $tenant_id,
					'context' => 'targeted_projection_read_repair',
					'message' => $throwable->getMessage(),
				)
			);
			return false;
		}
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
