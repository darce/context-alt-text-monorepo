<?php

declare(strict_types=1);

namespace AltContext\Api\Services;

use AltContext\Api\AnalysisJobsHostInterface;
use AltContext\Sovereign\Repositories\ClustersRepository;
use AltContext\Sovereign\Repositories\IdentityMembersRepository;
use AltContext\Sovereign\Repositories\SyncStateRepository;
use AltContext\Sovereign\Repositories\SyncStateRepositoryInterface;
use AltContext\Sovereign\Sync\SnapshotClient;
use AltContext\Sovereign\Sync\SyncPullJobFactory;
use AltContext\Sovereign\Sync\SyncPullJobInterface;
use Throwable;

use function absint;
use function get_transient;
use function is_array;
use function md5;
use function sanitize_text_field;
use function set_transient;
use function trim;

class ProjectionSyncService {
	private const PROJECTION_SYNC_TRANSIENT_PREFIX = 'acx_projection_sync_';
	private const PROJECTION_SYNC_SUCCESS_TTL_SECONDS = 300;
	private const PROJECTION_SYNC_RETRY_TTL_SECONDS = 5;

	private AnalysisJobsHostInterface $host;
	private SyncStateRepositoryInterface $sync_state_repository;
	private ?SyncPullJobInterface $sync_pull_job;
	private ?SyncPullJobFactory $sync_pull_job_factory;

	public function __construct(
		AnalysisJobsHostInterface $host,
		?SyncStateRepositoryInterface $sync_state_repository = null,
		?SyncPullJobInterface $sync_pull_job = null,
		?SyncPullJobFactory $sync_pull_job_factory = null
	) {
		$this->host = $host;
		$this->sync_state_repository = $sync_state_repository ?? new SyncStateRepository();
		$this->sync_pull_job = $sync_pull_job;
		$this->sync_pull_job_factory = $sync_pull_job_factory;
	}

	/**
	 * @param array<string,mixed> $job_payload
	 */
	public function maybe_trigger_projection_sync( array $job_payload ): void {
		$status           = sanitize_text_field( (string) ( $job_payload['status'] ?? '' ) );
		$snapshot_version = absint( $job_payload['snapshot_version'] ?? 0 );
		$acknowledged_at  = trim( (string) ( $job_payload['projection_acknowledged_at'] ?? '' ) );
		$job_id           = $this->projection_sync_job_id( $job_payload );

		if ( 'completed' !== $status || $snapshot_version <= 0 || '' !== $acknowledged_at || '' === $job_id ) {
			return;
		}

		$transient_key = $this->projection_sync_transient_key( $job_id, $snapshot_version );
		if ( false !== get_transient( $transient_key ) ) {
			return;
		}

		$sync_pull_job = $this->resolve_sync_pull_job();
		if ( null === $sync_pull_job ) {
			return;
		}

		$projection_payload = $this->build_inline_projection_payload( $job_payload, $job_id, $snapshot_version );

		try {
			$result = is_array( $projection_payload )
				? $sync_pull_job->perform_projection_payload( $this->host->get_tenant_id(), $projection_payload )
				: $sync_pull_job->perform_bypass_cooldown( $this->host->get_tenant_id() );
			$ttl    = $result->is_success()
				? self::PROJECTION_SYNC_SUCCESS_TTL_SECONDS
				: self::PROJECTION_SYNC_RETRY_TTL_SECONDS;
			set_transient( $transient_key, 1, $ttl );
		} catch ( Throwable $throwable ) {
			set_transient( $transient_key, 1, self::PROJECTION_SYNC_RETRY_TTL_SECONDS );
		}
	}

	private function projection_sync_job_id( array $job_payload ): string {
		$job_id = trim( (string) ( $job_payload['source_job_id'] ?? $job_payload['id'] ?? '' ) );
		return sanitize_text_field( $job_id );
	}

	/**
	 * @param array<string,mixed> $job_payload
	 * @return array<string,mixed>|null
	 */
	private function build_inline_projection_payload( array $job_payload, string $job_id, int $snapshot_version ): ?array {
		$projection_payload = $job_payload['projection_payload'] ?? null;
		if ( ! is_array( $projection_payload ) ) {
			return null;
		}

		$payload_snapshot_version = absint( $projection_payload['snapshot_version'] ?? 0 );
		if ( $payload_snapshot_version <= 0 || $payload_snapshot_version !== $snapshot_version ) {
			return null;
		}

		$projection_payload['source_job_id'] = $job_id;
		return $projection_payload;
	}

	private function projection_sync_transient_key( string $job_id, int $snapshot_version ): string {
		return self::PROJECTION_SYNC_TRANSIENT_PREFIX . md5( $job_id . ':' . (string) $snapshot_version );
	}

	private function resolve_sync_pull_job(): ?SyncPullJobInterface {
		if ( null !== $this->sync_pull_job ) {
			return $this->sync_pull_job;
		}

		try {
			$factory = $this->sync_pull_job_factory ?? new SyncPullJobFactory(
				new ClustersRepository(),
				new IdentityMembersRepository(),
				$this->sync_state_repository,
				new SnapshotClient()
			);
			$this->sync_pull_job = $factory->create();
		} catch ( Throwable $throwable ) {
			return null;
		}

		return $this->sync_pull_job;
	}
}
