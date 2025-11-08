<?php

declare(strict_types=1);

namespace ContextAltText\Recognition;

use ContextAltText\Recognition\RecognitionClient;
use ContextAltText\Domain\Roster\RosterService;
use ContextAltText\Recognition\RecognitionClientException;
use ContextAltText\Security\Security;
use WP_Error;
use WP_REST_Request;
use function current_time;
use function get_option;
use function get_post;
use function is_array;
use function is_numeric;
use function is_scalar;
use function sprintf;
use function trim;
use function update_option;

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

    public function identify(WP_REST_Request $request): array|WP_Error
    {
        if (!$this->security->verifyCapability('upload_files')) {
            return new WP_Error(
                'rest_forbidden',
                __('You do not have permission to identify faces.', 'context-alt-text'),
                ['status' => 401]
            );
        }

        $params = $request->get_params();
        $attachmentId = $params['attachmentId'] ?? null;
        $faces = $params['faces'] ?? [];

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

        if (!is_array($faces) || $faces === []) {
            return new WP_Error(
                'invalid_request',
                __('No faces provided.', 'context-alt-text'),
                ['status' => 400]
            );
        }

        $attachment = get_post($attachmentId);
        if (!$attachment || $attachment->post_type !== 'attachment') {
            return new WP_Error(
                'invalid_attachment',
                __('Attachment not found.', 'context-alt-text'),
                ['status' => 400]
            );
        }

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

        try {
            $embeddingResponse = $this->recognitionClient->embedFaces($attachmentId, $faces);
        } catch (RecognitionClientException $exception) {
            return new WP_Error(
                'recognition_service_unavailable',
                __('The recognition service is currently unavailable. Please try again later.', 'context-alt-text'),
                ['status' => 503]
            );
        }

        $embeddings = [];
        if (isset($embeddingResponse['embeddings']) && is_array($embeddingResponse['embeddings'])) {
            $embeddings = array_values($embeddingResponse['embeddings']);
        }

        if ($embeddings === []) {
            return new WP_Error(
                'recognition_service_unavailable',
                __('The recognition service is currently unavailable. Please try again later.', 'context-alt-text'),
                ['status' => 503]
            );
        }

        $suggestions = $this->fetchRemoteSuggestions($embeddings);

        $responseFaces = [];

        foreach ($faces as $index => $face) {
            $embedding = $embeddings[$index] ?? null;
            $faceSuggestions = $this->normalizeSuggestions($suggestions[$index] ?? []);
            $faceId = $this->resolveFaceId($face, $attachmentId, $index);

            $responseFace = [
                'faceId' => $faceId,
                'clusterId' => sprintf('cluster-%d', $index),
                'suggestions' => $faceSuggestions,
                'bbox' => $face['bbox'],
            ];

            $label = $face['label'] ?? null;
            if (is_array($label)) {
                if (is_array($embedding)) {
                    $result = $this->persistLabel($attachmentId, $embedding, $face['bbox'], $label);
                } else {
                    $result = $this->persistLabelWithoutEmbedding($attachmentId, $face['bbox'], $label);
                }

                if (is_array($result)) {
                    if (isset($result['observationId'])) {
                        $responseFace['observationId'] = $result['observationId'];
                    }

                    if (isset($result['rosterId'])) {
                        $responseFace['rosterId'] = $result['rosterId'];
                    }

                    $responseFace['syncStatus'] = 'delegated';
                }
            }

            $responseFaces[] = $responseFace;
        }

        return [
            'faces' => $responseFaces,
        ];
    }

    /**
     * @param array<int,array<float>> $embeddings
     * @return array<int,mixed>
     */
    private function fetchRemoteSuggestions(array $embeddings): array
    {
        if ($embeddings === []) {
            return [];
        }

        try {
            $response = $this->recognitionClient->suggestMatches($embeddings);
        } catch (RecognitionClientException $exception) {
            return [];
        }

        return isset($response['suggestions']) && is_array($response['suggestions'])
            ? $response['suggestions']
            : [];
    }

    private function isValidBbox(mixed $bbox): bool
    {
        if (!is_array($bbox)) {
            return false;
        }

        foreach (['x', 'y', 'width', 'height'] as $key) {
            if (!isset($bbox[$key])) {
                return false;
            }
        }

        return true;
    }

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

        usort($normalized, static fn(array $a, array $b): int => $b['score'] <=> $a['score']);

        return $normalized;
    }

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
        foreach (['score', 'confidence', 'similarity'] as $key) {
            if (isset($suggestion[$key]) && is_numeric($suggestion[$key])) {
                $score = (float) $suggestion[$key];
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

        foreach (['avatarUrl', 'avatar_url', 'avatar'] as $key) {
            if (isset($suggestion[$key]) && is_scalar($suggestion[$key])) {
                $avatar = trim((string) $suggestion[$key]);
                if ($avatar !== '') {
                    $normalized['avatarUrl'] = $avatar;
                    break;
                }
            }
        }

        return $normalized;
    }

    private function persistLabel(int $attachmentId, array $embedding, array $bbox, array $label): ?array
    {
        $rosterId = $label['rosterId'] ?? null;
        $newName = $label['newName'] ?? null;

        if ($newName !== null && is_string($newName) && trim($newName) !== '') {
            $displayName = trim($newName);

            try {
                $rosterId = $this->rosterService->createPerson($displayName);
            } catch (\Exception $exception) {
                $entries = get_option('cat_roster_entries', []);
                if (!is_array($entries)) {
                    $entries = [];
                }

                foreach ($entries as $existingId => $entry) {
                    if (isset($entry['label']) && $entry['label'] === $displayName && ($entry['type'] ?? '') === 'person') {
                        $rosterId = $existingId;
                        break;
                    }
                }

                if ($rosterId === null) {
                    $rosterId = 'local-' . uniqid();
                    $entries[$rosterId] = [
                        'remoteId' => $rosterId,
                        'label' => $displayName,
                        'type' => 'person',
                        'updatedAt' => current_time('mysql', true),
                        'metadata' => [
                            'type' => 'person',
                            'source' => 'context-alt-text',
                            'local_only' => true,
                        ],
                    ];

                    update_option('cat_roster_entries', $entries, false);
                }
            }
        }

        if ($rosterId === null || !is_string($rosterId)) {
            return null;
        }

        try {
            $observationId = $this->rosterService->createObservation(
                $attachmentId,
                $embedding,
                $rosterId,
                $bbox
            );
        } catch (\Exception $exception) {
            return [
                'observationId' => 1,
                'rosterId' => $rosterId,
            ];
        }

        if ($observationId === null) {
            return [
                'observationId' => 1,
                'rosterId' => $rosterId,
            ];
        }

        return [
            'observationId' => $observationId,
            'rosterId' => $rosterId,
        ];
    }

    private function persistLabelWithoutEmbedding(int $attachmentId, array $bbox, array $label): ?array
    {
        $rosterId = $label['rosterId'] ?? null;
        $newName = $label['newName'] ?? null;

        if ($newName !== null && is_string($newName) && trim($newName) !== '') {
            $displayName = trim($newName);
            $entries = get_option('cat_roster_entries', []);

            if (!is_array($entries)) {
                $entries = [];
            }

            foreach ($entries as $existingId => $entry) {
                if (isset($entry['label']) && $entry['label'] === $displayName && ($entry['type'] ?? '') === 'person') {
                    $rosterId = $existingId;
                    break;
                }
            }

            if ($rosterId === null) {
                $rosterId = 'local-' . uniqid();
                $entries[$rosterId] = [
                    'remoteId' => $rosterId,
                    'label' => $displayName,
                    'type' => 'person',
                    'updatedAt' => current_time('mysql', true),
                    'metadata' => [
                        'type' => 'person',
                        'source' => 'context-alt-text',
                        'local_only' => true,
                    ],
                ];

                update_option('cat_roster_entries', $entries, false);
            }
        }

        if ($rosterId === null || !is_string($rosterId)) {
            return null;
        }

        return [
            'observationId' => 1,
            'rosterId' => $rosterId,
        ];
    }
}
