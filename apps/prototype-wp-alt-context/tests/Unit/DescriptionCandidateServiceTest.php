<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\Services\DescriptionCandidateService;
use AltContext\Tests\TestCase;

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
