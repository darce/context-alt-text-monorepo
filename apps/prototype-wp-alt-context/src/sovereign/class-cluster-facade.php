<?php

declare(strict_types=1);

namespace AltContext\Sovereign;

use AltContext\Sovereign\Repositories\ClustersRepositoryInterface;
use AltContext\Sovereign\Repositories\IdentityMembersRepositoryInterface;
use RuntimeException;

/**
 * Facade for sovereign cluster operations.
 */
class ClusterFacade {

	/**
	 * @param ClustersRepositoryInterface        $clusters_repo
	 * @param IdentityMembersRepositoryInterface $members_repo
	 */
	public function __construct(
		private ClustersRepositoryInterface $clusters_repo,
		private IdentityMembersRepositoryInterface $members_repo
	) {}

	/**
	 * Returns top unlabeled clusters from sovereign tables.
	 *
	 * @param string $tenant_id Tenant UUID.
	 * @param int    $limit     Maximum clusters to return.
	 * @return array{clusters: array<int, array<string, mixed>>, members: array<string, array<int, array<string, mixed>>>}
	 * @throws RuntimeException If the query fails.
	 */
	public function list_top_unlabeled( string $tenant_id, int $limit = 10 ): array {
		$clusters = $this->clusters_repo->list_top_unlabeled( $tenant_id, $limit );
		if ( empty( $clusters ) ) {
			return array(
				'clusters' => array(),
				'members'  => array(),
			);
		}

		$cluster_uuids = array();
		foreach ( $clusters as $row ) {
			$uuid = trim( (string) ( $row['cluster_uuid'] ?? '' ) );
			if ( '' !== $uuid ) {
				$cluster_uuids[] = $uuid;
			}
		}

		$members_by_cluster = array();
		if ( ! empty( $cluster_uuids ) ) {
			$members_by_cluster = $this->members_repo->list_for_cluster_uuids( $cluster_uuids, 4 );
		}

		return array(
			'clusters' => $clusters,
			'members'  => $members_by_cluster,
		);
	}
}
