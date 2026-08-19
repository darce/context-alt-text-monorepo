<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\ClusterFacade;
use AltContext\Sovereign\Repositories\ClustersRepositoryInterface;
use AltContext\Sovereign\Repositories\IdentityMembersRepositoryInterface;
use PHPUnit\Framework\TestCase;

/**
 * @covers \AltContext\Sovereign\ClusterFacade
 */
class ClusterFacadeMembersDensifyTest extends TestCase {

	/**
	 * Repository returns a sparse map (no key for zero-member clusters). The
	 * facade must densify so mappers can distinguish "none" from "not fetched".
	 */
	public function test_list_top_unlabeled_densifies_sparse_members_map(): void {
		$clusters_repo = $this->createMock( ClustersRepositoryInterface::class );
		$members_repo  = $this->createMock( IdentityMembersRepositoryInterface::class );
		$facade        = new ClusterFacade( $clusters_repo, $members_repo );

		$clusters = [
			[ 'cluster_uuid' => 'uuid-with-members', 'identity_count' => 1 ],
			[ 'cluster_uuid' => 'uuid-empty', 'identity_count' => 1 ],
		];

		// Production shape: only clusters with rows are keyed.
		$sparse = [
			'uuid-with-members' => [
				[ 'identity_uuid' => 'id-1', 'attachment_id' => 10 ],
			],
		];

		$clusters_repo->method( 'list_top_unlabeled' )->willReturn( $clusters );
		$clusters_repo->method( 'count_top_unlabeled_singletons' )->willReturn( 0 );
		$members_repo->expects( $this->once() )
			->method( 'list_for_cluster_uuids' )
			->with(
				[ 'uuid-with-members', 'uuid-empty' ],
				IdentityMembersRepositoryInterface::PREVIEW_IDENTITIES_FETCH_LIMIT
			)
			->willReturn( $sparse );

		$result = $facade->list_top_unlabeled( 'tenant-123', 10 );

		$this->assertArrayHasKey( 'uuid-with-members', $result['members'] );
		$this->assertArrayHasKey( 'uuid-empty', $result['members'] );
		$this->assertSame( [], $result['members']['uuid-empty'] );
		$this->assertCount( 1, $result['members']['uuid-with-members'] );
	}

	public function test_densify_members_by_cluster_fills_missing_keys(): void {
		$dense = ClusterFacade::densify_members_by_cluster(
			[ 'a', 'b', 'c' ],
			[
				'a' => [ [ 'identity_uuid' => 'id-a' ] ],
				// b missing
				'c' => [],
			]
		);

		$this->assertSame( [ [ 'identity_uuid' => 'id-a' ] ], $dense['a'] );
		$this->assertSame( [], $dense['b'] );
		$this->assertSame( [], $dense['c'] );
	}
}
