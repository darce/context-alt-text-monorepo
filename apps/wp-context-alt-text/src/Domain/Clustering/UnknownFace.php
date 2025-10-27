<?php

declare(strict_types=1);

namespace ContextAltText\Domain\Clustering;

use DateTimeInterface;

/**
 * Value object representing a stored unknown face awaiting user confirmation.
 */
final class UnknownFace
{
    private ?int $id;
    private int $attachmentId;
    /** @var array{x:float,y:float,width:float,height:float} */
    private array $bbox;
    private ?string $embeddingId;
    /** @var float[]|null */
    private ?array $embeddingVector;
    private ?string $clusterId;
    private DateTimeInterface $detectedAt;
    private ?DateTimeInterface $resolvedAt;
    private ?string $rosterId;

    /**
     * @param array{x:float,y:float,width:float,height:float} $bbox
     * @param float[]|null $embeddingVector
     */
    public function __construct(
        ?int $id,
        int $attachmentId,
        array $bbox,
        ?string $embeddingId,
        ?array $embeddingVector,
        ?string $clusterId,
        DateTimeInterface $detectedAt,
        ?DateTimeInterface $resolvedAt = null,
        ?string $rosterId = null
    ) {
        $this->id = $id;
        $this->attachmentId = $attachmentId;
        $this->bbox = $bbox;
        $this->embeddingId = $embeddingId;
        $this->embeddingVector = $embeddingVector;
        $this->clusterId = $clusterId;
        $this->detectedAt = $detectedAt;
        $this->resolvedAt = $resolvedAt;
        $this->rosterId = $rosterId;
    }

    public function id(): ?int
    {
        return $this->id;
    }

    public function attachmentId(): int
    {
        return $this->attachmentId;
    }

    /**
     * @return array{x:float,y:float,width:float,height:float}
     */
    public function bbox(): array
    {
        return $this->bbox;
    }

    public function embeddingId(): ?string
    {
        return $this->embeddingId;
    }

    /**
     * @return float[]|null
     */
    public function embeddingVector(): ?array
    {
        return $this->embeddingVector;
    }

    public function clusterId(): ?string
    {
        return $this->clusterId;
    }

    public function detectedAt(): DateTimeInterface
    {
        return $this->detectedAt;
    }

    public function resolvedAt(): ?DateTimeInterface
    {
        return $this->resolvedAt;
    }

    public function rosterId(): ?string
    {
        return $this->rosterId;
    }
}
