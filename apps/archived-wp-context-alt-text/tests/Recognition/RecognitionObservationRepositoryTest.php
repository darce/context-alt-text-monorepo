<?php

declare(strict_types=1);

use ContextAltText\Recognition\RecognitionObservationRepository;
use PHPUnit\Framework\TestCase;

require_once __DIR__ . '/../bootstrap.php';

final class RecognitionObservationRepositoryTest extends TestCase
{
    protected function setUp(): void
    {
        parent::setUp();
        $GLOBALS['__cat_post_meta'] = [];
        $GLOBALS['__cat_options'] = [];
        $GLOBALS['__cat_terms'] = [];
        $GLOBALS['__cat_object_terms'] = [];
    }

    public function test_store_normalizes_confidence_and_source(): void
    {
        $repository = new RecognitionObservationRepository();

        $repository->store(15, [
            'jobId' => 'job-123',
            'updatedAt' => 1700000000,
            'observations' => [
                [
                    'status' => 'matched',
                    'confidence' => '0.83',
                    'match' => [
                        'confidence' => '0.87',
                    ],
                    'roster' => [
                        'remoteId' => 'remote-99',
                        'name' => 'Example',
                    ],
                ],
            ],
            'summary' => [
                'total' => 1,
                'matched' => 1,
                'needs_review' => 0,
            ],
            'confidenceScore' => '0.91',
            'sourceRemoteId' => 'remote-99',
            'context' => [
                'filename' => 'image.jpg',
                'imageUrl' => 'https://example.test/image.jpg',
            ],
        ]);

        $record = $repository->get(15);

        $this->assertSame('job-123', $record['jobId']);
        $this->assertSame(15, $record['attachmentId']);
        $this->assertSame(0.91, $record['confidenceScore']);
        $this->assertSame('remote-99', $record['sourceRemoteId']);
        $this->assertSame(1, $record['summary']['total']);
        $this->assertSame('image.jpg', $record['context']['filename']);

        $ids = $repository->getRecentAttachmentIds();
        $this->assertSame([15], $ids);

        $records = $repository->getMany([15]);
        $this->assertCount(1, $records);
        $this->assertSame('remote-99', $records[0]['sourceRemoteId']);
    }

    public function test_get_returns_defaults_when_missing(): void
    {
        $repository = new RecognitionObservationRepository();

        $record = $repository->get(42);

        $this->assertNull($record['jobId']);
        $this->assertSame(42, $record['attachmentId']);
        $this->assertSame(0.0, $record['confidenceScore']);
        $this->assertNull($record['sourceRemoteId']);
        $this->assertSame(0, $record['summary']['total']);
        $this->assertSame([], $record['observations']);
    }

    public function test_update_observation_normalizes_status_and_summary(): void
    {
        $repository = new RecognitionObservationRepository();

        $repository->store(21, [
            'jobId' => 'job-test',
            'updatedAt' => 1_700_000_000,
            'observations' => [
                [
                    'observationId' => 'job-test-0',
                    'status' => 'needs_review',
                    'label' => 'Face',
                    'roster' => null,
                ],
            ],
            'summary' => [
                'total' => 1,
                'matched' => 0,
                'needs_review' => 1,
            ],
        ]);

        $updated = $repository->updateObservation(21, 'job-test-0', [
            'status' => 'matched',
            'roster' => [
                'remoteId' => 'remote-1',
                'name' => 'Example User',
            ],
        ]);

        $this->assertNotNull($updated);
        $this->assertSame(21, $updated['attachmentId']);
        $this->assertSame(1, $updated['summary']['matched']);
        $this->assertSame(0, $updated['summary']['needs_review']);
        $this->assertSame('matched', $updated['observations'][0]['status']);
        $this->assertSame('remote-1', $updated['observations'][0]['roster']['remoteId']);
    }

    public function test_get_recent_attachment_ids_supports_offset(): void
    {
        $repository = new RecognitionObservationRepository();

        $repository->store(100, [
            'jobId' => 'job-100',
            'updatedAt' => 100,
            'observations' => [],
            'summary' => [
                'total' => 0,
                'matched' => 0,
                'needs_review' => 0,
            ],
        ]);

        $repository->store(200, [
            'jobId' => 'job-200',
            'updatedAt' => 200,
            'observations' => [],
            'summary' => [
                'total' => 0,
                'matched' => 0,
                'needs_review' => 0,
            ],
        ]);

        $repository->store(300, [
            'jobId' => 'job-300',
            'updatedAt' => 300,
            'observations' => [],
            'summary' => [
                'total' => 0,
                'matched' => 0,
                'needs_review' => 0,
            ],
        ]);

        $firstPage = $repository->getRecentAttachmentIds(2, 0);
        $secondPage = $repository->getRecentAttachmentIds(2, 2);

        $this->assertSame([300, 200], $firstPage);
        $this->assertSame([100], $secondPage);
    }

    public function test_store_syncs_matched_roster_tags(): void
    {
        $repository = new RecognitionObservationRepository();

        $repository->store(42, [
            'jobId' => 'job-42',
            'updatedAt' => 1_700_000_000,
            'observations' => [
                [
                    'observationId' => 'obs-1',
                    'status' => 'matched',
                    'roster' => [
                        'remoteId' => 'remote-abc',
                        'displayName' => 'Example Person',
                    ],
                ],
                [
                    'observationId' => 'obs-2',
                    'status' => 'needs_review',
                ],
            ],
            'summary' => [
                'total' => 2,
                'matched' => 1,
                'needs_review' => 1,
            ],
        ]);

        $tagAssignments = $GLOBALS['__cat_object_terms']['cat_roster_entity'] ?? [];
        $postTagAssignments = $tagAssignments[42] ?? [];

        $this->assertCount(1, $postTagAssignments);

        $termId = $postTagAssignments[0];
        $terms = $GLOBALS['__cat_terms']['cat_roster_entity']['by_id'] ?? [];
        $term = $terms[$termId] ?? null;

        $this->assertNotNull($term);
        $this->assertSame('Example Person', $term['name']);
        $this->assertSame('cat-recognition-remote-abc', $term['slug']);
    }

    public function test_update_observation_clears_managed_tags_when_status_changes(): void
    {
        $repository = new RecognitionObservationRepository();

        $repository->store(55, [
            'jobId' => 'job-55',
            'updatedAt' => 1_700_000_001,
            'observations' => [
                [
                    'observationId' => 'obs-55',
                    'status' => 'matched',
                    'roster' => [
                        'remoteId' => 'remote-xyz',
                        'name' => 'Another Person',
                    ],
                ],
            ],
            'summary' => [
                'total' => 1,
                'matched' => 1,
                'needs_review' => 0,
            ],
        ]);

        $objectTerms = $GLOBALS['__cat_object_terms']['cat_roster_entity'] ?? [];
        $initialAssignments = $objectTerms[55] ?? [];
        $this->assertNotEmpty($initialAssignments);

        $repository->updateObservation(55, 'obs-55', [
            'status' => 'needs_review',
            'roster' => null,
        ]);

        $objectTerms = $GLOBALS['__cat_object_terms']['cat_roster_entity'] ?? [];
        $updatedAssignments = $objectTerms[55] ?? [];

        $this->assertSame([], $updatedAssignments);
    }

    public function test_find_attachment_ids_needing_review_filters_by_type_and_exclusions(): void
    {
        $repository = new RecognitionObservationRepository();

        $repository->store(10, [
            'jobId' => 'job-10',
            'updatedAt' => 100,
            'observations' => [
                [
                    'observationId' => 'obs-10',
                    'status' => 'needs_review',
                    'entityType' => 'person',
                ],
            ],
            'summary' => [
                'total' => 1,
                'matched' => 0,
                'needs_review' => 1,
            ],
        ]);

        $repository->store(11, [
            'jobId' => 'job-11',
            'updatedAt' => 50,
            'observations' => [
                [
                    'observationId' => 'obs-11',
                    'status' => 'matched',
                    'entityType' => 'person',
                ],
            ],
            'summary' => [
                'total' => 1,
                'matched' => 1,
                'needs_review' => 0,
            ],
        ]);

        $repository->store(12, [
            'jobId' => 'job-12',
            'updatedAt' => 200,
            'observations' => [
                [
                    'observationId' => 'obs-12',
                    'status' => 'needs_review',
                    'entityType' => 'animal',
                ],
            ],
            'summary' => [
                'total' => 1,
                'matched' => 0,
                'needs_review' => 1,
            ],
        ]);

        $all = $repository->findAttachmentIdsNeedingReview();
        $this->assertSame([12, 10], $all);

        $people = $repository->findAttachmentIdsNeedingReview('person');
        $this->assertSame([10], $people);

        $excluding = $repository->findAttachmentIdsNeedingReview(null, 20, [12]);
        $this->assertSame([10], $excluding);
    }
}
