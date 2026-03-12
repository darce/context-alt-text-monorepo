<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Sync;

require_once __DIR__ . '/class-conflict-repository.php';
require_once __DIR__ . '/class-outbox-drain.php';
require_once __DIR__ . '/../repositories/class-clusters-repository.php';
require_once __DIR__ . '/../repositories/class-identity-members-repository.php';
require_once __DIR__ . '/../repositories/interface-clusters-repository.php';
require_once __DIR__ . '/../repositories/interface-identity-members-repository.php';

use AltContext\Sovereign\Repositories\ClustersRepository;
use AltContext\Sovereign\Repositories\ClustersRepositoryInterface;
use AltContext\Sovereign\Repositories\IdentityMembersRepository;
use AltContext\Sovereign\Repositories\IdentityMembersRepositoryInterface;

use function in_array;
use function is_array;

final class ConflictResolutionService {
	public const ACCEPT_MACHINE_OUTBOX_OPERATIONS = array(
		'cluster_label_updated',
		'cluster_dismissed',
		'cluster_undismissed',
		'identity_reassigned',
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

	public function __construct(
		?ConflictRepository $conflict_repository = null,
		?OutboxDrain $outbox_drain = null,
		?ClustersRepositoryInterface $clusters_repository = null,
		?IdentityMembersRepositoryInterface $members_repository = null
	) {
		$this->conflict_repository = $conflict_repository ?? new ConflictRepository();
		$this->outbox_drain = $outbox_drain ?? new OutboxDrain();
		$this->clusters_repository = $clusters_repository ?? new ClustersRepository();
		$this->members_repository = $members_repository ?? new IdentityMembersRepository();
	}

	/**
	 * @return array{ok:bool, reason:'success'|'not_found'|'already_resolved'|'resolution_not_allowed'|'entity_mutation_failed'|'conflict_update_failed', metrics_refreshed:bool}
	 */
	public function resolve( int $conflict_id, string $resolution, string $tenant_id ): array {
		global $wpdb;

		$conflict = $this->conflict_repository->find_conflict_by_id( $conflict_id, $tenant_id );
		if ( ! is_array( $conflict ) ) {
			return array(
				'ok' => false,
				'reason' => 'not_found',
				'metrics_refreshed' => false,
			);
		}

		if ( ! in_array( $resolution, array( 'accepted', 'dismissed' ), true ) ) {
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

		if ( 'accepted' === $resolution ) {
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

		return array(
			'ok' => true,
			'reason' => 'success',
			'metrics_refreshed' => $metrics_refreshed,
		);
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

		return $moved_rows > 0;
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

		return false;
	}
}
