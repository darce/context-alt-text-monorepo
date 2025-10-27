<?php

declare(strict_types=1);

namespace ContextAltText\Domain\Clustering;

/**
 * Contract for services capable of grouping unknown faces into clusters.
 */
interface ClusteringEngine
{
    /**
     * @param array<int,int|string> $faceIds
     * @return array<string,mixed>
     */
    public function clusterUnknownFaces(array $faceIds = []): array;

    /**
     * @return array<string,mixed>
     */
    public function getClusterDetail(string $clusterId): array;

    /**
     * @return array<int,array<string,mixed>>
     */
    public function getClusterSuggestions(string $clusterId): array;

    /**
     * Confirm a roster assignment for selected faces within a cluster.
     *
     * @param array<int|string> $faceIds
     * @return array<string,mixed>
     */
    public function confirmCluster(string $clusterId, string $rosterId, array $faceIds): array;
}
