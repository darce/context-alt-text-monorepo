<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\ClusterFacade;
use AltContext\Sovereign\Repositories\ClustersRepositoryInterface;
use AltContext\Sovereign\Repositories\IdentityMembersRepositoryInterface;
use PHPUnit\Framework\TestCase;
use RuntimeException;

class ClusterFacadeTest extends TestCase {

	public function test_preview_fetch_limit_is_one_past_preview_cap(): void {
		$this->assertSame(
			IdentityMembersRepositoryInterface::PREVIEW_IDENTITIES_PER_CLUSTER + 1,
			IdentityMembersRepositoryInterface::PREVIEW_IDENTITIES_FETCH_LIMIT
		);
	}

	public function test_list_top_unlabeled_orchestrates_repositories(): void {
		$clusters_repo = $this->createMock( ClustersRepositoryInterface::class );
		$members_repo  = $this->createMock( IdentityMembersRepositoryInterface::class );
		$facade        = new ClusterFacade( $clusters_repo, $members_repo );

		$tenant_id = 'tenant-123';
		$limit = 10;

		$clusters = [
			['cluster_uuid' => 'uuid-1', 'label' => 'A'],
		];
		$members = [
			'uuid-1' => [
				['identity_uuid' => 'id-1', 'attachment_id' => 10],
			],
		];

		$clusters_repo->expects( $this->once() )
			->method( 'list_top_unlabeled' )
			->with( $tenant_id, $limit )
			->willReturn( $clusters );
		$clusters_repo->expects( $this->once() )
			->method( 'count_top_unlabeled_singletons' )
			->with( $tenant_id )
			->willReturn( 2 );

		$members_repo->expects( $this->once() )
			->method( 'list_for_cluster_uuids' )
			->with( ['uuid-1'], IdentityMembersRepositoryInterface::PREVIEW_IDENTITIES_FETCH_LIMIT )
			->willReturn( $members );

		$result = $facade->list_top_unlabeled( $tenant_id, $limit );

		$this->assertSame( $clusters, $result['clusters'] );
		$this->assertSame( $members, $result['members'] );
		$this->assertSame( 2, $result['singleton_count'] );
	}

	public function test_list_top_unlabeled_returns_empty_when_no_clusters(): void {
		$clusters_repo = $this->createMock( ClustersRepositoryInterface::class );
		$members_repo  = $this->createMock( IdentityMembersRepositoryInterface::class );
		$facade        = new ClusterFacade( $clusters_repo, $members_repo );

		$clusters_repo->method( 'list_top_unlabeled' )->willReturn( [] );
		$clusters_repo->method( 'count_top_unlabeled_singletons' )->willReturn( 3 );
		$members_repo->expects( $this->never() )->method( 'list_for_cluster_uuids' );

		$result = $facade->list_top_unlabeled( 'tenant-123' );

		$this->assertEmpty( $result['clusters'] );
		$this->assertEmpty( $result['members'] );
		$this->assertSame( 3, $result['singleton_count'] );
	}
}
