<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Sync;

require_once __DIR__ . '/interface-snapshot-projector.php';
require_once __DIR__ . '/../repositories/class-member-conflict-recorder.php';

use AltContext\Sovereign\Repositories\ClustersRepositoryInterface;
use AltContext\Sovereign\Repositories\IdentityMembersRepositoryInterface;
use AltContext\Sovereign\Repositories\MemberConflictRecorder;
use AltContext\Sovereign\Repositories\SyncStateRepositoryInterface;
use RuntimeException;
use Throwable;

use function apply_filters;
use function do_action;
use function function_exists;
use function is_finite;
use function is_float;
use function is_int;
use function is_numeric;
use function is_string;
use function is_array;
use function is_object;
use function method_exists;
use function json_decode;
use function trim;
use function array_keys;
use function array_slice;
use function array_values;
use function array_fill_keys;
use function array_key_exists;
use function count;
use function max;

class SnapshotProjector implements SnapshotProjectorInterface {
	private const MAX_SNAPSHOT_BATCH_SIZE = 100;

	// E15-35 Slice 3 conflict-storm tunables. Divergence at or above the absolute
	// threshold — or above the given percentage of the tenant's curated clusters —
	// collapses the per-entity curated_* storm into one aggregate
	// backend_roster_regressed conflict. Each value is apply_filters-overridable and
	// fail-safe validated at read time (rg-008): an invalid filter value falls back
	// to the default so a bad filter can never disable the storm cap.
	private const DEFAULT_STORM_ABSOLUTE_THRESHOLD = 20;
	private const DEFAULT_STORM_RATIO_PERCENT      = 50;
	private const DEFAULT_STORM_ENTITY_CAP         = 2000;

	private ClustersRepositoryInterface $clusters_repository;
	private IdentityMembersRepositoryInterface $members_repository;
	private SyncStateRepositoryInterface $sync_state_repository;
	private ConflictRepository $conflict_repository;
	private MemberConflictRecorder $member_conflict_recorder;

	public function __construct(
		ClustersRepositoryInterface $clusters_repository,
		IdentityMembersRepositoryInterface $members_repository,
		SyncStateRepositoryInterface $sync_state_repository,
		?ConflictRepository $conflict_repository = null,
		?MemberConflictRecorder $member_conflict_recorder = null
	) {
		$this->clusters_repository   = $clusters_repository;
		$this->members_repository    = $members_repository;
		$this->sync_state_repository = $sync_state_repository;
		$this->conflict_repository   = $conflict_repository ?? new ConflictRepository();
		$this->member_conflict_recorder = $member_conflict_recorder ?? new MemberConflictRecorder( $this->conflict_repository );
	}

	/**
	 * @param array<string,mixed> $snapshot
	 * @throws RuntimeException When transaction support is unavailable.
	 */
	public function project( string $tenant_id, array $snapshot ): void {
		global $wpdb;

		$normalized_tenant_id = trim( $tenant_id );
		if ( '' === $normalized_tenant_id ) {
			$this->log_empty_tenant_id_guard();
			return;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'query' ) ) {
			throw new RuntimeException( 'Snapshot projection requires $wpdb query support.' );
		}

		$snapshot_version = (int) ( $snapshot['snapshot_version'] ?? 0 );
		$clusters         = is_array( $snapshot['clusters'] ?? null ) ? $snapshot['clusters'] : array();
		$members          = is_array( $snapshot['members'] ?? null ) ? $snapshot['members'] : array();
		$is_empty_snapshot = ( true === ( $snapshot['empty'] ?? false ) )
			|| ( empty( $clusters ) && 0 === $snapshot_version );

		if ( $is_empty_snapshot ) {
			$this->run_projection_transaction(
				function () use ( $normalized_tenant_id ): void {
					$this->sync_state_repository->upsert_snapshot_version( $normalized_tenant_id, 0 );
					$this->sync_state_repository->refresh_curation_metrics( $normalized_tenant_id );
				}
			);
			return;
		}

		// COR-1: an out-of-order full snapshot whose version is not newer than
		// what is already projected would regress curated/projection data.
		// Skip it entirely — this also avoids running the stale-row delete.
		$stored_version = $this->sync_state_repository->get_snapshot_version( $normalized_tenant_id );
		if ( $stored_version > 0 && $snapshot_version <= $stored_version ) {
			return;
		}

		$pre_projection_conflict_count = $this->sync_state_repository->get_conflict_count( $normalized_tenant_id );

		if ( $this->should_batch_cluster_only_snapshot( $clusters, $members ) ) {
			$conflicts_generated = $this->project_cluster_only_snapshot_in_batches( $normalized_tenant_id, $clusters, $snapshot_version, $pre_projection_conflict_count );
		} else {
			$conflicts_generated = $this->project_snapshot_in_single_transaction( $normalized_tenant_id, $clusters, $members, $snapshot_version, $pre_projection_conflict_count );
		}

		if ( function_exists( 'do_action' ) ) {
			$non_singleton_count = count(
				array_filter(
					$clusters,
					static function ( $cluster ): bool {
						return is_array( $cluster ) && (int) ( $cluster['identity_count'] ?? 0 ) > 1;
					}
				)
			);
			do_action( 'acx_snapshot_projected', $normalized_tenant_id, count( $clusters ), $non_singleton_count, $snapshot_version );
		}

		if ( $conflicts_generated > 0 && function_exists( 'do_action' ) ) {
			do_action( 'acx_projection_conflicts_detected', $conflicts_generated, $normalized_tenant_id );
		}
	}

	/**
	 * @param array<int,array<string,mixed>> $clusters
	 * @param array<int,array<string,mixed>> $members
	 */
	private function should_batch_cluster_only_snapshot( array $clusters, array $members ): bool {
		return empty( $members ) && count( $clusters ) > self::MAX_SNAPSHOT_BATCH_SIZE;
	}

	/**
	 * @param array<int,array<string,mixed>> $clusters
	 * @param array<int,array<string,mixed>> $members
	 */
	private function project_snapshot_in_single_transaction( string $tenant_id, array $clusters, array $members, int $snapshot_version, int $pre_projection_conflict_count ): int {
		$this->run_projection_transaction(
			function () use ( $tenant_id, $clusters, $members, $snapshot_version ): void {
				// E15-35 Slice 3: pre-count curated cluster AND member divergence
				// before any per-entity recording or merge so a mass-divergence
				// snapshot collapses into one aggregate conflict.
				$curated_clusters     = $this->clusters_repository->get_curated_clusters_for_tenant( $tenant_id );
				$curated_members      = $this->members_repository->get_curated_members_for_tenant( $tenant_id );
				$deleted_cluster_keys = $this->collect_deleted_curated_cluster_keys( $curated_clusters, $clusters );
				$member_divergence    = $this->member_conflict_recorder->collect_member_divergence( $curated_members, $members );
				$divergence_total     = count( $deleted_cluster_keys )
					+ count( $member_divergence['curated_member_deleted'] )
					+ count( $member_divergence['member_cluster_reassignment'] );
				$suppress_conflict_storm = $this->is_conflict_storm( $divergence_total, count( $curated_clusters ) );

				$this->record_person_name_conflicts( $tenant_id, $curated_clusters, $clusters, $snapshot_version );
				if ( $suppress_conflict_storm ) {
					$this->record_backend_roster_regression_aggregate(
						$tenant_id,
						$snapshot_version,
						$deleted_cluster_keys,
						$member_divergence,
						count( $curated_clusters ),
						count( $curated_members )
					);
				} else {
					$this->record_curated_cluster_deletion_conflicts( $tenant_id, $curated_clusters, $deleted_cluster_keys, $snapshot_version );
				}

				$this->clusters_repository->merge_snapshot_for_tenant( $tenant_id, $clusters, $snapshot_version );
				$this->members_repository->merge_snapshot_for_tenant( $tenant_id, $members, $snapshot_version, $suppress_conflict_storm );
				$this->sync_state_repository->upsert_snapshot_version( $tenant_id, $snapshot_version );
				$this->sync_state_repository->refresh_curation_metrics( $tenant_id );
			}
		);

		$post_projection_conflict_count = $this->sync_state_repository->get_conflict_count( $tenant_id );
		return max( 0, $post_projection_conflict_count - $pre_projection_conflict_count );
	}

	/**
	 * @param array<int,array<string,mixed>> $clusters
	 */
	private function project_cluster_only_snapshot_in_batches( string $tenant_id, array $clusters, int $snapshot_version, int $pre_projection_conflict_count ): int {
		$cluster_batches      = array_chunk( $clusters, self::MAX_SNAPSHOT_BATCH_SIZE );
		$total_batches        = count( $cluster_batches );
		$incoming_cluster_ids = array_values(
			array_filter(
				array_map(
					static function ( array $cluster ): string {
						return trim( (string) ( $cluster['cluster_uuid'] ?? '' ) );
					},
					$clusters
				)
			)
		);

		// E15-35 Slice 3: the batched path never runs the member merge, so only
		// curated-cluster divergence feeds the storm decision here.
		$curated_clusters     = $this->clusters_repository->get_curated_clusters_for_tenant( $tenant_id );
		$deleted_cluster_keys = $this->collect_deleted_curated_cluster_keys( $curated_clusters, $clusters );
		$suppress_conflict_storm = $this->is_conflict_storm( count( $deleted_cluster_keys ), count( $curated_clusters ) );

		foreach ( $cluster_batches as $index => $cluster_batch ) {
			$is_first_batch = 0 === $index;
			$is_last_batch  = ( $total_batches - 1 ) === $index;

			$this->run_projection_transaction(
				function () use ( $tenant_id, $incoming_cluster_ids, $cluster_batch, $clusters, $snapshot_version, $is_first_batch, $is_last_batch, $curated_clusters, $deleted_cluster_keys, $suppress_conflict_storm ): void {
					if ( $is_first_batch ) {
						$this->clusters_repository->prepare_snapshot_merge_for_tenant( $tenant_id, $incoming_cluster_ids );
						$this->record_person_name_conflicts( $tenant_id, $curated_clusters, $clusters, $snapshot_version );
						if ( $suppress_conflict_storm ) {
							$this->record_backend_roster_regression_aggregate(
								$tenant_id,
								$snapshot_version,
								$deleted_cluster_keys,
								array(
									'curated_member_deleted' => array(),
									'member_cluster_reassignment' => array(),
								),
								count( $curated_clusters ),
								0
							);
						} else {
							$this->record_curated_cluster_deletion_conflicts( $tenant_id, $curated_clusters, $deleted_cluster_keys, $snapshot_version );
						}
					}

					$this->clusters_repository->merge_snapshot_batch_for_tenant( $tenant_id, $cluster_batch, $snapshot_version );

					if ( $is_last_batch ) {
						$this->sync_state_repository->upsert_snapshot_version( $tenant_id, $snapshot_version );
						$this->sync_state_repository->refresh_curation_metrics( $tenant_id );
					}
				}
			);
		}

		$post_projection_conflict_count = $this->sync_state_repository->get_conflict_count( $tenant_id );
		return max( 0, $post_projection_conflict_count - $pre_projection_conflict_count );
	}

	/**
	 * @throws RuntimeException When transaction support is unavailable or commit fails.
	 * @throws Throwable Re-throws projection errors after rollback.
	 */
	private function run_projection_transaction( callable $callback ): void {
		global $wpdb;

		$started = false !== $wpdb->query( 'START TRANSACTION' );
		if ( ! $started ) {
			throw new RuntimeException( 'Snapshot projection requires transaction support.' );
		}

		try {
			$callback();
			$committed = false !== $wpdb->query( 'COMMIT' );
			if ( ! $committed ) {
				throw new RuntimeException( 'Snapshot projection failed to commit transaction.' );
			}
		} catch ( Throwable $throwable ) {
			$wpdb->query( 'ROLLBACK' );
			throw $throwable;
		}
	}

	/**
	 * @param array<string,mixed> $delta
	 * @throws RuntimeException When transaction support is unavailable or commit fails.
	 * @throws Throwable When downstream projection or repository writes fail after the transaction starts.
	 */
	public function project_delta( string $tenant_id, array $delta ): void {
		global $wpdb;

		$normalized_tenant_id = trim( $tenant_id );
		if ( '' === $normalized_tenant_id ) {
			$this->log_empty_tenant_id_guard();
			return;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'query' ) ) {
			throw new RuntimeException( 'Snapshot projection requires $wpdb query support.' );
		}

		$snapshot_version = (int) ( $delta['snapshot_version'] ?? 0 );

		// COR-1: a stale delta (version not newer than what is already projected)
		// would regress data and the stored version. Skip it before opening a
		// transaction.
		$stored_version = $this->sync_state_repository->get_snapshot_version( $normalized_tenant_id );
		if ( $stored_version > 0 && $snapshot_version <= $stored_version ) {
			return;
		}

		$started = false !== $wpdb->query( 'START TRANSACTION' );
		if ( ! $started ) {
			throw new RuntimeException( 'Snapshot projection requires transaction support.' );
		}

		try {
			$clusters         = is_array( $delta['clusters'] ?? null ) ? $delta['clusters'] : array();
			$members          = is_array( $delta['members'] ?? null ) ? $delta['members'] : array();

			if ( ! empty( $clusters ) || ! empty( $members ) ) {
				$snapshot_clusters = $this->build_delta_cluster_snapshot_payload( $normalized_tenant_id, $clusters );
				$snapshot_members  = $this->build_delta_member_snapshot_payload( $normalized_tenant_id, $snapshot_clusters, $clusters, $members );
				$pre_projection_conflict_count = $this->sync_state_repository->get_conflict_count( $normalized_tenant_id );

				$this->clusters_repository->merge_snapshot_for_tenant( $normalized_tenant_id, $snapshot_clusters, $snapshot_version );
				$this->members_repository->merge_snapshot_for_tenant( $normalized_tenant_id, $snapshot_members, $snapshot_version );
				$this->sync_state_repository->upsert_snapshot_version( $normalized_tenant_id, $snapshot_version );
				$this->sync_state_repository->refresh_curation_metrics( $normalized_tenant_id );
				$post_projection_conflict_count = $this->sync_state_repository->get_conflict_count( $normalized_tenant_id );
				$conflicts_generated            = max( 0, $post_projection_conflict_count - $pre_projection_conflict_count );

				if ( $conflicts_generated > 0 && function_exists( 'do_action' ) ) {
					do_action( 'acx_projection_conflicts_detected', $conflicts_generated, $normalized_tenant_id );
				}
			} else {
				$this->sync_state_repository->upsert_snapshot_version( $normalized_tenant_id, $snapshot_version );
				$this->sync_state_repository->refresh_curation_metrics( $normalized_tenant_id );
			}

			$committed = false !== $wpdb->query( 'COMMIT' );
			if ( ! $committed ) {
				throw new RuntimeException( 'Snapshot projection failed to commit transaction.' );
			}
		} catch ( Throwable $throwable ) {
			$wpdb->query( 'ROLLBACK' );
			throw $throwable;
		}
	}

	/**
	 * @param array<int,array<string,mixed>> $changed_clusters
	 * @return array<int,array<string,mixed>>
	 */
	private function build_delta_cluster_snapshot_payload( string $tenant_id, array $changed_clusters ): array {
		$existing_clusters = $this->list_all_clusters_for_tenant( $tenant_id );
		$changed_by_id     = array();

		foreach ( $changed_clusters as $cluster ) {
			if ( ! is_array( $cluster ) ) {
				continue;
			}

			$cluster_uuid = trim( (string) ( $cluster['cluster_uuid'] ?? '' ) );
			if ( '' === $cluster_uuid ) {
				continue;
			}

			$changed_by_id[ $cluster_uuid ] = $cluster;
		}

		$payload = array();
		foreach ( $existing_clusters as $cluster ) {
			if ( ! is_array( $cluster ) ) {
				continue;
			}

			$cluster_uuid = trim( (string) ( $cluster['cluster_uuid'] ?? '' ) );
			if ( '' === $cluster_uuid ) {
				continue;
			}

			if ( isset( $changed_by_id[ $cluster_uuid ] ) ) {
				$payload[] = $changed_by_id[ $cluster_uuid ];
				unset( $changed_by_id[ $cluster_uuid ] );
				continue;
			}

			$payload[] = $cluster;
		}

		foreach ( $changed_by_id as $cluster ) {
			$payload[] = $cluster;
		}

		return $payload;
	}

	/**
	 * @param array<int,array<string,mixed>> $snapshot_clusters
	 * @param array<int,array<string,mixed>> $changed_clusters
	 * @param array<int,array<string,mixed>> $changed_members
	 * @return array<int,array<string,mixed>>
	 */
	private function build_delta_member_snapshot_payload( string $tenant_id, array $snapshot_clusters, array $changed_clusters, array $changed_members ): array {
		$cluster_ids = array();
		foreach ( $snapshot_clusters as $cluster ) {
			if ( ! is_array( $cluster ) ) {
				continue;
			}

			$cluster_uuid = trim( (string) ( $cluster['cluster_uuid'] ?? '' ) );
			if ( '' !== $cluster_uuid ) {
				$cluster_ids[] = $cluster_uuid;
			}
		}

		$existing_members_by_cluster = $this->list_all_members_by_cluster( $tenant_id, $cluster_ids );
		$changed_cluster_ids         = array_fill_keys( $this->extract_cluster_ids( $changed_clusters ), true );
		$changed_members_by_cluster  = array();

		foreach ( $changed_members as $member ) {
			if ( ! is_array( $member ) ) {
				continue;
			}

			$cluster_uuid = trim( (string) ( $member['cluster_uuid'] ?? '' ) );
			if ( '' === $cluster_uuid ) {
				continue;
			}

			if ( ! isset( $changed_members_by_cluster[ $cluster_uuid ] ) ) {
				$changed_members_by_cluster[ $cluster_uuid ] = array();
			}

			$changed_members_by_cluster[ $cluster_uuid ][] = $member;
		}

		$payload = array();
		foreach ( $cluster_ids as $cluster_uuid ) {
			if ( isset( $changed_cluster_ids[ $cluster_uuid ] ) && isset( $changed_members_by_cluster[ $cluster_uuid ] ) ) {
				foreach ( $changed_members_by_cluster[ $cluster_uuid ] as $member ) {
					$payload[] = $member;
				}
				continue;
			}

			foreach ( $existing_members_by_cluster[ $cluster_uuid ] as $member ) {
				if ( is_array( $member ) ) {
					$payload[] = $this->hydrate_existing_member_snapshot_row( $member );
				}
			}
		}

		return $payload;
	}

	/**
	 * @return array<int,array<string,mixed>>
	 */
	private function list_all_clusters_for_tenant( string $tenant_id ): array {
		$offset   = 0;
		$page_size = 5000;
		$clusters = array();

		do {
			$page = $this->clusters_repository->list_for_tenant( $tenant_id, $page_size, $offset );
			foreach ( $page as $cluster ) {
				if ( is_array( $cluster ) ) {
					$clusters[] = $cluster;
				}
			}

			$page_count = count( $page );
			$offset    += $page_count;
		} while ( $page_count === $page_size );

		return $clusters;
	}

	/**
	 * @param string[] $cluster_ids
	 * @return array<string,array<int,array<string,mixed>>>
	 */
	private function list_all_members_by_cluster( string $tenant_id, array $cluster_ids ): array {
		$members_by_cluster = array();

		foreach ( $cluster_ids as $cluster_id ) {
			$offset    = 0;
			$page_size = 500;
			$members   = array();

			do {
				$page = $this->members_repository->list_for_cluster( $cluster_id, $page_size, $offset, $tenant_id );
				foreach ( $page as $member ) {
					if ( is_array( $member ) ) {
						$members[] = $member;
					}
				}

				$page_count = count( $page );
				$offset    += $page_count;
			} while ( $page_count === $page_size );

			$members_by_cluster[ $cluster_id ] = $members;
		}

		return $members_by_cluster;
	}

	/**
	 * @param array<int,array<string,mixed>> $clusters
	 * @return string[]
	 */
	private function extract_cluster_ids( array $clusters ): array {
		$cluster_ids = array();
		foreach ( $clusters as $cluster ) {
			if ( ! is_array( $cluster ) ) {
				continue;
			}

			$cluster_uuid = trim( (string) ( $cluster['cluster_uuid'] ?? '' ) );
			if ( '' !== $cluster_uuid ) {
				$cluster_ids[] = $cluster_uuid;
			}
		}

		return array_values( array_unique( $cluster_ids ) );
	}

	/**
	 * @param array<string,mixed> $member
	 * @return array<string,mixed>
	 */
	private function hydrate_existing_member_snapshot_row( array $member ): array {
		// rg-005 / DATA-15: pass assigned_at through delta re-merge so ORDER BY parity
		// with recognition (assigned_at ASC) is not lost when re-hydrating existing rows.
		$assigned_at = trim( (string) ( $member['assigned_at'] ?? '' ) );
		if ( '' === $assigned_at ) {
			$assigned_at = trim( (string) ( $member['created_at'] ?? '' ) );
		}

		$row = array(
			'identity_uuid' => trim( (string) ( $member['identity_uuid'] ?? '' ) ),
			'cluster_uuid'  => trim( (string) ( $member['cluster_uuid'] ?? '' ) ),
			'attachment_id' => (int) ( $member['attachment_id'] ?? 0 ),
			'thumb_path'    => trim( (string) ( $member['thumb_path'] ?? '' ) ),
			'similarity'    => $member['similarity'] ?? null,
			'assigned_at'   => $assigned_at,
		);

		$bbox_json = $member['bbox_json'] ?? null;
		if ( is_string( $bbox_json ) && '' !== trim( $bbox_json ) ) {
			$decoded_bbox = json_decode( $bbox_json, true );
			if ( is_array( $decoded_bbox ) ) {
				$row['bbox'] = $decoded_bbox;
			}
		}

		if ( array_key_exists( 'image_width', $member ) && is_int( $member['image_width'] ) ) {
			$row['image_width'] = $member['image_width'];
		}
		if ( array_key_exists( 'image_height', $member ) && is_int( $member['image_height'] ) ) {
			$row['image_height'] = $member['image_height'];
		}

		return $row;
	}

	/**
	 * Collect curated cluster UUIDs missing from the incoming snapshot without
	 * writing anything (E15-35 Slice 3 pre-count).
	 *
	 * @param array<string,array<string,mixed>> $curated_clusters Keyed by cluster_uuid.
	 * @param array<int,array<string,mixed>> $incoming_clusters
	 * @return string[]
	 */
	private function collect_deleted_curated_cluster_keys( array $curated_clusters, array $incoming_clusters ): array {
		if ( empty( $curated_clusters ) ) {
			return array();
		}

		$incoming_cluster_ids = array();
		foreach ( $incoming_clusters as $cluster ) {
			if ( ! is_array( $cluster ) ) {
				continue;
			}

			$cluster_uuid = trim( (string) ( $cluster['cluster_uuid'] ?? '' ) );
			if ( '' !== $cluster_uuid ) {
				$incoming_cluster_ids[ $cluster_uuid ] = true;
			}
		}

		$deleted_keys = array();
		foreach ( $curated_clusters as $cluster_uuid => $cluster ) {
			if ( isset( $incoming_cluster_ids[ $cluster_uuid ] ) || ! is_array( $cluster ) ) {
				continue;
			}

			$deleted_keys[] = (string) $cluster_uuid;
		}

		return $deleted_keys;
	}

	/**
	 * Divergence is a storm when it reaches the absolute entity threshold or exceeds
	 * the configured percentage of the tenant's curated clusters.
	 */
	private function is_conflict_storm( int $divergence_total, int $curated_cluster_count ): bool {
		if ( $divergence_total <= 0 ) {
			return false;
		}

		$absolute_threshold = $this->resolve_positive_int_tunable( 'acx_projection_conflict_storm_absolute_threshold', self::DEFAULT_STORM_ABSOLUTE_THRESHOLD );
		if ( $divergence_total >= $absolute_threshold ) {
			return true;
		}

		$ratio_percent = $this->resolve_positive_int_tunable( 'acx_projection_conflict_storm_ratio_percent', self::DEFAULT_STORM_RATIO_PERCENT );
		return $curated_cluster_count > 0 && ( $divergence_total * 100 ) > ( $ratio_percent * $curated_cluster_count );
	}

	/**
	 * Record ONE aggregate backend_roster_regressed conflict carrying per-code counts
	 * and the code-partitioned entity map, capped at a filterable max. Above the cap
	 * the persisted set is truncated and flagged (entity_set_truncated), which fails
	 * restore_local closed downstream. Cross-cycle dedup lives in the repository.
	 *
	 * @param string[] $deleted_cluster_keys
	 * @param array{curated_member_deleted:string[], member_cluster_reassignment:array<string,string>} $member_divergence
	 */
	private function record_backend_roster_regression_aggregate(
		string $tenant_id,
		int $snapshot_version,
		array $deleted_cluster_keys,
		array $member_divergence,
		int $curated_cluster_count,
		int $curated_member_count
	): void {
		$deleted_member_keys  = array_values( $member_divergence['curated_member_deleted'] );
		$reassignment_targets = $member_divergence['member_cluster_reassignment'];

		$counts = array(
			'curated_cluster_deleted' => count( $deleted_cluster_keys ),
			'curated_member_deleted' => count( $deleted_member_keys ),
			'member_cluster_reassignment' => count( $reassignment_targets ),
		);

		$entity_cap           = $this->resolve_positive_int_tunable( 'acx_projection_conflict_storm_entity_cap', self::DEFAULT_STORM_ENTITY_CAP );
		$entity_set_truncated = false;
		$entities             = array();
		$remaining            = $entity_cap;
		$partitions           = array(
			'curated_cluster_deleted' => array_values( $deleted_cluster_keys ),
			'curated_member_deleted' => $deleted_member_keys,
			'member_cluster_reassignment' => array_keys( $reassignment_targets ),
		);
		foreach ( $partitions as $conflict_code => $entity_keys ) {
			$kept                       = array_slice( $entity_keys, 0, max( 0, $remaining ) );
			$entities[ $conflict_code ] = $kept;
			$remaining                 -= count( $kept );
			if ( count( $kept ) < count( $entity_keys ) ) {
				$entity_set_truncated = true;
			}
		}

		$persisted_targets = array();
		foreach ( $entities['member_cluster_reassignment'] as $identity_uuid ) {
			if ( isset( $reassignment_targets[ $identity_uuid ] ) ) {
				$persisted_targets[ $identity_uuid ] = $reassignment_targets[ $identity_uuid ];
			}
		}

		$this->conflict_repository->record_backend_roster_regression(
			$tenant_id,
			max( 0, $snapshot_version ),
			array(
				'backend_version' => max( 0, $snapshot_version ),
				'counts' => $counts,
				'entities' => $entities,
				'entity_set_truncated' => $entity_set_truncated,
				'reassignment_targets' => $persisted_targets,
			),
			array(
				'curated_clusters' => $curated_cluster_count,
				'curated_members' => $curated_member_count,
			)
		);
	}

	/**
	 * Fail-safe tunable read (rg-008): a filter returning a non-finite, non-numeric,
	 * or non-positive value falls back to the default — a bad filter can never
	 * disable the storm threshold or the persisted-entity cap.
	 */
	private function resolve_positive_int_tunable( string $filter_name, int $default ): int {
		$value = apply_filters( $filter_name, $default );

		if ( is_int( $value ) ) {
			return $value > 0 ? $value : $default;
		}

		if ( is_float( $value ) ) {
			return is_finite( $value ) && $value > 0.0 ? max( 1, (int) $value ) : $default;
		}

		if ( is_string( $value ) && is_numeric( $value ) ) {
			$numeric = (float) $value;
			return is_finite( $numeric ) && $numeric > 0.0 ? max( 1, (int) $numeric ) : $default;
		}

		return $default;
	}

	/**
	 * @param array<string,array<string,mixed>> $curated_clusters Keyed by cluster_uuid.
	 * @param string[] $deleted_cluster_keys
	 */
	private function record_curated_cluster_deletion_conflicts( string $tenant_id, array $curated_clusters, array $deleted_cluster_keys, int $snapshot_version ): void {
		foreach ( $deleted_cluster_keys as $cluster_uuid ) {
			$cluster = $curated_clusters[ $cluster_uuid ] ?? null;
			if ( ! is_array( $cluster ) ) {
				continue;
			}

			$this->conflict_repository->record_projection_conflict(
				$tenant_id,
				'cluster',
				(string) $cluster_uuid,
				'curated_cluster_deleted',
				$snapshot_version,
				max( 0, (int) ( $cluster['snapshot_version'] ?? 0 ) ),
				max( 0, (int) ( $cluster['local_revision'] ?? 0 ) ),
				array(
					'cluster_uuid' => (string) $cluster_uuid,
					'status' => 'missing_from_snapshot',
				),
				array(
					'cluster_uuid' => (string) $cluster_uuid,
					'label' => $cluster['label'] ?? null,
					'person_id' => $cluster['person_id'] ?? null,
					'curation_state' => $cluster['curation_state'] ?? null,
				)
			);
		}
	}

	/**
	 * @param array<string,array<string,mixed>> $curated_clusters Keyed by cluster_uuid.
	 * @param array<int,array<string,mixed>> $incoming_clusters
	 */
	private function record_person_name_conflicts( string $tenant_id, array $curated_clusters, array $incoming_clusters, int $snapshot_version ): void {
		if ( empty( $curated_clusters ) ) {
			return;
		}

		$incoming_clusters_by_id = array();
		foreach ( $incoming_clusters as $cluster ) {
			if ( ! is_array( $cluster ) ) {
				continue;
			}

			$cluster_uuid = trim( (string) ( $cluster['cluster_uuid'] ?? '' ) );
			if ( '' === $cluster_uuid ) {
				continue;
			}

			$incoming_clusters_by_id[ $cluster_uuid ] = $cluster;
		}

		foreach ( $curated_clusters as $cluster_uuid => $cluster ) {
			if ( ! is_array( $cluster ) ) {
				continue;
			}

			$incoming_cluster = $incoming_clusters_by_id[ $cluster_uuid ] ?? null;
			if ( ! is_array( $incoming_cluster ) ) {
				continue;
			}

			$incoming_label = trim( (string) ( $incoming_cluster['label'] ?? $incoming_cluster['cluster_label'] ?? '' ) );
			$current_label = trim( (string) ( $cluster['label'] ?? $cluster['cluster_label'] ?? '' ) );
			$person_id = trim( (string) ( $cluster['person_id'] ?? '' ) );

			if ( '' === $person_id || '' === $incoming_label || '' === $current_label || $incoming_label === $current_label ) {
				continue;
			}

			$this->conflict_repository->record_projection_conflict(
				$tenant_id,
				'cluster',
				(string) $cluster_uuid,
				'person_name_conflict',
				$snapshot_version,
				max( 0, (int) ( $cluster['snapshot_version'] ?? 0 ) ),
				max( 0, (int) ( $cluster['local_revision'] ?? 0 ) ),
				array(
					'cluster_uuid' => (string) $cluster_uuid,
					'proposed_value' => $incoming_label,
					'status' => 'name_changed_from_snapshot',
				),
				array(
					'cluster_uuid' => (string) $cluster_uuid,
					'label' => $current_label,
					'person_id' => $cluster['person_id'] ?? null,
					'curation_state' => $cluster['curation_state'] ?? null,
				)
			);
		}
	}

	private function log_empty_tenant_id_guard(): void {
		if ( function_exists( 'do_action' ) ) {
			do_action(
				'acx_sovereign_warning',
				'empty_tenant_id',
				array(
					'method' => __METHOD__,
				)
			);
		}

		if ( function_exists( '_doing_it_wrong' ) ) {
			_doing_it_wrong( __METHOD__, 'Tenant ID must be non-empty for snapshot projection.', '4.13.1' );
		}
	}
}
