<?php

declare(strict_types=1);

namespace AltContext\Api\Services;

use AltContext\Sovereign\ClusterFacade;
use AltContext\Sovereign\Mappers\ClusterResponseMapper;
use AltContext\Sovereign\Mappers\MemberResponseMapper;
use AltContext\Sovereign\Repositories\ClustersRepositoryInterface;
use AltContext\Sovereign\Repositories\IdentityMembersRepositoryInterface;

/**
 * Collaborator bundle for ClusterReadService: the repositories, facade, and
 * mappers it reads through, the sibling read-path services, and the grouped
 * string configuration (ClusterReadConfig).
 */
final class ClusterReadDependencies {
	public ClustersRepositoryInterface $clusters_repository;
	public IdentityMembersRepositoryInterface $members_repository;
	public ClusterFacade $cluster_facade;
	public ClusterResponseMapper $cluster_mapper;
	public MemberResponseMapper $member_mapper;
	public ClusterProjectionSyncService $projection_sync_service;
	public ClusterResponseEnvelopeService $response_envelope_service;
	public ClusterReadConfig $config;

	public function __construct(
		ClustersRepositoryInterface $clusters_repository,
		IdentityMembersRepositoryInterface $members_repository,
		ClusterFacade $cluster_facade,
		ClusterResponseMapper $cluster_mapper,
		MemberResponseMapper $member_mapper,
		ClusterProjectionSyncService $projection_sync_service,
		ClusterResponseEnvelopeService $response_envelope_service,
		ClusterReadConfig $config
	) {
		$this->clusters_repository = $clusters_repository;
		$this->members_repository = $members_repository;
		$this->cluster_facade = $cluster_facade;
		$this->cluster_mapper = $cluster_mapper;
		$this->member_mapper = $member_mapper;
		$this->projection_sync_service = $projection_sync_service;
		$this->response_envelope_service = $response_envelope_service;
		$this->config = $config;
	}
}
