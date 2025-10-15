<?php

declare(strict_types=1);

namespace ContextAltText\Roster;

use ContextAltText\Recognition\RecognitionSettings;
use function array_filter;
use function array_merge;
use function ceil;
use function implode;
use function is_array;
use function is_numeric;
use function is_string;
use function json_decode;
use function max;
use function rawurlencode;
use function rtrim;
use function sprintf;
use function trim;
use function usleep;
use function wp_json_encode;
use function wp_remote_request;
use function wp_remote_retrieve_body;
use function wp_remote_retrieve_response_code;
use function wp_remote_retrieve_response_message;

/**
 * Lightweight HTTP client for interacting with the recognition service roster APIs.
 */
class RosterClient implements RosterRemote
{
    private const MAX_ATTEMPTS = 3;
    private const BASE_RETRY_DELAY_MS = 200;

    private RecognitionSettings $settings;

    public function __construct(RecognitionSettings $settings)
    {
        $this->settings = $settings;
    }

    /**
     * Create a roster entry via POST /api/v0/roster.
     *
     * @param array<string,mixed> $payload
     *
     * @return array<string,mixed>
     * @throws RosterClientException
     */
    public function createEntry(array $payload): array
    {
        [$path, $body] = $this->prepareCreatePayload($payload);

        return $this->requestJson('POST', $path, $body);
    }

    /**
     * Update an existing roster entry via PATCH /api/v0/roster/{remote_id}.
     *
     * @param array<string,mixed> $payload
     *
     * @return array<string,mixed>
     * @throws RosterClientException
     */
    public function updateEntry(string $remoteId, array $payload): array
    {
        if (isset($payload['embeddings']) && is_array($payload['embeddings']) && $payload['embeddings'] !== []) {
            $first = $payload['embeddings'][0];
            $embedding = $this->normalizeEmbeddingVector($first['embedding'] ?? null);

            if ($embedding !== []) {
                $appendPayload = [
                    'embedding' => $embedding,
                ];

                if (isset($first['metadata']) && is_array($first['metadata'])) {
                    $appendPayload['metadata'] = $first['metadata'];
                }

                if (!empty($first['image_path']) && is_string($first['image_path'])) {
                    $appendPayload['image_path'] = $first['image_path'];
                }

                $appendPayload['model'] = $this->getModelProfile();

                return $this->requestJson('POST', sprintf('/api/v0/roster/%s/embeddings', rawurlencode($remoteId)), $appendPayload);
            }
        }

        $path = sprintf('/api/v0/roster/%s', rawurlencode($remoteId));

        return $this->requestJson('PATCH', $path, $payload);
    }

    /**
     * Delete a roster entry via DELETE /api/v0/roster/{remote_id}.
     *
     * @throws RosterClientException
     */
    public function deleteEntry(string $remoteId): bool
    {
        $path = sprintf('/api/v0/roster/%s', rawurlencode($remoteId));
        $this->requestVoid('DELETE', $path);

        return true;
    }

    /**
     * Generate embeddings for roster images via POST /api/v0/embeddings.
     *
     * @param array<string,mixed> $payload
     *
     * @return array<string,mixed>
     * @throws RosterClientException
     */
    public function generateEmbeddings(array $payload): array
    {
        return $this->requestJson('POST', '/api/v0/embeddings', $payload);
    }

    /**
     * Append a reference embedding to an existing roster entry via POST /api/v0/roster/{remote_id}/embeddings.
     *
     * @param array<string,mixed> $payload
     *
     * @return array<string,mixed>
     * @throws RosterClientException
     */
    public function appendReferenceEmbedding(string $remoteId, array $payload): array
    {
        $path = sprintf('/api/v0/roster/%s/embeddings', rawurlencode($remoteId));

        return $this->requestJson('POST', $path, $payload);
    }

    /**
     * @param array<string,mixed>|null $payload
     *
     * @return array<string,mixed>
     * @throws RosterClientException
     */
    private function requestJson(string $method, string $path, ?array $payload = null): array
    {
        $response = $this->sendRequest($method, $path, $payload);

        $statusCode = wp_remote_retrieve_response_code($response);
        $body = wp_remote_retrieve_body($response);

        $decoded = json_decode($body, true);

        if ($statusCode < 200 || $statusCode >= 300) {
            $message = $this->buildErrorMessage($statusCode, wp_remote_retrieve_response_message($response), $body);

            throw new RosterClientException($message, $statusCode);
        }

        if (!is_array($decoded)) {
            throw new RosterClientException('Roster service returned an invalid response payload.', $statusCode);
        }

        return $decoded;
    }

    /**
     * @param array<string,mixed>|null $payload
     *
     * @throws RosterClientException
     */
    private function requestVoid(string $method, string $path, ?array $payload = null): void
    {
        $response = $this->sendRequest($method, $path, $payload);
        $statusCode = wp_remote_retrieve_response_code($response);

        if ($statusCode < 200 || $statusCode >= 300) {
            $body = wp_remote_retrieve_body($response);
            $message = $this->buildErrorMessage($statusCode, wp_remote_retrieve_response_message($response), $body);

            throw new RosterClientException($message, $statusCode);
        }
    }

    /**
     * @param array<string,mixed>|null $payload
     * @return array<string,mixed>
     * @throws RosterClientException
     */
    private function sendRequest(string $method, string $path, ?array $payload = null): array
    {
        $endpoint = $this->buildUrl($path);

        $headers = [
            'Accept' => 'application/json',
            'Content-Type' => 'application/json',
        ];

        $apiKey = $this->settings->getApiKey();
        if ($apiKey !== null) {
            $headers['Authorization'] = 'Bearer ' . $apiKey;
        }

        $args = [
            'method' => $method,
            'headers' => $headers,
            'timeout' => $this->getTimeoutSeconds(),
        ];

        if ($payload !== null) {
            $args['body'] = wp_json_encode($payload);
        }

        $attempts = self::MAX_ATTEMPTS;
        $lastError = null;

        for ($attempt = 0; $attempt < $attempts; $attempt++) {
            $response = wp_remote_request($endpoint, $args);

            if (is_array($response)) {
                $statusCode = wp_remote_retrieve_response_code($response);

                if ($statusCode >= 200 && $statusCode < 300) {
                    return $response;
                }

                $lastError = new RosterClientException(
                    $this->buildErrorMessage(
                        $statusCode,
                        wp_remote_retrieve_response_message($response),
                        wp_remote_retrieve_body($response)
                    ),
                    $statusCode
                );

                if ($this->shouldRetry($statusCode, $attempt, $attempts)) {
                    $this->backoff($attempt);
                    continue;
                }

                throw $lastError;
            }

            $lastError = new RosterClientException('Roster service request failed.');

            if ($this->shouldRetry(0, $attempt, $attempts)) {
                $this->backoff($attempt);
                continue;
            }

            throw $lastError;
        }

        if ($lastError instanceof RosterClientException) {
            throw $lastError;
        }

        throw new RosterClientException('Roster service request failed.');
    }

    /**
     * @throws RosterClientException
     */
    private function buildUrl(string $path): string
    {
        $baseUrl = $this->settings->getBaseUrl();

        if ($baseUrl === null) {
            throw new RosterClientException('Recognition service base URL is not configured.');
        }

        return rtrim($baseUrl, '/') . $path;
    }

    private function getTimeoutSeconds(): int
    {
        $milliseconds = $this->settings->getTimeoutMs();

        if ($milliseconds <= 0) {
            $milliseconds = 15000;
        }

        return (int) max(5, (int) ceil($milliseconds / 1000));
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
        $message = trim($statusMessage) !== '' ? trim($statusMessage) : 'Unexpected HTTP status';
        $body = trim($body);

        if ($body === '') {
            return sprintf('HTTP %d: %s', $statusCode, $message);
        }

        $decoded = json_decode($body, true);

        if (!is_array($decoded)) {
            return sprintf('HTTP %d: %s: %s', $statusCode, $message, $body);
        }

        $details = [];

        foreach (['error', 'message', 'detail'] as $key) {
            if (isset($decoded[$key]) && is_string($decoded[$key])) {
                $value = trim($decoded[$key]);
                if ($value !== '') {
                    $details[] = $value;
                }
            }
        }

        if (isset($decoded['errors']) && is_array($decoded['errors'])) {
            foreach ($decoded['errors'] as $error) {
                if (is_string($error) && trim($error) !== '') {
                    $details[] = trim($error);
                } elseif (is_array($error)) {
                    foreach ($error as $nested) {
                        if (is_string($nested) && trim($nested) !== '') {
                            $details[] = trim($nested);
                        }
                    }
                }
            }
        }

        if (empty($details)) {
            return sprintf('HTTP %d: %s', $statusCode, $message);
        }

        return sprintf('HTTP %d: %s: %s', $statusCode, $message, implode('; ', $details));
    }

    /**
     * @return array{0:string,1:array<string,mixed>}
     */
    private function prepareCreatePayload(array $payload): array
    {
        $label = isset($payload['label']) ? trim((string) $payload['label']) : '';
        if ($label === '') {
            throw new RosterClientException('Roster entry requires a label.', 400);
        }

        $embeddings = $payload['embeddings'] ?? [];
        if (!is_array($embeddings) || $embeddings === []) {
            throw new RosterClientException('Roster entry is missing embeddings.', 422);
        }

        $first = $embeddings[0];
        $embeddingVector = $this->normalizeEmbeddingVector($first['embedding'] ?? null);

        if ($embeddingVector === []) {
            throw new RosterClientException('Roster entry embeddings could not be generated.', 422);
        }

        $metadata = [];
        if (isset($payload['metadata']) && is_array($payload['metadata'])) {
            $metadata = $payload['metadata'];
        }

        if (isset($first['metadata']) && is_array($first['metadata'])) {
            $metadata = array_merge($metadata, $first['metadata']);
        }

        if (!empty($payload['type']) && is_string($payload['type'])) {
            $metadata['type'] = $payload['type'];
        }

        $metadata['source'] = 'context-alt-text';

        $body = [
            'name' => $label,
            'embedding' => $embeddingVector,
            'metadata' => $metadata,
        ];

        if (!empty($first['image_path']) && is_string($first['image_path'])) {
            $body['image_path'] = $first['image_path'];
        }

        $model = $this->getModelProfile();
        $path = sprintf('/api/v0/roster/%s/upsert', rawurlencode($model));

        return [$path, $body];
    }

    /**
     * @param mixed $embedding
     * @return array<int,float>
     */
    private function normalizeEmbeddingVector($embedding): array
    {
        if (!is_array($embedding)) {
            return [];
        }

        $vector = [];
        foreach ($embedding as $value) {
            if (is_numeric($value)) {
                $vector[] = (float) $value;
            }
        }

        return $vector;
    }

    private function getModelProfile(): string
    {
        $profile = $this->settings->getModelProfile();

        if ($profile === null || trim($profile) === '') {
            return 'insightface_w600k';
        }

        return trim($profile);
    }
}
