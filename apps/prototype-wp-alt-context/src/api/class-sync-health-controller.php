<?php

declare(strict_types=1);

namespace AltContext\Api;

require_once __DIR__ . '/class-abstract-recognition-proxy-controller.php';
require_once __DIR__ . '/class-recognition-circuit-keys.php';
require_once __DIR__ . '/../sovereign/repositories/interface-sync-state-repository.php';
require_once __DIR__ . '/../sovereign/repositories/class-sync-state-repository.php';
require_once __DIR__ . '/../sovereign/sync/class-conflict-repository.php';
require_once __DIR__ . '/../sovereign/sync/class-outbox-query-repository.php';
require_once __DIR__ . '/../sovereign/sync/class-outbox-status.php';

use AltContext\Sovereign\Repositories\SyncStateRepository;
use AltContext\Sovereign\Repositories\SyncStateRepositoryInterface;
use AltContext\Sovereign\Sync\ConflictRepository;
use AltContext\Sovereign\Sync\OutboxQueryRepository;
use AltContext\Sovereign\Sync\OutboxStatus;
use AltContext\Sovereign\Sync\SyncPullResult;
use WP_REST_Request;
use WP_REST_Response;

use function apply_filters;
use function get_transient;
use function is_array;
use function max;

class SyncHealthController extends AbstractRecognitionProxyController {
	private const DEFAULT_OPEN_CONFLICT_WARNING_THRESHOLD = 25;
	private SyncStateRepositoryInterface $sync_state_repository;
	private OutboxQueryRepository $outbox_query_repository;
	private ConflictRepository $conflict_repository;

	public function __construct(
		?SyncStateRepositoryInterface $sync_state_repository = null,
		?OutboxQueryRepository $outbox_query_repository = null,
		?RecognitionEndpointResolver $endpoint_resolver = null,
		?ConflictRepository $conflict_repository = null
	) {
		$this->sync_state_repository = $sync_state_repository ?? new SyncStateRepository();
		$this->outbox_query_repository = $outbox_query_repository ?? new OutboxQueryRepository();
		$this->conflict_repository = $conflict_repository ?? new ConflictRepository();
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
		$open_conflicts = $this->sync_state_repository->get_conflict_count( $tenant_id );

		return new WP_REST_Response(
			array(
				'breaker' => array(
					'state' => $is_open ? 'open' : 'closed',
					'base_url' => $base_url,
					'opened_at' => null,
				),
				'outbox' => array(
					'pending' => $this->outbox_query_repository->count_operations_by_status( $tenant_id, OutboxStatus::PENDING ),
					'failed' => $this->outbox_query_repository->count_operations_by_status( $tenant_id, OutboxStatus::FAILED ),
				),
				'conflicts' => array(
					'open' => $open_conflicts,
				),
				'replays' => array(
					'failed' => null,
					'source' => 'unavailable_local',
				),
				'last_pull' => array(
					'at' => $this->sync_state_repository->get_last_updated( $tenant_id ),
					'ok' => SyncPullResult::OK === $last_sync_result,
				),
				'warnings' => $this->build_warnings( $tenant_id, $open_conflicts ),
			),
			200
		);
	}

	/**
	 * @return array<int,array{code:string,message:string,count:int,threshold:int}>
	 */
	private function build_warnings( string $tenant_id, int $open_conflicts ): array {
		$warnings = array();
		$conflict_threshold = max(
			1,
			(int) apply_filters( 'acx_sync_health_open_conflict_warning_threshold', self::DEFAULT_OPEN_CONFLICT_WARNING_THRESHOLD )
		);

		if ( $open_conflicts >= $conflict_threshold ) {
			$warnings[] = array(
				'code' => 'open_conflicts_high',
				'message' => 'Open sync conflicts exceed the configured warning threshold.',
				'count' => $open_conflicts,
				'threshold' => $conflict_threshold,
			);
		}

		// E15-35 Slice 3: an open aggregate backend_roster_regressed conflict is the
		// degraded-mode signal — surface it so the workbench banner can render it.
		if ( is_array( $this->conflict_repository->find_open_backend_roster_regression( $tenant_id ) ) ) {
			$warnings[] = array(
				'code' => ConflictRepository::CONFLICT_CODE_BACKEND_ROSTER_REGRESSED,
				'message' => 'The recognition backend roster appears rolled back; local curation is preserved until the conflict is resolved.',
				'count' => 1,
				'threshold' => 1,
			);
		}

		return $warnings;
	}

	public function set_endpoint_resolver( RecognitionEndpointResolver $endpoint_resolver ): void {
		$this->inject_endpoint_resolver( $endpoint_resolver );
	}
}
