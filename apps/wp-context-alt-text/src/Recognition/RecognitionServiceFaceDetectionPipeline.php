<?php

declare(strict_types=1);

namespace ContextAltText\Recognition;

use ContextAltText\Shared\Logger;
use DateTimeImmutable;
use DateTimeInterface;
use function array_key_exists;
use function basename;
use function count;
use function file_exists;
use function function_exists;
use function get_attached_file;
use function getimagesize;
use function is_array;
use function is_numeric;
use function is_string;
use function max;
use function min;
use function time;
use function trim;
use function wp_get_attachment_metadata;
use function wp_get_attachment_url;

/**
 * Detection pipeline that delegates to the recognition service to locate faces.
 */
final class RecognitionServiceFaceDetectionPipeline implements FaceDetectionPipeline
{
    private RecognitionClient $client;

    public function __construct(RecognitionClient $client)
    {
        $this->client = $client;
    }

    /**
     * @return array<int,array{
     *     bbox: array{x:float,y:float,width:float,height:float},
     *     embeddingId: string|null,
     *     clusterId: string|null,
     *     detectedAt: DateTimeInterface|null
     * }>
     */
    public function detectFaces(int $attachmentId): array
    {
        $imageUrl = $this->resolveAttachmentUrl($attachmentId);
        if ($imageUrl === null) {
            Logger::warn('Face detection skipped: attachment URL unavailable.', [
                'attachmentId' => $attachmentId,
            ]);

            return [];
        }

        $dimensions = $this->resolveImageDimensions($attachmentId);
        if ($dimensions['width'] === null || $dimensions['height'] === null) {
            Logger::warn('Face detection skipped: attachment dimensions unavailable.', [
                'attachmentId' => $attachmentId,
            ]);

            return [];
        }

        $payload = [
            'images' => [
                [
                    'image_url' => $imageUrl,
                    'filename' => basename($imageUrl),
                ],
            ],
            'use_roster' => true,
        ];

        try {
            $response = $this->client->analyzeScene($payload);
        } catch (RecognitionClientException $exception) {
            Logger::error('Recognition service analyzeScene failed.', [
                'attachmentId' => $attachmentId,
                'message' => $exception->getMessage(),
                'code' => $exception->getCode(),
            ]);

            return [];
        }

        $results = [];
        $images = $response['results'] ?? [];

        if (!is_array($images) || $images === []) {
            return [];
        }

        foreach ($images as $imageIndex => $result) {
            if (!is_array($result)) {
                continue;
            }

            $entities = $result['detected_entities'] ?? [];
            $matches = $result['roster_matches'] ?? [];

            if (!is_array($entities) || $entities === []) {
                continue;
            }

            foreach ($entities as $entityIndex => $entity) {
                if (!is_array($entity)) {
                    continue;
                }

                $match = $matches[$entityIndex] ?? null;
                if ($this->isResolvedMatch($match)) {
                    continue;
                }

                $bbox = $this->normaliseBoundingBox($entity['bbox'] ?? null, $dimensions);

                if ($bbox === null) {
                    Logger::debug('Skipping detection due to invalid bounding box.', [
                        'attachmentId' => $attachmentId,
                        'imageIndex' => $imageIndex,
                        'entityIndex' => $entityIndex,
                    ]);
                    continue;
                }

                // Extract embedding ID if present
                $embeddingId = null;
                if (isset($entity['embedding_id']) && is_string($entity['embedding_id']) && trim($entity['embedding_id']) !== '') {
                    $embeddingId = trim($entity['embedding_id']);
                } elseif (isset($entity['face_id']) && is_string($entity['face_id']) && trim($entity['face_id']) !== '') {
                    $embeddingId = trim($entity['face_id']);
                }

                // Extract embedding vector if present
                $embeddingVector = null;
                if (isset($entity['face_data']['embedding']) && is_array($entity['face_data']['embedding'])) {
                    $embeddingVector = array_map('floatval', $entity['face_data']['embedding']);
                }

                $results[] = [
                    'bbox' => $bbox,
                    'embeddingId' => $embeddingId,
                    'embeddingVector' => $embeddingVector,
                    'clusterId' => null,
                    'detectedAt' => $this->resolveDetectedAt($entity),
                ];
            }
        }

        return $results;
    }

    private function resolveAttachmentUrl(int $attachmentId): ?string
    {
        if (!function_exists('wp_get_attachment_url')) {
            return null;
        }

        $url = wp_get_attachment_url($attachmentId);

        if (!is_string($url)) {
            return null;
        }

        $trimmed = trim($url);

        return $trimmed !== '' ? $trimmed : null;
    }

    /**
     * @return array{width:?int,height:?int}
     */
    private function resolveImageDimensions(int $attachmentId): array
    {
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

        if (($width === null || $height === null) && function_exists('get_attached_file')) {
            $path = get_attached_file($attachmentId);

            if (is_string($path) && $path !== '' && file_exists($path)) {
                $details = getimagesize($path);

                if (is_array($details) && count($details) >= 2) {
                    if (is_numeric($details[0])) {
                        $width = (int) $details[0];
                    }

                    if (is_numeric($details[1])) {
                        $height = (int) $details[1];
                    }
                }
            }
        }

        return [
            'width' => $width,
            'height' => $height,
        ];
    }

    /**
     * @param mixed $rawBbox
     * @return array{x:float,y:float,width:float,height:float}|null
     */
    private function normaliseBoundingBox(mixed $rawBbox, array $dimensions): ?array
    {
        if (!is_array($rawBbox)) {
            return null;
        }

        $width = $dimensions['width'];
        $height = $dimensions['height'];

        if (!is_numeric($width) || !is_numeric($height) || $width <= 0 || $height <= 0) {
            return null;
        }

        $xMin = $this->floatValue($rawBbox[0] ?? null);
        $yMin = $this->floatValue($rawBbox[1] ?? null);
        $xMax = $this->floatValue($rawBbox[2] ?? null);
        $yMax = $this->floatValue($rawBbox[3] ?? null);

        if ($xMin === null || $yMin === null || $xMax === null || $yMax === null) {
            return null;
        }

        $boxWidth = max(0.0, $xMax - $xMin);
        $boxHeight = max(0.0, $yMax - $yMin);

        if ($boxWidth <= 0.0 || $boxHeight <= 0.0) {
            return null;
        }

        $normalised = [
            'x' => $this->clamp($xMin / $width),
            'y' => $this->clamp($yMin / $height),
            'width' => $this->clamp($boxWidth / $width),
            'height' => $this->clamp($boxHeight / $height),
        ];

        if ($normalised['width'] <= 0.0 || $normalised['height'] <= 0.0) {
            return null;
        }

        return $normalised;
    }

    /**
     * @param mixed $match
     */
    private function isResolvedMatch(mixed $match): bool
    {
        if (!is_array($match)) {
            return false;
        }

        if (array_key_exists('is_match', $match)) {
            return (bool) $match['is_match'];
        }

        if (array_key_exists('meets_threshold', $match)) {
            return (bool) $match['meets_threshold'];
        }

        return false;
    }

    /**
     * @param array<string,mixed> $entity
     */
    private function resolveDetectedAt(array $entity): DateTimeInterface
    {
        $timestamp = time();

        if (isset($entity['detected_at']) && is_numeric($entity['detected_at'])) {
            $timestamp = (int) $entity['detected_at'];
        }

        return new DateTimeImmutable('@' . max(0, $timestamp));
    }

    private function floatValue(mixed $value): ?float
    {
        if (is_numeric($value)) {
            return (float) $value;
        }

        return null;
    }

    private function clamp(float $value): float
    {
        if ($value < 0.0) {
            return 0.0;
        }

        if ($value > 1.0) {
            return 1.0;
        }

        return $value;
    }
}
