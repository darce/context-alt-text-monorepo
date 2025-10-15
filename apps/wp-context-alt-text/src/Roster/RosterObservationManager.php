<?php

declare(strict_types=1);

namespace ContextAltText\Roster;

use ContextAltText\Domain\Roster\RosterService;
use ContextAltText\Recognition\RecognitionJobService;
use ContextAltText\Recognition\RecognitionObservationRepository;
use function array_filter;
use function in_array;
use function is_array;
use function is_numeric;
use function is_scalar;
use function sanitize_text_field;

final class RosterObservationManager
{
    private const MAX_AUTO_RETRY_ATTACHMENTS = 10;

    private RecognitionObservationRepository $observations;
    private RecognitionJobService $jobs;
    private ?\ContextAltText\Domain\Roster\RosterService $roster;

    public function __construct(
        RecognitionObservationRepository $observations,
        RecognitionJobService $jobs,
        ?\ContextAltText\Domain\Roster\RosterService $roster = null
    ) {
        $this->observations = $observations;
        $this->jobs = $jobs;
        $this->roster = $roster;
    }

    /**
     * @param array<string,mixed> $entry
     * @param array<string,mixed>|null $resolution
     */
    public function retryPendingForEntry(array $entry, ?array $resolution = null): void
    {
        $remoteId = $this->extractScalar($entry['remoteId'] ?? $entry['remote_id'] ?? null);

        if ($remoteId === '') {
            return;
        }

        $entityType = $this->extractScalar($entry['type'] ?? null);

        $exclude = [];

        if ($resolution !== null && isset($resolution['attachmentId']) && is_numeric($resolution['attachmentId'])) {
            $exclude[] = (int) $resolution['attachmentId'];
        }

        $attachmentIds = $this->observations->findAttachmentIdsNeedingReview(
            $entityType !== '' ? $entityType : null,
            self::MAX_AUTO_RETRY_ATTACHMENTS * 5,
            $exclude
        );

        if ($attachmentIds === []) {
            return;
        }

        $this->jobs->submit($attachmentIds);
    }

    /**
     * @param array<int,array<string,mixed>> $entries
     */
    public function retryPendingForEntries(array $entries): void
    {
        foreach ($entries as $entry) {
            if (!is_array($entry)) {
                continue;
            }

            $this->retryPendingForEntry($entry);
        }
    }

    /**
     * @param array<string,mixed> $resolution
     * @param array<string,mixed> $entry
     * @return array<string,mixed>|null
     */
    public function resolveObservationWithRoster(array $resolution, array $entry): ?array
    {
        $attachmentId = (int) ($resolution['attachmentId'] ?? 0);
        $observationId = $this->extractScalar($resolution['observationId'] ?? null);

        if ($attachmentId <= 0 || $observationId === '') {
            return null;
        }

        $status = $this->extractScalar($resolution['status'] ?? 'matched');
        if (!in_array($status, ['matched', 'needs_review'], true)) {
            $status = 'matched';
        }

        $updates = ['status' => $status];

        $label = $this->resolveLabel($resolution, $entry);

        if ($label !== '') {
            $updates['label'] = $label;
        }

        $entityType = $this->resolveEntityType($resolution, $entry);

        if ($entityType !== '') {
            $updates['entityType'] = $entityType;
        }

        $roster = [];
        $remoteId = $this->extractScalar($entry['remoteId'] ?? $entry['remote_id'] ?? null);

        if ($remoteId !== '') {
            $roster['remoteId'] = $remoteId;
        }

        if ($label !== '') {
            $roster['name'] = $label;
            $roster['displayName'] = $label;
        }

        if ($entityType !== '') {
            $roster['type'] = $entityType;
        }

        if ($roster !== []) {
            $updates['roster'] = $roster;
        }

        if ($status === 'matched') {
            $updates['match'] = [
                'isMatch' => true,
                'confidence' => 1.0,
                'similarity' => 1.0,
                'threshold' => 0.0,
            ];
        }

        $record = $this->observations->updateObservation($attachmentId, $observationId, $updates);

        if ($status === 'matched' && $remoteId !== '') {
            $this->attachReferenceToRoster($attachmentId, $observationId, $remoteId);
        }

        return $record;
    }

    /**
     * @param array<int,array<string,mixed>> $entries
     * @return array<int,array<string,mixed>>
     */
    public function autoAssignPending(array $entries): array
    {
        if ($entries === []) {
            return [];
        }

        $rosterIndex = [];

        foreach ($entries as $entry) {
            if (!is_array($entry)) {
                continue;
            }

            $remoteId = $this->extractScalar($entry['remoteId'] ?? $entry['remote_id'] ?? null);

            if ($remoteId === '') {
                continue;
            }

            $rosterIndex[$remoteId] = [
                'label' => $this->extractScalar($entry['label'] ?? $entry['name'] ?? null),
                'type' => $this->extractScalar($entry['type'] ?? null),
            ];
        }

        if ($rosterIndex === []) {
            return [];
        }

        $attachmentIds = $this->observations->findAttachmentIdsNeedingReview(
            null,
            self::MAX_AUTO_RETRY_ATTACHMENTS * 5
        );

        if ($attachmentIds === []) {
            return [];
        }

        $records = $this->observations->getMany($attachmentIds);
        $assignments = [];

        foreach ($records as $record) {
            if (!is_array($record)) {
                continue;
            }

            $attachmentId = (int) ($record['attachmentId'] ?? 0);

            if ($attachmentId <= 0) {
                continue;
            }

            $observations = isset($record['observations']) && is_array($record['observations'])
                ? $record['observations']
                : [];

            foreach ($observations as $observation) {
                if (!is_array($observation)) {
                    continue;
                }

                $status = $this->extractScalar($observation['status'] ?? null);
                if ($status !== 'needs_review') {
                    continue;
                }

                $observationId = $this->extractScalar($observation['observationId'] ?? null);
                if ($observationId === '') {
                    continue;
                }

                if ($this->attemptMatchFromPrimaryCandidate($rosterIndex, $attachmentId, $observation, $observationId, $assignments)) {
                    continue;
                }

                $candidates = isset($observation['candidates']) && is_array($observation['candidates'])
                    ? $observation['candidates']
                    : [];

                foreach ($candidates as $candidate) {
                    if (!is_array($candidate)) {
                        continue;
                    }

                    if ($this->attemptMatchFromCandidate(
                        $rosterIndex,
                        $attachmentId,
                        $observation,
                        $candidate,
                        $observationId,
                        $assignments
                    )) {
                        break;
                    }
                }
            }
        }

        return $assignments;
    }

    /**
     * @param array<string,array<string,string>> $rosterIndex
     * @param array<string,mixed> $observation
     * @param array<int,array<string,mixed>> $assignments
     */
    private function attemptMatchFromPrimaryCandidate(
        array $rosterIndex,
        int $attachmentId,
        array $observation,
        string $observationId,
        array &$assignments
    ): bool {
        $matchData = isset($observation['match']) && is_array($observation['match'])
            ? $observation['match']
            : [];

        $matchRemoteId = $this->extractScalar($matchData['remoteId'] ?? ($observation['roster']['remoteId'] ?? null));

        if (
            $matchRemoteId === ''
            || empty($matchData['isMatch'])
            || !isset($rosterIndex[$matchRemoteId])
        ) {
            return false;
        }

        $entryMeta = $rosterIndex[$matchRemoteId];
        $label = $entryMeta['label'] !== '' ? $entryMeta['label'] : $this->extractScalar($observation['label'] ?? null);
        $type = $entryMeta['type'] !== '' ? $entryMeta['type'] : $this->extractScalar($observation['entityType'] ?? null);

        $similarity = $this->normalizeFloat($matchData['similarity'] ?? 1.0);
        $threshold = $this->normalizeFloat($matchData['threshold'] ?? 0.0);

        if ($threshold <= 0.0 && $similarity >= 0.85) {
            $threshold = 0.85;
        }

        $updates = [
            'status' => 'matched',
            'match' => [
                'isMatch' => true,
                'similarity' => $similarity,
                'confidence' => $this->normalizeFloat($matchData['confidence'] ?? $similarity),
                'threshold' => $threshold,
            ],
            'roster' => array_filter([
                'remoteId' => $matchRemoteId,
                'name' => $entryMeta['label'] !== '' ? $entryMeta['label'] : $matchRemoteId,
                'displayName' => $entryMeta['label'] !== '' ? $entryMeta['label'] : $matchRemoteId,
                'type' => $type,
            ], static fn($value) => $value !== null && $value !== ''),
        ];

        if ($label !== '') {
            $updates['label'] = $label;
        }

        if ($type !== '') {
            $updates['entityType'] = $type;
        }

        $updatedRecord = $this->observations->updateObservation($attachmentId, $observationId, $updates);

        if ($updatedRecord === null) {
            return false;
        }

        $assignments[] = [
            'attachmentId' => $attachmentId,
            'observationId' => $observationId,
            'remoteId' => $matchRemoteId,
        ];

        return true;
    }

    /**
     * @param array<string,array<string,string>> $rosterIndex
     * @param array<string,mixed> $observation
     * @param array<string,mixed> $candidate
     * @param array<int,array<string,mixed>> $assignments
     */
    private function attemptMatchFromCandidate(
        array $rosterIndex,
        int $attachmentId,
        array $observation,
        array $candidate,
        string $observationId,
        array &$assignments
    ): bool {
        $candidateRemoteId = $this->extractScalar(
            $candidate['remoteId'] ?? $candidate['unique_id'] ?? null
        );

        if ($candidateRemoteId === '' || !isset($rosterIndex[$candidateRemoteId])) {
            return false;
        }

        $meetsThreshold = !empty($candidate['meetsThreshold']) || !empty($candidate['meets_threshold']);
        $similarity = $this->normalizeFloat($candidate['similarity'] ?? 0.0);

        $threshold = $this->normalizeFloat(
            $candidate['threshold'] ?? ($observation['match']['threshold'] ?? 0.0)
        );

        if (!$meetsThreshold && $threshold > 0.0 && $similarity >= $threshold) {
            $meetsThreshold = true;
        }

        if (!$meetsThreshold && $threshold <= 0.0 && $similarity >= 0.85) {
            $meetsThreshold = true;
        }

        if (!$meetsThreshold) {
            return false;
        }

        $entryMeta = $rosterIndex[$candidateRemoteId];
        $label = $entryMeta['label'] !== '' ? $entryMeta['label'] : $this->extractScalar($observation['label'] ?? null);
        $type = $entryMeta['type'] !== '' ? $entryMeta['type'] : $this->extractScalar($observation['entityType'] ?? null);

        $updates = [
            'status' => 'matched',
            'match' => [
                'isMatch' => true,
                'similarity' => $similarity !== 0.0 ? $similarity : $this->normalizeFloat($candidate['confidence'] ?? 1.0),
                'confidence' => $this->normalizeFloat($candidate['confidence'] ?? ($candidate['similarity'] ?? 1.0)),
                'threshold' => $threshold,
            ],
            'roster' => array_filter([
                'remoteId' => $candidateRemoteId,
                'name' => $entryMeta['label'] !== '' ? $entryMeta['label'] : $candidateRemoteId,
                'displayName' => $entryMeta['label'] !== '' ? $entryMeta['label'] : $candidateRemoteId,
                'type' => $type,
            ], static fn($value) => $value !== null && $value !== ''),
        ];

        if ($label !== '') {
            $updates['label'] = $label;
        }

        if ($type !== '') {
            $updates['entityType'] = $type;
        }

        $updatedRecord = $this->observations->updateObservation($attachmentId, $observationId, $updates);

        if ($updatedRecord === null) {
            return false;
        }

        $this->attachReferenceToRoster($attachmentId, $observationId, $candidateRemoteId);

        $assignments[] = [
            'attachmentId' => $attachmentId,
            'observationId' => $observationId,
            'remoteId' => $candidateRemoteId,
        ];

        return true;
    }

    private function attachReferenceToRoster(int $attachmentId, string $observationId, string $remoteId): void
    {
        if ($this->roster === null || $remoteId === '') {
            return;
        }

        $record = $this->observations->get($attachmentId);

        if (!is_array($record) || !isset($record['observations']) || !is_array($record['observations'])) {
            return;
        }

        $matchedObservation = null;

        foreach ($record['observations'] as $observation) {
            if (!is_array($observation)) {
                continue;
            }

            if (($observation['observationId'] ?? '') === $observationId) {
                $matchedObservation = $observation;
                break;
            }
        }

        if ($matchedObservation === null) {
            return;
        }

        $context = isset($record['context']) && is_array($record['context']) ? $record['context'] : [];
        $imageUrl = isset($context['imageUrl']) && is_scalar($context['imageUrl'])
            ? (string) $context['imageUrl']
            : null;

        $reference = [
            'attachment_id' => $attachmentId,
            'image_url' => $imageUrl,
            'metadata' => array_filter([
                'observationId' => $observationId,
                'source' => 'recognition',
                'matchedAt' => gmdate('c'),
                'similarity' => $matchedObservation['match']['similarity'] ?? null,
                'confidence' => $matchedObservation['match']['confidence'] ?? null,
                'boundingBox' => $matchedObservation['boundingBox'] ?? null,
            ], static fn($value) => $value !== null && $value !== ''),
        ];

        if (function_exists('wp_get_attachment_image_url')) {
            $thumbnail = wp_get_attachment_image_url($attachmentId, 'thumbnail');

            if (is_string($thumbnail) && $thumbnail !== '') {
                $reference['metadata']['thumbnailUrl'] = $thumbnail;
            }
        }

        $attached = $this->roster->attachReferenceImage($remoteId, $reference);

        $linkContext = [
            'observationId' => $observationId,
            'matchedAt' => gmdate('c'),
        ];

        $this->roster->linkMediaToEntry($remoteId, $attachmentId, $linkContext);
    }

    private function resolveLabel(array $resolution, array $entry): string
    {
        $label = $this->extractScalar($resolution['label'] ?? null);

        if ($label !== '') {
            return $label;
        }

        return $this->extractScalar($entry['label'] ?? $entry['name'] ?? null);
    }

    private function resolveEntityType(array $resolution, array $entry): string
    {
        $entityType = $this->extractScalar($resolution['entityType'] ?? null);

        if ($entityType !== '') {
            return $entityType;
        }

        return $this->extractScalar($entry['type'] ?? null);
    }

    /**
     * @param mixed $value
     */
    private function extractScalar($value): string
    {
        if (is_scalar($value)) {
            return sanitize_text_field((string) $value);
        }

        return '';
    }

    /**
     * @param mixed $value
     */
    private function normalizeFloat($value): float
    {
        if (is_numeric($value)) {
            return (float) $value;
        }

        return 0.0;
    }
}
