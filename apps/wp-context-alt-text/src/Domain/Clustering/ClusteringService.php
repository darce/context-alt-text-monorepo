<?php

declare(strict_types=1);

namespace ContextAltText\Domain\Clustering;

use ContextAltText\Infrastructure\Repositories\UnknownFaceRepository;
use ContextAltText\Recognition\ClusterClient;
use ContextAltText\Recognition\RecognitionClient;
use ContextAltText\Recognition\RecognitionClientException;
use ContextAltText\Domain\Roster\RosterService;
use ContextAltText\Roster\RosterClientException;
use DateTimeInterface;
use Throwable;

use function array_column;
use function array_filter;
use function array_sum;
use function array_unique;
use function array_values;
use function count;
use function function_exists;
use function ctype_digit;
use function is_wp_error;
use function is_array;
use function is_numeric;
use function is_string;
use function max;
use function round;
use function sort;
use function spl_object_id;
use function sprintf;
use function strpos;
use function substr;
use function trim;
use function usort;
use function wp_get_attachment_metadata;

/**
 * Coordinates clustering of unresolved faces, routing to local or remote strategies.
 */
final class ClusteringService implements ClusteringEngine
{
    private const LOCAL_CLUSTER_THRESHOLD = 1000;  // Temporarily increased to use local clustering until remote endpoint is implemented
    private const FETCH_LIMIT = 200;
    private const REMOTE_MIN_CLUSTER_SIZE = 2;
    private const REMOTE_SIMILARITY_THRESHOLD = 0.92;
    private const SUGGESTION_TOP_K = 5;
    private const SUGGESTION_THRESHOLD = 0.75;
    private const SUGGESTION_MIN_SCORE = 0.75;
    private const CASCADE_BASE_THRESHOLD = 0.85;
    private const CASCADE_AUTO_THRESHOLD = 0.9;

    private UnknownFaceRepository $repository;
    private ClusterClient $clusterClient;
    private RecognitionClient $recognitionClient;
    private RosterService $rosterService;
    /** @var array<int,array{width:?int,height:?int}> */
    private array $dimensionsCache = [];

    public function __construct(
        UnknownFaceRepository $repository,
        ClusterClient $clusterClient,
        RecognitionClient $recognitionClient,
        RosterService $rosterService
    )
    {
        $this->repository = $repository;
        $this->clusterClient = $clusterClient;
        $this->recognitionClient = $recognitionClient;
        $this->rosterService = $rosterService;
    }

    /**
     * Cluster unresolved faces, delegating to MediaPipe (local) or recognition service (remote).
     *
     * @param array<int,int|string> $faceIds Optional subset of face IDs to evaluate.
     * @return array<string,mixed>
     */
    public function clusterUnknownFaces(array $faceIds = []): array
    {
        $faces = $this->loadFaces($faceIds);

        error_log(sprintf('[ClusteringService] Loaded %d faces', count($faces)));

        if ($faces === []) {
            error_log('[ClusteringService] No faces found, returning empty local response');
            return $this->buildLocalResponse($faces);
        }

        if (count($faces) <= self::LOCAL_CLUSTER_THRESHOLD) {
            return $this->buildLocalResponse($faces);
        }

        try {
            $payload = $this->buildRemotePayload($faces);

            if ($payload['embeddings'] === []) {
                return $this->buildLocalResponse($faces);
            }

            $response = $this->clusterClient->requestClustering($payload);

            return $this->buildRemoteResponse($response, $faces);
        } catch (Throwable $exception) {
            return $this->buildLocalResponse($faces, $exception);
        }
    }

    public function getClusterDetail(string $clusterId): array
    {
        $faces = $this->repository->findFacesByCluster($clusterId);

        if ($faces === []) {
            return [
                'cluster' => [
                    'id' => $clusterId,
                    'face_count' => 0,
                    'created_at' => null,
                    'updated_at' => null,
                    'sample_face' => null,
                    'suggestion' => null,
                ],
                'faces' => [],
            ];
        }

        $serializedFaces = $this->serializeFaces($faces);

        $earliest = $faces[0]->detectedAt();
        $latest = $faces[0]->detectedAt();

        foreach ($faces as $face) {
            $detectedAt = $face->detectedAt();
            if ($detectedAt->getTimestamp() < $earliest->getTimestamp()) {
                $earliest = $detectedAt;
            }

            if ($detectedAt->getTimestamp() > $latest->getTimestamp()) {
                $latest = $detectedAt;
            }
        }

        $sample = $serializedFaces[0];

        return [
            'cluster' => [
                'id' => $clusterId,
                'face_count' => count($serializedFaces),
                'created_at' => $this->formatDate($earliest),
                'updated_at' => $this->formatDate($latest),
                'sample_face' => [
                    'attachment_id' => (int) ($sample['attachmentId'] ?? 0),
                    'thumbnail_url' => $sample['thumbnail_url'] ?? null,
                    'bbox' => $sample['bbox'] ?? null,
                ],
                'suggestion' => null,
            ],
            'faces' => $serializedFaces,
        ];
    }

    /**
     * @return array<int,array<string,mixed>>
     */
    public function getClusterSuggestions(string $clusterId): array
    {
        $faces = $this->repository->findFacesByCluster($clusterId);

        if ($faces === []) {
            return [];
        }

        $embeddingData = $this->embedFacesForCluster($faces);
        $vectors = $embeddingData['vectors'];
        $mappings = $embeddingData['mappings'];

        if ($vectors === [] || $mappings === []) {
            return [];
        }

        try {
            $response = $this->recognitionClient->suggestMatches(
                $vectors,
                self::SUGGESTION_TOP_K,
                self::SUGGESTION_THRESHOLD
            );
        } catch (RecognitionClientException $exception) {
            return [];
        }

        $rawSuggestions = isset($response['suggestions']) && is_array($response['suggestions'])
            ? $response['suggestions']
            : [];

        if ($rawSuggestions === []) {
            return [];
        }

        return $this->aggregateSuggestions($clusterId, $rawSuggestions, $mappings);
    }

    /**
     * @param array<int|string> $faceIds
     * @return array<string,mixed>
     */
    public function confirmCluster(string $clusterId, string $rosterId, array $faceIds): array
    {
        $cluster = trim($clusterId);
        $roster = trim($rosterId);

        $response = [
            'cluster_id' => $cluster,
            'roster_id' => $roster,
            'confirmed' => [],
            'warnings' => [],
            'errors' => [],
            'cascade' => [
                'auto' => [],
                'candidates' => [],
            ],
        ];

        $selectedIds = $this->normaliseFaceSelection($faceIds);

        if ($cluster === '' || $roster === '' || $selectedIds === []) {
            $response['errors'][] = 'Cluster, roster, and face selection are required.';

            return $response;
        }

        $faces = $this->repository->findFacesByIds($selectedIds);

        if ($faces === []) {
            $response['errors'][] = 'No unresolved faces matched the supplied identifiers.';

            return $response;
        }

        $facesById = [];
        foreach ($faces as $face) {
            $databaseId = $face->id();
            if ($databaseId === null) {
                continue;
            }

            $faceCluster = $face->clusterId() ?? '';
            if ($faceCluster !== $cluster) {
                $response['warnings'][] = sprintf(
                    'Face %d does not belong to cluster %s and was skipped.',
                    $databaseId,
                    $cluster
                );
                continue;
            }

            $facesById[$databaseId] = $face;
        }

        if ($facesById === []) {
            $response['errors'][] = 'None of the selected faces belong to this cluster.';

            return $response;
        }

        $suggestionsSnapshot = $this->getClusterSuggestions($cluster);
        $embeddings = $this->embedFaceVectors(array_values($facesById));

        foreach ($facesById as $databaseId => $face) {
            $vector = $embeddings[$databaseId] ?? [];

            if ($vector === []) {
                $response['warnings'][] = sprintf(
                    'Unable to generate embedding for face %d; confirmation skipped.',
                    $databaseId
                );
                continue;
            }

            try {
                $observationId = $this->rosterService->createObservation(
                    $face->attachmentId(),
                    $vector,
                    $roster,
                    $face->bbox()
                );
            } catch (RosterClientException $exception) {
                $response['warnings'][] = sprintf(
                    'Failed to create observation for face %d: %s',
                    $databaseId,
                    $exception->getMessage()
                );
                continue;
            } catch (Throwable $exception) {
                $response['warnings'][] = sprintf(
                    'Unexpected error creating observation for face %d: %s',
                    $databaseId,
                    $exception->getMessage()
                );
                continue;
            }

            try {
                $syncResult = $this->recognitionClient->addRosterEmbedding(
                    $roster,
                    (string) $observationId,
                    $vector,
                    [
                        'attachmentId' => $face->attachmentId(),
                        'bbox' => $face->bbox(),
                        'source' => 'assisted-face-id',
                    ]
                );

                if (function_exists('is_wp_error') && is_wp_error($syncResult)) {
                    $response['warnings'][] = sprintf(
                        'Embedding sync skipped for face %d: %s',
                        $databaseId,
                        $syncResult->get_error_message()
                    );
                }
            } catch (RecognitionClientException $exception) {
                $response['warnings'][] = sprintf(
                    'Failed to sync embedding for face %d: %s',
                    $databaseId,
                    $exception->getMessage()
                );
            }

            $this->repository->markFaceAsResolved($databaseId, $roster);

            $response['confirmed'][] = [
                'face_id' => $this->remoteFaceId($face),
                'database_id' => $databaseId,
                'observation_id' => $observationId,
            ];
        }

        $response['labeled_count'] = count($response['confirmed']);

        $confirmedIds = array_column($response['confirmed'], 'database_id');
        $response['cascade'] = $this->buildCascadeFromSuggestions(
            $suggestionsSnapshot,
            $roster,
            $confirmedIds
        );

        return $response;
    }

    /**
     * @param array<int,array<string,mixed>> $suggestions
     * @param array<int,int> $confirmedDatabaseIds
     * @return array{auto: array<int,array<string,mixed>>, candidates: array<int,array<string,mixed>>}
     */
    private function buildCascadeFromSuggestions(array $suggestions, string $rosterId, array $confirmedDatabaseIds): array
    {
        $confirmedLookup = [];

        foreach ($confirmedDatabaseIds as $id) {
            $confirmedLookup[(int) $id] = true;
        }

        $auto = [];
        $candidates = [];

        foreach ($suggestions as $suggestion) {
            if (!is_array($suggestion)) {
                continue;
            }

            $suggestedRoster = $suggestion['roster_id'] ?? ($suggestion['rosterId'] ?? null);
            if (!is_string($suggestedRoster) || trim($suggestedRoster) === '' || $suggestedRoster !== $rosterId) {
                continue;
            }

            $confidence = isset($suggestion['confidence']) && is_numeric($suggestion['confidence'])
                ? (float) $suggestion['confidence']
                : 0.0;

            $faceIds = [];
            if (isset($suggestion['face_ids']) && is_array($suggestion['face_ids'])) {
                $faceIds = $suggestion['face_ids'];
            } elseif (isset($suggestion['faceIds']) && is_array($suggestion['faceIds'])) {
                $faceIds = $suggestion['faceIds'];
            }

            foreach ($faceIds as $remoteId) {
                if (!is_string($remoteId)) {
                    continue;
                }

                $databaseId = $this->databaseIdFromRemoteId($remoteId);
                if ($databaseId === null || isset($confirmedLookup[$databaseId])) {
                    continue;
                }

                $entry = [
                    'face_id' => $remoteId,
                    'database_id' => $databaseId,
                    'confidence' => round($confidence, 4),
                ];

                if ($confidence >= self::CASCADE_AUTO_THRESHOLD) {
                    $auto[] = $entry;
                } elseif ($confidence >= self::CASCADE_BASE_THRESHOLD) {
                    $candidates[] = $entry;
                }
            }
        }

        return [
            'auto' => $auto,
            'candidates' => $candidates,
        ];
    }

    /**
     * @param UnknownFace[] $faces
     * @return array<int,array<float>>
     */
    private function embedFaceVectors(array $faces): array
    {
        if ($faces === []) {
            return [];
        }

        $vectors = [];
        $grouped = [];

        foreach ($faces as $face) {
            $databaseId = $face->id();
            if ($databaseId === null) {
                continue;
            }

            $grouped[$face->attachmentId()][] = [
                'id' => $databaseId,
                'face' => $face,
            ];
        }

        foreach ($grouped as $attachmentId => $items) {
            $payload = [];

            foreach ($items as $index => $item) {
                $payload[] = [
                    'bbox' => $item['face']->bbox(),
                    'index' => $index,
                ];
            }

            if ($payload === []) {
                continue;
            }

            try {
                $response = $this->recognitionClient->embedFaces((int) $attachmentId, $payload);
            } catch (RecognitionClientException $exception) {
                continue;
            }

            $embeddings = isset($response['embeddings']) && is_array($response['embeddings'])
                ? $response['embeddings']
                : [];

            if ($embeddings === []) {
                continue;
            }

            foreach ($embeddings as $position => $vector) {
                if (!is_array($vector)) {
                    continue;
                }

                $item = $items[$position] ?? null;
                if (!is_array($item) || !isset($item['id'])) {
                    continue;
                }

                $normalized = $this->normaliseEmbeddingVector($vector);
                if ($normalized === []) {
                    continue;
                }

                $vectors[(int) $item['id']] = $normalized;
            }
        }

        return $vectors;
    }

    /**
     * @param array<int|string> $faceIds
     * @return array<int,int>
     */
    private function normaliseFaceSelection(array $faceIds): array
    {
        $normalized = [];

        foreach ($faceIds as $faceId) {
            $resolvedId = null;

            if (is_numeric($faceId)) {
                $resolvedId = (int) $faceId;
            } elseif (is_string($faceId)) {
                $resolvedId = $this->databaseIdFromRemoteId($faceId);
            }

            if ($resolvedId !== null && $resolvedId > 0) {
                $normalized[$resolvedId] = $resolvedId;
            }
        }

        $ids = array_values($normalized);
        sort($ids);

        return $ids;
    }

    private function databaseIdFromRemoteId(string $remoteId): ?int
    {
        $trimmed = trim($remoteId);

        if ($trimmed === '') {
            return null;
        }

        $numeric = $trimmed;

        if (strpos($trimmed, 'face-') === 0) {
            $numeric = substr($trimmed, 5);
        }

        if ($numeric === '' || !ctype_digit($numeric)) {
            return null;
        }

        $id = (int) $numeric;

        return $id > 0 ? $id : null;
    }

    /**
     * @param array<int,int|string> $faceIds
     * @return UnknownFace[]
     */
    private function loadFaces(array $faceIds): array
    {
        $limit = $faceIds === [] ? self::FETCH_LIMIT : max(self::FETCH_LIMIT, count($faceIds));
        $faces = $this->repository->findUnresolvedFaces($limit);

        if ($faceIds === []) {
            return $faces;
        }

        $idLookup = [];
        foreach ($faceIds as $faceId) {
            $id = (int) $faceId;
            if ($id > 0) {
                $idLookup[$id] = true;
            }
        }

        if ($idLookup === []) {
            return [];
        }

        return array_values(
            array_filter(
                $faces,
                static fn(UnknownFace $face): bool => $face->id() !== null && isset($idLookup[$face->id()])
            )
        );
    }

    /**
     * @param UnknownFace[] $faces
     */
    private function buildLocalResponse(array $faces, ?Throwable $error = null): array
    {
        // Perform local clustering using embeddings
        $embeddings = [];
        $facesByIndex = [];
        $index = 0;
        
        $assignedClusters = [];

        foreach ($faces as $face) {
            $vector = $this->resolveEmbeddingVector($face);
            if ($vector !== []) {
                $embeddings[$index] = $vector;
                $facesByIndex[$index] = $face;
                $index++;
            }
        }
        
        // If we have embeddings, perform clustering
        if ($embeddings !== []) {
            $clusterAssignments = $this->clusterEmbeddingsLocally($embeddings, 0.45); // Using 0.45 similarity threshold
            
            // Update cluster assignments in database
            foreach ($clusterAssignments as $idx => $clusterId) {
                $face = $facesByIndex[$idx];
                $faceId = $face->id();
                if ($faceId !== null) {
                    $this->repository->updateClusterAssignment($faceId, $clusterId);
                    $assignedClusters[$faceId] = $clusterId;
                }
            }
        }
        
        $payload = [
            'strategy' => 'local',
            'faces' => $this->serializeFaces($faces, $assignedClusters),
        ];

        if ($error !== null) {
            $payload['error'] = $error->getMessage();
        }

        return $payload;
    }
    
    /**
     * Cluster embeddings locally using single-linkage clustering.
     *
     * @param array<int,array<float>> $embeddings
     * @param float $threshold Similarity threshold to merge clusters
     * @return array<int,string> Cluster ID for each embedding index
     */
    private function clusterEmbeddingsLocally(array $embeddings, float $threshold): array
    {
        $count = count($embeddings);
        
        if ($count === 0) {
            return [];
        }
        
        // Normalize all embeddings
        $normalized = [];
        foreach ($embeddings as $idx => $embedding) {
            $normalized[$idx] = $this->normalizeVector($embedding);
        }
        
        // Build similarity matrix
        $similarity = array_fill(0, $count, array_fill(0, $count, 0.0));
        
        $indices = array_keys($embeddings);
        for ($i = 0; $i < $count; $i++) {
            for ($j = $i + 1; $j < $count; $j++) {
                $idxA = $indices[$i];
                $idxB = $indices[$j];
                $score = $this->cosineSimilarity($normalized[$idxA], $normalized[$idxB]);
                $similarity[$i][$j] = $score;
                $similarity[$j][$i] = $score;
            }
        }
        
        // Start with each embedding as its own cluster
        $clusters = [];
        for ($i = 0; $i < $count; $i++) {
            $clusters[] = [$i];
        }
        
        // Merge clusters using single-linkage
        $merged = true;
        while ($merged) {
            $merged = false;
            $maxSimilarity = -1.0;
            $mergeA = -1;
            $mergeB = -1;
            
            $clusterCount = count($clusters);
            for ($i = 0; $i < $clusterCount; $i++) {
                for ($j = $i + 1; $j < $clusterCount; $j++) {
                    $clusterSimilarity = -1.0;
                    foreach ($clusters[$i] as $faceIdxA) {
                        foreach ($clusters[$j] as $faceIdxB) {
                            $clusterSimilarity = max(
                                $clusterSimilarity,
                                $similarity[$faceIdxA][$faceIdxB] ?? 0.0
                            );
                        }
                    }
                    
                    if ($clusterSimilarity >= $threshold && $clusterSimilarity > $maxSimilarity) {
                        $maxSimilarity = $clusterSimilarity;
                        $mergeA = $i;
                        $mergeB = $j;
                    }
                }
            }
            
            if ($mergeA >= 0 && $mergeB >= 0) {
                $clusters[$mergeA] = array_merge($clusters[$mergeA], $clusters[$mergeB]);
                array_splice($clusters, $mergeB, 1);
                $merged = true;
            }
        }
        
        // Assign cluster IDs
        $clusterIds = [];
        foreach ($clusters as $clusterIndex => $clusterIndices) {
            sort($clusterIndices);
            $clusterId = sprintf('local-cluster-%03d', $clusterIndex + 1);
            
            foreach ($clusterIndices as $faceIndex) {
                $originalIdx = $indices[$faceIndex];
                $clusterIds[$originalIdx] = $clusterId;
            }
        }
        
        // Ensure every embedding has a cluster ID
        foreach ($embeddings as $idx => $embedding) {
            if (!isset($clusterIds[$idx])) {
                $clusterIds[$idx] = sprintf('local-cluster-single-%d', $idx);
            }
        }
        
        return $clusterIds;
    }
    
    /**
     * Normalize a vector to unit length.
     *
     * @param array<float> $vector
     * @return array<float>
     */
    private function normalizeVector(array $vector): array
    {
        $magnitude = 0.0;
        foreach ($vector as $val) {
            $magnitude += $val * $val;
        }
        $magnitude = sqrt($magnitude);
        
        if ($magnitude < 1e-10) {
            return $vector;
        }
        
        $normalized = [];
        foreach ($vector as $val) {
            $normalized[] = $val / $magnitude;
        }
        
        return $normalized;
    }
    
    /**
     * Compute cosine similarity between two normalized vectors.
     *
     * @param array<float> $a
     * @param array<float> $b
     * @return float
     */
    private function cosineSimilarity(array $a, array $b): float
    {
        $dotProduct = 0.0;
        $count = min(count($a), count($b));
        
        for ($i = 0; $i < $count; $i++) {
            $dotProduct += $a[$i] * $b[$i];
        }
        
        return $dotProduct;
    }

    /**
     * @param UnknownFace[] $faces
     * @return array<string,mixed>
     */
    private function buildRemotePayload(array $faces): array
    {
        $embeddings = [];

        foreach ($faces as $face) {
            $vector = $this->resolveEmbeddingVector($face);
            $embeddingId = $face->embeddingId();

            if ($vector === [] && $embeddingId === null) {
                continue;
            }

            $embeddings[] = [
                'id' => $this->remoteFaceId($face),
                'vector' => $vector,
                'embedding_id' => $embeddingId,
                'metadata' => [
                    'attachment_id' => $face->attachmentId(),
                    'bbox' => $face->bbox(),
                ],
            ];
        }

        return [
            'embeddings' => $embeddings,
            'min_cluster_size' => self::REMOTE_MIN_CLUSTER_SIZE,
            'similarity_threshold' => self::REMOTE_SIMILARITY_THRESHOLD,
        ];
    }

    /**
     * @param array<string,mixed> $response
     * @param UnknownFace[] $faces
     * @return array<string,mixed>
     */
    private function buildRemoteResponse(array $response, array $faces): array
    {
        $clustersRaw = [];
        if (isset($response['clusters']) && is_array($response['clusters'])) {
            $clustersRaw = $response['clusters'];
        }

        $faceLookup = [];
        foreach ($faces as $face) {
            $faceLookup[$this->remoteFaceId($face)] = $face;
        }

        $assignedClusters = [];
        $clusters = [];

        foreach ($clustersRaw as $cluster) {
            if (!is_array($cluster)) {
                continue;
            }

            $clusterId = isset($cluster['cluster_id']) ? (string) $cluster['cluster_id'] : '';
            if ($clusterId === '') {
                continue;
            }

            $faceIdsRaw = isset($cluster['face_ids']) && is_array($cluster['face_ids'])
                ? $cluster['face_ids']
                : [];

            $mappedFaceIds = [];

            foreach ($faceIdsRaw as $remoteFaceId) {
                if (!is_string($remoteFaceId)) {
                    continue;
                }

                $face = $faceLookup[$remoteFaceId] ?? null;
                if (!$face instanceof UnknownFace) {
                    continue;
                }

                $databaseId = $face->id();
                if ($databaseId === null) {
                    continue;
                }

                $this->repository->updateClusterAssignment($databaseId, $clusterId);
                $assignedClusters[$databaseId] = $clusterId;
                $mappedFaceIds[] = $databaseId;
            }

            if ($mappedFaceIds === []) {
                continue;
            }

            $clusters[] = [
                'id' => $clusterId,
                'faceIds' => $mappedFaceIds,
                'size' => count($mappedFaceIds),
            ];
        }

        $unclustered = [];
        if (isset($response['unclustered_face_ids']) && is_array($response['unclustered_face_ids'])) {
            foreach ($response['unclustered_face_ids'] as $remoteFaceId) {
                if (!is_string($remoteFaceId)) {
                    continue;
                }

                $face = $faceLookup[$remoteFaceId] ?? null;
                if (!$face instanceof UnknownFace) {
                    continue;
                }

                $faceId = $face->id();
                if ($faceId !== null) {
                    $unclustered[] = $faceId;
                }
            }
        }

        return [
            'strategy' => 'remote',
            'clusters' => $clusters,
            'unclustered' => $unclustered,
            'faces' => $this->serializeFaces($faces, $assignedClusters),
        ];
    }

    /**
     * @param UnknownFace[] $faces
     * @param array<int,string> $assignedClusters
     * @return array<int,array<string,mixed>>
     */
    private function serializeFaces(array $faces, array $assignedClusters = []): array
    {
        $payload = [];

        foreach ($faces as $face) {
            $id = $face->id();
            $clusterId = $id !== null && isset($assignedClusters[$id])
                ? $assignedClusters[$id]
                : $face->clusterId();

            $bbox = $face->bbox();
            $dimensions = $this->resolveImageDimensions($face->attachmentId());

            if ($dimensions['width'] !== null && $dimensions['height'] !== null) {
                $bbox['imageWidth'] = $dimensions['width'];
                $bbox['imageHeight'] = $dimensions['height'];
            }

            $payload[] = [
                'id' => $this->remoteFaceId($face),
                'databaseId' => $id,
                'attachmentId' => $face->attachmentId(),
                'bbox' => $bbox,
                'embeddingId' => $face->embeddingId(),
                'clusterId' => $clusterId,
                'detectedAt' => $this->formatDate($face->detectedAt()),
                'resolvedAt' => $face->resolvedAt() ? $this->formatDate($face->resolvedAt()) : null,
                'rosterId' => $face->rosterId(),
            ];
        }

        return $payload;
    }

    private function remoteFaceId(UnknownFace $face): string
    {
        $id = $face->id();

        if ($id !== null) {
            return 'face-' . $id;
        }

        return 'face-' . spl_object_id($face);
    }

    /**
     * @param UnknownFace[] $faces
     * @return array{vectors: array<int,array<float>>, mappings: array<int,array{face:UnknownFace,face_id:string}>}
     */
    private function embedFacesForCluster(array $faces): array
    {
        $vectors = [];
        $mappings = [];

        $byAttachment = [];

        foreach ($faces as $face) {
            $byAttachment[$face->attachmentId()][] = $face;
        }

        foreach ($byAttachment as $attachmentId => $attachmentFaces) {
            $payloadFaces = [];

            foreach ($attachmentFaces as $index => $face) {
                $payloadFaces[] = [
                    'bbox' => $face->bbox(),
                    'index' => $index,
                ];
            }

            if ($payloadFaces === []) {
                continue;
            }

            try {
                $response = $this->recognitionClient->embedFaces((int) $attachmentId, $payloadFaces);
            } catch (RecognitionClientException $exception) {
                continue;
            }

            $embeddings = isset($response['embeddings']) && is_array($response['embeddings'])
                ? $response['embeddings']
                : [];

            if ($embeddings === []) {
                continue;
            }

            foreach ($embeddings as $position => $vector) {
                if (!is_array($vector)) {
                    continue;
                }

                $normalised = $this->normaliseEmbeddingVector($vector);
                if ($normalised === []) {
                    continue;
                }

                $face = $attachmentFaces[$position] ?? null;
                if (!$face instanceof UnknownFace) {
                    continue;
                }

                $vectors[] = $normalised;
                $mappings[] = [
                    'face' => $face,
                    'face_id' => $this->remoteFaceId($face),
                ];
            }
        }

        return [
            'vectors' => $vectors,
            'mappings' => $mappings,
        ];
    }

    /**
     * @param array<int,mixed> $vector
     * @return array<int,float>
     */
    private function normaliseEmbeddingVector(array $vector): array
    {
        $normalised = [];

        foreach ($vector as $value) {
            if (is_numeric($value)) {
                $normalised[] = (float) $value;
            }
        }

        return $normalised;
    }

    /**
     * @param array<int,array<mixed>> $rawSuggestions
     * @param array<int,array{face:UnknownFace,face_id:string}> $mappings
     * @return array<int,array<string,mixed>>
     */
    private function aggregateSuggestions(string $clusterId, array $rawSuggestions, array $mappings): array
    {
        $aggregate = [];

        foreach ($rawSuggestions as $index => $matches) {
            if (!isset($mappings[$index])) {
                continue;
            }

            $faceMeta = $mappings[$index];
            $faceId = $faceMeta['face_id'];

            if (!is_array($matches) || $matches === []) {
                continue;
            }

            foreach ($matches as $match) {
                if (!is_array($match)) {
                    continue;
                }

                $rosterId = $this->stringValue($match['rosterId'] ?? ($match['roster_id'] ?? null));
                if ($rosterId === null || $rosterId === '') {
                    continue;
                }

                $display = $this->stringValue($match['display'] ?? ($match['display_name'] ?? null)) ?? '';
                $score = $this->floatValue($match['score'] ?? ($match['confidence'] ?? null));

                if ($score === null || $score < self::SUGGESTION_MIN_SCORE) {
                    continue;
                }

                if (!isset($aggregate[$rosterId])) {
                    $aggregate[$rosterId] = [
                        'display' => $display,
                        'scores' => [],
                        'face_ids' => [],
                    ];
                }

                if ($display !== '') {
                    $aggregate[$rosterId]['display'] = $display;
                }

                $aggregate[$rosterId]['scores'][] = $score;
                $aggregate[$rosterId]['face_ids'][] = $faceId;
            }
        }

        if ($aggregate === []) {
            return [];
        }

        $results = [];

        foreach ($aggregate as $rosterId => $data) {
            $scores = $data['scores'];
            $maxScore = (float) max($scores);
            $averageScore = array_sum($scores) / max(1, count($scores));
            $faceIds = array_values(array_unique($data['face_ids']));

            $results[] = [
                'cluster_id' => $clusterId,
                'roster_id' => (string) $rosterId,
                'display_name' => $data['display'],
                'confidence' => round($maxScore, 4),
                'confidence_level' => $this->confidenceLevel($maxScore),
                'match_count' => count($scores),
                'face_ids' => $faceIds,
                'reason' => $this->buildSuggestionReason(count($scores), $maxScore, $averageScore),
            ];
        }

        usort(
            $results,
            static function (array $a, array $b): int {
                $byConfidence = $b['confidence'] <=> $a['confidence'];
                if ($byConfidence !== 0) {
                    return $byConfidence;
                }

                return $b['match_count'] <=> $a['match_count'];
            }
        );

        return $results;
    }

    private function stringValue(mixed $value): ?string
    {
        if (is_string($value)) {
            $trimmed = trim($value);

            return $trimmed === '' ? null : $trimmed;
        }

        if (is_numeric($value)) {
            return (string) $value;
        }

        return null;
    }

    private function floatValue(mixed $value): ?float
    {
        if (is_numeric($value)) {
            return (float) $value;
        }

        return null;
    }

    private function confidenceLevel(float $score): string
    {
        if ($score >= 0.9) {
            return 'high';
        }

        if ($score >= 0.75) {
            return 'medium';
        }

        return 'low';
    }

    private function buildSuggestionReason(int $matchCount, float $maxScore, float $averageScore): string
    {
        $bestPercent = (int) round($maxScore * 100);
        $averagePercent = (int) round($averageScore * 100);

        if ($matchCount <= 1) {
            return sprintf('Best match at %d%% similarity', $bestPercent);
        }

        return sprintf(
            '%d faces matched (best %d%%, avg %d%%)',
            $matchCount,
            $bestPercent,
            $averagePercent
        );
    }

    /**
     * Resolve embedding vectors for remote clustering.
     *
     * @return float[]
     */
    private function resolveEmbeddingVector(UnknownFace $face): array
    {
        $embeddingVector = $face->embeddingVector();

        if ($embeddingVector === null || !is_array($embeddingVector)) {
            return [];
        }

        // Validate vector has correct dimension (512 for InsightFace)
        if (count($embeddingVector) !== 512) {
            error_log(sprintf(
                '[ClusteringService] Invalid embedding dimension for face %d: expected 512, got %d',
                $face->id() ?? 0,
                count($embeddingVector)
            ));
            return [];
        }

        // Vector is already normalized by InsightFace, return as-is
        return $embeddingVector;
    }

    private function formatDate(DateTimeInterface $date): string
    {
        return $date->format(DATE_ATOM);
    }

    /**
     * @return array{width:?int,height:?int}
     */
    private function resolveImageDimensions(int $attachmentId): array
    {
        if (isset($this->dimensionsCache[$attachmentId])) {
            return $this->dimensionsCache[$attachmentId];
        }

        $width = null;
        $height = null;

        if (function_exists('wp_get_attachment_metadata')) {
            $metadata = wp_get_attachment_metadata($attachmentId);

            if (is_array($metadata)) {
                if (isset($metadata['width']) && is_numeric($metadata['width'])) {
                    $width = (int) $metadata['width'];
                }

                if (isset($metadata['height']) && is_numeric($metadata['height'])) {
                    $height = (int) $metadata['height'];
                }
            }
        }

        $resolved = [
            'width' => $width,
            'height' => $height,
        ];

        $this->dimensionsCache[$attachmentId] = $resolved;

        return $resolved;
    }
}
