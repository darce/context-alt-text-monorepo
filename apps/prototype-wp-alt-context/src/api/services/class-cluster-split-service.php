<?php

declare(strict_types=1);

namespace AltContext\Api\Services;

require_once __DIR__ . '/../../support/trait-runs-transactional.php';

use AltContext\Api\ClusterMutationHostInterface;
use AltContext\Support\RunsTransactional;
use AltContext\Sovereign\Repositories\SyncStateRepository;
use AltContext\Sovereign\Repositories\SyncStateRepositoryInterface;
use AltContext\Sovereign\Sync\SplitTopologyCommandDrain;
use AltContext\Sovereign\Sync\TopologyCommandRepository;
use AltContext\Sovereign\Sync\TopologyCommandRepositoryInterface;
use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

use function absint;
use function array_filter;
use function array_map;
use function array_values;
use function get_current_user_id;
use function is_array;
use function is_object;
use function is_wp_error;
use function max;
use function method_exists;
use function sanitize_text_field;

class ClusterSplitService {
	use RunsTransactional;

	private ClusterMutationHostInterface $host;
	private SyncStateRepositoryInterface $sync_state_repository;
	private TopologyCommandRepositoryInterface $topology_command_repository;

	public function __construct(
		ClusterMutationHostInterface $host,
		?SyncStateRepositoryInterface $sync_state_repository = null,
		?TopologyCommandRepositoryInterface $topology_command_repository = null
	) {
		$this->host = $host;
		$this->sync_state_repository = $sync_state_repository ?? new SyncStateRepository();
		$this->topology_command_repository = $topology_command_repository ?? new TopologyCommandRepository();
	}

	public function split_cluster( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		global $wpdb;
		$tenant_id = $this->host->get_tenant_id();

		$cluster_id = sanitize_text_field( (string) $request->get_param( 'cluster_id' ) );

		if ( '' === $cluster_id ) {
			return new WP_Error( 'missing_cluster_id', 'Cluster ID is required.', array( 'status' => 400 ) );
		}

		$cluster = $this->host->get_projected_cluster_or_error( $cluster_id );
		if ( is_wp_error( $cluster ) ) {
			return $cluster;
		}

		$n_clusters = absint( $request->get_param( 'n_clusters' ) ?? 0 );

		$payload = array(
			'tenant_id'  => $tenant_id,
			'cluster_id' => $cluster_id,
			'n_clusters' => $n_clusters,
			'user_id'    => get_current_user_id(),
		);
		$anchor_identity_id = sanitize_text_field( (string) $request->get_param( 'anchor_identity_id' ) );
		if ( '' !== $anchor_identity_id ) {
			$payload['anchor_identity_id'] = $anchor_identity_id;
		}
		$split_mode = sanitize_text_field( (string) $request->get_param( 'split_mode' ) );
		if ( '' !== $split_mode ) {
			$payload['split_mode'] = $split_mode;
		}

		$desired_cluster_ids = $request->get_param( 'desired_cluster_ids' );
		if ( is_array( $desired_cluster_ids ) && ! empty( $desired_cluster_ids ) ) {
			$payload['desired_cluster_ids'] = array_values(
				array_filter(
					array_map(
						static function ( $value ): string {
							return sanitize_text_field( (string) $value );
						},
						$desired_cluster_ids
					),
					static function ( string $value ): bool {
						return '' !== $value;
					}
				)
			);
		}

		$idempotency_key = $this->host->resolve_split_idempotency_key(
			$request,
			$cluster_id,
			max( 0, (int) ( $cluster['snapshot_version'] ?? $this->sync_state_repository->get_snapshot_version( $tenant_id ) ) ),
			$payload
		);

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'query' ) ) {
			return new WP_Error( 'acx_db_error', 'Database access is unavailable.', array( 'status' => 500 ) );
		}

		$result = $this->run_transactional(
			function () use ( $tenant_id, $cluster_id, $cluster, $payload, $idempotency_key ): WP_REST_Response|WP_Error {
				$command_id = $this->topology_command_repository->enqueue(
					$tenant_id,
					'cluster_split',
					$cluster_id,
					max( 0, (int) ( $cluster['snapshot_version'] ?? $this->sync_state_repository->get_snapshot_version( $tenant_id ) ) ),
					$payload,
					$idempotency_key
				);

				if ( false === $command_id ) {
					return new WP_Error( 'acx_db_error', 'Could not queue split topology command.', array( 'status' => 500 ) );
				}

				$this->sync_state_repository->touch_local_curation_marker( $tenant_id );
				$this->sync_state_repository->refresh_curation_metrics( $tenant_id );

				return new WP_REST_Response(
					array(
						'command_id' => $command_id,
						'synced' => false,
						'status' => 'pending',
						'command_state' => 'queued',
						'projection_state' => 'awaiting_backend_partition',
						'cluster_id' => $cluster_id,
						'idempotency_key' => $idempotency_key,
					),
					200
				);
			}
		);

		if ( is_wp_error( $result ) ) {
			return $result;
		}

		SplitTopologyCommandDrain::maybe_schedule_drain();

		return $result;
	}
}
