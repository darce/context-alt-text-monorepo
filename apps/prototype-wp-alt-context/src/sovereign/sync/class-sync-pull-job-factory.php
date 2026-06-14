<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Sync;

require_once __DIR__ . '/class-snapshot-client.php';
require_once __DIR__ . '/interface-snapshot-projector.php';
require_once __DIR__ . '/class-snapshot-projector.php';
require_once __DIR__ . '/class-sync-pull-job.php';
require_once __DIR__ . '/../repositories/interface-clusters-repository.php';
require_once __DIR__ . '/../repositories/interface-identity-members-repository.php';
require_once __DIR__ . '/../repositories/interface-sync-state-repository.php';

use AltContext\Sovereign\Repositories\ClustersRepositoryInterface;
use AltContext\Sovereign\Repositories\IdentityMembersRepositoryInterface;
use AltContext\Sovereign\Repositories\SyncStateRepositoryInterface;

final class SyncPullJobFactory {
	private ClustersRepositoryInterface $clusters_repository;
	private IdentityMembersRepositoryInterface $members_repository;
	private SyncStateRepositoryInterface $sync_state_repository;
	private SnapshotClient $snapshot_client;

	public function __construct(
		ClustersRepositoryInterface $clusters_repository,
		IdentityMembersRepositoryInterface $members_repository,
		SyncStateRepositoryInterface $sync_state_repository,
		?SnapshotClient $snapshot_client = null
	) {
		$this->clusters_repository = $clusters_repository;
		$this->members_repository = $members_repository;
		$this->sync_state_repository = $sync_state_repository;
		$this->snapshot_client = $snapshot_client ?? new SnapshotClient();
	}

	public function create(): SyncPullJobInterface {
		return new SyncPullJob(
			$this->snapshot_client,
			new SnapshotProjector(
				$this->clusters_repository,
				$this->members_repository,
				$this->sync_state_repository
			),
			$this->sync_state_repository
		);
	}
}
