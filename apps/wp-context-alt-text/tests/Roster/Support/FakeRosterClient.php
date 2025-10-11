<?php

declare(strict_types=1);

namespace ContextAltText\Tests\Roster\Support;

use ContextAltText\Roster\RosterClientException;
use ContextAltText\Roster\RosterRemote;

final class FakeRosterClient implements RosterRemote
{
    /** @var array<int,array<string,mixed>> */
    public array $created = [];
    /** @var array<int,array{remoteId:string,payload:array<string,mixed>}> */
    public array $updated = [];
    /** @var array<int,array<string,mixed>> */
    public array $embeddings = [];
    /** @var array<int,array{remoteId:string}> */
    public array $deleted = [];

    /** @var array<string,mixed> */
    public array $responses = [
        'create' => ['id' => 'remote-1'],
        'update' => ['id' => 'remote-1'],
        'embeddings' => ['vectors' => [[0.1, 0.2]]],
    ];

    /** @var array<int,RosterClientException> */
    public array $embeddedFailures = [];

    public function createEntry(array $payload): array
    {
        $this->created[] = $payload;

        if (isset($this->responses['create']['throw']) && $this->responses['create']['throw'] instanceof RosterClientException) {
            throw $this->responses['create']['throw'];
        }

        return $this->responses['create'];
    }

    public function updateEntry(string $remoteId, array $payload): array
    {
        $this->updated[] = [
            'remoteId' => $remoteId,
            'payload' => $payload,
        ];

        if (isset($this->responses['update']['throw']) && $this->responses['update']['throw'] instanceof RosterClientException) {
            throw $this->responses['update']['throw'];
        }

        return $this->responses['update'];
    }

    public function deleteEntry(string $remoteId): bool
    {
        $this->deleted[] = ['remoteId' => $remoteId];

        return true;
    }

    public function generateEmbeddings(array $payload): array
    {
        if ($this->embeddedFailures !== []) {
            throw array_shift($this->embeddedFailures);
        }

        $this->embeddings[] = $payload;

        return $this->responses['embeddings'];
    }
}
