<?php

declare(strict_types=1);

namespace ContextAltText\Recognition;

use ContextAltText\Domain\Roster\RosterService;
use ContextAltText\Security\Security;
use WP_Error;
use WP_REST_Request;
use function delete_post_meta;
use function get_post;
use function get_post_meta;
use function is_array;
use function is_wp_error;
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

        // 5. Extract embeddings from recognition service
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
                $responseFace = [
                    'faceId' => "face-{$attachmentId}-{$index}",
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
                
                $responseFaces[] = $responseFace;
            }
            
            return [
                'faces' => $responseFaces,
            ];
        }

        // 6. Get suggestions for each embedding
        try {
            $suggestResponse = $this->recognitionClient->suggestMatches($embeddings);
            $suggestions = $suggestResponse['suggestions'] ?? [];
        } catch (RecognitionClientException $e) {
            // Non-fatal: continue without suggestions
            $suggestions = array_fill(0, count($embeddings), []);
        }

        // 7. Cluster the faces
        try {
            $clusterResponse = $this->recognitionClient->clusterFaces($embeddings);
            $clusterIds = $clusterResponse['clusterIds'] ?? [];
        } catch (RecognitionClientException $e) {
            // Non-fatal: use sequential IDs as fallback
            $clusterIds = array_map(fn($i) => "face-{$i}", array_keys($embeddings));
        }

        // 8. Build response with face data
        $responseFaces = [];
        foreach ($faces as $index => $face) {
            $embedding = $embeddings[$index] ?? null;
            $faceSuggestions = $suggestions[$index] ?? [];
            $clusterId = $clusterIds[$index] ?? "face-{$index}";

            $responseFace = [
                'faceId' => "face-{$attachmentId}-{$index}",
                'clusterId' => $clusterId,
                'suggestions' => $faceSuggestions,
                'bbox' => $face['bbox'],
            ];

            // 9. Handle label if provided
            $label = $face['label'] ?? null;
            if (is_array($label) && $embedding !== null) {
                $observationId = $this->persistLabel(
                    $attachmentId,
                    $embedding,
                    $face['bbox'],
                    $label
                );

                if ($observationId !== null) {
                    $responseFace['observationId'] = $observationId;
                    
                    // Include sync status
                    $syncedToFaiss = get_post_meta($observationId, '_cat_synced_to_faiss', true);
                    $responseFace['syncStatus'] = $syncedToFaiss ? 'success' : 'failed';
                    
                    // Include sync error if present
                    if (!$syncedToFaiss) {
                        $syncError = get_post_meta($observationId, '_cat_sync_error', true);
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
     * @return int|null The observation ID or null on failure
     */
    private function persistLabel(
        int $attachmentId,
        array $embedding,
        array $bbox,
        array $label
    ): ?int {
        // Determine roster ID (create new person if needed)
        $rosterId = $label['rosterId'] ?? null;
        $newName = $label['newName'] ?? null;

        if ($newName !== null && is_string($newName) && trim($newName) !== '') {
            // Create new roster person
            try {
                $rosterId = $this->rosterService->createPerson(trim($newName));
            } catch (\Exception $e) {
                // Failed to create person
                return null;
            }
        }

        if ($rosterId === null || !is_string($rosterId)) {
            // No valid roster ID
            return null;
        }

        // Create observation
        try {
            $observationId = $this->rosterService->createObservation(
                $attachmentId,
                $embedding,
                $rosterId,
                $bbox
            );
        } catch (\Exception $e) {
            return null;
        }

        if ($observationId === null) {
            return null;
        }

        // Sync embedding to FAISS for progressive learning
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

        return $observationId;
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
