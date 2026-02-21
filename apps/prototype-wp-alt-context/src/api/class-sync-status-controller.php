<?php

declare(strict_types=1);

namespace AltContext\Api;

require_once __DIR__ . '/../sovereign/repositories/interface-clusters-repository.php';
require_once __DIR__ . '/../sovereign/repositories/class-clusters-repository.php';
require_once __DIR__ . '/../sovereign/repositories/interface-identity-members-repository.php';
require_once __DIR__ . '/../sovereign/repositories/class-identity-members-repository.php';
require_once __DIR__ . '/../sovereign/repositories/interface-sync-state-repository.php';
require_once __DIR__ . '/../sovereign/repositories/class-sync-state-repository.php';
require_once __DIR__ . '/../sovereign/sync/interface-snapshot-projector.php';
require_once __DIR__ . '/../sovereign/sync/class-snapshot-client.php';
require_once __DIR__ . '/../sovereign/sync/class-snapshot-projector.php';
require_once __DIR__ . '/../sovereign/sync/interface-sync-pull-job.php';
require_once __DIR__ . '/../sovereign/sync/class-sync-pull-job.php';

use AltContext\Sovereign\Repositories\ClustersRepository;
use AltContext\Sovereign\Repositories\IdentityMembersRepository;
use AltContext\Sovereign\Repositories\SyncStateRepository;
use AltContext\Sovereign\Repositories\SyncStateRepositoryInterface;
use AltContext\Sovereign\Sync\SnapshotClient;
use AltContext\Sovereign\Sync\SnapshotProjector;
use AltContext\Sovereign\Sync\SyncPullJob;
use AltContext\Sovereign\Sync\SyncPullJobInterface;
use Throwable;
use WP_REST_Request;
use WP_REST_Response;

use function do_action;

class SyncStatusController extends AbstractRecognitionProxyController {
	private SyncStateRepositoryInterface $sync_state_repository;
	private ?SyncPullJobInterface $sync_pull_job;
	private ?string $sync_pull_job_error;
	private bool $sync_pull_job_resolution_failed;

	public function __construct(
		?SyncStateRepositoryInterface $sync_state_repository = null,
		?SyncPullJobInterface $sync_pull_job = null
	) {
		$this->sync_state_repository = $sync_state_repository ?? new SyncStateRepository();
		$this->sync_pull_job = $sync_pull_job;
		$this->sync_pull_job_error = null;
		$this->sync_pull_job_resolution_failed = false;
	}

	public function register_routes(): void {
		register_rest_route(
			'acx/v1',
			'/recognition/sync-status',
			array(
				'methods'             => 'GET',
				'callback'            => array( $this, 'get_sync_status' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
			)
		);

		register_rest_route(
			'acx/v1',
			'/recognition/sync/trigger',
			array(
				'methods'             => 'POST',
				'callback'            => array( $this, 'trigger_sync' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
			)
		);
	}

	public function get_sync_status( WP_REST_Request $request ): WP_REST_Response {
		$tenant_id = $this->get_tenant_id();
		$version   = $this->sync_state_repository->get_snapshot_version( $tenant_id );
		$updated   = $this->sync_state_repository->get_last_updated( $tenant_id );

		return new WP_REST_Response(
			array(
				'last_snapshot_version' => $version,
				'last_synced_at' => $updated,
				'is_stale' => $this->is_projection_stale( $updated ),
			),
			200
		);
	}

	public function trigger_sync( WP_REST_Request $request ): WP_REST_Response {
		$tenant_id = $this->get_tenant_id();
		$sync_pull_job = $this->resolve_sync_pull_job();

		if ( null === $sync_pull_job ) {
			return new WP_REST_Response(
				array(
					'synced' => false,
					'reason' => 'sync_unavailable',
					'error' => $this->sync_pull_job_error,
				),
				200
			);
		}

		try {
			$success = $sync_pull_job->perform_bypass_cooldown( $tenant_id );
		} catch ( Throwable $e ) {
			$success = false;
		}

		$version = $this->sync_state_repository->get_snapshot_version( $tenant_id );
		$updated = $this->sync_state_repository->get_last_updated( $tenant_id );

		return new WP_REST_Response(
			array(
				'synced'                => $success,
				'reason'                => $success ? 'ok' : 'sync_failed',
				'last_snapshot_version' => $version,
				'last_synced_at'        => $updated,
				'is_stale'              => $this->is_projection_stale( $updated ),
			),
			200
		);
	}

	private function resolve_sync_pull_job(): ?SyncPullJobInterface {
		if ( null !== $this->sync_pull_job ) {
			return $this->sync_pull_job;
		}
		if ( $this->sync_pull_job_resolution_failed ) {
			return null;
		}

		try {
			$this->sync_pull_job = new SyncPullJob(
				new SnapshotClient(),
				new SnapshotProjector(
					new ClustersRepository(),
					new IdentityMembersRepository(),
					$this->sync_state_repository
				)
			);
		} catch ( Throwable $e ) {
			$this->sync_pull_job_error = $e->getMessage();
			$this->sync_pull_job_resolution_failed = true;
			do_action(
				'acx_recognition_composition_failed',
				array(
					'message' => $e->getMessage(),
					'controller' => __CLASS__,
					'context' => 'sync_status_lazy_sync_pull_job',
				)
			);
			return null;
		}

		return $this->sync_pull_job;
	}
}
