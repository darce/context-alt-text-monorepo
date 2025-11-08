<?php

declare(strict_types=1);

namespace ContextAltText\Recognition;

interface ClusterClient
{
    /**
     * @param array<string,mixed> $payload
     * @return array<string,mixed>
     */
    public function requestClustering(array $payload): array;
}
