<?php

declare(strict_types=1);

namespace ContextAltText\Recognition;

final class NullFaceDetectionPipeline implements FaceDetectionPipeline
{
    public function detectFaces(int $attachmentId): array
    {
        return [];
    }
}
