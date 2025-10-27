<?php

declare(strict_types=1);

namespace ContextAltText\Recognition;

use ContextAltText\Domain\Clustering\ClusteringEngine;
use ContextAltText\Security\Security;
use WP_Error;
use WP_REST_Request;
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

    public function __construct(
        Security $security,
        ClusteringEngine $clusteringService,
        FaceThumbnailProvider $thumbnailProvider
    ) {
        $this->security = $security;
        $this->clusteringService = $clusteringService;
        $this->thumbnailProvider = $thumbnailProvider;
    }

    /**
     * Handle GET /cat/v1/clusters.
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
        $perPage = max(1, min(50, (int) ($request->get_param('per_page') ?? 20)));

        $payload = $this->clusteringService->clusterUnknownFaces();

        error_log(sprintf('[ClusterController] Payload contains %d faces', count($payload['faces'] ?? [])));
        
        $clusters = $this->buildClusters($payload);
        
        error_log(sprintf('[ClusterController] Built %d clusters from payload', count($clusters)));
        
        $total = count($clusters);

        $offset = ($page - 1) * $perPage;
        $paged = array_slice($clusters, $offset, $perPage);
        
        error_log(sprintf('[ClusterController] Returning %d clusters (page %d, perPage %d, total %d)', count($paged), $page, $perPage, $total));

        return [
            'clusters' => array_values($paged),
            'total' => $total,
            'page' => $page,
            'per_page' => $perPage,
        ];
    }

    /**
     * @return array<string,mixed>|WP_Error
     */
    public function getClusterDetail(WP_REST_Request $request)
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

        $detail = $this->clusteringService->getClusterDetail($clusterId);

        $facesRaw = isset($detail['faces']) && is_array($detail['faces']) ? $detail['faces'] : [];
        $faces = [];

        foreach ($facesRaw as $face) {
            if (!is_array($face)) {
                continue;
            }

            $thumbnail = $this->thumbnailProvider->generateThumbnail($face);
            $face['thumbnail_url'] = $thumbnail;
            $faces[] = $face;
        }

        $cluster = isset($detail['cluster']) && is_array($detail['cluster'])
            ? $detail['cluster']
            : ['id' => $clusterId];

        $cluster['id'] = isset($cluster['id']) && is_string($cluster['id']) && trim($cluster['id']) !== ''
            ? $cluster['id']
            : $clusterId;

        $cluster['face_count'] = isset($cluster['face_count'])
            ? (int) $cluster['face_count']
            : count($faces);

        if (!isset($cluster['sample_face']) || !is_array($cluster['sample_face'])) {
            $sample = $faces[0] ?? null;
            $cluster['sample_face'] = $sample
                ? [
                    'attachment_id' => (int) ($sample['attachmentId'] ?? 0),
                    'thumbnail_url' => $sample['thumbnail_url'] ?? null,
                    'bbox' => $sample['bbox'] ?? null,
                ]
                : null;
        } elseif (!isset($cluster['sample_face']['thumbnail_url']) && isset($faces[0]['thumbnail_url'])) {
            $cluster['sample_face']['thumbnail_url'] = $faces[0]['thumbnail_url'];
        }

        $detail['cluster'] = $cluster;
        $detail['faces'] = $faces;

        return $detail;
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
}
