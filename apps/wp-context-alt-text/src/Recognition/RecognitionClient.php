<?php

declare(strict_types=1);

namespace ContextAltText\Recognition;

use WP_Error;
use function ceil;
use function implode;
use function is_array;
use function is_string;
use function is_wp_error;
use function json_decode;
use function max;
use function http_build_query;
use function rawurlencode;
use function rtrim;
use function sprintf;
use function trim;
use function usleep;
use function wp_json_encode;
use function wp_remote_get;
use function wp_remote_post;
use function wp_remote_retrieve_body;
use function wp_remote_retrieve_response_code;
use function wp_remote_retrieve_response_message;

class RecognitionClient
{
    private const MAX_ATTEMPTS = 3;
    private const BASE_RETRY_DELAY_MS = 200;

    private RecognitionSettings $settings;

    public function __construct(RecognitionSettings $settings)
    {
        $this->settings = $settings;
    }

    /**
     * @param array<string,mixed> $payload
     *
     * @return array<string,mixed>
     * @throws RecognitionClientException
     */
    public function analyzeScene(array $payload): array
    {
        $endpoint = $this->buildUrl('/api/v0/analyze-scene');

        return $this->postJson($endpoint, $payload);
    }

    public function analyzeSceneBase64(array $images, ?float $threshold = null, bool $useRoster = true): array
    {
        $payloadImages = [];

        foreach ($images as $index => $image) {
            if (!is_array($image)) {
                continue;
            }

            $base64 = $image['base64'] ?? $image['image_base64'] ?? '';
            $base64 = is_string($base64) ? trim($base64) : '';

            $filename = $image['filename'] ?? $image['name'] ?? null;
            if (!is_string($filename) || trim($filename) === '') {
                $filename = sprintf('image_%d.png', $index);
            }

            $payloadImages[] = [
                'filename' => $filename,
                'image_base64' => $base64,
            ];
        }

        if ($payloadImages === []) {
            throw new RecognitionClientException('No images provided for analyzeSceneBase64.');
        }

        $payload = [
            'images' => $payloadImages,
            'use_roster' => $useRoster,
        ];

        if ($threshold !== null) {
            $payload['threshold'] = $threshold;
        }

        return $this->analyzeScene($payload);
    }

    /**
     * @param array<string,mixed> $payload
     *
     * @return array<string,mixed>
     * @throws RecognitionClientException
     */
    public function embeddings(array $payload): array
    {
        $endpoint = $this->buildUrl('/api/v0/embeddings');

        return $this->postJson($endpoint, $payload);
    }

    public function generateEmbeddings(array $image, ?float $threshold = null): array
    {
        $payload = [
            'image' => [
                'filename' => isset($image['filename']) && is_string($image['filename'])
                    ? trim($image['filename'])
                    : null,
                'image_base64' => isset($image['base64']) && is_string($image['base64'])
                    ? trim($image['base64'])
                    : (isset($image['image_base64']) && is_string($image['image_base64'])
                        ? trim($image['image_base64'])
                        : null),
                'image_url' => isset($image['image_url']) && is_string($image['image_url'])
                    ? trim($image['image_url'])
                    : (isset($image['url']) && is_string($image['url']) ? trim($image['url']) : null),
            ],
        ];

        if ($threshold !== null) {
            $payload['threshold'] = $threshold;
        }

        return $this->embeddings($payload);
    }

    /**
     * @return array<string,mixed>
     * @throws RecognitionClientException
     */
    public function getHealth(): array
    {
        $endpoint = $this->buildUrl('/api/v0/health');

        $args = [
            'headers' => $this->buildHeaders(),
            'timeout' => $this->getTimeoutSeconds(),
        ];

        return $this->requestJson('GET', $endpoint, $args);
    }

    public function health(): array
    {
        return $this->getHealth();
    }

    public function getServiceInfo(): array
    {
        $endpoint = $this->buildUrl('/api/v0/service/info');

        return $this->requestJson('GET', $endpoint, [
            'headers' => $this->buildHeaders(),
            'timeout' => $this->getTimeoutSeconds(),
        ]);
    }

    public function getRosterList(int $page = 1, int $perPage = 20, ?string $model = null, bool $includeEmbeddings = false): array
    {
        $modelProfile = $model ?? $this->settings->getModelProfile() ?? 'insightface_w600k';

        $query = [
            'page' => max(1, (int) $page),
            'per_page' => max(1, (int) $perPage),
        ];

        if ($includeEmbeddings) {
            $query['include_embeddings'] = 'true';
        }

        $endpoint = $this->buildUrl(sprintf('/api/v0/roster/%s', rawurlencode($modelProfile)));

        if ($query !== []) {
            $endpoint .= '?' . http_build_query($query);
        }

        return $this->requestJson('GET', $endpoint, [
            'headers' => $this->buildHeaders(),
            'timeout' => $this->getTimeoutSeconds(),
        ]);
    }

    /**
     * @param array<string,mixed> $payload
     *
     * @return array<string,mixed>
     * @throws RecognitionClientException
     */
    private function postJson(string $endpoint, array $payload): array
    {
        $args = [
            'headers' => $this->buildHeaders(),
            'body' => wp_json_encode($payload),
            'timeout' => $this->getTimeoutSeconds(),
        ];

        return $this->requestJson('POST', $endpoint, $args);
    }

    /**
     * @param 'GET'|'POST' $method
     * @param array<string,mixed> $args
     *
     * @return array<string,mixed>
     * @throws RecognitionClientException
     */
    private function requestJson(string $method, string $endpoint, array $args): array
    {
        $attempts = max(1, self::MAX_ATTEMPTS);
        $lastException = null;

        for ($attempt = 0; $attempt < $attempts; $attempt++) {
            if ($method === 'GET') {
                $response = wp_remote_get($endpoint, $args);
            } else {
                $response = wp_remote_post($endpoint, $args);
            }

            if (is_wp_error($response)) {
                /** @var WP_Error $response */
                $lastException = new RecognitionClientException($response->get_error_message());

                if ($this->shouldRetry(0, $attempt, $attempts)) {
                    $this->backoff($attempt);
                    continue;
                }

                throw $lastException;
            }

            $statusCode = wp_remote_retrieve_response_code($response);

            if ($statusCode >= 200 && $statusCode < 300) {
                $body = wp_remote_retrieve_body($response);
                $decoded = json_decode($body, true);

                if (!is_array($decoded)) {
                    throw new RecognitionClientException('Recognition service returned an invalid response payload.');
                }

                return $decoded;
            }

            $body = wp_remote_retrieve_body($response);
            $message = wp_remote_retrieve_response_message($response);
            $errorMessage = $this->buildErrorMessage($statusCode, $message, $body);
            $lastException = new RecognitionClientException($errorMessage, $statusCode);

            if ($this->shouldRetry($statusCode, $attempt, $attempts)) {
                $this->backoff($attempt);
                continue;
            }

            throw $lastException;
        }

        if ($lastException !== null) {
            throw $lastException;
        }

        throw new RecognitionClientException('Recognition service request failed.');
    }


    /**
     * @return array<string,string>
     */
    private function buildHeaders(): array
    {
        $headers = [
            'Accept' => 'application/json',
            'Content-Type' => 'application/json',
        ];

        $apiKey = $this->settings->getApiKey();

        if ($apiKey !== null) {
            $headers['Authorization'] = 'Bearer ' . $apiKey;
        }

        $modelProfile = $this->settings->getModelProfile();

        if ($modelProfile !== null) {
            $headers['X-CAT-Model-Profile'] = $modelProfile;
        }

        return $headers;
    }

    /**
     * @throws RecognitionClientException
     */
    private function buildUrl(string $path): string
    {
        $baseUrl = $this->settings->getBaseUrl();

        if ($baseUrl === null) {
            throw new RecognitionClientException('Recognition service base URL is not configured.');
        }

        return rtrim($baseUrl, '/') . $path;
    }

    private function getTimeoutSeconds(): int
    {
        $milliseconds = $this->settings->getTimeoutMs();

        if ($milliseconds <= 0) {
            $milliseconds = 15000;
        }

        // wp_remote_post expects seconds with decimals.
        return (int) max(5, ceil($milliseconds / 1000));
    }

    private function shouldRetry(int $statusCode, int $attempt, int $maxAttempts): bool
    {
        if ($attempt >= $maxAttempts - 1) {
            return false;
        }

        if ($statusCode === 0) {
            return true;
        }

        if ($statusCode === 408 || $statusCode === 429) {
            return true;
        }

        if ($statusCode >= 500 && $statusCode < 600) {
            return true;
        }

        return false;
    }

    private function backoff(int $attempt): void
    {
        $delayMs = (int) min(1000, self::BASE_RETRY_DELAY_MS * (2 ** $attempt));
        if ($delayMs <= 0) {
            return;
        }

        usleep($delayMs * 1000);
    }

    private function buildErrorMessage(int $statusCode, string $statusMessage, string $body): string
    {
        $message = $statusMessage !== '' ? $statusMessage : 'Unexpected HTTP status';

        $body = trim($body);

        if ($body === '') {
            return sprintf('HTTP %d: %s', $statusCode, $message);
        }

        $decoded = json_decode($body, true);

        if (is_array($decoded)) {
            $details = [];

            foreach (['error', 'message', 'detail'] as $key) {
                if (isset($decoded[$key]) && is_string($decoded[$key]) && trim($decoded[$key]) !== '') {
                    $details[] = trim($decoded[$key]);
                }
            }

            if (isset($decoded['errors']) && is_array($decoded['errors'])) {
                foreach ($decoded['errors'] as $item) {
                    if (is_string($item) && trim($item) !== '') {
                        $details[] = trim($item);
                    } elseif (is_array($item)) {
                        foreach ($item as $value) {
                            if (is_string($value) && trim($value) !== '') {
                                $details[] = trim($value);
                            }
                        }
                    }
                }
            }

            if (!empty($details)) {
                $message .= ': ' . implode('; ', $details);
            }
        } else {
            $message .= ': ' . $body;
        }

        return sprintf('HTTP %d: %s', $statusCode, $message);
    }

    /**
     * Extract face embeddings from an attachment
     *
     * @param int $attachmentId The WordPress attachment ID
     * @param array<int,array<string,mixed>> $faces Array of face data with bbox coordinates
     * @return array<string,mixed> Response with embeddings
     * @throws RecognitionClientException
     */
    public function embedFaces(int $attachmentId, array $faces): array
    {
        // Build payload with face crops
        $crops = [];
        foreach ($faces as $index => $face) {
            $bbox = $face['bbox'] ?? [];
            $crops[] = [
                'attachmentId' => $attachmentId,
                'bbox' => $bbox,
                'index' => $index,
            ];
        }

        $payload = [
            'faces' => $crops,
        ];

        $endpoint = $this->buildUrl('/api/v0/embed-faces');
        return $this->postJson($endpoint, $payload);
    }

    /**
     * Suggest roster matches for embeddings
     *
     * @param array<int,array<float>> $embeddings Array of face embeddings
     * @param int $topK Number of top matches to return per embedding (default 5)
     * @param float $threshold Minimum similarity score (default 0.92)
     * @return array<string,mixed> Response with suggestions
     * @throws RecognitionClientException
     */
    public function suggestMatches(array $embeddings, int $topK = 5, float $threshold = 0.92): array
    {
        $payload = [
            'embeddings' => $embeddings,
            'topK' => $topK,
            'threshold' => $threshold,
        ];

        $endpoint = $this->buildUrl('/api/v0/suggest');
        return $this->postJson($endpoint, $payload);
    }

    /**
     * Cluster face embeddings
     *
     * @param array<int,array<float>> $embeddings Array of face embeddings
     * @param string $algorithm Clustering algorithm ('dbscan' or 'agglomerative')
     * @param float $distanceThreshold Distance threshold for clustering
     * @param int $minSamples Minimum samples for DBSCAN
     * @param string $linkage Linkage method for agglomerative
     * @return array<string,mixed> Response with cluster IDs
     * @throws RecognitionClientException
     */
    public function clusterFaces(
        array $embeddings,
        string $algorithm = 'dbscan',
        float $distanceThreshold = 0.6,
        int $minSamples = 2,
        string $linkage = 'average'
    ): array {
        $payload = [
            'embeddings' => $embeddings,
            'algorithm' => $algorithm,
            'distanceThreshold' => $distanceThreshold,
            'minSamples' => $minSamples,
            'linkage' => $linkage,
        ];

        $endpoint = $this->buildUrl('/api/v0/cluster-unknowns');
        return $this->postJson($endpoint, $payload);
    }

    /**
     * Add an embedding to an existing roster entry (progressive learning)
     *
     * Syncs a confirmed face observation to the FAISS index for improved future suggestions.
     * This enables Apple Photos-style progressive learning where confirmed faces improve
     * the model over time.
     *
     * @param string $rosterId Unique identifier for the roster entry
     * @param string $observationId WordPress observation post ID for deduplication
     * @param array<float> $embedding Face embedding vector (512-dimensional)
     * @param array<string,mixed>|null $metadata Optional metadata (attachmentId, bbox, source, etc.)
     * @return array<string,mixed>|WP_Error Response with sync status or error
     * @throws RecognitionClientException
     */
    public function addRosterEmbedding(
        string $rosterId,
        string $observationId,
        array $embedding,
        ?array $metadata = null
    ): array|WP_Error {
        $payload = [
            'rosterId' => $rosterId,
            'observationId' => $observationId,
            'embedding' => $embedding,
            'model' => 'insightface_w600k',
        ];

        if ($metadata !== null) {
            $payload['metadata'] = $metadata;
        }

        try {
            $endpoint = $this->buildUrl('/api/v0/roster/add-embedding');
            $response = $this->postJson($endpoint, $payload);
            return $response;
        } catch (RecognitionClientException $e) {
            // Check for duplicate (409 Conflict)
            if ($e->getCode() === 409) {
                return new WP_Error(
                    'duplicate_observation',
                    'This observation has already been synced to the FAISS index',
                    ['observationId' => $observationId, 'rosterId' => $rosterId]
                );
            }

            // Check for roster not found (404)
            if ($e->getCode() === 404) {
                return new WP_Error(
                    'roster_not_found',
                    sprintf('Roster entry "%s" not found', $rosterId),
                    ['rosterId' => $rosterId]
                );
            }

            // General error
            return new WP_Error(
                'sync_failed',
                sprintf('Failed to sync embedding: %s', $e->getMessage()),
                ['rosterId' => $rosterId, 'observationId' => $observationId]
            );
        }
    }

    /**
     * Add a roster entry to the Recognition Service
     *
     * @param array{rosterId: string, embedding: array<float>} $payload Roster entry data
     * @return array<string,mixed> Response with status
     * @throws RecognitionClientException
     */
    public function addRosterEntry(array $payload): array
    {
        $endpoint = $this->buildUrl('/api/v0/roster/entries');
        return $this->postJson($endpoint, $payload);
    }

    /**
     * Check if recognition service is healthy
     *
     * @return array{status: string, message?: string}
     * @throws RecognitionClientException
     */
    public function checkHealth(): array
    {
        $endpoint = $this->buildUrl('/health');
        
        try {
            $response = wp_remote_get($endpoint, [
                'timeout' => 5,
                'headers' => $this->buildHeaders(),
            ]);

            if (is_wp_error($response)) {
                throw new RecognitionClientException(
                    'Health check failed: ' . $response->get_error_message(),
                    0
                );
            }

            $code = wp_remote_retrieve_response_code($response);
            if ($code !== 200) {
                return [
                    'status' => 'unhealthy',
                    'message' => 'Service returned non-200 status',
                ];
            }

            $body = wp_remote_retrieve_body($response);
            $data = json_decode($body, true);
            
            return is_array($data) ? $data : ['status' => 'healthy'];
        } catch (RecognitionClientException $e) {
            return [
                'status' => 'unhealthy',
                'message' => $e->getMessage(),
            ];
        }
    }

    /**
     * Get roster statistics from FAISS
     *
     * @return array{totalEmbeddings: int, totalPeople: int, lastSyncAt?: string}
     * @throws RecognitionClientException
     */
    public function getRosterStats(): array
    {
        $endpoint = $this->buildUrl('/api/v0/roster/stats');
        
        try {
            $response = wp_remote_get($endpoint, [
                'timeout' => 5,
                'headers' => $this->buildHeaders(),
            ]);

            if (is_wp_error($response)) {
                throw new RecognitionClientException(
                    'Failed to get roster stats: ' . $response->get_error_message(),
                    0
                );
            }

            $code = wp_remote_retrieve_response_code($response);
            if ($code !== 200) {
                throw new RecognitionClientException(
                    'Roster stats endpoint returned ' . $code,
                    $code
                );
            }

            $body = wp_remote_retrieve_body($response);
            $data = json_decode($body, true);
            
            if (!is_array($data)) {
                throw new RecognitionClientException('Invalid roster stats response');
            }
            
            return $data;
        } catch (RecognitionClientException $e) {
            // Return empty stats on error
            return [
                'totalEmbeddings' => 0,
                'totalPeople' => 0,
            ];
        }
    }
}
