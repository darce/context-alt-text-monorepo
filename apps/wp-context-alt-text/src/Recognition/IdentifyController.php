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
        // 1. Verify user capability
        if (!$this->security->verifyCapability('upload_files')) {
            return new WP_Error(
                'rest_forbidden',
                __('You do not have permission to identify faces.', 'context-alt-text'),
                ['status' => 401]
            );
        }

        // 2. Validate request parameters
        $params = $request->get_body_params();
        $attachmentId = $params['attachmentId'] ?? null;
        $faces = $params['faces'] ?? [];

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
            return new WP_Error(
                'recognition_service_error',
                $e->getMessage(),
                ['status' => $e->getCode() ?: 503]
            );
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
}
