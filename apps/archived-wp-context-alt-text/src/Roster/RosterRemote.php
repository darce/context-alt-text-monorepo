<?php

declare(strict_types=1);

namespace ContextAltText\Roster;

interface RosterRemote
{
    /**
     * @param array<string,mixed> $payload
     *
     * @return array<string,mixed>
     */
    public function createEntry(array $payload): array;

    /**
     * @param array<string,mixed> $payload
     *
     * @return array<string,mixed>
     */
    public function updateEntry(string $remoteId, array $payload): array;

    public function deleteEntry(string $remoteId): bool;

    /**
     * @param array<string,mixed> $payload
     *
     * @return array<string,mixed>
     */
    public function generateEmbeddings(array $payload): array;

    /**
     * @param array<string,mixed> $payload
     *
     * @return array<string,mixed>
     */
    public function appendReferenceEmbedding(string $remoteId, array $payload): array;
}
