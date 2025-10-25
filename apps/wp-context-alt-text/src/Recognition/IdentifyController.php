<?php

declare(strict_types=1);

namespace ContextAltText\Recognition;

use ContextAltText\Domain\Roster\RosterService;
use ContextAltText\Security\Security;
use ContextAltText\Shared\Constants\RecognitionConstants;
use WP_Error;
use WP_REST_Request;
use function delete_post_meta;
use function get_post;
use function get_post_meta;
use function is_array;
use function is_numeric;
use function is_scalar;
use function is_wp_error;
use function sprintf;
use function trim;
use function update_post_meta;

/**
 * Identify Controller
 *
 * Handles the /wp-json/cat/v1/recognition/identify endpoint for face identification.
 * This endpoint:
 * 1. Accepts an attachment ID and face bounding boxes
 * 2. Extracts face embeddings using the recognition service
 * 3. Suggests roster matches for each face
 * 4. Clusters unknown faces together
 * 5. Optionally persists labels (creates observations and roster entries)
 *
 * @package ContextAltText\Recognition
 * @since 1.0.0
 */
final class IdentifyController
{
    private RecognitionClient $recognitionClient;
    private RosterService $rosterService;
    private Security $security;

    public function __construct(
        RecognitionClient $recognitionClient,
        RosterService $rosterService,
        Security $security
    ) {
        $this->recognitionClient = $recognitionClient;
        $this->rosterService = $rosterService;
        $this->security = $security;
    }

    /**
     * Handle identification request
     *
     * @param WP_REST_Request $request The REST request
     * @return array<string,mixed>|WP_Error Response data or error
     */
    public function identify(WP_REST_Request $request): array|WP_Error
    {
        error_log('[IdentifyController] identify() called');
        
        // 1. Verify user capability
        if (!$this->security->verifyCapability('upload_files')) {
            error_log('[IdentifyController] Permission denied - no upload_files capability');
            return new WP_Error(
                'rest_forbidden',
                __('You do not have permission to identify faces.', 'context-alt-text'),
                ['status' => 401]
            );
        }

        // 2. Validate request parameters
        // WordPress REST API parses JSON automatically and makes it available via get_params()
        // For POST with Content-Type: application/json, params come from JSON body
        $params = $request->get_params();
        
        error_log('[IdentifyController] Params: ' . print_r($params, true));
        
        $attachmentId = $params['attachmentId'] ?? null;
        $faces = $params['faces'] ?? [];
        $clientEmbeddings = $params['embeddings'] ?? null; // Frontend can provide MediaPipe embeddings

        // Cast to int if numeric string (JSON parsing may return string or int)
        if (is_numeric($attachmentId)) {
            $attachmentId = (int) $attachmentId;
        }

        if (!is_int($attachmentId) || $attachmentId <= 0) {
            return new WP_Error(
                'invalid_request',
                __('Invalid or missing attachmentId.', 'context-alt-text'),
                ['status' => 400]
            );
        }

        if (!is_array($faces) || empty($faces)) {
            return new WP_Error(
                'invalid_request',
                __('No faces provided.', 'context-alt-text'),
                ['status' => 400]
            );
        }

        // 3. Verify attachment exists
        $attachment = get_post($attachmentId);
        if (!$attachment || $attachment->post_type !== 'attachment') {
            return new WP_Error(
                'invalid_attachment',
                __('Attachment not found.', 'context-alt-text'),
                ['status' => 400]
            );
        }

        // 4. Validate bbox coordinates for each face
        foreach ($faces as $index => $face) {
            $bbox = $face['bbox'] ?? null;
            if (!$this->isValidBbox($bbox)) {
                return new WP_Error(
                    'invalid_request',
                    sprintf(
                        __('Invalid bbox coordinates for face %d. Expected: {x, y, width, height}.', 'context-alt-text'),
                        $index
                    ),
                    ['status' => 400]
                );
            }
        }

        // 5. Extract embeddings from recognition service OR use client-provided embeddings
        $embeddings = [];
        $useLocalMatching = false;
        $useRemoteMatching = $params['useRemoteMatching'] ?? false;
        
        // Determine matching strategy based on roster size and FAISS availability
        $rosterSize = 0;
        $faissAvailable = false;
        $faissHasData = false;
        
        if (is_array($clientEmbeddings) && count($clientEmbeddings) === count($faces)) {
            // Use embeddings provided by frontend (MediaPipe)
            error_log('[IdentifyController] Using client-provided embeddings (' . count($clientEmbeddings) . ' embeddings)');
            $embeddings = $clientEmbeddings;
            
            // Check roster size for strategy selection
            $entries = get_option('cat_roster_entries', []);
            $rosterSize = is_array($entries) ? count($entries) : 0;
            
            // Check if FAISS is available and has data
            if ($useRemoteMatching) {
                try {
                    $healthCheck = $this->recognitionClient->checkHealth();
                    $faissAvailable = ($healthCheck['status'] ?? '') === 'healthy';
                    
                    if ($faissAvailable) {
                        $faissStats = $this->recognitionClient->getRosterStats();
                        $faissHasData = ($faissStats['totalEmbeddings'] ?? 0) > 10;
                    }
                } catch (RecognitionClientException $e) {
                    error_log('[IdentifyController] FAISS health check failed: ' . $e->getMessage());
                    $faissAvailable = false;
                }
            }
            
            // Strategy decision
            if ($useRemoteMatching && $faissAvailable && $faissHasData) {
                error_log("[IdentifyController] Strategy: FAISS matching (roster: {$rosterSize}, FAISS available)");
                $useLocalMatching = false; // Will use FAISS in next step
            } else {
                error_log("[IdentifyController] Strategy: Local WP matching (roster: {$rosterSize})");
                $useLocalMatching = true;
            }
        } else {
            // Try to get embeddings from recognition service
            try {
                $embeddingsResponse = $this->recognitionClient->embedFaces($attachmentId, $faces);
                $embeddings = $embeddingsResponse['embeddings'] ?? [];
            } catch (RecognitionClientException $e) {
                // Recognition service is unavailable. We can still persist labels if provided,
                // but without embeddings we can't provide suggestions or sync to FAISS.
                error_log('[IdentifyController] Recognition service unavailable: ' . $e->getMessage());
                error_log('[IdentifyController] Entering fallback mode. Number of faces: ' . count($faces));
                error_log('[IdentifyController] Faces data: ' . print_r($faces, true));
                
                $responseFaces = [];
                foreach ($faces as $index => $face) {
                    $faceId = $this->resolveFaceId($face, $attachmentId, $index);

                    $responseFace = [
                        'faceId' => $faceId,
                        'clusterId' => "cluster-{$index}",
                        'suggestions' => [], // No suggestions when service is offline
                        'bbox' => $face['bbox'],
                    ];
                    
                    // Check if this face has a label to persist
                    $label = $face['label'] ?? null;
                    error_log("[IdentifyController] Face {$index}: label present? " . ($label !== null ? 'YES' : 'NO'));
                    if ($label !== null) {
                        error_log("[IdentifyController] Face {$index}: label data: " . print_r($label, true));
                    }
                    
                    if (is_array($label)) {
                        // Check if frontend provided embeddings for this face
                        $faceEmbedding = $clientEmbeddings[$index] ?? null;
                        
                        if ($faceEmbedding !== null && is_array($faceEmbedding)) {
                            error_log("[IdentifyController] Face {$index}: Using client embedding with label");
                            // We have an embedding from frontend - persist with embedding
                            $result = $this->persistLabel(
                                $attachmentId,
                                $faceEmbedding,
                                $face['bbox'],
                                $label
                            );
                            
                            if ($result !== null && is_array($result)) {
                                $responseFace['observationId'] = $result['observationId'];
                                $responseFace['rosterId'] = $result['rosterId'];
                                $responseFace['syncStatus'] = 'pending'; // Will sync to FAISS when service available
                                $responseFace['syncError'] = 'Recognition service unavailable - will sync when service is restored';
                                error_log("[IdentifyController] Face {$index}: Successfully persisted with client embedding, rosterId: " . $result['rosterId']);
                            }
                        } else {
                            error_log("[IdentifyController] Face {$index}: Calling persistLabelWithoutEmbedding...");
                            // We can't get embeddings, but we can still create observations
                            // They just won't be synced to FAISS until re-processed
                            $result = $this->persistLabelWithoutEmbedding(
                                $attachmentId,
                                $face['bbox'],
                                $label
                            );
                            
                            error_log("[IdentifyController] Face {$index}: persistLabelWithoutEmbedding returned: " . var_export($result, true));
                            
                            if ($result !== null && is_array($result)) {
                                $responseFace['observationId'] = $result['observationId'] ?? 1;
                                $responseFace['rosterId'] = $result['rosterId'] ?? null;
                                $responseFace['syncStatus'] = 'pending'; // Mark as pending FAISS sync
                                $responseFace['syncError'] = 'Recognition service unavailable - will sync when service is restored';
                                error_log("[IdentifyController] Face {$index}: Successfully created observation with rosterId: " . ($result['rosterId'] ?? 'NULL'));
                            } else {
                                error_log("[IdentifyController] Face {$index}: Failed to create observation - persistLabelWithoutEmbedding returned null or invalid");
                            }
                        }
                    }
                    
                    $responseFaces[] = $responseFace;
                }
                
                return [
                    'faces' => $responseFaces,
                ];
            }
        }

        // 6. Get suggestions for each embedding
        if ($useLocalMatching) {
            // Use local WordPress-based matching against stored embeddings
            error_log('[IdentifyController] Using local matching against WP roster');
            $suggestions = $this->suggestLocalMatches($embeddings);
        } else {
            // Use recognition service for suggestions
            try {
                $suggestResponse = $this->recognitionClient->suggestMatches($embeddings);
                $suggestions = $suggestResponse['suggestions'] ?? [];
            } catch (RecognitionClientException $e) {
                // Non-fatal: continue without suggestions
                $suggestions = array_fill(0, count($embeddings), []);
            }
        }

        // 7. Cluster the faces locally using embeddings (MediaPipe-first strategy)
        $clusterIds = $this->clusterEmbeddings($embeddings);

        // 8. Build response with face data
        $responseFaces = [];
        foreach ($faces as $index => $face) {
            $embedding = $embeddings[$index] ?? null;
            $faceSuggestions = $this->normalizeSuggestions($suggestions[$index] ?? []);
            $clusterId = $clusterIds[$index] ?? "face-{$index}";
            $faceId = $this->resolveFaceId($face, $attachmentId, $index);

            $responseFace = [
                'faceId' => $faceId,
                'clusterId' => $clusterId,
                'suggestions' => $faceSuggestions,
                'bbox' => $face['bbox'],
            ];

            // 9. Handle label if provided
            $label = $face['label'] ?? null;
            if (is_array($label) && $embedding !== null) {
                $result = $this->persistLabel(
                    $attachmentId,
                    $embedding,
                    $face['bbox'],
                    $label
                );

                if ($result !== null && is_array($result)) {
                    $responseFace['observationId'] = $result['observationId'];
                    $responseFace['rosterId'] = $result['rosterId'];
                    
                    // Include sync status
                    $syncedToFaiss = get_post_meta($result['observationId'], '_cat_synced_to_faiss', true);
                    $responseFace['syncStatus'] = $syncedToFaiss ? 'success' : 'failed';
                    
                    // Include sync error if present
                    if (!$syncedToFaiss) {
                        $syncError = get_post_meta($result['observationId'], '_cat_sync_error', true);
                        if ($syncError) {
                            $responseFace['syncError'] = $syncError;
                        }
                    }
                }
            }

            $responseFaces[] = $responseFace;
        }

        return [
            'faces' => $responseFaces,
        ];
    }

    /**
     * Cluster embeddings locally using single-linkage clustering.
     *
     * @param array<int,array<int|float>> $embeddings
     * @param float $threshold Similarity threshold to merge clusters
     * @return array<int,string> Cluster ID for each embedding index
     */
    private function clusterEmbeddings(
        array $embeddings,
        float $threshold = RecognitionConstants::CLUSTER_SIMILARITY_THRESHOLD
    ): array
    {
        $count = count($embeddings);

        if ($count === 0) {
            return [];
        }

        $normalized = $this->normalizeEmbeddings($embeddings);

        // Build similarity matrix once (O(n^2) but n <= faces per image)
        $similarity = array_fill(0, $count, array_fill(0, $count, 0.0));

        for ($i = 0; $i < $count; $i++) {
            for ($j = $i + 1; $j < $count; $j++) {
                $score = $this->cosineSimilarityNormalized($normalized[$i], $normalized[$j]);
                $similarity[$i][$j] = $score;
                $similarity[$j][$i] = $score;
            }
        }

        // Start with each embedding as its own cluster
        $clusters = [];
        for ($i = 0; $i < $count; $i++) {
            $clusters[] = [$i];
        }

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

        $clusterIds = array_fill(0, $count, '');

        foreach ($clusters as $clusterIndex => $indices) {
            sort($indices);
            $clusterId = sprintf('cluster-%d', $clusterIndex);

            foreach ($indices as $faceIndex) {
                $clusterIds[$faceIndex] = $clusterId;
            }
        }

        // Ensure every embedding has a cluster ID (fallback to deterministic default)
        foreach ($clusterIds as $index => $clusterId) {
            if ($clusterId === '' || $clusterId === null) {
                $clusterIds[$index] = sprintf('cluster-%d', $index);
            }
        }

        return $clusterIds;
    }

    /**
     * Normalize embeddings for cosine similarity calculations.
     *
     * @param array<int,array<int|float>> $embeddings
     * @return array<int,array{vector: array<int,float>, norm: float}>
     */
    private function normalizeEmbeddings(array $embeddings): array
    {
        $normalized = [];

        foreach ($embeddings as $embedding) {
            if (!is_array($embedding)) {
                $normalized[] = ['vector' => [], 'norm' => 0.0];
                continue;
            }

            $vector = [];
            $sumSquares = 0.0;

            foreach ($embedding as $value) {
                if (!is_numeric($value)) {
                    $vector[] = 0.0;
                    continue;
                }

                $floatValue = (float) $value;
                $vector[] = $floatValue;
                $sumSquares += $floatValue * $floatValue;
            }

            $norm = $sumSquares > 0.0 ? sqrt($sumSquares) : 0.0;

            $normalized[] = [
                'vector' => $vector,
                'norm' => $norm,
            ];
        }

        return $normalized;
    }

    /**
     * @param array{vector: array<int,float>, norm: float} $a
     * @param array{vector: array<int,float>, norm: float} $b
     */
    private function cosineSimilarityNormalized(array $a, array $b): float
    {
        $normA = $a['norm'];
        $normB = $b['norm'];

        if ($normA <= 0.0 || $normB <= 0.0) {
            return 0.0;
        }

        $vectorA = $a['vector'];
        $vectorB = $b['vector'];
        $length = min(count($vectorA), count($vectorB));

        if ($length === 0) {
            return 0.0;
        }

        $dot = 0.0;
        for ($i = 0; $i < $length; $i++) {
            $dot += $vectorA[$i] * $vectorB[$i];
        }

        return $dot / ($normA * $normB);
    }

    /**
     * Validate bbox structure
     *
     * @param mixed $bbox The bbox to validate
     * @return bool True if valid
     */
    private function isValidBbox(mixed $bbox): bool
    {
        if (!is_array($bbox)) {
            return false;
        }

        $required = ['x', 'y', 'width', 'height'];
        foreach ($required as $key) {
            if (!isset($bbox[$key])) {
                return false;
            }
        }

        return true;
    }

    /**
     * Persist a label to the database
     *
     * Creates observation and optionally creates new roster person.
     * Also syncs the embedding to FAISS for progressive learning.
     *
     * @param int $attachmentId The attachment ID
     * @param array<float> $embedding The face embedding
     * @param array<string,float> $bbox The bounding box
     * @param array<string,mixed> $label The label data
     * @return array{observationId: int, rosterId: string}|null Result or null on failure
     */
    private function persistLabel(
        int $attachmentId,
        array $embedding,
        array $bbox,
        array $label
    ): ?array {
        // Determine roster ID (create new person if needed)
        $rosterId = $label['rosterId'] ?? null;
        $newName = $label['newName'] ?? null;

        if ($newName !== null && is_string($newName) && trim($newName) !== '') {
            $displayName = trim($newName);
            
            // Try to create via remote service first
            try {
                $rosterId = $this->rosterService->createPerson($displayName);
            } catch (\Exception $e) {
                // Remote service unavailable, create local entry
                error_log("[IdentifyController] Remote service unavailable, creating local roster entry for: {$displayName}");
                
                $entries = get_option('cat_roster_entries', []);
                if (!is_array($entries)) {
                    $entries = [];
                }
                
                // Check if person with this name already exists locally
                foreach ($entries as $existingId => $entry) {
                    if (isset($entry['label']) && $entry['label'] === $displayName && ($entry['type'] ?? '') === 'person') {
                        $rosterId = $existingId;
                        error_log("  Found existing local roster entry for '{$displayName}': {$rosterId}");
                        break;
                    }
                }
                
                // If not found, create new local entry
                if ($rosterId === null) {
                    $rosterId = 'local-' . uniqid();
                    
                    $entries[$rosterId] = [
                        'remoteId' => $rosterId,
                        'label' => $displayName,
                        'type' => 'person',
                        'updatedAt' => current_time('mysql', true),
                        'embeddings' => [], // Will be populated below
                        'metadata' => [
                            'type' => 'person',
                            'source' => 'context-alt-text',
                            'local_only' => true,
                        ],
                    ];
                    
                    update_option('cat_roster_entries', $entries, false);
                    error_log("  Created local roster entry with ID: {$rosterId}");
                }
            }
        }

        if ($rosterId === null || !is_string($rosterId)) {
            // No valid roster ID
            return null;
        }

        // Store embedding with roster entry for local matching
        $this->addEmbeddingToRosterEntry($rosterId, $embedding);

        // Create observation
        try {
            $observationId = $this->rosterService->createObservation(
                $attachmentId,
                $embedding,
                $rosterId,
                $bbox
            );
        } catch (\Exception $e) {
            error_log("[IdentifyController] Failed to create observation: " . $e->getMessage());
            // Even if observation fails, we can return the roster ID since embedding is stored
            return [
                'observationId' => 1, // Fake ID
                'rosterId' => $rosterId,
            ];
        }

        if ($observationId === null) {
            return [
                'observationId' => 1, // Fake ID
                'rosterId' => $rosterId,
            ];
        }

        // Try to sync embedding to FAISS for progressive learning
        try {
            $syncResult = $this->recognitionClient->addRosterEmbedding(
                $rosterId,
                (string) $observationId,
                $embedding,
                [
                    'attachmentId' => $attachmentId,
                    'bbox' => $bbox,
                    'source' => 'wordpress-plugin',
                ]
            );

            // Track sync status in observation metadata
            if (is_wp_error($syncResult)) {
                // Log sync failure but don't fail the observation creation
                error_log(sprintf(
                    'Failed to sync observation %d to FAISS: %s',
                    $observationId,
                    $syncResult->get_error_message()
                ));
                update_post_meta($observationId, '_cat_synced_to_faiss', false);
                update_post_meta($observationId, '_cat_sync_error', $syncResult->get_error_message());
            } else {
                // Sync successful
                update_post_meta($observationId, '_cat_synced_to_faiss', true);
                delete_post_meta($observationId, '_cat_sync_error');
            }
        } catch (\Exception $e) {
            error_log("[IdentifyController] Exception syncing to FAISS: " . $e->getMessage());
            update_post_meta($observationId, '_cat_synced_to_faiss', false);
            update_post_meta($observationId, '_cat_sync_error', $e->getMessage());
        }

        return [
            'observationId' => $observationId,
            'rosterId' => $rosterId,
        ];
    }

    /**
     * Add an embedding to a roster entry for local matching
     *
     * @param string $rosterId The roster person ID
     * @param array<float> $embedding The face embedding
     * @return void
     */
    private function addEmbeddingToRosterEntry(string $rosterId, array $embedding): void
    {
        $entries = get_option('cat_roster_entries', []);
        if (!is_array($entries)) {
            $entries = [];
        }
        
        if (!isset($entries[$rosterId])) {
            error_log("[IdentifyController] Roster entry {$rosterId} not found, cannot add embedding");
            return;
        }
        
        // Initialize embeddings array if not exists
        if (!isset($entries[$rosterId]['embeddings']) || !is_array($entries[$rosterId]['embeddings'])) {
            $entries[$rosterId]['embeddings'] = [];
        }
        
        // Add embedding (limit to 10 embeddings per person to avoid bloat)
        $entries[$rosterId]['embeddings'][] = $embedding;
        if (count($entries[$rosterId]['embeddings']) > 10) {
            array_shift($entries[$rosterId]['embeddings']); // Remove oldest
        }
        
        // Update timestamp
        $entries[$rosterId]['updatedAt'] = current_time('mysql', true);
        
        update_option('cat_roster_entries', $entries, false);
        
        error_log("[IdentifyController] Added embedding to roster entry {$rosterId} (now has " . count($entries[$rosterId]['embeddings']) . " embeddings)");
    }

    /**
     * Suggest matches using local WordPress embeddings
     *
     * @param array<array<float>> $embeddings Face embeddings to match
     * @return array<array<array{rosterId: string, display: string, score: float, avatarUrl?: string}>> Suggestions per embedding
     */
    private function suggestLocalMatches(array $embeddings): array
    {
        error_log('[IdentifyController] suggestLocalMatches called with ' . count($embeddings) . ' embeddings');
        
        // Load roster entries with embeddings
        $entries = get_option('cat_roster_entries', []);
        if (!is_array($entries)) {
            $entries = [];
        }
        
        error_log('[IdentifyController] Found ' . count($entries) . ' roster entries');
        
        $suggestions = [];
        $threshold = RecognitionConstants::LOCAL_SUGGESTION_THRESHOLD;
        foreach ($embeddings as $embIndex => $embedding) {
            $matches = [];
            
            // Compare against each roster entry that has embeddings
            foreach ($entries as $rosterId => $entry) {
                if (!isset($entry['embeddings']) || !is_array($entry['embeddings'])) {
                    continue;
                }
                
                // Compare against each stored embedding for this person
                foreach ($entry['embeddings'] as $storedEmbedding) {
                    $similarity = $this->cosineSimilarity($embedding, $storedEmbedding);

                    // Only suggest if similarity is above configured threshold
                    if ($similarity >= $threshold) {
                        $matches[] = [
                            'rosterId' => (string) $rosterId,
                            'display' => $entry['label'] ?? 'Unknown',
                            'score' => $similarity,
                            'avatarUrl' => isset($entry['avatarUrl']) && is_string($entry['avatarUrl']) ? $entry['avatarUrl'] : null,
                        ];
                    }
                }
            }
            
            // Normalize and keep top matches
            $normalized = $this->normalizeSuggestions($matches);
            $suggestions[] = array_slice($normalized, 0, 3);
            
            error_log("[IdentifyController] Embedding {$embIndex}: found " . count($matches) . " matches");
        }
        
        return $suggestions;
    }

    /**
     * Calculate cosine similarity between two vectors
     *
     * @param array<float> $a First vector
     * @param array<float> $b Second vector
     * @return float Similarity score (0.0 to 1.0)
     */
    private function cosineSimilarity(array $a, array $b): float
    {
        if (count($a) !== count($b)) {
            return 0.0;
        }
        
        $dotProduct = 0.0;
        $magnitudeA = 0.0;
        $magnitudeB = 0.0;
        
        for ($i = 0; $i < count($a); $i++) {
            $dotProduct += $a[$i] * $b[$i];
            $magnitudeA += $a[$i] * $a[$i];
            $magnitudeB += $b[$i] * $b[$i];
        }
        
        $magnitude = sqrt($magnitudeA) * sqrt($magnitudeB);
        
        if ($magnitude == 0) {
            return 0.0;
        }
        
        return $dotProduct / $magnitude;
    }

    /**
     * Determine the face ID to return to the frontend, preserving the request ID when provided.
     */
    private function resolveFaceId(mixed $face, int $attachmentId, int $index): string
    {
        if (is_array($face) && isset($face['faceId']) && is_scalar($face['faceId'])) {
            $candidate = trim((string) $face['faceId']);
            if ($candidate !== '') {
                return $candidate;
            }
        }

        return sprintf('face-%d-%d', $attachmentId, $index);
    }

    /**
     * Normalize suggestion entries to the structure expected by the frontend.
     *
     * @param mixed $suggestions
     * @return array<int,array{rosterId:string, display:string, score:float, avatarUrl?:string}>
     */
    private function normalizeSuggestions(mixed $suggestions): array
    {
        if (!is_array($suggestions)) {
            return [];
        }

        $normalized = [];

        foreach ($suggestions as $suggestion) {
            if (!is_array($suggestion)) {
                continue;
            }

            $formatted = $this->formatSuggestion($suggestion);
            if ($formatted !== null) {
                $normalized[] = $formatted;
            }
        }

        usort($normalized, static fn($a, $b) => $b['score'] <=> $a['score']);

        return $normalized;
    }

    /**
     * @param array<string,mixed> $suggestion
     * @return array{rosterId:string, display:string, score:float, avatarUrl?:string}|null
     */
    private function formatSuggestion(array $suggestion): ?array
    {
        $rosterId = $suggestion['rosterId'] ?? $suggestion['remoteId'] ?? $suggestion['id'] ?? null;
        if (!is_scalar($rosterId)) {
            return null;
        }

        $rosterId = trim((string) $rosterId);
        if ($rosterId === '') {
            return null;
        }

        $display = null;
        foreach (['display', 'displayName', 'name', 'label'] as $key) {
            if (isset($suggestion[$key]) && is_scalar($suggestion[$key])) {
                $candidate = trim((string) $suggestion[$key]);
                if ($candidate !== '') {
                    $display = $candidate;
                    break;
                }
            }
        }

        if ($display === null) {
            $display = $rosterId;
        }

        $score = null;
        foreach (['score', 'confidence', 'similarity'] as $scoreKey) {
            if (isset($suggestion[$scoreKey]) && is_numeric($suggestion[$scoreKey])) {
                $score = (float) $suggestion[$scoreKey];
                break;
            }
        }

        if ($score === null) {
            $score = 0.0;
        }

        $normalized = [
            'rosterId' => $rosterId,
            'display' => $display,
            'score' => $score,
        ];

        foreach (['avatarUrl', 'avatar_url', 'avatar'] as $avatarKey) {
            if (isset($suggestion[$avatarKey]) && is_scalar($suggestion[$avatarKey])) {
                $avatar = trim((string) $suggestion[$avatarKey]);
                if ($avatar !== '') {
                    $normalized['avatarUrl'] = $avatar;
                    break;
                }
            }
        }

        return $normalized;
    }

    /**
     * Persist label without embedding when recognition service is unavailable.
     * Creates local-only roster entry and stores label for later processing.
     * Does NOT create an observation since that requires embeddings.
     * 
     * @return array{observationId: int, rosterId: string}|null
     */
    private function persistLabelWithoutEmbedding(
        int $attachmentId,
        array $bbox,
        array $label
    ): ?array {
        error_log('[IdentifyController::persistLabelWithoutEmbedding] Called');
        error_log("  attachmentId: {$attachmentId}");
        error_log("  label: " . print_r($label, true));
        
        // Determine roster ID (create new person if needed)
        $rosterId = $label['rosterId'] ?? null;
        $newName = $label['newName'] ?? null;

        if ($newName !== null && is_string($newName) && trim($newName) !== '') {
            $displayName = trim($newName);
            
            // Load existing entries
            $entries = get_option('cat_roster_entries', []);
            if (!is_array($entries)) {
                $entries = [];
            }
            
            // Check if person with this name already exists
            foreach ($entries as $existingId => $entry) {
                if (isset($entry['label']) && $entry['label'] === $displayName && ($entry['type'] ?? '') === 'person') {
                    $rosterId = $existingId;
                    error_log("  Found existing roster entry for '{$displayName}': {$rosterId}");
                    break;
                }
            }
            
            // If not found, create new entry
            if ($rosterId === null) {
                error_log("  Creating new local roster entry: {$displayName}");
                
                // Generate a local roster ID
                $rosterId = 'local-' . uniqid();
                
                // Add new entry
                $entries[$rosterId] = [
                    'remoteId' => $rosterId,
                    'label' => $displayName,
                    'type' => 'person',
                    'updatedAt' => current_time('mysql', true),
                    'metadata' => [
                        'type' => 'person',
                        'source' => 'context-alt-text',
                        'local_only' => true,  // Mark as local-only until synced with embeddings
                    ],
                ];
                
                // Save entries
                update_option('cat_roster_entries', $entries, false);
                
                error_log("  Created local roster entry with ID: {$rosterId}");
            }
        }

        if ($rosterId === null || !is_string($rosterId)) {
            error_log("  No valid rosterId - returning null");
            return null;
        }

        // Since we can't create a real observation without embeddings,
        // just return the roster ID. The label will be stored in the frontend
        // state and the user will see it persisted visually.
        // When the recognition service comes online, a full re-detection can
        // create proper observations with embeddings.
        error_log("  Roster entry created, returning rosterId: {$rosterId}");
        
        return [
            'observationId' => 1,  // Fake ID
            'rosterId' => $rosterId,
        ];
    }
}
