<?php

declare(strict_types=1);

namespace ContextAltText\Infrastructure\Repositories;

use ContextAltText\Domain\Clustering\UnknownFace;
use ContextAltText\Infrastructure\Database\UnknownFaceTableInstaller;
use DateTimeImmutable;
use DateTimeInterface;
use JsonException;
use RuntimeException;

final class UnknownFaceRepository
{
    /** @var \wpdb */
    private $wpdb;

    /** @var bool */
    private $tableChecked = false;

    /**
     * @param \wpdb|null $database Optional WordPress database instance.
     */
    public function __construct($database = null)
    {
        if ($database === null) {
            global $wpdb;
            $database = $wpdb;
        }

        $this->wpdb = $database;
    }

    public function saveUnknownFace(UnknownFace $face): int
    {
        $this->ensureTableExists();

        $table = $this->tableName();
        $bboxJson = $this->encodeBbox($face->bbox());
        $detectedAt = $this->formatDate($face->detectedAt());
        $resolvedAt = $this->formatNullableDate($face->resolvedAt());

        if ($face->id() === null) {
            $data = [
                'attachment_id' => $face->attachmentId(),
                'bbox_json' => $bboxJson,
                'embedding_id' => $face->embeddingId(),
                'embedding_vector' => $this->encodeEmbeddingVector($face->embeddingVector()),
                'thumbnail' => $face->thumbnail(),
                'cluster_id' => $face->clusterId(),
                'detected_at' => $detectedAt,
                'resolved_at' => $resolvedAt,
                'roster_id' => $face->rosterId(),
            ];

            $format = ['%d', '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s'];

            $this->wpdb->insert($table, $data, $format);
            $insertId = (int) ($this->wpdb->insert_id ?? 0);

            if ($insertId <= 0) {
                throw new RuntimeException('Failed to insert unknown face record.');
            }

            return $insertId;
        }

        $data = [
            'attachment_id' => $face->attachmentId(),
            'bbox_json' => $bboxJson,
            'embedding_id' => $face->embeddingId(),
            'embedding_vector' => $this->encodeEmbeddingVector($face->embeddingVector()),
            'thumbnail' => $face->thumbnail(),
            'cluster_id' => $face->clusterId(),
            'detected_at' => $detectedAt,
            'resolved_at' => $resolvedAt,
            'roster_id' => $face->rosterId(),
        ];

        $where = ['id' => $face->id()];
        $format = ['%d', '%s', '%s', '%s', '%s', '%s', '%s', '%s', '%s'];
        $whereFormat = ['%d'];

        $this->wpdb->update($table, $data, $where, $format, $whereFormat);

        return (int) $face->id();
    }

    /**
     * @return UnknownFace[]
     */
    public function findUnresolvedFaces(int $limit = 100): array
    {
        $this->ensureTableExists();

        $table = $this->tableName();
        $sql = $this->wpdb->prepare(
            "SELECT * FROM {$table} WHERE resolved_at IS NULL ORDER BY detected_at ASC LIMIT %d",
            $limit
        );

        error_log(sprintf('[UnknownFaceRepository] Query: %s', $sql));
        
        $rows = $this->wpdb->get_results($sql, \ARRAY_A);

        error_log(sprintf('[UnknownFaceRepository] Found %d unresolved faces (limit: %d)', count($rows), $limit));

        return array_map(fn(array $row) => $this->hydrate($row), $rows);
    }

    /**
     * @return UnknownFace[]
     */
    public function findFacesByCluster(string $clusterId): array
    {
        $table = $this->tableName();
        
        // Check if clusterId is in the format "face-{id}" (generated from face database ID)
        if (preg_match('/^face-(\d+)$/', $clusterId, $matches)) {
            $faceId = (int) $matches[1];
            $sql = $this->wpdb->prepare(
                "SELECT * FROM {$table} WHERE id = %d AND resolved_at IS NULL",
                $faceId
            );
        } else {
            // Look up by actual cluster_id column
            $sql = $this->wpdb->prepare(
                "SELECT * FROM {$table} WHERE cluster_id = %s AND resolved_at IS NULL ORDER BY detected_at ASC",
                $clusterId
            );
        }

        $rows = $this->wpdb->get_results($sql, \ARRAY_A);

        return array_map(fn(array $row) => $this->hydrate($row), $rows);
    }

    public function findFaceById(int $faceId): ?UnknownFace
    {
        $table = $this->tableName();
        $sql = $this->wpdb->prepare(
            "SELECT * FROM {$table} WHERE id = %d",
            $faceId
        );

        /** @var array<string,mixed>|null $row */
        $row = $this->wpdb->get_row($sql, \ARRAY_A);

        if (!is_array($row)) {
            return null;
        }

        return $this->hydrate($row);
    }

    /**
     * @param array<int,int> $faceIds
     * @return UnknownFace[]
     */
    public function findFacesByIds(array $faceIds): array
    {
        $normalized = [];

        foreach ($faceIds as $faceId) {
            $id = (int) $faceId;
            if ($id > 0) {
                $normalized[$id] = $id;
            }
        }

        if ($normalized === []) {
            return [];
        }

        $table = $this->tableName();
        $placeholders = implode(', ', array_fill(0, count($normalized), '%d'));

        /** @var int[] $values */
        $values = array_values($normalized);

        $sql = $this->wpdb->prepare(
            "SELECT * FROM {$table} WHERE id IN ({$placeholders}) AND resolved_at IS NULL ORDER BY detected_at ASC",
            ...$values
        );

        $rows = $this->wpdb->get_results($sql, \ARRAY_A);

        return array_map(fn(array $row) => $this->hydrate($row), $rows);
    }

    /**
     * @return UnknownFace[]
     */
    public function findFacesByAttachment(int $attachmentId): array
    {
        $table = $this->tableName();
        $sql = $this->wpdb->prepare(
            "SELECT * FROM {$table} WHERE attachment_id = %d ORDER BY detected_at ASC",
            $attachmentId
        );

        $rows = $this->wpdb->get_results($sql, \ARRAY_A);

        return array_map(fn(array $row) => $this->hydrate($row), $rows);
    }

    public function markFaceAsResolved(int $faceId, string $rosterId): bool
    {
        $table = $this->tableName();
        $resolvedAt = gmdate('Y-m-d H:i:s');

        $sql = $this->wpdb->prepare(
            "UPDATE {$table} SET resolved_at = %s, roster_id = %s WHERE id = %d",
            $resolvedAt,
            $rosterId,
            $faceId
        );

        return (bool) $this->wpdb->query($sql);
    }

    public function updateClusterAssignment(int $faceId, string $clusterId): bool
    {
        $table = $this->tableName();
        $sql = $this->wpdb->prepare(
            "UPDATE {$table} SET cluster_id = %s WHERE id = %d",
            $clusterId,
            $faceId
        );

        return (bool) $this->wpdb->query($sql);
    }

    private function tableName(): string
    {
        return $this->wpdb->prefix . 'cat_unknown_faces';
    }

    /**
     * Ensure the table exists before trying to use it.
     * This handles cases where the plugin was updated but not reactivated.
     */
    private function ensureTableExists(): void
    {
        if ($this->tableChecked) {
            return;
        }

        // Always run installer to check for missing columns
        $installer = new UnknownFaceTableInstaller($this->wpdb);
        $installer->install();

        $this->tableChecked = true;
    }

    /**
     * @param array{x:float,y:float,width:float,height:float} $bbox
     */
    private function encodeBbox(array $bbox): string
    {
        try {
            return json_encode($bbox, JSON_THROW_ON_ERROR);
        } catch (JsonException $exception) {
            throw new RuntimeException('Failed to encode bounding box.', 0, $exception);
        }
    }

    /**
     * @param float[]|null $embeddingVector
     */
    private function encodeEmbeddingVector(?array $embeddingVector): ?string
    {
        if ($embeddingVector === null) {
            return null;
        }

        try {
            return json_encode($embeddingVector, JSON_THROW_ON_ERROR);
        } catch (JsonException $exception) {
            throw new RuntimeException('Failed to encode embedding vector.', 0, $exception);
        }
    }

    private function formatDate(DateTimeInterface $date): string
    {
        return $date->format('Y-m-d H:i:s');
    }

    private function formatNullableDate(?DateTimeInterface $date): ?string
    {
        return $date ? $this->formatDate($date) : null;
    }

    /**
     * @param array<string,mixed> $row
     */
    private function hydrate(array $row): UnknownFace
    {
        $bbox = $this->decodeBbox($row['bbox_json']);
        $embeddingVector = $this->decodeEmbeddingVector($row['embedding_vector'] ?? null);
        $thumbnail = isset($row['thumbnail']) && is_string($row['thumbnail']) ? $row['thumbnail'] : null;

        return new UnknownFace(
            isset($row['id']) ? (int) $row['id'] : null,
            (int) $row['attachment_id'],
            $bbox,
            $row['embedding_id'] !== null ? (string) $row['embedding_id'] : null,
            $embeddingVector,
            $thumbnail,
            $row['cluster_id'] !== null ? (string) $row['cluster_id'] : null,
            new DateTimeImmutable((string) $row['detected_at']),
            isset($row['resolved_at']) && $row['resolved_at'] !== null ? new DateTimeImmutable((string) $row['resolved_at']) : null,
            $row['roster_id'] !== null ? (string) $row['roster_id'] : null
        );
    }

    /**
     * @return array{x:float,y:float,width:float,height:float}
     */
    private function decodeBbox(string $json): array
    {
        try {
            $data = json_decode($json, true, 512, JSON_THROW_ON_ERROR);
        } catch (JsonException $exception) {
            throw new RuntimeException('Failed to decode bounding box.', 0, $exception);
        }

        return [
            'x' => (float) ($data['x'] ?? 0.0),
            'y' => (float) ($data['y'] ?? 0.0),
            'width' => (float) ($data['width'] ?? 0.0),
            'height' => (float) ($data['height'] ?? 0.0),
        ];
    }

    /**
     * @return float[]|null
     */
    private function decodeEmbeddingVector(?string $json): ?array
    {
        if ($json === null || $json === '') {
            return null;
        }

        try {
            $data = json_decode($json, true, 512, JSON_THROW_ON_ERROR);
        } catch (JsonException $exception) {
            error_log('[UnknownFaceRepository] Failed to decode embedding vector: ' . $exception->getMessage());
            return null;
        }

        if (!is_array($data)) {
            return null;
        }

        return array_map('floatval', $data);
    }
}
