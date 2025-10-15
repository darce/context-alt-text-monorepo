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
}
