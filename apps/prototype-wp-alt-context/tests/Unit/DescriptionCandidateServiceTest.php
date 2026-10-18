<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\Services\DescriptionCandidateService;
use AltContext\Api\Services\DescriptionHistoryService;
use AltContext\Tests\TestCase;
use WP_Error;

/**
 * @covers \AltContext\Api\Services\DescriptionCandidateService
 */
class DescriptionCandidateServiceTest extends TestCase
{
    public function testListsMissingAltCandidatesWithStableOrderingAndExclusions(): void
    {
        $this->plantAttachment(30, 'No alt later', 'image/jpeg', '');
        $this->plantAttachment(10, 'Has human alt', 'image/jpeg', 'A human-written description.');
        $this->plantAttachment(20, 'No alt first', 'image/png', '');
        $this->plantAttachment(40, 'Unsupported pdf', 'application/pdf', '');

        $service = new DescriptionCandidateService();
        $result = $service->list_missing_alt_candidates(limit: 10, offset: 0);

        $this->assertSame(10, $result['limit']);
        $this->assertSame(0, $result['offset']);
        $this->assertSame(2, $result['total_candidates']);
        $this->assertSame(array(20, 30), array_column($result['candidates'], 'media_id'));
        $this->assertSame('missing_alt', $result['candidates'][0]['reason']);
        $this->assertSame('20-no-alt-first.jpg', $result['candidates'][0]['filename']);
        $this->assertSame('', $result['candidates'][0]['current_alt_text']);

        // Unified row set: every candidate row also carries the CLI-consumed
        // fields, with candidate_reason mirroring reason (reconciliation rule).
        $this->assertSame('No alt first', $result['candidates'][0]['title']);
        $this->assertSame('image/png', $result['candidates'][0]['mime_type']);
        $this->assertSame('missing_alt', $result['candidates'][0]['candidate_reason']);
        $this->assertFalse($result['candidates'][0]['has_alt_text']);
        $this->assertNull($result['candidates'][0]['provenance']);

        $this->assertSame(2, $result['total_exclusions']);
        $this->assertSame(
            array(
                array('media_id' => 10, 'reason' => 'has_alt_text'),
                array('media_id' => 40, 'reason' => 'unsupported_mime'),
            ),
            array_map(
                static fn (array $row): array => array(
                    'media_id' => $row['media_id'],
                    'reason'   => $row['reason'],
                ),
                $result['exclusions']
            )
        );

        // Exclusion rows carry the same unified set so both consumers read
        // consistent fields off any partition.
        $this->assertTrue($result['exclusions'][0]['has_alt_text']);
        $this->assertSame('has_alt_text', $result['exclusions'][0]['candidate_reason']);
        $this->assertSame('A human-written description.', $result['exclusions'][0]['current_alt_text']);
    }

    public function testPaginatesCandidatesAfterFiltering(): void
    {
        $this->plantAttachment(30, 'Third', 'image/jpeg', '');
        $this->plantAttachment(10, 'First', 'image/jpeg', '');
        $this->plantAttachment(20, 'Second', 'image/webp', '');

        $service = new DescriptionCandidateService();
        $result = $service->list_missing_alt_candidates(limit: 1, offset: 1);

        $this->assertSame(3, $result['total_candidates']);
        $this->assertSame(1, $result['limit']);
        $this->assertSame(1, $result['offset']);
        $this->assertSame(array(20), array_column($result['candidates'], 'media_id'));
    }

    public function testLimitIsClampedToServiceMaximum(): void
    {
        $this->plantAttachment(1, 'One', 'image/jpeg', '');

        $service = new DescriptionCandidateService();
        $result = $service->list_missing_alt_candidates(limit: 500, offset: -10);

        $this->assertSame(100, $result['limit']);
        $this->assertSame(0, $result['offset']);
    }

    /**
     * WBUX-5-R16-BR-06 pin 2: provenance-gap item (alt present + pending marker)
     * is not a missing-alt candidate — reason stays has_alt_text.
     */
    public function testProvenanceGapItemIsHasAltTextExclusionNotMissingAltCandidate(): void
    {
        $this->plantAttachment(60, 'Gap with alt', 'image/jpeg', 'Alt present after partial write.');
        $GLOBALS['__ac_post_meta'][60]['_acx_description_provenance_pending'] = array(
            'run_id'     => 'single_image',
            'draft_hash' => hash('sha256', 'Alt present after partial write.'),
        );

        $service = new DescriptionCandidateService();
        $result  = $service->list_missing_alt_candidates(limit: 10, offset: 0);

        $this->assertSame(0, $result['total_candidates']);
        $this->assertSame(array(), $result['candidates']);
        $this->assertSame(1, $result['total_exclusions']);
        $this->assertSame(60, $result['exclusions'][0]['media_id']);
        $this->assertSame('has_alt_text', $result['exclusions'][0]['reason']);
        $this->assertTrue($result['exclusions'][0]['has_alt_text']);
    }

    /**
     * WBUX-5-R16-BR-06 pin 4: fully stamped item remains a has_alt_text exclusion.
     */
    public function testFullyStampedItemIsHasAltTextExclusion(): void
    {
        $this->plantAttachment(70, 'Stamped', 'image/jpeg', 'Generated stamp.');
        $GLOBALS['__ac_post_meta'][70]['_acx_description_provenance'] = array(
            'alt_text_draft' => 'Generated stamp.',
            'model_id'       => 'local-v1',
        );

        $service = new DescriptionCandidateService();
        $result  = $service->list_missing_alt_candidates(limit: 10, offset: 0);

        $this->assertSame(0, $result['total_candidates']);
        $this->assertSame(70, $result['exclusions'][0]['media_id']);
        $this->assertSame('has_alt_text', $result['exclusions'][0]['reason']);
    }

    /**
     * WBUX-5-S2C3C-BR-01 [TEST-06] headline: empty alt + acx_alt_decorative
     * marker classifies as decorative; empty alt without the marker stays
     * missing_alt. These two states must not share a bucket (MECE / [NAV-05]).
     *
     * Discriminates against today's broken code, which maps every empty alt to
     * missing_alt regardless of the marker.
     */
    public function testEmptyAltWithDecorativeMarkerClassifiesAsDecorativeNotMissingAlt(): void
    {
        // Decorative: empty alt + durable marker.
        $this->plantAttachment(80, 'Spacer', 'image/jpeg', '');
        $GLOBALS['__ac_post_meta'][80]['acx_alt_decorative'] = '1';

        // Genuinely missing: empty alt, no marker.
        $this->plantAttachment(81, 'Undescribed', 'image/png', '');

        $service = new DescriptionCandidateService();
        $result  = $service->list_missing_alt_candidates(limit: 10, offset: 0);

        // Only the undescribed image is a candidate.
        $this->assertSame(1, $result['total_candidates']);
        $this->assertSame(array(81), array_column($result['candidates'], 'media_id'));
        $this->assertSame('missing_alt', $result['candidates'][0]['reason']);
        $this->assertSame('missing_alt', $result['candidates'][0]['candidate_reason']);
        $this->assertFalse($result['candidates'][0]['has_alt_text']);

        // Decorative lands in exclusions with reason decorative (not missing_alt).
        $this->assertSame(1, $result['total_exclusions']);
        $this->assertSame(80, $result['exclusions'][0]['media_id']);
        $this->assertSame('decorative', $result['exclusions'][0]['reason']);
        $this->assertSame('decorative', $result['exclusions'][0]['candidate_reason']);
        $this->assertFalse($result['exclusions'][0]['has_alt_text']);
        $this->assertSame('', $result['exclusions'][0]['current_alt_text']);

        // CLI status path shares build_row — same classification for both ids.
        $status = $service->get_status_for_media_ids(array(80, 81));
        $this->assertCount(2, $status);
        $byId = array();
        foreach ($status as $row) {
            $byId[(int) $row['media_id']] = $row;
        }
        $this->assertSame('decorative', $byId[80]['reason']);
        $this->assertSame('decorative', $byId[80]['candidate_reason']);
        $this->assertSame('missing_alt', $byId[81]['reason']);
        $this->assertSame('missing_alt', $byId[81]['candidate_reason']);
    }

    /**
     * A-02: after un-mark via record_correction(…, false), classification is
     * missing_alt — the image returns to the describe-candidate queue.
     * Disk state is produced by the real un-mark write path, not planted meta
     * that only looks post-un-mark [TEST-15]. human_edit from the correction
     * is intentionally ignored by the classifier.
     */
    public function testEmptyAltWithoutDecorativeMarkerAfterUnmarkIsMissingAlt(): void
    {
        // Start decorative: empty alt + marker. post_type required for correction.
        $this->plantAttachment(84, 'Unmarked spacer', 'image/jpeg', '');
        $GLOBALS['__ac_posts'][84]->post_type = 'attachment';
        $GLOBALS['__ac_post_meta'][84]['acx_alt_decorative'] = '1';

        $candidate = new DescriptionCandidateService();
        $before    = $candidate->get_status_for_media_ids(array(84));
        $this->assertSame('decorative', $before[0]['reason']);

        $correction = (new DescriptionHistoryService())->record_correction(84, '', false);
        $this->assertNotInstanceOf(WP_Error::class, $correction);
        $this->assertSame('', get_post_meta(84, 'acx_alt_decorative', true));
        $this->assertArrayNotHasKey('acx_alt_decorative', $GLOBALS['__ac_post_meta'][84] ?? []);

        $status = $candidate->get_status_for_media_ids(array(84));
        $this->assertSame('missing_alt', $status[0]['reason']);
        $this->assertSame('missing_alt', $status[0]['candidate_reason']);

        $result = $candidate->list_missing_alt_candidates(limit: 10, offset: 0);
        $ids    = array_column($result['candidates'], 'media_id');
        $this->assertContains(84, $ids);
        $this->assertNotContains(
            84,
            array_column($result['exclusions'], 'media_id'),
            'Unmarked empty-alt row must not stay in decorative exclusions'
        );
    }

    /**
     * Stale-marker precedence: non-empty alt wins over a leftover decorative
     * marker. has_alt is checked before the marker so a real description is
     * never hidden behind bookkeeping.
     */
    public function testNonEmptyAltWithStaleDecorativeMarkerClassifiesAsHasAltText(): void
    {
        $this->plantAttachment(82, 'Described with stale flag', 'image/jpeg', 'A real description.');
        $GLOBALS['__ac_post_meta'][82]['acx_alt_decorative'] = '1';

        $service = new DescriptionCandidateService();
        $result  = $service->list_missing_alt_candidates(limit: 10, offset: 0);

        $this->assertSame(0, $result['total_candidates']);
        $this->assertSame(1, $result['total_exclusions']);
        $this->assertSame(82, $result['exclusions'][0]['media_id']);
        $this->assertSame('has_alt_text', $result['exclusions'][0]['reason']);
        $this->assertSame('has_alt_text', $result['exclusions'][0]['candidate_reason']);
        $this->assertTrue($result['exclusions'][0]['has_alt_text']);
        // Must not classify as decorative when a real alt is present.
        $this->assertNotSame('decorative', $result['exclusions'][0]['reason']);

        $status = $service->get_status_for_media_ids(array(82));
        $this->assertSame('has_alt_text', $status[0]['reason']);
        $this->assertNotSame('decorative', $status[0]['reason']);
    }

    /**
     * Unsupported mime and not_found still win over a decorative marker.
     */
    public function testUnsupportedMimeAndNotFoundWinOverDecorativeMarker(): void
    {
        $this->plantAttachment(83, 'Decorative pdf', 'application/pdf', '');
        $GLOBALS['__ac_post_meta'][83]['acx_alt_decorative'] = '1';

        $service = new DescriptionCandidateService();
        $result  = $service->list_missing_alt_candidates(limit: 10, offset: 0);

        $this->assertSame(0, $result['total_candidates']);
        $this->assertSame(1, $result['total_exclusions']);
        $this->assertSame('unsupported_mime', $result['exclusions'][0]['reason']);
        $this->assertSame('unsupported_mime', $result['exclusions'][0]['candidate_reason']);
        $this->assertNotSame('decorative', $result['exclusions'][0]['reason']);

        // not_found: id with no planted post, but marker present in meta.
        $GLOBALS['__ac_post_meta'][9999]['acx_alt_decorative'] = '1';
        $GLOBALS['__ac_post_meta'][9999]['_wp_attachment_image_alt'] = '';
        $status = $service->get_status_for_media_ids(array(9999));
        $this->assertCount(1, $status);
        $this->assertSame('not_found', $status[0]['reason']);
        $this->assertSame('not_found', $status[0]['candidate_reason']);
        $this->assertNotSame('decorative', $status[0]['reason']);
    }

    private function plantAttachment(int $id, string $title, string $mimeType, string $altText): void
    {
        $slug = strtolower(str_replace(' ', '-', $title));
        $GLOBALS['__ac_posts'][$id] = (object) array(
            'ID'         => $id,
            'post_title' => $title,
        );
        $GLOBALS['__ac_get_posts_results'][] = $GLOBALS['__ac_posts'][$id];
        $GLOBALS['__ac_attachment_mimes'][$id] = $mimeType;
        $GLOBALS['__ac_attached_file'][$id] = "/tmp/{$id}-{$slug}.jpg";
        $GLOBALS['__ac_post_meta'][$id]['_wp_attachment_image_alt'] = $altText;
    }
}
