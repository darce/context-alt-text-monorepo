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
	 * @return array{clusters: array<int, array<string, mixed>>, members: array<string, array<int, array<string, mixed>>>, singleton_count: int}
	 * @throws RuntimeException If the query fails.
	 */
	public function list_top_unlabeled( string $tenant_id, int $limit = 10 ): array {
		$clusters = $this->clusters_repo->list_top_unlabeled( $tenant_id, $limit );
		$singleton_count = $this->clusters_repo->count_top_unlabeled_singletons( $tenant_id );
		if ( empty( $clusters ) ) {
			return array(
				'clusters' => array(),
				'members'  => array(),
				'singleton_count' => $singleton_count,
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
			// Repository returns a sparse map (no key when a cluster has zero
			// rows). Densify so callers can treat [] as "none" and absence as
			// "not fetched" (UI-01 / LO-01).
			$members_by_cluster = self::densify_members_by_cluster(
				$cluster_uuids,
				$this->members_repo->list_for_cluster_uuids(
					$cluster_uuids,
					IdentityMembersRepositoryInterface::PREVIEW_IDENTITIES_FETCH_LIMIT
				)
			);
		}

		return array(
			'clusters' => $clusters,
			'members'  => $members_by_cluster,
			'singleton_count' => $singleton_count,
		);
	}

	/**
	 * Expand a sparse members-by-cluster map to one key per requested uuid.
	 *
	 * @param array<int,string> $cluster_uuids
	 * @param array<string,array<int,array<string,mixed>>> $members_by_cluster
	 * @return array<string,array<int,array<string,mixed>>>
	 */
	public static function densify_members_by_cluster( array $cluster_uuids, array $members_by_cluster ): array {
		$dense = array();
		foreach ( $cluster_uuids as $uuid ) {
			$uuid = trim( (string) $uuid );
			if ( '' === $uuid ) {
				continue;
			}
			if ( isset( $members_by_cluster[ $uuid ] ) && is_array( $members_by_cluster[ $uuid ] ) ) {
				$dense[ $uuid ] = $members_by_cluster[ $uuid ];
			} else {
				$dense[ $uuid ] = array();
			}
		}

		return $dense;
	}
}
