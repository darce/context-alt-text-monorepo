<?php

declare(strict_types=1);

namespace ContextAltText\Recognition;

use ContextAltText\Domain\Clustering\ClusteringEngine;
use ContextAltText\Infrastructure\Repositories\UnknownFaceRepository;
use ContextAltText\Infrastructure\Repositories\UnknownFaceRepositoryInterface;
use ContextAltText\Security\Security;
use WP_Error;
use WP_REST_Request;
use WP_REST_Response;
use function __;
use function array_slice;
use function array_values;
use function count;
use function is_array;
use function is_numeric;
use function is_string;
use function max;
use function strtotime;
use function uniqid;
use function usort;
use function trim;

/**
 * REST controller exposing clustered unknown faces for the workbench UI.
 */
final class ClusterController
{
    private Security $security;
    private ClusteringEngine $clusteringService;
    private FaceThumbnailProvider $thumbnailProvider;
    private UnknownFaceRepositoryInterface $repository;

    public function __construct(
        Security $security,
        ClusteringEngine $clusteringService,
        FaceThumbnailProvider $thumbnailProvider,
        UnknownFaceRepositoryInterface $repository
    ) {
        $this->security = $security;
        $this->clusteringService = $clusteringService;
        $this->thumbnailProvider = $thumbnailProvider;
        $this->repository = $repository;
    }

    /**
     * Handle GET /cat/v1/clusters.
     * Returns lightweight cluster summaries with up to 4 preview faces each.
     *
     * @return array<string,mixed>|WP_Error
     */
    public function listClusters(WP_REST_Request $request)
    {
        if (!$this->security->verifyCapability('upload_files')) {
            return new WP_Error(
                'rest_forbidden',
                __('You are not allowed to view face clusters.', 'context-alt-text'),
                ['status' => 403]
            );
        }

        $page = max(1, (int) ($request->get_param('page') ?? 1));
        $perPage = max(1, (int) ($request->get_param('per_page') ?? 50));

        $offset = ($page - 1) * $perPage;

        // Fetch lightweight cluster summaries from repository
        $summaries = $this->repository->findClusterSummaries($perPage, $offset);
        $total = $this->repository->countUnresolvedClusters();

        $clusters = [];

        foreach ($summaries as $summary) {
            $clusterId = $summary['cluster_id'];
            $previewFaceIds = $summary['preview_face_ids'];

            // Load preview faces (up to 4)
            $previewFaces = $this->repository->findFacesByIds($previewFaceIds);

            $serializedPreviewFaces = [];
            foreach ($previewFaces as $face) {
                $thumbnailUrl = $this->thumbnailProvider->generateThumbnail([
                    'id' => (string) $face->id(),
                    'attachmentId' => $face->attachmentId(),
                    'bbox' => $face->bbox(),
                    'thumbnail' => $face->thumbnail(),
                ]);

                // Exclude embedding_id from preview faces to reduce payload size
                $serializedPreviewFaces[] = [
                    'id' => $face->id(),
                    'attachment_id' => $face->attachmentId(),
                    'thumbnail_url' => $thumbnailUrl,
                    'bbox' => $face->bbox(),
                    'detected_at' => $face->detectedAt(),
                ];
            }

            $clusters[] = [
                'id' => $clusterId,
                'face_count' => $summary['face_count'],
                'preview_faces' => $serializedPreviewFaces,
                'created_at' => $summary['created_at'],
                'updated_at' => $summary['updated_at'],
            ];
        }

        return [
            'clusters' => $clusters,
            'total' => $total,
            'page' => $page,
            'per_page' => $perPage,
        ];
    }

    /**
     * Handle GET /cat/v1/clusters/{id} - returns paginated faces for a cluster.
     * Includes full face data including embedding_id for detail view.
     *
     * @return array<string,mixed>|WP_Error
     */
    public function getClusterDetailPage(WP_REST_Request $request)
    {
        if (!$this->security->verifyCapability('upload_files')) {
            return new WP_Error(
                'rest_forbidden',
                __('You are not allowed to view face clusters.', 'context-alt-text'),
                ['status' => 403]
            );
        }

        $clusterId = trim((string) $request->get_param('id'));
        $page = max(1, (int) ($request->get_param('page') ?? 1));
        $perPage = max(1, (int) ($request->get_param('per_page') ?? 20));

        if ($clusterId === '') {
            return new WP_Error(
                'invalid_request',
                __('Cluster identifier is required.', 'context-alt-text'),
                ['status' => 400]
            );
        }

        // Fetch paginated faces for this cluster
        $result = $this->repository->findFacesPage($clusterId, $page, $perPage);

        $serializedFaces = [];
        foreach ($result['faces'] as $face) {
            $thumbnailUrl = $this->thumbnailProvider->generateThumbnail([
                'id' => (string) $face->id(),
                'attachmentId' => $face->attachmentId(),
                'bbox' => $face->bbox(),
                'thumbnail' => $face->thumbnail(),
            ]);

            // Include embedding_id for detail view (may be needed for operations)
            $serializedFaces[] = [
                'id' => $face->id(),
                'attachment_id' => $face->attachmentId(),
                'embedding_id' => $face->embeddingId(),
                'thumbnail_url' => $thumbnailUrl,
                'bbox' => $face->bbox(),
                'detected_at' => $face->detectedAt(),
                'cluster_id' => $face->clusterId(),
            ];
        }

        $totalPages = (int) ceil($result['total'] / $result['per_page']);
        $hasMore = $result['page'] < $totalPages;

        return [
            'cluster_id' => $clusterId,
            'faces' => $serializedFaces,
            'pagination' => [
                'current_page' => $result['page'],
                'per_page' => $result['per_page'],
                'total_pages' => $totalPages,
                'total_faces' => $result['total'],
                'has_more' => $hasMore,
            ],
        ];
    }

    /**
     * @return array<string,mixed>|WP_Error
     */
    public function getClusterSuggestions(WP_REST_Request $request)
    {
        if (!$this->security->verifyCapability('upload_files')) {
            return new WP_Error(
                'rest_forbidden',
                __('You are not allowed to view face clusters.', 'context-alt-text'),
                ['status' => 403]
            );
        }

        $clusterId = (string) $request->get_param('id');

        if (trim($clusterId) === '') {
            return new WP_Error(
                'invalid_request',
                __('Cluster identifier is required.', 'context-alt-text'),
                ['status' => 400]
            );
        }

        $suggestions = $this->clusteringService->getClusterSuggestions($clusterId);

        return [
            'cluster_id' => $clusterId,
            'suggestions' => $suggestions,
        ];
    }

    /**
     * @return array<string,mixed>|WP_Error
     */
    public function confirmCluster(WP_REST_Request $request)
    {
        if (!$this->security->verifyCapability('upload_files')) {
            return new WP_Error(
                'rest_forbidden',
                __('You are not allowed to confirm face clusters.', 'context-alt-text'),
                ['status' => 403]
            );
        }

        $clusterId = trim((string) $request->get_param('id'));
        $payload = method_exists($request, 'get_json_params') ? $request->get_json_params() : null;
        $rosterParam = null;
        $faceIds = [];

        if (is_array($payload)) {
            if (isset($payload['roster_id']) && (is_string($payload['roster_id']) || is_numeric($payload['roster_id']))) {
                $rosterParam = (string) $payload['roster_id'];
            }

            if (isset($payload['face_ids']) && is_array($payload['face_ids'])) {
                $faceIds = $payload['face_ids'];
            }
        }

        if ($rosterParam === null) {
            $fallbackRoster = $request->get_param('roster_id');
            if (is_string($fallbackRoster) || is_numeric($fallbackRoster)) {
                $rosterParam = (string) $fallbackRoster;
            }
        }

        if ($faceIds === []) {
            $fallbackFaceIds = $request->get_param('face_ids');
            if (is_array($fallbackFaceIds)) {
                $faceIds = $fallbackFaceIds;
            } elseif ($fallbackFaceIds !== null) {
                $faceIds = [(string) $fallbackFaceIds];
            }
        }

        $rosterId = $rosterParam !== null ? trim($rosterParam) : '';

        if ($clusterId === '' || $rosterId === '' || $faceIds === []) {
            return new WP_Error(
                'invalid_request',
                __('Cluster, roster, and face selection are required.', 'context-alt-text'),
                ['status' => 400]
            );
        }

        $result = $this->clusteringService->confirmCluster($clusterId, $rosterId, $faceIds);

        $labeledCount = isset($result['labeled_count']) ? (int) $result['labeled_count'] : 0;
        $errors = isset($result['errors']) && is_array($result['errors']) ? $result['errors'] : [];

        if ($labeledCount === 0 && $errors !== []) {
            $message = is_string($errors[0] ?? null)
                ? $errors[0]
                : __('Cluster confirmation failed.', 'context-alt-text');

            return new WP_Error(
                'cluster_confirmation_failed',
                $message,
                [
                    'status' => 400,
                    'details' => $result,
                ]
            );
        }

        return $result;
    }

    /**
     * @param array<string,mixed> $payload
     * @return array<int,array<string,mixed>>
     */
    private function buildClusters(array $payload): array
    {
        $facesRaw = isset($payload['faces']) && is_array($payload['faces']) ? $payload['faces'] : [];

        error_log(sprintf('[ClusterController::buildClusters] Processing %d faces', count($facesRaw)));

        $facesById = [];
        foreach ($facesRaw as $face) {
            $id = isset($face['databaseId']) && is_numeric($face['databaseId'])
                ? (int) $face['databaseId']
                : null;

            if ($id !== null) {
                $facesById[$id] = $face;
            }
        }

        $clustersRaw = isset($payload['clusters']) && is_array($payload['clusters'])
            ? $payload['clusters']
            : [];

        error_log(sprintf('[ClusterController::buildClusters] Found %d pre-defined clusters', count($clustersRaw)));

        $clusters = [];

        if ($clustersRaw !== []) {
            foreach ($clustersRaw as $cluster) {
                if (!is_array($cluster)) {
                    continue;
                }

                $clusterId = isset($cluster['id'])
                    ? (string) $cluster['id']
                    : (isset($cluster['cluster_id']) ? (string) $cluster['cluster_id'] : '');

                if ($clusterId === '') {
                    continue;
                }

                $faceIds = isset($cluster['faceIds']) && is_array($cluster['faceIds'])
                    ? $cluster['faceIds']
                    : (isset($cluster['face_ids']) && is_array($cluster['face_ids']) ? $cluster['face_ids'] : []);

                $faces = [];

                foreach ($faceIds as $faceId) {
                    $databaseId = is_numeric($faceId) ? (int) $faceId : null;

                    if ($databaseId !== null && isset($facesById[$databaseId])) {
                        $faces[] = $facesById[$databaseId];
                    } else {
                        $fallback = $this->findFaceByRemoteId($facesRaw, (string) $faceId);
                        if ($fallback !== null) {
                            $faces[] = $fallback;
                        }
                    }
                }

                if ($faces === []) {
                    continue;
                }

                $clusters[] = $this->serialiseCluster($clusterId, $faces);
            }
        } else {
            error_log('[ClusterController::buildClusters] No pre-defined clusters, grouping faces by clusterId');
            
            $groups = [];

            foreach ($facesRaw as $face) {
                $clusterId = isset($face['clusterId']) && is_string($face['clusterId']) && $face['clusterId'] !== ''
                    ? (string) $face['clusterId']
                    : (string) ($face['id'] ?? uniqid('face-', true));

                $groups[$clusterId][] = $face;
            }

            error_log(sprintf('[ClusterController::buildClusters] Grouped into %d clusters', count($groups)));

            foreach ($groups as $clusterId => $faces) {
                $clusters[] = $this->serialiseCluster((string) $clusterId, $faces);
            }
        }

        error_log(sprintf('[ClusterController::buildClusters] Returning %d total clusters', count($clusters)));

        return $clusters;
    }

    /**
     * @param array<int,array<string,mixed>> $faces
     * @return array<string,mixed>
     */
    private function serialiseCluster(string $clusterId, array $faces): array
    {
        usort($faces, static function (array $a, array $b): int {
            $aDetected = isset($a['detectedAt']) ? strtotime((string) $a['detectedAt']) : 0;
            $bDetected = isset($b['detectedAt']) ? strtotime((string) $b['detectedAt']) : 0;

            return $aDetected <=> $bDetected;
        });

        $faceCount = count($faces);
        $firstFace = $faces[0];
        $lastFace = $faces[$faceCount - 1] ?? $firstFace;

        $thumbnailUrl = $this->thumbnailProvider->generateThumbnail($firstFace);

        return [
            'id' => $clusterId,
            'face_count' => $faceCount,
            'sample_face' => [
                'attachment_id' => (int) ($firstFace['attachmentId'] ?? 0),
                'thumbnail_url' => $thumbnailUrl,
                'bbox' => $firstFace['bbox'] ?? null,
            ],
            'suggestion' => $firstFace['suggestion'] ?? null,
            'created_at' => $firstFace['detectedAt'] ?? null,
            'updated_at' => $lastFace['detectedAt'] ?? $firstFace['detectedAt'] ?? null,
        ];
    }

    /**
     * @param array<int,array<string,mixed>> $faces
     */
    private function findFaceByRemoteId(array $faces, string $remoteId): ?array
    {
        foreach ($faces as $face) {
            if (isset($face['id']) && (string) $face['id'] === $remoteId) {
                return $face;
            }
        }

        return null;
    }

    /**
     * Handle POST /cat/v1/unknown-clusters/move
     * Move faces from one cluster to another (before confirmation).
     *
     * @return array<string,mixed>|WP_Error
     */
    public function moveFaces(WP_REST_Request $request)
    {
        if (!$this->security->verifyCapability('manage_options')) {
            return new WP_Error(
                'rest_forbidden',
                __('You are not allowed to move faces between clusters.', 'context-alt-text'),
                ['status' => 403]
            );
        }

        // Get parameters from JSON body
        $payload = $request->get_json_params();
        
        if (!is_array($payload)) {
            return new WP_Error(
                'invalid_request',
                __('Request body must be JSON.', 'context-alt-text'),
                ['status' => 400]
            );
        }

        $faceIds = isset($payload['face_ids']) && is_array($payload['face_ids']) ? $payload['face_ids'] : [];
        $sourceClusterId = isset($payload['source_cluster_id']) ? (string) $payload['source_cluster_id'] : '';
        $targetClusterId = isset($payload['target_cluster_id']) ? (string) $payload['target_cluster_id'] : '';

        // Validate input
        if ($faceIds === [] || $sourceClusterId === '' || $targetClusterId === '') {
            return new WP_Error(
                'invalid_request',
                __('face_ids, source_cluster_id, and target_cluster_id are required.', 'context-alt-text'),
                ['status' => 400]
            );
        }

        // Convert face IDs to integers
        $faceIds = array_map('intval', $faceIds);
        $faceIds = array_filter($faceIds, fn($id) => $id > 0);

        if ($faceIds === []) {
            return new WP_Error(
                'invalid_request',
                __('Valid face_ids are required.', 'context-alt-text'),
                ['status' => 400]
            );
        }

        // Load faces from database
        $faces = $this->repository->findFacesByIds($faceIds);

        if ($faces === []) {
            return new WP_Error(
                'not_found',
                __('No faces found with provided IDs.', 'context-alt-text'),
                ['status' => 404]
            );
        }

        // Verify all faces belong to source cluster and are unresolved
        foreach ($faces as $face) {
            if ($face->clusterId() !== $sourceClusterId) {
                return new WP_Error(
                    'invalid_request',
                    sprintf(
                        __('Face %d does not belong to cluster %s.', 'context-alt-text'),
                        $face->id(),
                        $sourceClusterId
                    ),
                    ['status' => 400]
                );
            }

            if ($face->resolvedAt() !== null) {
                return new WP_Error(
                    'invalid_request',
                    sprintf(
                        __('Face %d is already resolved.', 'context-alt-text'),
                        $face->id()
                    ),
                    ['status' => 400]
                );
            }
        }

        // Update cluster_id for each face
        $updatedCount = $this->repository->updateClusterMembership(
            $faceIds,
            $targetClusterId,
            (int) get_current_user_id()
        );

        // Return success
        return new WP_REST_Response([
            'success' => true,
            'moved_count' => $updatedCount,
            'source_cluster_id' => $sourceClusterId,
            'target_cluster_id' => $targetClusterId,
        ], 200);
    }

    /**
     * Handle DELETE /cat/v1/unknown-faces/:id
     * Soft delete a face (dismiss as irrelevant).
     *
     * @return array<string,mixed>|WP_Error
     */
    public function deleteFace(WP_REST_Request $request)
    {
        if (!$this->security->verifyCapability('manage_options')) {
            return new WP_Error(
                'rest_forbidden',
                __('You are not allowed to delete faces.', 'context-alt-text'),
                ['status' => 403]
            );
        }

        $faceId = (int) $request->get_param('id');

        if ($faceId <= 0) {
            return new WP_Error(
                'invalid_request',
                __('Valid face ID is required.', 'context-alt-text'),
                ['status' => 400]
            );
        }

        // Load face to verify it exists and is unresolved
        $face = $this->repository->findFaceById($faceId);

        if ($face === null) {
            return new WP_Error(
                'not_found',
                __('Face not found.', 'context-alt-text'),
                ['status' => 404]
            );
        }

        if ($face->resolvedAt() !== null) {
            return new WP_Error(
                'invalid_request',
                __('Cannot delete resolved face.', 'context-alt-text'),
                ['status' => 400]
            );
        }

        // Soft delete: mark as resolved with special roster_id
        $deleted = $this->repository->softDeleteFace(
            $faceId,
            (int) get_current_user_id()
        );

        if (!$deleted) {
            return new WP_Error(
                'deletion_failed',
                __('Failed to delete face.', 'context-alt-text'),
                ['status' => 500]
            );
        }

        // Log deletion
        error_log(sprintf(
            '[ClusterController] User %d deleted face %d (attachment %d, cluster %s)',
            get_current_user_id(),
            $faceId,
            $face->attachmentId(),
            $face->clusterId()
        ));

        return new WP_REST_Response([
            'success' => true,
            'face_id' => $faceId,
            'cluster_id' => $face->clusterId(),
        ], 200);
    }

    /**
     * Handle POST /cat/v1/unknown-clusters/clear-all
     * Bulk clear all remaining unresolved faces.
     *
     * @return array<string,mixed>|WP_Error
     */
    public function clearAllFaces(WP_REST_Request $request)
    {
        if (!$this->security->verifyCapability('manage_options')) {
            return new WP_Error(
                'rest_forbidden',
                __('You are not allowed to clear faces.', 'context-alt-text'),
                ['status' => 403]
            );
        }

        // Get count of faces to clear
        $count = $this->repository->countUnresolvedFaces();

        if ($count === 0) {
            return new WP_REST_Response([
                'message' => __('No unknown faces to clear.', 'context-alt-text'),
                'cleared_count' => 0,
            ], 200);
        }

        // Bulk update: mark all as cleared
        $clearedCount = $this->repository->clearAllUnresolvedFaces(
            (int) get_current_user_id()
        );

        // Log the action
        error_log(sprintf(
            '[ClusterController] User %d cleared all %d unknown faces',
            get_current_user_id(),
            $clearedCount
        ));

        return new WP_REST_Response([
            'success' => true,
            'cleared_count' => $clearedCount,
        ], 200);
    }
}
