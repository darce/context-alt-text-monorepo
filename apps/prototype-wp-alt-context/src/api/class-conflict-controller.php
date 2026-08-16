<?php

declare(strict_types=1);

namespace AltContext\Api;

require_once __DIR__ . '/class-abstract-recognition-proxy-controller.php';
require_once __DIR__ . '/../sovereign/sync/class-conflict-repository.php';
require_once __DIR__ . '/../sovereign/sync/class-conflict-resolution-service.php';
require_once __DIR__ . '/../sovereign/sync/class-outbox-drain.php';
require_once __DIR__ . '/../sovereign/repositories/interface-sync-state-repository.php';
require_once __DIR__ . '/../sovereign/repositories/class-sync-state-repository.php';

use AltContext\Sovereign\Repositories\SyncStateRepository;
use AltContext\Sovereign\Repositories\SyncStateRepositoryInterface;
use AltContext\Sovereign\Sync\ConflictRepository;
use AltContext\Sovereign\Sync\ConflictResolutionService;
use AltContext\Sovereign\Sync\OutboxDrain;
use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

use function absint;
use function is_array;
use function is_string;
use function sanitize_key;
use function sanitize_text_field;
use function trim;

class ConflictController extends AbstractRecognitionProxyController {
	private ConflictRepository $conflict_repository;
	private ConflictResolutionService $conflict_resolution_service;
	private OutboxDrain $outbox_drain;
	private SyncStateRepositoryInterface $sync_state_repository;

	public function __construct(
		?ConflictRepository $conflict_repository = null,
		?ConflictResolutionService $conflict_resolution_service = null,
		?OutboxDrain $outbox_drain = null,
		?SyncStateRepositoryInterface $sync_state_repository = null
	) {
		$this->conflict_repository = $conflict_repository ?? new ConflictRepository();
		$this->conflict_resolution_service = $conflict_resolution_service ?? new ConflictResolutionService();
		$this->outbox_drain = $outbox_drain ?? new OutboxDrain();
		$this->sync_state_repository = $sync_state_repository ?? new SyncStateRepository();
	}

	public function register_routes(): void {
		register_rest_route(
			'acx/v1',
			'/recognition/conflicts',
			array(
				'methods' => 'GET',
				'callback' => array( $this, 'list_conflicts' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
			)
		);

		register_rest_route(
			'acx/v1',
			'/recognition/conflicts/(?P<id>\d+)',
			array(
				'methods' => 'GET',
				'callback' => array( $this, 'get_conflict_detail' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
			)
		);

		register_rest_route(
			'acx/v1',
			'/recognition/conflicts/(?P<id>\d+)/resolve',
			array(
				'methods' => 'POST',
				'callback' => array( $this, 'resolve_conflict' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
			)
		);

		register_rest_route(
			'acx/v1',
			'/recognition/outbox',
			array(
				'methods' => 'GET',
				'callback' => array( $this, 'list_outbox_operations' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
			)
		);

		register_rest_route(
			'acx/v1',
			'/recognition/outbox/failed',
			array(
				'methods' => 'GET',
				'callback' => array( $this, 'list_failed_outbox_operations' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
			)
		);

		register_rest_route(
			'acx/v1',
			'/recognition/outbox/(?P<id>\d+)/retry',
			array(
				'methods' => 'POST',
				'callback' => array( $this, 'retry_failed_operation' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
			)
		);

		register_rest_route(
			'acx/v1',
			'/recognition/outbox/(?P<id>\d+)/discard',
			array(
				'methods' => 'POST',
				'callback' => array( $this, 'discard_operation' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
			)
		);
	}

	public function list_conflicts( WP_REST_Request $request ): WP_REST_Response {
		$tenant_id = $this->get_tenant_id();
		$limit = max( 1, min( 200, absint( $request->get_param( 'limit' ) ?? 50 ) ) );
		$offset = max( 0, absint( $request->get_param( 'offset' ) ?? 0 ) );
		$resolution_status = sanitize_key( (string) ( $request->get_param( 'resolution_status' ) ?? 'open' ) );
		if ( '' === $resolution_status ) {
			$resolution_status = 'open';
		}

		$items = $this->conflict_repository->find_conflicts_for_tenant( $tenant_id, $resolution_status, $limit, $offset );
		$total = $this->conflict_repository->count_conflicts( $tenant_id, $resolution_status );
		$outbox_operations = $this->load_outbox_operations_for_conflicts( $items, $tenant_id );

		return new WP_REST_Response(
			array(
				'items' => array_map(
					fn( array $conflict ): array => $this->map_conflict_record( $conflict, $outbox_operations ),
					$items
				),
				'total' => $total,
				'limit' => $limit,
				'offset' => $offset,
			),
			200
		);
	}

	public function get_conflict_detail( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$conflict = $this->conflict_repository->find_conflict_by_id(
			absint( $request->get_param( 'id' ) ),
			$this->get_tenant_id()
		);

		if ( ! is_array( $conflict ) ) {
			return new WP_Error( 'conflict_not_found', 'Conflict not found.', array( 'status' => 404 ) );
		}

		return new WP_REST_Response(
			array(
				'conflict' => $this->map_conflict_record( $conflict ),
			),
			200
		);
	}

	public function resolve_conflict( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$tenant_id = $this->get_tenant_id();
		$conflict_id = absint( $request->get_param( 'id' ) );
		$resolution_status = sanitize_key( (string) ( $request->get_param( 'resolution_status' ) ?? '' ) );
		$merged_value = sanitize_text_field( (string) ( $request->get_param( 'merged_value' ) ?? '' ) );
		$conflict = $this->conflict_repository->find_conflict_by_id( $conflict_id, $tenant_id );
		if ( ! is_array( $conflict ) ) {
			return new WP_Error( 'conflict_not_found', 'Conflict not found.', array( 'status' => 404 ) );
		}

		$allowed_resolutions = $this->determine_allowed_resolutions( $conflict, $tenant_id );
		if ( '' === $resolution_status || ! in_array( $resolution_status, $allowed_resolutions, true ) ) {
			return new WP_Error( 'resolution_not_allowed', 'Resolution is not allowed for this conflict.', array( 'status' => 422 ) );
		}

		$result = $this->conflict_resolution_service->resolve(
			$conflict_id,
			$resolution_status,
			$tenant_id,
			'' !== $merged_value ? $merged_value : null
		);
		if ( ! (bool) ( $result['ok'] ?? false ) ) {
			return $this->map_resolution_error( (string) ( $result['reason'] ?? 'conflict_update_failed' ) );
		}

		if ( ! (bool) ( $result['metrics_refreshed'] ?? false ) ) {
			$this->sync_state_repository->refresh_curation_metrics( $tenant_id );
		}
		$resolved_conflict = $this->conflict_repository->find_conflict_by_id( $conflict_id, $tenant_id );

		return new WP_REST_Response(
			array(
				'conflict' => is_array( $resolved_conflict ) ? $this->map_conflict_record( $resolved_conflict ) : null,
			),
			200
		);
	}

	public function list_failed_outbox_operations( WP_REST_Request $request ): WP_REST_Response {
		$tenant_id = $this->get_tenant_id();
		$limit = max( 1, min( 200, absint( $request->get_param( 'limit' ) ?? 50 ) ) );
		$offset = max( 0, absint( $request->get_param( 'offset' ) ?? 0 ) );
		$items = $this->outbox_drain->find_failed_operations( $tenant_id, $limit, $offset );
		$total = $this->outbox_drain->count_failed_operations( $tenant_id );

		return new WP_REST_Response(
			array(
				'items' => array_map( array( $this, 'map_operation_record' ), $items ),
				'total' => $total,
				'limit' => $limit,
				'offset' => $offset,
			),
			200
		);
	}

	public function list_outbox_operations( WP_REST_Request $request ): WP_REST_Response {
		$tenant_id = $this->get_tenant_id();
		$limit = max( 1, min( 200, absint( $request->get_param( 'limit' ) ?? 50 ) ) );
		$offset = max( 0, absint( $request->get_param( 'offset' ) ?? 0 ) );
		$status = sanitize_key( (string) ( $request->get_param( 'status' ) ?? '' ) );
		if ( '' === $status ) {
			$status = null;
		}

		$items = $this->outbox_drain->find_operations( $tenant_id, $status, $limit, $offset );
		$total = $this->outbox_drain->count_operations( $tenant_id, $status );

		return new WP_REST_Response(
			array(
				'items' => array_map( array( $this, 'map_operation_record' ), $items ),
				'total' => $total,
				'limit' => $limit,
				'offset' => $offset,
			),
			200
		);
	}

	public function retry_failed_operation( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$tenant_id = $this->get_tenant_id();
		$outbox_id = absint( $request->get_param( 'id' ) );
		$operation = $this->outbox_drain->find_operation_by_id( $outbox_id, $tenant_id );
		if ( ! is_array( $operation ) ) {
			return new WP_Error( 'outbox_operation_not_found', 'Outbox operation not found.', array( 'status' => 404 ) );
		}

		if ( 'failed' !== (string) ( $operation['status'] ?? '' ) ) {
			return new WP_Error( 'outbox_operation_not_failed', 'Outbox operation is not in failed status.', array( 'status' => 409 ) );
		}

		if ( ! $this->outbox_drain->retry_failed_operation( $outbox_id, $tenant_id ) ) {
			return new WP_Error( 'outbox_retry_failed', 'Retrying the outbox operation failed.', array( 'status' => 500 ) );
		}

		$updated_operation = $this->outbox_drain->find_operation_by_id( $outbox_id, $tenant_id );
		if ( ! is_array( $updated_operation ) ) {
			return new WP_Error( 'outbox_retry_failed', 'Retried outbox operation could not be reloaded.', array( 'status' => 500 ) );
		}

		$this->sync_state_repository->refresh_curation_metrics( $tenant_id );

		return new WP_REST_Response(
			array(
				'operation' => $this->map_operation_record( $updated_operation ),
			),
			200
		);
	}

	public function discard_operation( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$tenant_id = $this->get_tenant_id();
		$outbox_id = absint( $request->get_param( 'id' ) );
		$operation = $this->outbox_drain->find_operation_by_id( $outbox_id, $tenant_id );
		if ( ! is_array( $operation ) ) {
			return new WP_Error( 'outbox_operation_not_found', 'Outbox operation not found.', array( 'status' => 404 ) );
		}

		if ( 'failed' !== (string) ( $operation['status'] ?? '' ) ) {
			return new WP_Error( 'outbox_operation_not_failed', 'Outbox operation is not in failed status.', array( 'status' => 409 ) );
		}

		if ( ! $this->outbox_drain->discard_operation( $outbox_id, $tenant_id ) ) {
			return new WP_Error( 'outbox_discard_failed', 'Discarding the outbox operation failed.', array( 'status' => 500 ) );
		}

		$updated_operation = $this->outbox_drain->find_operation_by_id( $outbox_id, $tenant_id );
		if ( ! is_array( $updated_operation ) ) {
			return new WP_Error( 'outbox_discard_failed', 'Discarded outbox operation could not be reloaded.', array( 'status' => 500 ) );
		}

		$this->sync_state_repository->refresh_curation_metrics( $tenant_id );

		return new WP_REST_Response(
			array(
				'operation' => $this->map_operation_record( $updated_operation ),
			),
			200
		);
	}

	/**
	 * @param array<string,mixed> $conflict
	 * @param array<int,array<string,mixed>> $outbox_operations
	 * @return array<string,mixed>
	 */
	private function map_conflict_record( array $conflict, array $outbox_operations = array() ): array {
		$outbox_id = absint( $conflict['outbox_id'] ?? 0 );
		$allowed_resolutions = $this->determine_allowed_resolutions(
			$conflict,
			(string) ( $conflict['tenant_id'] ?? '' ),
			$outbox_operations
		);

		return array(
			'id' => absint( $conflict['id'] ?? 0 ),
			'tenant_id' => (string) ( $conflict['tenant_id'] ?? '' ),
			'entity_type' => (string) ( $conflict['entity_type'] ?? '' ),
			'entity_key' => (string) ( $conflict['entity_key'] ?? '' ),
			'outbox_id' => $outbox_id,
			'expected_base_version' => absint( $conflict['expected_base_version'] ?? 0 ),
			'backend_version' => absint( $conflict['backend_version'] ?? 0 ),
			'local_revision' => absint( $conflict['local_revision'] ?? 0 ),
			'conflict_code' => (string) ( $conflict['conflict_code'] ?? '' ),
			'backend_proposed_value' => is_string( $conflict['backend_proposed_value'] ?? null ) ? $conflict['backend_proposed_value'] : null,
			'machine_payload' => $conflict['machine_payload'] ?? array(),
			'local_payload' => $conflict['local_payload'] ?? array(),
			'resolution_status' => (string) ( $conflict['resolution_status'] ?? 'open' ),
			'resolved_at' => $conflict['resolved_at'] ?? null,
			'created_at' => $conflict['created_at'] ?? null,
			'allowed_resolutions' => $allowed_resolutions,
		);
	}

	/**
	 * @param array<string,mixed> $operation
	 * @return array<string,mixed>
	 */
	private function map_operation_record( array $operation ): array {
		return array(
			'id' => absint( $operation['id'] ?? 0 ),
			'tenant_id' => (string) ( $operation['tenant_id'] ?? '' ),
			'operation_type' => (string) ( $operation['operation_type'] ?? '' ),
			'entity_type' => (string) ( $operation['entity_type'] ?? '' ),
			'entity_key' => (string) ( $operation['entity_key'] ?? '' ),
			'status' => (string) ( $operation['status'] ?? '' ),
			'attempts' => absint( $operation['attempts'] ?? 0 ),
			'expected_base_version' => absint( $operation['expected_base_version'] ?? 0 ),
			'local_revision' => absint( $operation['local_revision'] ?? 0 ),
			'last_error_code' => $operation['last_error_code'] ?? null,
			'last_error_message' => $operation['last_error_message'] ?? null,
			'payload' => $operation['payload'] ?? array(),
			'created_at' => $operation['created_at'] ?? null,
			'last_attempted_at' => $operation['last_attempted_at'] ?? null,
			'acknowledged_at' => $operation['acknowledged_at'] ?? null,
		);
	}

	/**
	 * @param array<string,mixed> $conflict
	 * @param array<int,array<string,mixed>> $outbox_operations
	 * @return string[]
	 */
	private function determine_allowed_resolutions( array $conflict, string $tenant_id, array $outbox_operations = array() ): array {
		$outbox_id = absint( $conflict['outbox_id'] ?? 0 );
		$conflict_code = trim( (string) ( $conflict['conflict_code'] ?? '' ) );
		if ( 'person_name_conflict' === $conflict_code ) {
			return array( 'accept_backend', 'merge', 'dismissed' );
		}

		if ( 'drift_conflict' === $conflict_code ) {
			return array( 'accept_backend', 'dismissed' );
		}

		// E15-35 Slice 3 aggregate: restore_local is offered only while the
		// persisted entity set is complete; a truncated aggregate fails closed to
		// accept_backend / bulk recovery.
		if ( ConflictRepository::CONFLICT_CODE_BACKEND_ROSTER_REGRESSED === $conflict_code ) {
			$machine_payload = $conflict['machine_payload'] ?? array();
			$entity_set_truncated = is_array( $machine_payload ) && ! empty( $machine_payload['entity_set_truncated'] );

			return $entity_set_truncated
				? array( 'accept_backend', 'dismissed' )
				: array( 'restore_local', 'accept_backend', 'dismissed' );
		}

		if ( 0 === $outbox_id ) {
			return array( 'accepted', 'dismissed' );
		}

		$operation = $outbox_operations[ $outbox_id ] ?? $this->outbox_drain->find_operation_by_id( $outbox_id, $tenant_id );
		$operation_type = is_array( $operation ) ? trim( (string) ( $operation['operation_type'] ?? '' ) ) : '';
		if ( in_array( $operation_type, ConflictResolutionService::ACCEPT_MACHINE_OUTBOX_OPERATIONS, true ) ) {
			return array( 'accepted', 'dismissed' );
		}

		if (
			in_array( $operation_type, ConflictResolutionService::ACCEPT_MACHINE_COMPOUND_OUTBOX_OPERATIONS, true )
			&& $this->can_accept_compound_operation( $operation_type, $conflict, $operation )
		) {
			return array( 'accepted', 'dismissed' );
		}

		if ( '' !== $operation_type ) {
			return array( 'dismissed' );
		}

		return array();
	}

	/**
	 * @param array<string,mixed> $conflict
	 * @param array<string,mixed>|null $operation
	 */
	private function can_accept_compound_operation( string $operation_type, array $conflict, ?array $operation ): bool {
		if ( ! is_array( $operation ) ) {
			return false;
		}

		$payload = $operation['payload'] ?? array();
		if ( ! is_array( $payload ) ) {
			return false;
		}

		if ( 'revert_merge_cluster' === $operation_type ) {
			return '' !== trim( (string) ( $payload['target_cluster_id'] ?? '' ) )
				&& '' !== trim( (string) ( $payload['desired_source_cluster_id'] ?? '' ) )
				&& is_array( $payload['moved_identity_ids'] ?? null )
				&& array() !== $payload['moved_identity_ids'];
		}

		if ( in_array( $operation_type, array( 'assign_outlier_to_cluster', 'cluster_created_for_identity' ), true ) ) {
			$machine_payload = $conflict['machine_payload'] ?? array();
			return is_array( $machine_payload )
				&& '' !== trim( (string) ( $machine_payload['cluster_uuid'] ?? '' ) )
				&& '' !== trim( (string) ( $payload['identity_id'] ?? '' ) );
		}

		return false;
	}

	/**
	 * @param array<int,array<string,mixed>> $conflicts
	 * @return array<int,array<string,mixed>>
	 */
	private function load_outbox_operations_for_conflicts( array $conflicts, string $tenant_id ): array {
		$outbox_ids = array();
		foreach ( $conflicts as $conflict ) {
			if ( ! is_array( $conflict ) ) {
				continue;
			}

			$outbox_id = absint( $conflict['outbox_id'] ?? 0 );
			if ( $outbox_id > 0 ) {
				$outbox_ids[] = $outbox_id;
			}
		}

		if ( array() === $outbox_ids ) {
			return array();
		}

		return $this->outbox_drain->find_operations_by_ids( $outbox_ids, $tenant_id );
	}

	private function map_resolution_error( string $reason ): WP_Error {
		if ( 'already_resolved' === $reason ) {
			return new WP_Error( 'conflict_already_resolved', 'Conflict is already resolved.', array( 'status' => 409 ) );
		}

		if ( 'resolution_not_allowed' === $reason ) {
			return new WP_Error( 'resolution_not_allowed', 'Resolution is not allowed for this conflict.', array( 'status' => 422 ) );
		}

		if ( 'reserved_label' === $reason ) {
			return new WP_Error( 'reserved_label', 'Labels beginning with cluster- or cluster_ are reserved.', array( 'status' => 400 ) );
		}

		if ( 'not_found' === $reason ) {
			return new WP_Error( 'conflict_not_found', 'Conflict not found.', array( 'status' => 404 ) );
		}

		return new WP_Error( 'conflict_resolution_failed', 'Conflict resolution failed.', array( 'status' => 500 ) );
	}
}
