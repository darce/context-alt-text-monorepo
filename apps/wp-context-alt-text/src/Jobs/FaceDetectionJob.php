<?php

declare(strict_types=1);

namespace ContextAltText\Jobs;

use ContextAltText\Domain\Clustering\UnknownFace;
use ContextAltText\Infrastructure\Repositories\UnknownFaceRepository;
use ContextAltText\Recognition\FaceDetectionPipeline;
use DateTimeImmutable;
use DateTimeInterface;

use function max;
use function min;
use function sprintf;

final class FaceDetectionJob
{
    private FaceDetectionPipeline $pipeline;
    private UnknownFaceRepository $repository;

    public function __construct(FaceDetectionPipeline $pipeline, UnknownFaceRepository $repository)
    {
        $this->pipeline = $pipeline;
        $this->repository = $repository;
    }

    public function execute(int $attachmentId): void
    {
        $detections = $this->pipeline->detectFaces($attachmentId);

        error_log(sprintf('[FaceDetectionJob] Attachment %d: Found %d detections', $attachmentId, count($detections)));

        // Load existing faces for this attachment to check for duplicates
        $existingFaces = $this->repository->findFacesByAttachment($attachmentId);
        $existingBboxes = $this->extractBboxes($existingFaces);

        error_log(sprintf('[FaceDetectionJob] Attachment %d: Found %d existing faces', $attachmentId, count($existingFaces)));

        $savedCount = 0;
        $skippedCount = 0;

        foreach ($detections as $detection) {
            // Skip if a face with similar bbox already exists for this attachment
            if ($this->isDuplicateFace($detection['bbox'], $existingBboxes)) {
                $skippedCount++;
                continue;
            }

            $face = $this->hydrateUnknownFace($attachmentId, $detection);
            $faceId = $this->repository->saveUnknownFace($face);
            error_log(sprintf('[FaceDetectionJob] Saved face ID %d for attachment %d', $faceId, $attachmentId));
            $savedCount++;
        }

        if ($skippedCount > 0) {
            error_log(sprintf('[FaceDetectionJob] Attachment %d: Skipped %d duplicate faces', $attachmentId, $skippedCount));
        }
    }

    /**
     * @param array{
     *     bbox: array{x:float,y:float,width:float,height:float},
     *     embeddingId: string|null,
     *     embeddingVector: float[]|null,
     *     clusterId: string|null,
     *     detectedAt: DateTimeInterface|null
     * } $detection
     */
    private function hydrateUnknownFace(int $attachmentId, array $detection): UnknownFace
    {
        $detectedAt = $detection['detectedAt'] ?? null;
        if (!$detectedAt instanceof DateTimeInterface) {
            $detectedAt = new DateTimeImmutable('now');
        }

        return new UnknownFace(
            null,
            $attachmentId,
            $detection['bbox'],
            $detection['embeddingId'] ?? null,
            $detection['embeddingVector'] ?? null,
            $detection['clusterId'] ?? null,
            $detectedAt,
            null,
            null
        );
    }

    /**
     * Extract bounding boxes from existing faces.
     *
     * @param UnknownFace[] $faces
     * @return array<int,array{x:float,y:float,width:float,height:float}>
     */
    private function extractBboxes(array $faces): array
    {
        $bboxes = [];
        foreach ($faces as $face) {
            $bboxes[] = $face->bbox();
        }
        return $bboxes;
    }

    /**
     * Check if a face with similar bounding box already exists.
     * Uses IoU (Intersection over Union) to determine similarity.
     *
     * @param array{x:float,y:float,width:float,height:float} $bbox
     * @param array<int,array{x:float,y:float,width:float,height:float}> $existingBboxes
     */
    private function isDuplicateFace(array $bbox, array $existingBboxes): bool
    {
        foreach ($existingBboxes as $existingBbox) {
            $iou = $this->calculateIoU($bbox, $existingBbox);
            
            error_log(sprintf('[FaceDetectionJob] IoU comparison: %.4f (threshold: 0.8)', $iou));
            
            // If IoU is > 0.8, consider it a duplicate (same face region)
            if ($iou > 0.8) {
                error_log('[FaceDetectionJob] Detected duplicate face, skipping');
                return true;
            }
        }
        return false;
    }

    /**
     * Calculate Intersection over Union (IoU) between two bounding boxes.
     *
     * @param array{x:float,y:float,width:float,height:float} $bbox1
     * @param array{x:float,y:float,width:float,height:float} $bbox2
     */
    private function calculateIoU(array $bbox1, array $bbox2): float
    {
        // Calculate coordinates for both boxes
        $x1_min = $bbox1['x'];
        $y1_min = $bbox1['y'];
        $x1_max = $bbox1['x'] + $bbox1['width'];
        $y1_max = $bbox1['y'] + $bbox1['height'];

        $x2_min = $bbox2['x'];
        $y2_min = $bbox2['y'];
        $x2_max = $bbox2['x'] + $bbox2['width'];
        $y2_max = $bbox2['y'] + $bbox2['height'];

        // Calculate intersection area
        $intersect_x_min = max($x1_min, $x2_min);
        $intersect_y_min = max($y1_min, $y2_min);
        $intersect_x_max = min($x1_max, $x2_max);
        $intersect_y_max = min($y1_max, $y2_max);

        // Check if there is no intersection
        if ($intersect_x_max <= $intersect_x_min || $intersect_y_max <= $intersect_y_min) {
            return 0.0;
        }

        $intersect_width = $intersect_x_max - $intersect_x_min;
        $intersect_height = $intersect_y_max - $intersect_y_min;
        $intersection = $intersect_width * $intersect_height;

        // Calculate union area
        $area1 = $bbox1['width'] * $bbox1['height'];
        $area2 = $bbox2['width'] * $bbox2['height'];
        $union = $area1 + $area2 - $intersection;

        // Avoid division by zero
        if ($union <= 0) {
            return 0.0;
        }

        return $intersection / $union;
    }
}
