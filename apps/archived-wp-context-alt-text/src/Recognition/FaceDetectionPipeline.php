<?php

declare(strict_types=1);

namespace ContextAltText\Recognition;

use DateTimeInterface;

/**
 * Contract for services capable of detecting faces and producing embeddings.
 */
interface FaceDetectionPipeline
{
    /**
     * @return array<int,array{
     *     bbox: array{x:float,y:float,width:float,height:float},
     *     embeddingId: string|null,
     *     clusterId: string|null,
     *     detectedAt: DateTimeInterface|null
     * }>
     */
    public function detectFaces(int $attachmentId): array;
}
