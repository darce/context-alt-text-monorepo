<?php

declare(strict_types=1);

namespace ContextAltText\Infrastructure\Repositories;

use ContextAltText\Domain\Clustering\UnknownFace;

interface UnknownFaceRepositoryInterface
{
    /**
     * @return UnknownFace[]
     */
    public function findUnresolvedFaces(int $limit = 10000): array;

    /**
     * Retrieve cluster summaries with aggregated metadata and limited preview face IDs.
     *
     * @return array<int, array{cluster_id: string, face_count: int, created_at: string, updated_at: string, preview_face_ids: int[]}>
     */
    public function findClusterSummaries(int $limit, int $offset): array;

    /**
     * Retrieve a paginated subset of faces within a specific cluster.
     *
     * @return array{faces: UnknownFace[], total: int, page: int, per_page: int, has_more: bool}
     */
    public function findFacesPage(string $clusterId, int $page, int $perPage): array;

    /**
     * Count total number of unresolved clusters.
     */
    public function countUnresolvedClusters(): int;

    /**
     * Count total number of unresolved faces.
     */
    public function countUnresolvedFaces(): int;

    /**
     * @return UnknownFace[]
     */
    public function findFacesByCluster(string $clusterId): array;

    public function findFaceById(int $faceId): ?UnknownFace;

    /**
     * @param int[] $faceIds
     * @return UnknownFace[]
     */
    public function findFacesByIds(array $faceIds): array;

    public function markFaceAsResolved(int $faceId, string $rosterId): bool;

    /**
     * @param int[] $faceIds
     */
    public function updateClusterMembership(array $faceIds, string $targetClusterId, int $userId): int;

    public function softDeleteFace(int $faceId, int $userId): bool;

    public function clearAllUnresolvedFaces(int $userId): int;
}
