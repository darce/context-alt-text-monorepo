<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Sync;

require_once __DIR__ . '/../repositories/interface-clusters-repository.php';
require_once __DIR__ . '/../repositories/interface-identity-members-repository.php';
require_once __DIR__ . '/../repositories/interface-sync-state-repository.php';
require_once __DIR__ . '/../repositories/class-clusters-repository.php';
require_once __DIR__ . '/../repositories/class-identity-members-repository.php';
require_once __DIR__ . '/../repositories/class-sync-state-repository.php';
require_once __DIR__ . '/../class-projection-query-exception.php';
require_once __DIR__ . '/../../support/class-telemetry.php';
require_once __DIR__ . '/class-snapshot-client.php';
require_once __DIR__ . '/class-snapshot-projector.php';
require_once __DIR__ . '/class-snapshot-client-transport.php';
require_once __DIR__ . '/class-cross-plane-sequencer.php';
require_once __DIR__ . '/interface-topology-command-repository.php';
require_once __DIR__ . '/class-topology-command-repository.php';

use AltContext\Sovereign\ProjectionQueryException;
use AltContext\Sovereign\Repositories\ClustersRepository;
use AltContext\Sovereign\Repositories\ClustersRepositoryInterface;
use AltContext\Sovereign\Repositories\IdentityMembersRepository;
use AltContext\Sovereign\Repositories\IdentityMembersRepositoryInterface;
use AltContext\Sovereign\Repositories\SyncStateRepository;
use AltContext\Sovereign\Repositories\SyncStateRepositoryInterface;
use AltContext\Support\Telemetry;
use Throwable;
use WP_Error;

use function add_action;
use function apply_filters;
use function array_keys;
use function array_map;
use function array_merge;
use function array_unique;
use function count;
use function do_action;
use function function_exists;
use function in_array;
use function is_array;
use function is_string;
use function is_wp_error;
use function max;
use function sprintf;
use function time;
use function trim;
use function wp_clear_scheduled_hook;
use function wp_next_scheduled;
use function wp_schedule_single_event;

class SplitTopologyCommandDrain {
	private const DRAIN_HOOK = 'acx_sync_drain_split_topology_commands';
	private const ACTION_SCHEDULER_GROUP = 'acx-sync';
	private const DEFAULT_BATCH_SIZE = 10;
	private const MAX_MEMBER_LOAD_PAGES = 20;
	private const DEFAULT_MAX_ATTEMPTS = 5;

	private TopologyCommandRepositoryInterface $repository;
	private SnapshotClientTransport $transport;
	private SnapshotClient $snapshot_client;
	private SnapshotProjectorInterface $snapshot_projector;
	private ClustersRepositoryInterface $clusters_repository;
	private IdentityMembersRepositoryInterface $members_repository;
	private SyncStateRepositoryInterface $sync_state_repository;
	private CrossPlaneSequencer $sequencer;
	private int $batch_size;

	public function __construct(
		?TopologyCommandRepositoryInterface $repository = null,
		?SnapshotClientTransport $transport = null,
		?SnapshotClient $snapshot_client = null,
		?SnapshotProjectorInterface $snapshot_projector = null,
		?ClustersRepositoryInterface $clusters_repository = null,
		?IdentityMembersRepositoryInterface $members_repository = null,
		?SyncStateRepositoryInterface $sync_state_repository = null,
		?CrossPlaneSequencer $sequencer = null
	) {
		$this->repository = $repository ?? new TopologyCommandRepository();
		$this->transport = $transport ?? new SnapshotClientTransport();
		$this->snapshot_client = $snapshot_client ?? new SnapshotClient( $this->transport );
		$this->clusters_repository = $clusters_repository ?? new ClustersRepository();
		$this->members_repository = $members_repository ?? new IdentityMembersRepository();
		$this->sync_state_repository = $sync_state_repository ?? new SyncStateRepository();
		$this->snapshot_projector = $snapshot_projector ?? new SnapshotProjector(
			$this->clusters_repository,
			$this->members_repository,
			$this->sync_state_repository
		);
		$this->sequencer = $sequencer ?? new CrossPlaneSequencer( $this->repository );
		$this->batch_size = max( 1, (int) apply_filters( 'acx_split_topology_drain_batch_size', self::DEFAULT_BATCH_SIZE ) );
	}

	public function register(): void {
		add_action( self::DRAIN_HOOK, array( $this, 'drain' ) );

		if ( ! empty( $this->repository->find_reconcilable( null, 1 ) ) ) {
			self::maybe_schedule_drain();
		}
	}

	public static function maybe_schedule_drain(): void {
		if ( function_exists( 'as_enqueue_async_action' ) && function_exists( 'as_next_scheduled_action' ) ) {
			$group = self::action_scheduler_group();
			$existing = as_next_scheduled_action( self::DRAIN_HOOK, array(), $group );
			if ( false !== $existing && null !== $existing ) {
				return;
			}

			try {
				$action_id = as_enqueue_async_action( self::DRAIN_HOOK, array(), $group );
				if ( (int) $action_id > 0 ) {
					return;
				}
			} catch ( Throwable $exception ) {
				do_action( 'acx_split_topology_action_scheduler_enqueue_failed', $exception );
			}
		}

		if ( false === wp_next_scheduled( self::DRAIN_HOOK, array() ) ) {
			wp_schedule_single_event( time(), self::DRAIN_HOOK, array() );
		}
	}

	public static function clear_scheduled_drain(): void {
		wp_clear_scheduled_hook( self::DRAIN_HOOK, array() );

		if ( function_exists( 'as_unschedule_all_actions' ) ) {
			as_unschedule_all_actions( self::DRAIN_HOOK, array(), self::action_scheduler_group() );
		}
	}

	public function drain(): void {
		$commands = $this->repository->find_reconcilable( null, $this->batch_size );
		if ( empty( $commands ) ) {
			return;
		}

		$processed_tenants = $this->process_command_batch( $commands );
		$this->refresh_curation_metrics_for_tenants( array_keys( $processed_tenants ) );

		if ( count( $commands ) >= $this->batch_size && ! empty( $this->repository->find_reconcilable( null, 1 ) ) ) {
			self::maybe_schedule_drain();
		}
	}

	/**
	 * @param array<int,array<string,mixed>> $commands
	 * @return array<string,true>
	 */
	private function process_command_batch( array $commands ): array {
		$processed_tenants = array();
		foreach ( $commands as $command ) {
			if ( ! is_array( $command ) ) {
				continue;
			}

			$this->process_command( $command );

			$tenant_id = trim( (string) ( $command['tenant_id'] ?? '' ) );
			if ( '' !== $tenant_id ) {
				$processed_tenants[ $tenant_id ] = true;
			}
		}

		return $processed_tenants;
	}

	/**
	 * @param array<int,string> $tenant_ids
	 */
	private function refresh_curation_metrics_for_tenants( array $tenant_ids ): void {
		foreach ( $tenant_ids as $tenant_id ) {
			$this->sync_state_repository->refresh_curation_metrics( $tenant_id );
		}
	}

	/**
	 * @param array<string,mixed> $command
	 */
	private function process_command( array $command ): void {
		$command_id = max( 0, (int) ( $command['id'] ?? 0 ) );
		if ( $command_id <= 0 ) {
			return;
		}

		$current_status = trim( (string) ( $command['status'] ?? 'pending' ) );
		if ( 'pending' === $current_status && ! $this->sequencer->is_split_command_ready( $command ) ) {
			self::maybe_schedule_drain();
			return;
		}

		// CON-4: claim the command before processing so a second concurrent drain cannot
		// re-dispatch a pending command or re-apply an applied command's member delta and
		// revert an interleaved user reassign. A lost claim means a peer drain owns it.
		if ( ! $this->repository->claim_command( $command_id, $current_status ) ) {
			return;
		}

		try {
			if ( 'applied' === $current_status ) {
				$this->process_applied_split_command( $command_id, $command );
				return;
			}

			$this->process_pending_split_command( $command_id, $command );
		} catch ( ProjectionQueryException $exception ) {
			// rg-007 / E21-14-BR-11: one unit's projection failure must not strand the claim
			// or halt the batch — mark this command failed and continue.
			Telemetry::log_line(
				sprintf(
					'[acx] SplitTopologyCommandDrain projection failure on command %d: %s',
					$command_id,
					$exception->getMessage()
				)
			);
			$this->repository->record_failure(
				$command_id,
				'failed',
				'projection_query_failed',
				$this->normalize_text( $exception->getMessage(), 'Projection query failed during topology drain.' ),
				true,
				null
			);
		}
	}

	/**
	 * @param array<string,mixed> $command
	 */
	private function process_applied_split_command( int $command_id, array $command ): void {
		$stored_result = $this->decode_result_payload( $command['result_json'] ?? null );
		if ( empty( $stored_result ) ) {
			$this->repository->record_failure(
				$command_id,
				'failed',
				'missing_result_payload',
				'Applied split topology command is missing durable result metadata.',
				false,
				'applied'
			);
			return;
		}

		if ( $this->reconcile_command( $command, $stored_result ) ) {
			$this->repository->mark_reconciled( $command_id, $stored_result, 'applied' );
			return;
		}

		$reconcile_attempts = max( 0, (int) ( $command['reconcile_attempts'] ?? 0 ) ) + 1;
		$next_status = $reconcile_attempts >= $this->resolve_max_attempts() ? 'failed' : 'applied';
		$this->repository->record_reconcile_failure(
			$command_id,
			$next_status,
			'projection_reconcile_failed',
			'Split topology command could not be reconciled locally.',
			'applied'
		);
	}

	/**
	 * @param array<string,mixed> $command
	 */
	private function process_pending_split_command( int $command_id, array $command ): void {
		$result = $this->dispatch_command( $command );
		$status = trim( (string) ( $result['status'] ?? 'failed' ) );

		if ( 'applied' === $status ) {
			// Claimed as 'pending'; record_dispatch_result is the pending->applied transition.
			if ( ! $this->repository->record_dispatch_result( $command_id, $result, 'pending' ) ) {
				return;
			}

			if ( $this->reconcile_command( $command, $result ) ) {
				$this->repository->mark_reconciled( $command_id, $result, 'applied' );
				return;
			}

			$attempts = max( 0, (int) ( $command['attempts'] ?? 0 ) ) + 1;
			$retryable = $attempts < $this->resolve_max_attempts();
			// Row is now 'applied' after record_dispatch_result; guard the reconcile-fail write on it.
			$this->repository->record_failure(
				$command_id,
				$retryable ? 'applied' : 'failed',
				'projection_reconcile_failed',
				'Split topology command could not be reconciled locally.',
				false,
				'applied'
			);
			return;
		}

		if ( 'conflict' === $status ) {
			// Claimed as 'pending'; record_dispatch_result is the pending->conflict transition.
			// If this drain outlived its lease and a peer re-claimed + advanced the row, the
			// guarded write matches 0 rows -> do not re-project a stale conflict snapshot over
			// the peer's state. Mirrors the 'applied' branch's guarded early-return.
			if ( ! $this->repository->record_dispatch_result( $command_id, $result, 'pending' ) ) {
				return;
			}

			$this->reconcile_conflict( $command, $result );
			return;
		}

		$attempts = max( 0, (int) ( $command['attempts'] ?? 0 ) ) + 1;
		$retryable = (bool) ( $result['retryable'] ?? true );
		$next_status = ( $retryable && $attempts < $this->resolve_max_attempts() ) ? 'pending' : 'failed';
		// Dispatch failed before any status flip; the row is still 'pending'.
		$this->repository->record_failure(
			$command_id,
			$next_status,
			$this->normalize_text( $result['error_code'] ?? '', 'dispatch_failed' ),
			$this->normalize_text( $result['error_message'] ?? '', 'Split topology command dispatch failed.' ),
			true,
			'pending'
		);
	}

	/**
	 * @param array<string,mixed> $command
	 * @return array<string,mixed>
	 */
	private function dispatch_command( array $command ): array {
		$command_type = trim( (string) ( $command['command_type'] ?? '' ) );
		if ( 'cluster_split' !== $command_type ) {
			return array(
				'status' => 'failed',
				'error_code' => 'unsupported_command',
				'error_message' => 'Unsupported topology command type.',
				'retryable' => false,
			);
		}

		$body = $this->build_split_dispatch_request_body( $command );
		$response = $this->transport->request( 'POST', '/recognition/topology-commands/split', $body, array() );

		return $this->normalize_split_transport_response( $response );
	}

	/**
	 * @param array<string,mixed> $command
	 * @return array<string,mixed>
	 */
	private function build_split_dispatch_request_body( array $command ): array {
		$payload = $command['payload_json'] ?? array();
		if ( is_string( $payload ) ) {
			$decoded = json_decode( $payload, true );
			$payload = is_array( $decoded ) ? $decoded : array();
		}
		if ( ! is_array( $payload ) ) {
			$payload = array();
		}

		return array_merge(
			$payload,
			array(
				'tenant_id' => trim( (string) ( $command['tenant_id'] ?? '' ) ),
				'cluster_id' => trim( (string) ( $command['entity_key'] ?? '' ) ),
				'expected_base_version' => max( 0, (int) ( $command['expected_base_version'] ?? 0 ) ),
				'idempotency_key' => trim( (string) ( $command['idempotency_key'] ?? '' ) ),
			)
		);
	}

	/**
	 * @param \WP_REST_Response|\WP_Error $response
	 * @return array<string,mixed>
	 */
	private function normalize_split_transport_response( $response ): array {
		if ( is_wp_error( $response ) ) {
			return array(
				'status' => 'failed',
				'error_code' => $this->normalize_text( $response->get_error_code(), 'transport_error' ),
				'error_message' => $this->normalize_text( $response->get_error_message(), 'Remote split transport failed.' ),
				'retryable' => true,
			);
		}

		if ( ! $response instanceof \WP_REST_Response ) {
			return array(
				'status' => 'failed',
				'error_code' => 'unexpected_response',
				'error_message' => 'Remote split transport returned an unexpected response type.',
				'retryable' => true,
			);
		}

		$status_code = $response->get_status();
		$data = $response->get_data();
		$data = is_array( $data ) ? $data : array();

		if ( $status_code >= 200 && $status_code < 300 ) {
			$data['status'] = $this->normalize_text( $data['status'] ?? '', 'applied' );
			return $data;
		}

		if ( 409 === $status_code ) {
			return array(
				'status' => 'conflict',
				'conflict_code' => $this->normalize_text( $data['conflict_code'] ?? '', 'cluster_version_conflict' ),
				'backend_version' => max( 0, (int) ( $data['backend_version'] ?? 0 ) ),
				'error_message' => $this->normalize_text( $data['message'] ?? '', 'Remote split conflict.' ),
				'machine_payload' => is_array( $data['machine_payload'] ?? null ) ? $data['machine_payload'] : array(),
			);
		}

		return array(
			'status' => 'failed',
			'error_code' => $this->normalize_text( $data['error_code'] ?? '', 'remote_error' ),
			'error_message' => $this->normalize_text( $data['message'] ?? '', 'Remote split command failed.' ),
			'retryable' => $status_code >= 500 || 408 === $status_code || 429 === $status_code,
		);
	}

	/**
	 * @param array<string,mixed> $command
	 * @param array<string,mixed> $result
	 */
	private function reconcile_conflict( array $command, array $result ): void {
		$tenant_id = trim( (string) ( $command['tenant_id'] ?? '' ) );
		if ( '' === $tenant_id ) {
			return;
		}

		$affected_cluster_ids = $this->extract_affected_cluster_ids( $command, $result );
		$reconciled_payload   = ! empty( $affected_cluster_ids )
			? $this->fetch_targeted_snapshot_for_clusters( $tenant_id, $affected_cluster_ids )
			: null;

		if ( $this->project_split_conflict_via_targeted_snapshot( $tenant_id, $command, $result, $reconciled_payload ) ) {
			return;
		}

		$this->project_split_conflict_via_full_snapshot( $tenant_id, $command, $result, $reconciled_payload );
	}

	/**
	 * @param array<string,mixed> $command
	 * @param array<string,mixed> $result
	 * @param array<string,mixed>|WP_Error|null $reconciled_payload
	 */
	private function project_split_conflict_via_targeted_snapshot( string $tenant_id, array $command, array $result, $reconciled_payload ): bool {
		if ( ! is_array( $reconciled_payload ) || ! $this->reconcile_targeted_snapshot( $tenant_id, $command, $reconciled_payload ) ) {
			return false;
		}

		do_action( 'acx_split_topology_conflict_detected', $command, $result, $reconciled_payload );
		return true;
	}

	/**
	 * @param array<string,mixed> $command
	 * @param array<string,mixed> $result
	 * @param array<string,mixed>|WP_Error|null $reconciled_payload
	 */
	private function project_split_conflict_via_full_snapshot( string $tenant_id, array $command, array $result, $reconciled_payload ): void {
		$snapshot = $this->snapshot_client->fetch_snapshot( $tenant_id );
		if ( is_wp_error( $snapshot ) ) {
			do_action( 'acx_split_topology_conflict_detected', $command, $result, $reconciled_payload );
			return;
		}

		$this->snapshot_projector->project( $tenant_id, $snapshot );
		do_action( 'acx_split_topology_conflict_detected', $command, $result, $snapshot );
	}

	/**
	 * @param array<string,mixed> $command
	 * @param array<string,mixed> $result
	 */
	private function reconcile_command( array $command, array $result ): bool {
		$tenant_id = trim( (string) ( $command['tenant_id'] ?? '' ) );
		if ( '' === $tenant_id ) {
			return false;
		}

		if ( $this->reconcile_command_via_member_delta( $tenant_id, $result ) ) {
			return true;
		}

		if ( $this->reconcile_command_via_targeted_snapshot( $tenant_id, $command, $result ) ) {
			return true;
		}

		return $this->reconcile_command_via_full_snapshot( $tenant_id );
	}

	/**
	 * @param array<string,mixed> $result
	 */
	private function reconcile_command_via_member_delta( string $tenant_id, array $result ): bool {
		if ( ! $this->has_complete_member_delta( $tenant_id, $result ) ) {
			return false;
		}

		return $this->apply_member_delta( $tenant_id, $result );
	}

	/**
	 * @param array<string,mixed> $command
	 * @param array<string,mixed> $result
	 */
	private function reconcile_command_via_targeted_snapshot( string $tenant_id, array $command, array $result ): bool {
		$affected_cluster_ids = $this->extract_affected_cluster_ids( $command, $result );
		if ( empty( $affected_cluster_ids ) ) {
			return false;
		}

		return $this->reconcile_targeted_snapshot(
			$tenant_id,
			$command,
			$this->fetch_targeted_snapshot_for_clusters( $tenant_id, $affected_cluster_ids )
		);
	}

	private function reconcile_command_via_full_snapshot( string $tenant_id ): bool {
		$snapshot = $this->snapshot_client->fetch_snapshot( $tenant_id );
		if ( is_wp_error( $snapshot ) ) {
			return false;
		}

		$this->snapshot_projector->project( $tenant_id, $snapshot );
		return true;
	}

	/**
	 * @param array<string,mixed>|WP_Error $snapshot
	 * @param array<string,mixed> $command
	 */
	private function reconcile_targeted_snapshot( string $tenant_id, array $command, $snapshot ): bool {
		if ( is_wp_error( $snapshot ) || ! is_array( $snapshot ) ) {
			return false;
		}

		$result = $this->build_result_from_targeted_snapshot( $command, $snapshot );
		if ( ! is_array( $result ) || ! $this->has_complete_member_delta( $tenant_id, $result ) ) {
			return false;
		}

		return $this->apply_member_delta( $tenant_id, $result );
	}

	/**
	 * @param string[] $cluster_ids
	 * @return array<string,mixed>|WP_Error
	 */
	private function fetch_targeted_snapshot_for_clusters( string $tenant_id, array $cluster_ids ) {
		return $this->snapshot_client->fetch_targeted_snapshot( $tenant_id, $cluster_ids );
	}

	/**
	 * @param array<string,mixed> $command
	 * @param array<string,mixed> $snapshot
	 * @return array<string,mixed>|null
	 */
	private function build_result_from_targeted_snapshot( array $command, array $snapshot ): ?array {
		$source_cluster_id = trim( (string) ( $command['entity_key'] ?? '' ) );
		if ( '' === $source_cluster_id ) {
			return null;
		}

		$snapshot_version = max( 0, (int) ( $snapshot['snapshot_version'] ?? 0 ) );
		if ( $snapshot_version <= 0 ) {
			return null;
		}

		$member_delta = $this->collect_targeted_snapshot_member_delta( $source_cluster_id, $snapshot );
		if ( null === $member_delta ) {
			return null;
		}

		return array(
			'status' => 'applied',
			'original_cluster_id' => $source_cluster_id,
			'new_cluster_ids' => $member_delta['new_cluster_ids'],
			'member_delta' => array(
				'source_cluster_id' => $source_cluster_id,
				'remaining_identity_ids' => $member_delta['remaining_identity_ids'],
				'created_clusters' => $member_delta['created_clusters'],
			),
			'moved_counts' => $member_delta['moved_counts'],
			'affected_cluster_ids' => $this->extract_affected_cluster_ids( $command, $snapshot ),
			'result_snapshot_version' => $snapshot_version,
		);
	}

	/**
	 * @param array<string,mixed> $snapshot
	 * @return array{
	 *   remaining_identity_ids: array<int,string>,
	 *   created_clusters: array<int,array<string,mixed>>,
	 *   new_cluster_ids: array<int,string>,
	 *   moved_counts: array<int,int>
	 * }|null
	 */
	private function collect_targeted_snapshot_member_delta( string $source_cluster_id, array $snapshot ): ?array {
		$clusters = is_array( $snapshot['clusters'] ?? null ) ? $snapshot['clusters'] : array();
		$members = is_array( $snapshot['members'] ?? null ) ? $snapshot['members'] : array();
		if ( empty( $clusters ) ) {
			return null;
		}

		$remaining_identity_ids = array();
		$created_clusters = array();
		$new_cluster_ids = array();
		$moved_counts = array();

		foreach ( $clusters as $cluster ) {
			if ( ! is_array( $cluster ) ) {
				continue;
			}

			$cluster_id = trim( (string) ( $cluster['cluster_uuid'] ?? '' ) );
			if ( '' === $cluster_id ) {
				continue;
			}

			$identity_ids = array();
			foreach ( $members as $member ) {
				if ( ! is_array( $member ) ) {
					continue;
				}
				if ( $cluster_id !== trim( (string) ( $member['cluster_uuid'] ?? '' ) ) ) {
					continue;
				}

				$identity_id = trim( (string) ( $member['identity_uuid'] ?? '' ) );
				if ( '' !== $identity_id ) {
					$identity_ids[] = $identity_id;
				}
			}

			$identity_ids = $this->normalize_identity_ids( $identity_ids );
			if ( $cluster_id === $source_cluster_id ) {
				$remaining_identity_ids = $identity_ids;
				continue;
			}

			$new_cluster_ids[] = $cluster_id;
			$moved_counts[] = count( $identity_ids );
			$created_clusters[] = array(
				'cluster_id' => $cluster_id,
				'identity_ids' => $identity_ids,
			);
		}

		return array(
			'remaining_identity_ids' => $remaining_identity_ids,
			'created_clusters' => $created_clusters,
			'new_cluster_ids' => $new_cluster_ids,
			'moved_counts' => $moved_counts,
		);
	}

	/**
	 * @param array<string,mixed> $command
	 * @param array<string,mixed> $payload
	 * @return string[]
	 */
	private function extract_affected_cluster_ids( array $command, array $payload ): array {
		$affected_cluster_ids = is_array( $payload['affected_cluster_ids'] ?? null ) ? $payload['affected_cluster_ids'] : array();
		$new_cluster_ids = is_array( $payload['new_cluster_ids'] ?? null ) ? $payload['new_cluster_ids'] : array();
		$clusters = is_array( $payload['clusters'] ?? null ) ? $payload['clusters'] : array();
		foreach ( $clusters as $cluster ) {
			if ( ! is_array( $cluster ) ) {
				continue;
			}
			$affected_cluster_ids[] = $cluster['cluster_uuid'] ?? '';
		}

		return $this->normalize_identity_ids(
			array_merge(
				array(
					$command['entity_key'] ?? '',
					$payload['original_cluster_id'] ?? '',
					$payload['cluster_id'] ?? '',
				),
				$affected_cluster_ids,
				$new_cluster_ids
			)
		);
	}

	private function has_complete_member_delta( string $tenant_id, array $result ): bool {
		$member_delta = is_array( $result['member_delta'] ?? null ) ? $result['member_delta'] : array();
		$source_cluster_id = trim( (string) ( $member_delta['source_cluster_id'] ?? '' ) );
		$created_clusters = is_array( $member_delta['created_clusters'] ?? null ) ? $member_delta['created_clusters'] : array();
		$remaining_identity_ids = $this->normalize_identity_ids( $member_delta['remaining_identity_ids'] ?? array() );
		$new_cluster_ids = $this->normalize_identity_ids( $result['new_cluster_ids'] ?? array() );
		if ( '' === $source_cluster_id || count( $created_clusters ) !== count( $new_cluster_ids ) ) {
			return false;
		}

		$local_members = $this->load_all_members_for_cluster( $tenant_id, $source_cluster_id );
		if ( empty( $local_members ) ) {
			return false;
		}

		$expected_identity_ids = array();
		foreach ( $local_members as $member ) {
			if ( ! is_array( $member ) ) {
				continue;
			}

			$identity_id = trim( (string) ( $member['identity_uuid'] ?? '' ) );
			if ( '' !== $identity_id ) {
				$expected_identity_ids[] = $identity_id;
			}
		}

		$delta_identity_ids = $remaining_identity_ids;
		foreach ( $created_clusters as $created_cluster ) {
			if ( ! is_array( $created_cluster ) ) {
				return false;
			}

			$cluster_id = trim( (string) ( $created_cluster['cluster_id'] ?? '' ) );
			if ( '' === $cluster_id || ! in_array( $cluster_id, $new_cluster_ids, true ) ) {
				return false;
			}

			$delta_identity_ids = array_merge(
				$delta_identity_ids,
				$this->normalize_identity_ids( $created_cluster['identity_ids'] ?? array() )
			);
		}

		$expected_identity_ids = array_values( array_unique( $expected_identity_ids ) );
		$delta_identity_ids = array_values( array_unique( $delta_identity_ids ) );
		sort( $expected_identity_ids );
		sort( $delta_identity_ids );

		return $expected_identity_ids === $delta_identity_ids;
	}

	private function apply_member_delta( string $tenant_id, array $result ): bool {
		global $wpdb;

		$member_delta = is_array( $result['member_delta'] ?? null ) ? $result['member_delta'] : array();
		$source_cluster_id = trim( (string) ( $member_delta['source_cluster_id'] ?? '' ) );
		$snapshot_version = max( 0, (int) ( $result['result_snapshot_version'] ?? 0 ) );
		if ( '' === $source_cluster_id || $snapshot_version <= 0 ) {
			return false;
		}

		$local_members = $this->load_all_members_for_cluster( $tenant_id, $source_cluster_id );
		if ( empty( $local_members ) ) {
			return false;
		}

		$members_by_identity = array();
		foreach ( $local_members as $member ) {
			if ( ! is_array( $member ) ) {
				continue;
			}

			$identity_id = trim( (string) ( $member['identity_uuid'] ?? '' ) );
			if ( '' !== $identity_id ) {
				$members_by_identity[ $identity_id ] = $member;
			}
		}

		$remaining_identity_ids = $this->normalize_identity_ids( $member_delta['remaining_identity_ids'] ?? array() );
		$created_clusters = is_array( $member_delta['created_clusters'] ?? null ) ? $member_delta['created_clusters'] : array();
		$transaction_started = false;

		if ( isset( $wpdb ) && is_object( $wpdb ) && method_exists( $wpdb, 'query' ) ) {
			$transaction_started = false !== $wpdb->query( 'START TRANSACTION' );
		}

		if ( ! $this->apply_created_clusters( $tenant_id, $snapshot_version, $created_clusters, $members_by_identity ) ) {
			if ( $transaction_started ) {
				$wpdb->query( 'ROLLBACK' );
			}
			return false;
		}

		if ( ! $this->apply_member_rows( $source_cluster_id, $snapshot_version, $remaining_identity_ids, $members_by_identity ) ) {
			if ( $transaction_started ) {
				$wpdb->query( 'ROLLBACK' );
			}
			return false;
		}

		if ( ! $this->finalize_snapshot( $tenant_id, $source_cluster_id, $snapshot_version, $remaining_identity_ids, $members_by_identity ) ) {
			if ( $transaction_started ) {
				$wpdb->query( 'ROLLBACK' );
			}
			return false;
		}

		if ( $transaction_started && false === $wpdb->query( 'COMMIT' ) ) {
			$wpdb->query( 'ROLLBACK' );
			return false;
		}

		return true;
	}

	/**
	 * @param array<int,array<string,mixed>> $created_clusters
	 * @param array<string,array<string,mixed>> $members_by_identity
	 */
	private function apply_created_clusters(
		string $tenant_id,
		int $snapshot_version,
		array $created_clusters,
		array $members_by_identity
	): bool {
		foreach ( $created_clusters as $created_cluster ) {
			if ( ! is_array( $created_cluster ) ) {
				return false;
			}

			$cluster_id = trim( (string) ( $created_cluster['cluster_id'] ?? '' ) );
			$identity_ids = $this->normalize_identity_ids( $created_cluster['identity_ids'] ?? array() );
			if ( '' === $cluster_id || empty( $identity_ids ) ) {
				return false;
			}

			$representative_thumb_path = null;
			foreach ( $identity_ids as $identity_id ) {
				if ( ! isset( $members_by_identity[ $identity_id ] ) ) {
					return false;
				}
				if ( null === $representative_thumb_path ) {
					$candidate_thumb_path = trim( (string) ( $members_by_identity[ $identity_id ]['thumb_path'] ?? '' ) );
					if ( '' !== $candidate_thumb_path ) {
						$representative_thumb_path = $candidate_thumb_path;
					}
				}
			}

			$this->clusters_repository->upsert_projection_cluster(
				$tenant_id,
				$cluster_id,
				'',
				count( $identity_ids ),
				$snapshot_version,
				$representative_thumb_path
			);

			foreach ( $identity_ids as $identity_id ) {
				$this->members_repository->assign_to_cluster_for_projection( $identity_id, $cluster_id, $snapshot_version );
			}
		}

		return true;
	}

	/**
	 * @param array<int,string> $remaining_identity_ids
	 * @param array<string,array<string,mixed>> $members_by_identity
	 */
	private function apply_member_rows(
		string $source_cluster_id,
		int $snapshot_version,
		array $remaining_identity_ids,
		array $members_by_identity
	): bool {
		foreach ( $remaining_identity_ids as $identity_id ) {
			if ( ! isset( $members_by_identity[ $identity_id ] ) ) {
				return false;
			}

			$current_cluster_id = trim( (string) ( $members_by_identity[ $identity_id ]['cluster_uuid'] ?? '' ) );
			if ( $current_cluster_id !== $source_cluster_id ) {
				$this->members_repository->assign_to_cluster_for_projection( $identity_id, $source_cluster_id, $snapshot_version );
			}
		}

		return true;
	}

	/**
	 * @param array<int,string> $remaining_identity_ids
	 * @param array<string,array<string,mixed>> $members_by_identity
	 */
	private function finalize_snapshot(
		string $tenant_id,
		string $source_cluster_id,
		int $snapshot_version,
		array $remaining_identity_ids,
		array $members_by_identity
	): bool {
		$source_thumb_path = null;
		foreach ( $remaining_identity_ids as $identity_id ) {
			if ( ! isset( $members_by_identity[ $identity_id ] ) ) {
				return false;
			}
			if ( null === $source_thumb_path ) {
				$candidate_thumb_path = trim( (string) ( $members_by_identity[ $identity_id ]['thumb_path'] ?? '' ) );
				if ( '' !== $candidate_thumb_path ) {
					$source_thumb_path = $candidate_thumb_path;
				}
			}
		}

		$this->clusters_repository->update_projection_cluster(
			$source_cluster_id,
			count( $remaining_identity_ids ),
			$snapshot_version,
			$source_thumb_path
		);
		$this->sync_state_repository->upsert_snapshot_version( $tenant_id, $snapshot_version );

		return true;
	}

	/**
	 * @return array<int,array<string,mixed>>
	 */
	private function load_all_members_for_cluster( string $tenant_id, string $cluster_id ): array {
		$limit = IdentityMembersRepositoryInterface::DEFAULT_CLUSTER_MEMBER_LIMIT;
		$offset = 0;
		$members = array();
		$total_count = null;
		$page_count = 0;

		// Split-topology drain runs under the tenant-scoped sequencing barrier; mid-drain member
		// mutations are out of scope for this paged read helper.
		while ( $page_count < self::MAX_MEMBER_LOAD_PAGES ) {
			$page = $this->members_repository->list_for_cluster( $cluster_id, $limit, $offset, $tenant_id );
			if ( empty( $page ) ) {
				break;
			}

			array_push( $members, ...$page );
			$offset += count( $page );
			++$page_count;

			if ( null === $total_count && isset( $page[0]['total_count'] ) && is_numeric( $page[0]['total_count'] ) ) {
				$total_count = max( 0, (int) $page[0]['total_count'] );
			}

			if ( null !== $total_count && $offset >= $total_count ) {
				break;
			}

			if ( count( $page ) < $limit ) {
				break;
			}
		}

		if ( $page_count >= self::MAX_MEMBER_LOAD_PAGES && ( null === $total_count || $offset < $total_count ) ) {
			Telemetry::log_line(
				sprintf(
					'[acx] SplitTopologyCommandDrain capped member pagination for cluster %s tenant %s after %d pages (%d loaded of %s).',
					$cluster_id,
					$tenant_id,
					$page_count,
					$offset,
					null === $total_count ? 'unknown total' : (string) $total_count
				)
			);
		}

		return $members;
	}

	/**
	 * @param mixed $value
	 * @return string[]
	 */
	private function normalize_identity_ids( $value ): array {
		if ( ! is_array( $value ) ) {
			return array();
		}

		return array_values(
			array_unique(
				array_filter(
					array_map(
						static function ( $item ): string {
							return trim( (string) $item );
						},
						$value
					),
					static function ( string $item ): bool {
						return '' !== $item;
					}
				)
			)
		);
	}

	private function resolve_max_attempts(): int {
		return max( 1, (int) apply_filters( 'acx_split_topology_max_attempts', self::DEFAULT_MAX_ATTEMPTS ) );
	}

	/**
	 * @return array<string,mixed>
	 */
	private function decode_result_payload( mixed $value ): array {
		if ( is_array( $value ) ) {
			return $value;
		}

		if ( ! is_string( $value ) || '' === trim( $value ) ) {
			return array();
		}

		$decoded = json_decode( $value, true );

		return is_array( $decoded ) ? $decoded : array();
	}

	private static function action_scheduler_group(): string {
		return self::ACTION_SCHEDULER_GROUP;
	}

	private function normalize_text( mixed $value, string $fallback ): string {
		if ( is_string( $value ) ) {
			$normalized = trim( $value );
			if ( '' !== $normalized ) {
				return $normalized;
			}
		}

		return $fallback;
	}
}
