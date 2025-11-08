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
    /** @var array<int,array{remoteId:string,payload:array<string,mixed>}> */
    public array $appended = [];

    /** @var array<string,mixed> */
    public array $responses = [
        'create' => [
            'success' => true,
            'entry' => [
                'unique_id' => 'remote-1',
                'name' => 'Example',
                'display_name' => 'Example',
                'metadata' => [],
                'reference_images' => [],
                'updated_timestamp' => '2024-01-01T00:00:00Z',
            ],
        ],
        'update' => [
            'message' => 'Reference embedding appended',
            'entry' => [
                'unique_id' => 'remote-1',
                'name' => 'Example',
                'display_name' => 'Example',
                'metadata' => [],
                'reference_images' => [],
                'updated_timestamp' => '2024-01-02T00:00:00Z',
            ],
        ],
        'embeddings' => ['faces' => [['embedding' => [0.1, 0.2]]]],
        'delete' => ['result' => true],
        'append' => ['status' => 'ok'],
    ];

    /** @var array<int,RosterClientException> */
    public array $embeddedFailures = [];

    public function createEntry(array $payload): array
    {
        $this->created[] = $payload;

        if (isset($this->responses['create']['throw']) && $this->responses['create']['throw'] instanceof RosterClientException) {
            throw $this->responses['create']['throw'];
        }

        $response = $this->responses['create'];

        $label = '';
        if (isset($payload['label']) && is_scalar($payload['label'])) {
            $label = (string) $payload['label'];
        } elseif (isset($payload['name']) && is_scalar($payload['name'])) {
            $label = (string) $payload['name'];
        }

        $type = '';
        if (isset($payload['type']) && is_scalar($payload['type'])) {
            $type = (string) $payload['type'];
        } elseif (isset($payload['metadata']['type']) && is_scalar($payload['metadata']['type'])) {
            $type = (string) $payload['metadata']['type'];
        }

        if ($type !== '') {
            if (!isset($response['entry']['metadata']) || !is_array($response['entry']['metadata'])) {
                $response['entry']['metadata'] = [];
            }

            $response['entry']['metadata']['type'] = $type;
        }

        $referenceImages = [];
        if (isset($payload['embeddings']) && is_array($payload['embeddings'])) {
            foreach ($payload['embeddings'] as $embedding) {
                if (!is_array($embedding)) {
                    continue;
                }

                $referenceImages[] = [
                    'image_path' => $embedding['image_path'] ?? null,
                    'metadata' => $embedding['metadata'] ?? [],
                ];
            }
        }

        if ($label !== '') {
            $response['entry']['display_name'] = $label;
            $response['entry']['name'] = $label;
        }

        if ($referenceImages !== []) {
            $response['entry']['reference_images'] = $referenceImages;
        }

        if (!isset($response['entry']['unique_id']) || !is_string($response['entry']['unique_id'])) {
            $response['entry']['unique_id'] = 'remote-' . count($this->created);
        }

        if (!isset($response['id']) && isset($response['entry']['unique_id'])) {
            $response['id'] = $response['entry']['unique_id'];
        }

        return $response;
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

        $response = $this->responses['update'];

        $label = '';
        if (isset($payload['label']) && is_scalar($payload['label'])) {
            $label = (string) $payload['label'];
        } elseif (isset($payload['name']) && is_scalar($payload['name'])) {
            $label = (string) $payload['name'];
        }

        if ($label !== '') {
            $response['entry']['display_name'] = $label;
            $response['entry']['name'] = $label;
        }

        $type = '';
        if (isset($payload['type']) && is_scalar($payload['type'])) {
            $type = (string) $payload['type'];
        } elseif (isset($payload['metadata']['type']) && is_scalar($payload['metadata']['type'])) {
            $type = (string) $payload['metadata']['type'];
        }

        if ($type !== '') {
            if (!isset($response['entry']['metadata']) || !is_array($response['entry']['metadata'])) {
                $response['entry']['metadata'] = [];
            }

            $response['entry']['metadata']['type'] = $type;
        }

        $response['entry']['unique_id'] = $remoteId;
        $response['id'] = $remoteId;

        return $response;
    }

    public function deleteEntry(string $remoteId): bool
    {
        $this->deleted[] = ['remoteId' => $remoteId];

        if (isset($this->responses['delete']['throw']) && $this->responses['delete']['throw'] instanceof RosterClientException) {
            throw $this->responses['delete']['throw'];
        }

        if (array_key_exists('result', $this->responses['delete'])) {
            return (bool) $this->responses['delete']['result'];
        }

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

    public function appendReferenceEmbedding(string $remoteId, array $payload): array
    {
        $this->appended[] = [
            'remoteId' => $remoteId,
            'payload' => $payload,
        ];

        if (isset($this->responses['append']['throw']) && $this->responses['append']['throw'] instanceof RosterClientException) {
            throw $this->responses['append']['throw'];
        }

        return $this->responses['append'];
    }
}
