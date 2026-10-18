<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Sync;

require_once __DIR__ . '/class-conflict-repository.php';
require_once __DIR__ . '/class-outbox-drain.php';
require_once __DIR__ . '/class-curation-idempotency-key.php';
require_once __DIR__ . '/interface-outbox-writer.php';
require_once __DIR__ . '/class-outbox-writer.php';
require_once __DIR__ . '/../class-projection-query-exception.php';
require_once __DIR__ . '/../repositories/class-clusters-repository.php';
require_once __DIR__ . '/../repositories/class-identity-members-repository.php';
require_once __DIR__ . '/../repositories/interface-clusters-repository.php';
require_once __DIR__ . '/../repositories/interface-identity-members-repository.php';
require_once __DIR__ . '/../../support/class-telemetry.php';
require_once __DIR__ . '/../../support/trait-detects-system-defined-labels.php';

use AltContext\Sovereign\ProjectionQueryException;
use AltContext\Sovereign\Repositories\ClustersRepository;
use AltContext\Sovereign\Repositories\ClustersRepositoryInterface;
use AltContext\Sovereign\Repositories\IdentityMembersRepository;
use AltContext\Sovereign\Repositories\IdentityMembersRepositoryInterface;
use AltContext\Support\Telemetry;
use AltContext\Support\DetectsSystemDefinedLabels;

use function function_exists;
use function get_current_user_id;
use function in_array;
use function is_array;
use function is_string;
use function max;
use function sprintf;
use function trim;

final class ConflictResolutionService {
	use DetectsSystemDefinedLabels;

	public const OUTBOX_OPERATION_CLUSTER_LABEL_UPDATED = 'cluster_label_updated';
	public const OUTBOX_OPERATION_IDENTITY_REASSIGNED   = 'identity_reassigned';

	public const ACCEPT_MACHINE_OUTBOX_OPERATIONS = array(
		self::OUTBOX_OPERATION_CLUSTER_LABEL_UPDATED,
		'cluster_dismissed',
		'cluster_undismissed',
		self::OUTBOX_OPERATION_IDENTITY_REASSIGNED,
		'cluster_person_bound',
		'cluster_person_unbound',
	);

	public const ACCEPT_MACHINE_COMPOUND_OUTBOX_OPERATIONS = array(
		'revert_merge_cluster',
		'assign_outlier_to_cluster',
		'cluster_created_for_identity',
	);

	private ConflictRepository $conflict_repository;
	private OutboxDrain $outbox_drain;
	private ClustersRepositoryInterface $clusters_repository;
	private IdentityMembersRepositoryInterface $members_repository;
	private OutboxWriterInterface $outbox_writer;

	public function __construct(
		?ConflictRepository $conflict_repository = null,
		?OutboxDrain $outbox_drain = null,
		?ClustersRepositoryInterface $clusters_repository = null,
		?IdentityMembersRepositoryInterface $members_repository = null,
		?OutboxWriterInterface $outbox_writer = null
	) {
		$this->conflict_repository = $conflict_repository ?? new ConflictRepository();
		$this->outbox_drain = $outbox_drain ?? new OutboxDrain();
		$this->clusters_repository = $clusters_repository ?? new ClustersRepository();
		$this->members_repository = $members_repository ?? new IdentityMembersRepository();
		$this->outbox_writer = $outbox_writer ?? new OutboxWriter();
	}

	/**
	 * @return array{ok:bool, reason:'success'|'not_found'|'already_resolved'|'resolution_not_allowed'|'reserved_label'|'entity_mutation_failed'|'conflict_update_failed', metrics_refreshed:bool, restore_report?:array{enqueued:int, skipped:int, skipped_keys:string[]}}
	 *         restore_report is present only for successful restore_local resolutions: entities whose
	 *         local curated state no longer exists are skipped and counted, not fatal.
	 */
	public function resolve( int $conflict_id, string $resolution, string $tenant_id, ?string $merged_value = null ): array {
		global $wpdb;

		$conflict = $this->conflict_repository->find_conflict_by_id( $conflict_id, $tenant_id );
		if ( ! is_array( $conflict ) ) {
			return array(
				'ok' => false,
				'reason' => 'not_found',
				'metrics_refreshed' => false,
			);
		}

		if ( ! in_array( $resolution, array( 'accepted', 'dismissed', 'accept_backend', 'merge', 'restore_local' ), true ) ) {
			return array(
				'ok' => false,
				'reason' => 'resolution_not_allowed',
				'metrics_refreshed' => false,
			);
		}

		// restore_local is code-guarded (PR3-03): only a non-truncated
		// backend_roster_regressed aggregate qualifies, so whitelisting the string
		// cannot turn restore_local into a silent no-op resolve of ordinary conflicts.
		// A truncated aggregate fails closed — the operator uses accept_backend or
		// bulk dead-letter recovery instead of silently restoring a subset.
		if ( 'restore_local' === $resolution && ! $this->is_restorable_roster_regression( $conflict ) ) {
			return array(
				'ok' => false,
				'reason' => 'resolution_not_allowed',
				'metrics_refreshed' => false,
			);
		}

		if ( 'open' !== (string) ( $conflict['resolution_status'] ?? 'open' ) ) {
			return array(
				'ok' => false,
				'reason' => 'already_resolved',
				'metrics_refreshed' => false,
			);
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'query' ) ) {
			return array(
				'ok' => false,
				'reason' => 'entity_mutation_failed',
				'metrics_refreshed' => false,
			);
		}

		if ( false === $wpdb->query( 'START TRANSACTION' ) ) {
			return array(
				'ok' => false,
				'reason' => 'entity_mutation_failed',
				'metrics_refreshed' => false,
			);
		}

		$has_outbox_conflict = ! empty( $conflict['outbox_id'] );
		$mutation_ok = true;
		$metrics_refreshed = false;
		$restore_report = null;

		try {
			if ( 'accepted' === $resolution || 'accept_backend' === $resolution ) {
				if ( $has_outbox_conflict ) {
					$operation = $this->outbox_drain->find_operation_by_id( (int) $conflict['outbox_id'], $tenant_id );
					$operation_type = is_array( $operation ) ? (string) ( $operation['operation_type'] ?? '' ) : '';
					if (
						! in_array( $operation_type, self::ACCEPT_MACHINE_OUTBOX_OPERATIONS, true )
						&& ! in_array( $operation_type, self::ACCEPT_MACHINE_COMPOUND_OUTBOX_OPERATIONS, true )
					) {
						$wpdb->query( 'ROLLBACK' );
						return array(
							'ok' => false,
							'reason' => 'resolution_not_allowed',
							'metrics_refreshed' => false,
						);
					}

					if ( in_array( $operation_type, self::ACCEPT_MACHINE_COMPOUND_OUTBOX_OPERATIONS, true ) ) {
						$mutation_ok = $this->resolve_compound_outbox_acceptance( $operation_type, $operation, $conflict, $tenant_id );
					} else {
						$mutation_ok = $this->clear_curation_for_entity(
							(string) ( $conflict['entity_type'] ?? '' ),
							(string) ( $conflict['entity_key'] ?? '' ),
							$tenant_id
						) > 0;
					}
					if ( $mutation_ok ) {
						$mutation_ok = $this->outbox_drain->discard_operation( (int) $conflict['outbox_id'], $tenant_id );
						$metrics_refreshed = $mutation_ok;
					}
				} else {
					$mutation_ok = $this->resolve_projection_acceptance( $conflict, $tenant_id );
				}
			} elseif ( 'merge' === $resolution ) {
				$normalized_merged_value = is_string( $merged_value ) ? trim( $merged_value ) : '';
				if ( '' === $normalized_merged_value ) {
					$wpdb->query( 'ROLLBACK' );
					return array(
						'ok' => false,
						'reason' => 'resolution_not_allowed',
						'metrics_refreshed' => false,
					);
				}

				if (
					'person_name_conflict' === (string) ( $conflict['conflict_code'] ?? '' )
					&& $this->is_reserved_label_shape( $normalized_merged_value )
				) {
					$wpdb->query( 'ROLLBACK' );
					return array(
						'ok' => false,
						'reason' => 'reserved_label',
						'metrics_refreshed' => false,
					);
				}

				$mutation_ok = $this->resolve_merge_acceptance( $conflict, $tenant_id, $normalized_merged_value );
				$metrics_refreshed = $mutation_ok;
				if ( $mutation_ok && $has_outbox_conflict ) {
					$mutation_ok = $this->outbox_drain->re_enqueue_with_current_base(
						(int) $conflict['outbox_id'],
						(int) ( $conflict['backend_version'] ?? 0 ),
						$tenant_id,
						$normalized_merged_value
					);
					$metrics_refreshed = $mutation_ok;
				}
			} elseif ( 'restore_local' === $resolution ) {
				// Top-level branch by construction (PR2-01): resolve_projection_acceptance()
				// only runs under accepted|accept_backend, so restore_local dispatches here,
				// beside merge/accept_backend. Local curation is the good copy — synthesize
				// re-push outbox ops instead of mutating local state.
				$restore_report = $this->restore_local_roster_curation( $conflict, $tenant_id );
				$mutation_ok = null !== $restore_report;
				$metrics_refreshed = $mutation_ok && $restore_report['enqueued'] > 0;
			} elseif ( $has_outbox_conflict ) {
				$mutation_ok = $this->outbox_drain->re_enqueue_with_current_base(
					(int) $conflict['outbox_id'],
					(int) ( $conflict['backend_version'] ?? 0 ),
					$tenant_id
				);
				$metrics_refreshed = $mutation_ok;
			}

			if ( ! $mutation_ok ) {
				$wpdb->query( 'ROLLBACK' );
				return array(
					'ok' => false,
					'reason' => 'entity_mutation_failed',
					'metrics_refreshed' => false,
				);
			}

			if ( ! $this->conflict_repository->mark_resolved( $conflict_id, $resolution, $tenant_id ) ) {
				$wpdb->query( 'ROLLBACK' );
				return array(
					'ok' => false,
					'reason' => 'conflict_update_failed',
					'metrics_refreshed' => false,
				);
			}

			if ( false === $wpdb->query( 'COMMIT' ) ) {
				$wpdb->query( 'ROLLBACK' );
				return array(
					'ok' => false,
					'reason' => 'conflict_update_failed',
					'metrics_refreshed' => false,
				);
			}
		} catch ( ProjectionQueryException $exception ) {
			// E21-14-BR-11: projection read failure mid-resolve must not fatal the request.
			$wpdb->query( 'ROLLBACK' );
			Telemetry::log_line(
				sprintf(
					'[acx] ConflictResolutionService projection failure on conflict %d: %s',
					$conflict_id,
					$exception->getMessage()
				)
			);
			return array(
				'ok' => false,
				'reason' => 'entity_mutation_failed',
				'metrics_refreshed' => false,
			);
		}

		$result = array(
			'ok' => true,
			'reason' => 'success',
			'metrics_refreshed' => $metrics_refreshed,
		);
		if ( null !== $restore_report ) {
			$result['restore_report'] = $restore_report;
		}

		return $result;
	}

	/**
	 * restore_local eligibility guard: only a backend_roster_regressed aggregate
	 * whose persisted entity set was NOT truncated may be restored.
	 *
	 * @param array<string,mixed> $conflict
	 */
	private function is_restorable_roster_regression( array $conflict ): bool {
		if ( ConflictRepository::CONFLICT_CODE_BACKEND_ROSTER_REGRESSED !== (string) ( $conflict['conflict_code'] ?? '' ) ) {
			return false;
		}

		$machine_payload = $conflict['machine_payload'] ?? array();
		return ! ( is_array( $machine_payload ) && ! empty( $machine_payload['entity_set_truncated'] ) );
	}

	/**
	 * Synthesize re-push outbox ops for every entity in the aggregate's persisted,
	 * code-partitioned entity map, from bulk local curated reads (two queries, not
	 * 2N lookups). Entities whose local curated state no longer exists are skipped
	 * and reported — a partially-restorable set must not fail the resolution.
	 * Idempotency keys come from the shared derivation so a replayed resolution
	 * cannot double-apply.
	 *
	 * @param array<string,mixed> $conflict
	 * @return array{enqueued:int, skipped:int, skipped_keys:string[]}|null Null when an enqueue write fails.
	 */
	private function restore_local_roster_curation( array $conflict, string $tenant_id ): ?array {
		$machine_payload = is_array( $conflict['machine_payload'] ?? null ) ? $conflict['machine_payload'] : array();
		$entities = is_array( $machine_payload['entities'] ?? null ) ? $machine_payload['entities'] : array();
		$backend_version = max( 0, (int) ( $conflict['backend_version'] ?? 0 ) );

		$curated_clusters = $this->clusters_repository->get_curated_clusters_for_tenant( $tenant_id );
		$curated_members  = $this->members_repository->get_curated_members_for_tenant( $tenant_id );

		$enqueued = 0;
		$skipped = 0;
		$skipped_keys = array();

		$deleted_cluster_keys = is_array( $entities['curated_cluster_deleted'] ?? null ) ? $entities['curated_cluster_deleted'] : array();
		foreach ( $deleted_cluster_keys as $cluster_uuid ) {
			$cluster_uuid = trim( (string) $cluster_uuid );
			$cluster = $curated_clusters[ $cluster_uuid ] ?? null;
			$label = is_array( $cluster ) ? trim( (string) ( $cluster['label'] ?? '' ) ) : '';
			if ( '' === $cluster_uuid || ! is_array( $cluster ) || '' === $label ) {
				++$skipped;
				if ( '' !== $cluster_uuid ) {
					$skipped_keys[] = $cluster_uuid;
				}
				continue;
			}

			$payload = array(
				'cluster_uuid' => $cluster_uuid,
				'label' => $label,
			);
			$target_revision = max( 1, (int) ( $cluster['local_revision'] ?? 0 ) + 1 );
			if ( ! $this->enqueue_restore_operation( $tenant_id, self::OUTBOX_OPERATION_CLUSTER_LABEL_UPDATED, 'cluster', $cluster_uuid, $backend_version, $target_revision, $payload ) ) {
				return null;
			}
			++$enqueued;
		}

		$member_keys = array();
		foreach ( array( 'curated_member_deleted', 'member_cluster_reassignment' ) as $member_code ) {
			$partition = is_array( $entities[ $member_code ] ?? null ) ? $entities[ $member_code ] : array();
			foreach ( $partition as $identity_uuid ) {
				$member_keys[] = trim( (string) $identity_uuid );
			}
		}

		foreach ( $member_keys as $identity_uuid ) {
			$member = $curated_members[ $identity_uuid ] ?? null;
			$local_cluster_uuid = is_array( $member ) ? trim( (string) ( $member['cluster_uuid'] ?? '' ) ) : '';
			if ( '' === $identity_uuid || ! is_array( $member ) || '' === $local_cluster_uuid ) {
				++$skipped;
				if ( '' !== $identity_uuid ) {
					$skipped_keys[] = $identity_uuid;
				}
				continue;
			}

			// Same payload shape ClusterMutationsController enqueues for a member
			// reassignment; the target is the LOCAL curated cluster (the good copy).
			$payload = array(
				'tenant_id' => $tenant_id,
				'identity_id' => $identity_uuid,
				'target_cluster_id' => $local_cluster_uuid,
				'user_id' => function_exists( 'get_current_user_id' ) ? (int) get_current_user_id() : 0,
			);
			if ( ! $this->enqueue_restore_operation( $tenant_id, self::OUTBOX_OPERATION_IDENTITY_REASSIGNED, 'member', $identity_uuid, $backend_version, 1, $payload ) ) {
				return null;
			}
			++$enqueued;
		}

		return array(
			'enqueued' => $enqueued,
			'skipped' => $skipped,
			'skipped_keys' => $skipped_keys,
		);
	}

	/**
	 * @param array<string,mixed> $payload
	 */
	private function enqueue_restore_operation( string $tenant_id, string $operation_type, string $entity_type, string $entity_key, int $expected_base_version, int $target_revision, array $payload ): bool {
		$result = $this->outbox_writer->enqueue(
			$tenant_id,
			$operation_type,
			$entity_type,
			$entity_key,
			$expected_base_version,
			$target_revision,
			$payload,
			CurationIdempotencyKey::derive( $tenant_id, $operation_type, $entity_type, $entity_key, $target_revision, $payload )
		);

		return false !== $result;
	}

	private function clear_curation_for_entity( string $entity_type, string $entity_key, string $tenant_id ): int {
		if ( 'cluster' === $entity_type ) {
			return $this->clusters_repository->reset_curation( $entity_key, $tenant_id );
		}

		if ( 'member' === $entity_type ) {
			return $this->members_repository->reset_curation( $entity_key, $tenant_id );
		}

		return 0;
	}

	/**
	 * @param array<string,mixed>|null $operation
	 * @param array<string,mixed> $conflict
	 */
	private function resolve_compound_outbox_acceptance( string $operation_type, ?array $operation, array $conflict, string $tenant_id ): bool {
		if ( 'revert_merge_cluster' !== $operation_type || ! is_array( $operation ) ) {
			return $this->resolve_identity_reassignment_compound_acceptance( $operation_type, $operation, $conflict, $tenant_id );
		}

		$payload = $operation['payload'] ?? array();
		if ( ! is_array( $payload ) ) {
			return false;
		}

		$target_cluster_id = (string) ( $payload['target_cluster_id'] ?? '' );
		$source_cluster_id = (string) ( $payload['desired_source_cluster_id'] ?? '' );
		$moved_identity_ids = is_array( $payload['moved_identity_ids'] ?? null ) ? $payload['moved_identity_ids'] : array();

		if ( '' === $target_cluster_id || '' === $source_cluster_id || array() === $moved_identity_ids ) {
			return false;
		}

		$moved_rows = 0;
		foreach ( $moved_identity_ids as $identity_id ) {
			$normalized_identity_id = is_string( $identity_id ) ? $identity_id : '';
			if ( '' === $normalized_identity_id ) {
				return false;
			}

			$result = $this->members_repository->accept_machine_cluster_assignment( $normalized_identity_id, $target_cluster_id, $tenant_id );
			if ( $result <= 0 ) {
				return false;
			}
			++$moved_rows;
		}

		if ( $this->members_repository->count_for_cluster( $source_cluster_id ) > 0 ) {
			return false;
		}

		$target_member_count = $this->members_repository->count_for_cluster( $target_cluster_id );
		if ( $this->clusters_repository->update_identity_count( $target_cluster_id, $target_member_count ) <= 0 ) {
			return false;
		}

		if ( $this->clusters_repository->delete_cluster_with_members( $source_cluster_id, $tenant_id ) <= 0 ) {
			return false;
		}

		return true;
	}

	/**
	 * @param array<string,mixed>|null $operation
	 * @param array<string,mixed> $conflict
	 */
	private function resolve_identity_reassignment_compound_acceptance( string $operation_type, ?array $operation, array $conflict, string $tenant_id ): bool {
		if (
			! in_array( $operation_type, array( 'assign_outlier_to_cluster', 'cluster_created_for_identity' ), true )
			|| ! is_array( $operation )
		) {
			return false;
		}

		$payload = $operation['payload'] ?? array();
		if ( ! is_array( $payload ) ) {
			return false;
		}

		$identity_id = (string) ( $payload['identity_id'] ?? '' );
		$machine_payload = $conflict['machine_payload'] ?? array();
		$machine_cluster_id = is_array( $machine_payload ) ? (string) ( $machine_payload['cluster_uuid'] ?? '' ) : '';
		if ( '' === $identity_id || '' === $machine_cluster_id ) {
			return false;
		}

		$current_member = $this->members_repository->find_by_identity_uuid( $identity_id );
		if ( ! is_array( $current_member ) ) {
			return false;
		}

		$current_cluster_id = (string) ( $current_member['cluster_uuid'] ?? '' );
		if ( '' === $current_cluster_id ) {
			return false;
		}

		if ( $this->members_repository->accept_machine_cluster_assignment( $identity_id, $machine_cluster_id, $tenant_id ) <= 0 ) {
			return false;
		}

		$machine_cluster_count = $this->members_repository->count_for_cluster( $machine_cluster_id );
		if ( $this->clusters_repository->update_identity_count( $machine_cluster_id, $machine_cluster_count ) <= 0 ) {
			return false;
		}

		if ( 'cluster_created_for_identity' === $operation_type ) {
			if ( $this->members_repository->count_for_cluster( $current_cluster_id ) > 0 ) {
				return false;
			}

			return $this->clusters_repository->delete_cluster_with_members( $current_cluster_id, $tenant_id ) > 0;
		}

		$current_cluster_count = $this->members_repository->count_for_cluster( $current_cluster_id );
		return $this->clusters_repository->update_identity_count( $current_cluster_id, $current_cluster_count ) > 0;
	}

	/**
	 * @param array<string,mixed> $conflict
	 */
	private function resolve_projection_acceptance( array $conflict, string $tenant_id ): bool {
		$entity_key = (string) ( $conflict['entity_key'] ?? '' );
		$conflict_code = (string) ( $conflict['conflict_code'] ?? '' );

		if ( 'curated_cluster_deleted' === $conflict_code ) {
			return $this->clusters_repository->delete_cluster_with_members( $entity_key, $tenant_id ) > 0;
		}

		if ( 'curated_member_deleted' === $conflict_code ) {
			return $this->members_repository->delete_member( $entity_key, $tenant_id ) > 0;
		}

		if ( 'member_cluster_reassignment' === $conflict_code ) {
			$machine_payload = $conflict['machine_payload'] ?? array();
			$cluster_uuid = is_array( $machine_payload ) ? (string) ( $machine_payload['cluster_uuid'] ?? '' ) : '';
			if ( '' === $cluster_uuid ) {
				return false;
			}

			return $this->members_repository->accept_machine_cluster_assignment( $entity_key, $cluster_uuid, $tenant_id ) > 0;
		}

		if ( 'drift_conflict' === $conflict_code ) {
			return $this->clear_curation_for_entity(
				(string) ( $conflict['entity_type'] ?? '' ),
				$entity_key,
				$tenant_id
			) > 0;
		}

		if ( 'person_name_conflict' === $conflict_code ) {
			return $this->accept_backend_person_name_conflict( $conflict, $tenant_id );
		}

		// E15-35 Slice 3: without this branch an aggregate falls through to the
		// `return false` below → entity_mutation_failed, so it could never clear.
		if ( ConflictRepository::CONFLICT_CODE_BACKEND_ROSTER_REGRESSED === $conflict_code ) {
			return $this->accept_backend_roster_regression( $conflict, $tenant_id );
		}

		return false;
	}

	/**
	 * accept_backend for the aggregate: apply the per-entity deletes/reassignments
	 * across the persisted, code-partitioned entity set — the same mutations the
	 * per-code branches use. Entities already gone locally are idempotently skipped
	 * (0 affected rows is not a failure for an accepted deletion).
	 *
	 * Truncation is intentionally multi-cycle here. When the divergence exceeded the
	 * storm entity cap (DEFAULT_STORM_ENTITY_CAP = 2000), the aggregate persisted only
	 * the first <=2000 keys and flagged entity_set_truncated. Unlike restore_local
	 * (which fails closed on a truncated aggregate), accept_backend reconciles exactly
	 * that persisted <=2000-key subset and returns true — it does NOT attempt the
	 * unpersisted remainder, which was never recorded on this row. The remainder is
	 * expected to converge on the next projection cycle: the still-diverging entities
	 * raise a fresh backend_roster_regressed aggregate (a new backend_version) that the
	 * operator accepts in turn, so a very large regression drains over successive
	 * cycles rather than in a single accept.
	 *
	 * @param array<string,mixed> $conflict
	 */
	private function accept_backend_roster_regression( array $conflict, string $tenant_id ): bool {
		$machine_payload = is_array( $conflict['machine_payload'] ?? null ) ? $conflict['machine_payload'] : array();
		$entities = is_array( $machine_payload['entities'] ?? null ) ? $machine_payload['entities'] : array();
		if ( array() === $entities ) {
			return false;
		}

		$deleted_cluster_keys = is_array( $entities['curated_cluster_deleted'] ?? null ) ? $entities['curated_cluster_deleted'] : array();
		foreach ( $deleted_cluster_keys as $cluster_uuid ) {
			$cluster_uuid = trim( (string) $cluster_uuid );
			if ( '' !== $cluster_uuid ) {
				$this->clusters_repository->delete_cluster_with_members( $cluster_uuid, $tenant_id );
			}
		}

		$deleted_member_keys = is_array( $entities['curated_member_deleted'] ?? null ) ? $entities['curated_member_deleted'] : array();
		foreach ( $deleted_member_keys as $identity_uuid ) {
			$identity_uuid = trim( (string) $identity_uuid );
			if ( '' !== $identity_uuid ) {
				$this->members_repository->delete_member( $identity_uuid, $tenant_id );
			}
		}

		$reassigned_member_keys = is_array( $entities['member_cluster_reassignment'] ?? null ) ? $entities['member_cluster_reassignment'] : array();
		$reassignment_targets = is_array( $machine_payload['reassignment_targets'] ?? null ) ? $machine_payload['reassignment_targets'] : array();
		foreach ( $reassigned_member_keys as $identity_uuid ) {
			$identity_uuid = trim( (string) $identity_uuid );
			if ( '' === $identity_uuid ) {
				continue;
			}

			$target_cluster_uuid = trim( (string) ( $reassignment_targets[ $identity_uuid ] ?? '' ) );
			if ( '' !== $target_cluster_uuid ) {
				$this->members_repository->accept_machine_cluster_assignment( $identity_uuid, $target_cluster_uuid, $tenant_id );
			} else {
				// No recorded target: clear the curation guard so the next
				// projection cycle applies the backend assignment.
				$this->members_repository->reset_curation( $identity_uuid, $tenant_id );
			}
		}

		return true;
	}

	/**
	 * @param array<string,mixed> $conflict
	 */
	private function resolve_merge_acceptance( array $conflict, string $tenant_id, string $merged_value ): bool {
		$conflict_code = (string) ( $conflict['conflict_code'] ?? '' );
		if ( 'person_name_conflict' === $conflict_code ) {
			if ( $this->is_reserved_label_shape( $merged_value ) ) {
				return false;
			}

			return $this->clusters_repository->update_label( (string) ( $conflict['entity_key'] ?? '' ), $merged_value, true ) > 0;
		}

		if ( 'drift_conflict' === $conflict_code ) {
			return $this->clear_curation_for_entity(
				(string) ( $conflict['entity_type'] ?? '' ),
				(string) ( $conflict['entity_key'] ?? '' ),
				$tenant_id
			) > 0;
		}

		return false;
	}

	/**
	 * @param array<string,mixed> $conflict
	 */
	private function accept_backend_person_name_conflict( array $conflict, string $tenant_id ): bool {
		$entity_key = (string) ( $conflict['entity_key'] ?? '' );
		$backend_value = $this->resolve_backend_value( $conflict );
		if ( '' === $entity_key || '' === $backend_value ) {
			return false;
		}

		if ( 'cluster' !== (string) ( $conflict['entity_type'] ?? '' ) ) {
			return false;
		}

		if ( $this->is_reserved_label_shape( $backend_value ) ) {
			$this->log_reserved_label_write_skipped( $conflict, 'backend' );
			return true;
		}

		return $this->clusters_repository->update_label( $entity_key, $backend_value, false ) > 0;
	}

	/**
	 * @param array<string,mixed> $conflict
	 */
	private function log_reserved_label_write_skipped( array $conflict, string $source ): void {
		Telemetry::log_line(
			sprintf(
				'acx conflict resolution skipped reserved label write: conflict_id=%d entity_key=%s source=%s',
				(int) ( $conflict['id'] ?? 0 ),
				(string) ( $conflict['entity_key'] ?? '' ),
				$source
			)
		);
	}

	/**
	 * @param array<string,mixed> $conflict
	 */
	private function resolve_backend_value( array $conflict ): string {
		$backend_value = trim( (string) ( $conflict['backend_proposed_value'] ?? '' ) );
		if ( '' !== $backend_value ) {
			return $backend_value;
		}

		$machine_payload = $conflict['machine_payload'] ?? array();
		if ( is_array( $machine_payload ) ) {
			foreach ( array( 'merged_value', 'label', 'name', 'proposed_value' ) as $key ) {
				$value = trim( (string) ( $machine_payload[ $key ] ?? '' ) );
				if ( '' !== $value ) {
					return $value;
				}
			}
		}

		return '';
	}
}
