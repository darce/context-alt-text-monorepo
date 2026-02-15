<?php

declare(strict_types=1);

namespace AltContext\Api;

use AltContext\Sovereign\Repositories\SyncStateRepository;
use AltContext\Sovereign\Repositories\SyncStateRepositoryInterface;
use WP_REST_Request;
use WP_REST_Response;

use function apply_filters;
use function is_string;
use function max;
use function strtotime;
use function time;
use function trim;

class SyncStatusController extends AbstractRecognitionProxyController {
	private SyncStateRepositoryInterface $sync_state_repository;

	public function __construct( ?SyncStateRepositoryInterface $sync_state_repository = null ) {
		$this->sync_state_repository = $sync_state_repository ?? new SyncStateRepository();
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

	private function is_projection_stale( ?string $updated_at ): bool {
		if ( ! is_string( $updated_at ) || '' === trim( $updated_at ) ) {
			return true;
		}

		$timestamp = strtotime( $updated_at );
		if ( false === $timestamp ) {
			return true;
		}

		$threshold = (int) apply_filters( 'acx_sync_stale_threshold_seconds', 3600 );
		$threshold = max( 60, $threshold );

		$age = max( 0, time() - $timestamp );

		return $age > $threshold;
	}
}
