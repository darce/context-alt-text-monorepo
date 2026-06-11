<?php

declare(strict_types=1);

namespace AltContext\Api;

require_once __DIR__ . '/class-recognition-circuit-keys.php';
require_once __DIR__ . '/../sovereign/repositories/interface-sync-state-repository.php';
require_once __DIR__ . '/../sovereign/repositories/class-sync-state-repository.php';
require_once __DIR__ . '/../sovereign/sync/class-outbox-query-repository.php';

use AltContext\Sovereign\Repositories\SyncStateRepository;
use AltContext\Sovereign\Repositories\SyncStateRepositoryInterface;
use AltContext\Sovereign\Sync\OutboxQueryRepository;
use AltContext\Sovereign\Sync\SyncPullResult;
use WP_REST_Request;
use WP_REST_Response;

use function get_transient;

class SyncHealthController extends AbstractRecognitionProxyController {
	private SyncStateRepositoryInterface $sync_state_repository;
	private OutboxQueryRepository $outbox_query_repository;

	public function __construct(
		?SyncStateRepositoryInterface $sync_state_repository = null,
		?OutboxQueryRepository $outbox_query_repository = null,
		?RecognitionEndpointResolver $endpoint_resolver = null
	) {
		$this->sync_state_repository = $sync_state_repository ?? new SyncStateRepository();
		$this->outbox_query_repository = $outbox_query_repository ?? new OutboxQueryRepository();
		if ( null !== $endpoint_resolver ) {
			$this->set_endpoint_resolver( $endpoint_resolver );
		}
	}

	public function register_routes(): void {
		register_rest_route(
			'acx/v1',
			'/recognition/sync/health',
			array(
				'methods'             => 'GET',
				'callback'            => array( $this, 'get_sync_health' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
			)
		);
	}

	public function get_sync_health( WP_REST_Request $request ): WP_REST_Response {
		$tenant_id = $this->get_tenant_id();
		$base_url = $this->get_recognition_base_url();
		$circuit_key = RecognitionCircuitKeys::for_base_url( $base_url );
		$is_open = false !== get_transient( $circuit_key );
		$last_sync_result = $this->sync_state_repository->get_last_sync_result( $tenant_id );

		return new WP_REST_Response(
			array(
				'breaker' => array(
					'state' => $is_open ? 'open' : 'closed',
					'base_url' => $base_url,
					'opened_at' => null,
				),
				'outbox' => array(
					'pending' => $this->outbox_query_repository->count_operations_by_status( $tenant_id, 'pending' ),
					'failed' => $this->outbox_query_repository->count_operations_by_status( $tenant_id, 'failed' ),
				),
				'conflicts' => array(
					'open' => $this->sync_state_repository->get_conflict_count( $tenant_id ),
				),
				'replays' => array(
					'failed' => null,
					'source' => 'unavailable_local',
				),
				'last_pull' => array(
					'at' => $this->sync_state_repository->get_last_updated( $tenant_id ),
					'ok' => SyncPullResult::OK === $last_sync_result,
				),
			),
			200
		);
	}

	public function set_endpoint_resolver( RecognitionEndpointResolver $endpoint_resolver ): void {
		$this->inject_endpoint_resolver( $endpoint_resolver );
	}
}
