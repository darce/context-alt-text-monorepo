<?php

declare(strict_types=1);

namespace AltContext\Api\Services;

require_once __DIR__ . '/../../support/trait-runs-transactional.php';
require_once __DIR__ . '/../../support/trait-detects-system-defined-labels.php';
require_once __DIR__ . '/class-person-resolution-service.php';
require_once __DIR__ . '/../../sovereign/repositories/class-cluster-curation-writer.php';

use AltContext\Api\ClusterMutationHostInterface;
use AltContext\Support\RunsTransactional;
use AltContext\Support\DetectsSystemDefinedLabels;
use AltContext\Sovereign\Repositories\ClusterCurationWriter;
use AltContext\Sovereign\Repositories\ClustersRepository;
use AltContext\Sovereign\Repositories\ClustersRepositoryInterface;
use AltContext\Sovereign\Repositories\SyncStateRepository;
use AltContext\Sovereign\Repositories\SyncStateRepositoryInterface;
use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

use function current_time;
use function is_array;
use function is_object;
use function is_wp_error;
use function max;
use function method_exists;
use function sanitize_text_field;
use function sprintf;

/**
 * Label curation with person-projection write-through.
 *
 * PersonResolutionService is transaction-agnostic: this service owns the
 * run_transactional boundary and must not nest another START TRANSACTION.
 */
class ClusterLabelService {
	use DetectsSystemDefinedLabels;
	use RunsTransactional;

	private ClusterMutationHostInterface $host;
	private ClustersRepositoryInterface $clusters_repository;
	private SyncStateRepositoryInterface $sync_state_repository;

	public function __construct(
		ClusterMutationHostInterface $host,
		?ClustersRepositoryInterface $clusters_repository = null,
		?SyncStateRepositoryInterface $sync_state_repository = null
	) {
		$this->host = $host;
		$this->clusters_repository = $clusters_repository ?? new ClustersRepository();
		$this->sync_state_repository = $sync_state_repository ?? new SyncStateRepository();
	}

	public function update_cluster_label( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		global $wpdb;
		$tenant_id = $this->host->get_tenant_id();

		$cluster_id = sanitize_text_field( (string) $request->get_param( 'cluster_id' ) );
		$label      = sanitize_text_field( (string) $request->get_param( 'label' ) );

		if ( '' === $cluster_id ) {
			return new WP_Error( 'missing_cluster_id', 'Cluster ID is required.', array( 'status' => 400 ) );
		}

		if ( '' === $label ) {
			return new WP_Error( 'missing_label', 'Label cannot be empty.', array( 'status' => 400 ) );
		}

		if ( $this->is_reserved_label_shape( $label ) ) {
			return new WP_Error( 'reserved_label', 'Labels beginning with cluster- or cluster_ are reserved.', array( 'status' => 400 ) );
		}

		if ( $this->host->should_proxy_mutation_to_backend( $tenant_id ) ) {
			$proxied = $this->host->proxy_cluster_mutation(
				'PATCH',
				sprintf( '/recognition/clusters/%s', $cluster_id ),
				array(
					'tenant_id' => $tenant_id,
					'label'     => $label,
				)
			);
			if ( is_wp_error( $proxied ) ) {
				return $proxied;
			}

			$status = $proxied instanceof WP_REST_Response ? $proxied->get_status() : 0;
			if ( $status < 200 || $status >= 300 ) {
				return $proxied;
			}

			$resolved = $this->persist_local_person_for_label( $label );
			if ( is_wp_error( $resolved ) ) {
				return $resolved;
			}

			$data = $proxied->get_data();
			if ( ! is_array( $data ) ) {
				$data = array();
			}
			$data['person_id']    = (int) $resolved['person_id'];
			$bound                = $this->bind_persisted_person( $cluster_id, (int) $resolved['person_id'], $tenant_id );
			if ( is_wp_error( $bound ) ) {
				return $bound;
			}
			$data['roster_bound'] = $bound;
			$proxied->set_data( $data );

			return $proxied;
		}

		$cluster = $this->clusters_repository->find_by_uuid( $cluster_id );
		if ( ! is_array( $cluster ) ) {
			$cluster = $this->host->get_projected_cluster_or_error( $cluster_id );
			if ( is_wp_error( $cluster ) ) {
				return $cluster;
			}
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'query' ) || ! method_exists( $wpdb, 'update' ) ) {
			return new WP_Error( 'acx_db_error', 'Database access is unavailable.', array( 'status' => 500 ) );
		}

		$affected_rows        = 0;
		$person_write_through = false;
		$result               = $this->run_transactional(
			function () use ( $cluster_id, $label, $cluster, $tenant_id, &$affected_rows, &$person_write_through ): WP_REST_Response|WP_Error {
				global $wpdb;

				$affected_rows      = $this->clusters_repository->update_label( $cluster_id, $label );
				$label_changed      = $affected_rows > 0;
				$existing_person_id = isset( $cluster['person_id'] ) ? (int) $cluster['person_id'] : 0;
				$has_person_binding = $existing_person_id > 0;

				// Identical-label resubmit: update_label is a no-op, but the cluster may
				// still lack a person binding (label path wrote the text without write-through).
				// Only short-circuit when both the label row and the person bind are already set.
				if ( ! $label_changed && $has_person_binding ) {
					return new WP_REST_Response(
						array(
							'cluster_id' => $cluster_id,
							'label'      => $label,
							'synced'     => false,
							'status'     => 'acknowledged',
						),
						200
					);
				}

				// Preserve the pre-write-through dual-write contract: label curation
				// still emits cluster_label_updated as the primary outbox event when the
				// label actually changed. Person-projection write-through below is additive (rg-002).
				if ( $label_changed ) {
					if ( ! $this->host->enqueue_curation_operation(
						'cluster_label_updated',
						$cluster_id,
						$cluster,
						array(
							'cluster_uuid' => $cluster_id,
							'label'        => $label,
						)
					) ) {
						return new WP_Error( 'acx_db_error', 'Could not enqueue label replay operation.', array( 'status' => 500 ) );
					}
				}

				// Caller owns the transaction: resolver must not open nested START TRANSACTION.
				$resolver = new PersonResolutionService();
				$resolved = $resolver->resolve_or_create(
					$label,
					function ( string $person_uuid, string $name, array $tags ) use ( $cluster ): bool {
						// person_created local_revision is always 1 for a newly created person.
						return $this->host->enqueue_curation_operation(
							'person_created',
							$person_uuid,
							array(
								'local_revision'   => 0,
								'snapshot_version' => max( 0, (int) ( $cluster['snapshot_version'] ?? 0 ) ),
							),
							array(
								'person_uuid' => $person_uuid,
								'name'        => $name,
								'tags'        => $tags,
							),
							'person'
						);
					}
				);
				if ( is_wp_error( $resolved ) ) {
					return $resolved;
				}

				$writer = new ClusterCurationWriter( $wpdb->prefix . 'acx_clusters' );
				$bound  = $writer->bind_person_to_cluster( $cluster_id, (int) $resolved['person_id'], $tenant_id, true );
				if ( false === $bound ) {
					return new WP_Error( 'acx_db_error', 'Could not bind person to cluster.', array( 'status' => 500 ) );
				}

				if ( ! $this->host->enqueue_curation_operation(
					'cluster_person_bound',
					$cluster_id,
					$cluster,
					array(
						'cluster_uuid' => $cluster_id,
						'person_uuid'  => $resolved['person_uuid'],
						'person_name'  => $resolved['name'],
					)
				) ) {
					return new WP_Error( 'acx_db_error', 'Could not enqueue person-bind replay operation.', array( 'status' => 500 ) );
				}

				$person_write_through = true;
				$this->sync_state_repository->touch_local_curation_marker( $tenant_id );

				return new WP_REST_Response(
					array(
						'cluster_id'    => $cluster_id,
						'label'         => $label,
						'synced'        => false,
						'status'        => 'pending',
						'person_id'     => (int) $resolved['person_id'],
						'roster_bound'  => ClusterCurationWriter::bind_succeeded( $bound ),
					),
					200
				);
			}
		);

		if ( is_wp_error( $result ) ) {
			return $result;
		}

		if ( $affected_rows > 0 || $person_write_through ) {
			$this->host->trigger_xmp_refresh_for_cluster_ids( array( $cluster_id ), 'cluster-label-update' );
		}

		return $result;
	}

	/**
	 * Bind a locally persisted person after a successful proxy label write.
	 *
	 * @return bool|WP_Error true when bound (including already-bound), false when no cluster row matched.
	 */
	private function bind_persisted_person( string $cluster_id, int $person_id, string $tenant_id ): bool|WP_Error {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'update' ) ) {
			return new WP_Error( 'acx_db_error', 'Could not bind person to cluster.', array( 'status' => 500 ) );
		}

		$writer = new ClusterCurationWriter( $wpdb->prefix . 'acx_clusters' );
		$bound  = $writer->bind_person_to_cluster( $cluster_id, $person_id, $tenant_id, true );
		if ( false === $bound ) {
			return new WP_Error( 'acx_db_error', 'Could not bind person to cluster.', array( 'status' => 500 ) );
		}

		return ClusterCurationWriter::bind_succeeded( $bound );
	}

	private function persist_local_person_for_label( string $label ): array|WP_Error {
		$result = $this->run_transactional(
			function () use ( $label ): array|WP_Error {
				$resolver = new PersonResolutionService();
				return $resolver->resolve_or_create(
					$label,
					function ( string $person_uuid, string $name, array $tags ): bool {
						return $this->host->enqueue_curation_operation(
							'person_created',
							$person_uuid,
							array(
								'local_revision'   => 0,
								'snapshot_version' => 0,
							),
							array(
								'person_uuid' => $person_uuid,
								'name'        => $name,
								'tags'        => $tags,
							),
							'person'
						);
					}
				);
			}
		);

		return $result;
	}
}
