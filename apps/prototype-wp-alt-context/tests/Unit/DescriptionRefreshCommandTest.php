<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\Services\DescriptionContentRefreshService;
use AltContext\Cli\DescriptionRefreshCommand;
use AltContext\Tests\TestCase;
use RuntimeException;

/**
 * @covers \AltContext\Cli\DescriptionRefreshCommand
 */
class DescriptionRefreshCommandTest extends TestCase
{
    protected function setUp(): void
    {
        parent::setUp();
        \WP_CLI::reset_cli_messages();
    }

    public function testInvokeDryRunReportsCandidatesWithoutUpdatingContent(): void
    {
        $this->setPostMeta(42, '_wp_attachment_image_alt', 'New bridge alt text');
        $post = (object) [
            'ID' => 101,
            'post_type' => 'post',
            'post_title' => 'Block post',
            'post_content' => '<img class="wp-image-42" src="/bridge.jpg" alt="Old bridge alt" />',
        ];
        $GLOBALS['__ac_posts'][101] = $post;
        $GLOBALS['__ac_get_posts_results'] = [$post];

        (new DescriptionRefreshCommand())->__invoke(['42'], ['limit' => 10]);

        $this->assertSame('Old bridge alt', $this->getEmbeddedAlt($GLOBALS['__ac_posts'][101]->post_content));
        $this->assertSame([], $GLOBALS['__ac_updated_posts']);
        $this->assertStringContainsString('dry_run=1', \WP_CLI::$messages['success'][0] ?? '');
        $this->assertStringContainsString('candidates=1', \WP_CLI::$messages['success'][0] ?? '');
        // dry_run summary has no changed/failed — do not fabricate [rg-015].
        $this->assertStringNotContainsString('changed=', \WP_CLI::$messages['success'][0] ?? '');
        $this->assertStringNotContainsString('failed=', \WP_CLI::$messages['success'][0] ?? '');
    }

    public function testInvokeApplyUpdatesContent(): void
    {
        $this->setPostMeta(42, '_wp_attachment_image_alt', 'New bridge alt text');
        $post = (object) [
            'ID' => 101,
            'post_type' => 'post',
            'post_title' => 'Block post',
            'post_content' => '<img class="wp-image-42" src="/bridge.jpg" alt="Old bridge alt" />',
        ];
        $GLOBALS['__ac_posts'][101] = $post;
        $GLOBALS['__ac_get_posts_results'] = [$post];

        (new DescriptionRefreshCommand())->__invoke(['42'], ['apply' => true, 'limit' => 10]);

        $this->assertSame('New bridge alt text', $this->getEmbeddedAlt($GLOBALS['__ac_posts'][101]->post_content));
        $this->assertStringContainsString('dry_run=0', \WP_CLI::$messages['success'][0] ?? '');
        $this->assertStringContainsString('changed=1', \WP_CLI::$messages['success'][0] ?? '');
        $this->assertStringContainsString('failed=0', \WP_CLI::$messages['success'][0] ?? '');
        // R18-BR-03 normal path: skipped key present in real apply() summary.
        $this->assertStringContainsString('skipped=', \WP_CLI::$messages['success'][0] ?? '');
        $this->assertStringContainsString('Description refresh complete.', \WP_CLI::$messages['success'][0] ?? '');
    }

    /**
     * R16-BR-03 / [HAI-13] [rg-015]: post-update failure must surface on the
     * CLI as failed=N (not success with silent zero), with actionable rows.
     * R17-BR-11: leading sentence must not claim "complete" on failure.
     */
    public function testInvokeApplyReportsPostUpdateFailures(): void
    {
        $this->setPostMeta(42, '_wp_attachment_image_alt', 'New bridge alt text');
        $originalContent = '<img class="wp-image-42" src="/bridge.jpg" alt="Old bridge alt" />';
        $post = (object) [
            'ID' => 601,
            'post_type' => 'post',
            'post_title' => 'Unwritable post',
            'post_content' => $originalContent,
        ];
        $GLOBALS['__ac_posts'][601] = $post;
        $GLOBALS['__ac_get_posts_results'] = [$post];
        $GLOBALS['__ac_wp_update_post_fail'][601] = true;

        $threw = false;
        try {
            (new DescriptionRefreshCommand())->__invoke(['42'], ['apply' => true, 'limit' => 10]);
        } catch (RuntimeException $e) {
            $threw = true;
            $this->assertStringContainsString('failed=1', $e->getMessage());
            $this->assertStringContainsString('Description refresh failed.', $e->getMessage());
            $this->assertStringNotContainsString('Description refresh complete.', $e->getMessage());
        }

        $this->assertTrue($threw, 'WP_CLI::error must throw for non-zero exit on failures');
        $this->assertSame([], \WP_CLI::$messages['success']);
        $this->assertNotEmpty(\WP_CLI::$messages['error']);
        $error = \WP_CLI::$messages['error'][0] ?? '';
        $this->assertStringContainsString('failed=1', $error);
        $this->assertStringContainsString('changed=0', $error);
        $this->assertStringContainsString('candidates=1', $error);
        $this->assertStringContainsString('Description refresh failed.', $error);
        $this->assertStringNotContainsString('Description refresh complete.', $error);

        $logs = implode("\n", \WP_CLI::$messages['log']);
        $this->assertStringContainsString('post_id=601', $logs);
        $this->assertStringContainsString('media_id=42', $logs);
        $this->assertStringContainsString('post_update_failed', $logs);

        // Content must remain intact on failed write.
        $this->assertSame($originalContent, $GLOBALS['__ac_posts'][601]->post_content);
    }

    /**
     * BR-141: CLI path shares the service normalizer — entity-encoded meta
     * must still apply once and then report already_current on dry_run.
     */
    public function testInvokeApplyIsIdempotentWithEntityEncodedMeta(): void
    {
        $this->setPostMeta(42, '_wp_attachment_image_alt', 'x &lt;= y');
        $post = (object) [
            'ID' => 101,
            'post_type' => 'post',
            'post_title' => 'Entity alt post',
            'post_content' => '<img class="wp-image-42" src="/cmp.jpg" alt="old comparison" />',
        ];
        $GLOBALS['__ac_posts'][101] = $post;
        $GLOBALS['__ac_get_posts_results'] = [$post];

        $command = new DescriptionRefreshCommand();
        $command->__invoke(['42'], ['apply' => true, 'limit' => 10]);

        $this->assertStringContainsString('changed=1', \WP_CLI::$messages['success'][0] ?? '');
        $this->assertStringNotContainsString('old comparison', $GLOBALS['__ac_posts'][101]->post_content);
        $this->assertCount(1, $GLOBALS['__ac_updated_posts']);

        \WP_CLI::reset_cli_messages();
        $command->__invoke(['42'], ['limit' => 10]);

        $this->assertStringContainsString('candidates=0', \WP_CLI::$messages['success'][0] ?? '');
        $this->assertStringContainsString('skipped=1', \WP_CLI::$messages['success'][0] ?? '');
        // dry_run must not touch content again.
        $this->assertCount(1, $GLOBALS['__ac_updated_posts']);
    }

    /**
     * R17-BR-04: summary omits `failed` while result['failed'] is non-empty →
     * non-zero exit. Absence of the key is never treated as zero failures.
     */
    public function testApplyMissingFailedKeyWithFailedRowsExitsNonZero(): void
    {
        $service = new FixedRefreshService([
            'summary' => [
                'dry_run' => false,
                'candidates' => 1,
                'changed' => 0,
                // deliberately omit 'failed'
                'skipped' => 0,
            ],
            'failed' => [
                [
                    'post_id' => 701,
                    'media_id' => 42,
                    'reason' => 'post_update_failed',
                ],
            ],
            'changed' => [],
            'skipped' => [],
        ]);

        $threw = false;
        try {
            (new DescriptionRefreshCommand($service))->__invoke(['42'], ['apply' => true, 'limit' => 10]);
        } catch (RuntimeException $e) {
            $threw = true;
            $this->assertStringContainsString('Description refresh failed.', $e->getMessage());
            // Do not invent failed=0 in the printed summary.
            $this->assertStringNotContainsString('failed=0', $e->getMessage());
            $this->assertStringNotContainsString('Description refresh complete.', $e->getMessage());
        }

        $this->assertTrue($threw, 'missing failed key + failed rows must exit non-zero');
        $this->assertSame([], \WP_CLI::$messages['success']);
        $this->assertNotEmpty(\WP_CLI::$messages['error']);
        $logs = implode("\n", \WP_CLI::$messages['log']);
        $this->assertStringContainsString('post_id=701', $logs);
        $this->assertStringContainsString('post_update_failed', $logs);
    }

    /**
     * R17-BR-04 integrity: absent failed key with empty failed rows is still
     * non-zero — absence of evidence is not success.
     */
    public function testApplyMissingFailedKeyAloneExitsNonZero(): void
    {
        $service = new FixedRefreshService([
            'summary' => [
                'dry_run' => false,
                'candidates' => 0,
                'changed' => 0,
                'skipped' => 0,
            ],
            'failed' => [],
            'changed' => [],
            'skipped' => [],
        ]);

        $threw = false;
        try {
            (new DescriptionRefreshCommand($service))->__invoke(['42'], ['apply' => true, 'limit' => 10]);
        } catch (RuntimeException $e) {
            $threw = true;
            $this->assertStringContainsString('incomplete', $e->getMessage());
            $this->assertStringContainsString('missing failed', $e->getMessage());
        }

        $this->assertTrue($threw);
        $this->assertSame([], \WP_CLI::$messages['success']);
    }

    /**
     * R20-BR-07 (was F-11/max): summary.failed under-reporting row count is a
     * data-integrity error — exit non-zero; do not paper over with max() or
     * print the disagreeing failed= token.
     */
    public function testApplyUnderReportedFailedCountPrintsMaxOfRows(): void
    {
        $service = new FixedRefreshService([
            'summary' => [
                'dry_run' => false,
                'candidates' => 2,
                'changed' => 0,
                'failed' => 0, // under-reports the two logged rows
                'skipped' => 0,
            ],
            'failed' => [
                [
                    'post_id' => 901,
                    'media_id' => 42,
                    'reason' => 'post_update_failed',
                ],
                [
                    'post_id' => 902,
                    'media_id' => 43,
                    'reason' => 'post_update_failed',
                ],
            ],
            'changed' => [],
            'skipped' => [],
        ]);

        $threw = false;
        try {
            (new DescriptionRefreshCommand($service))->__invoke(['42'], ['apply' => true, 'limit' => 10]);
        } catch (RuntimeException $e) {
            $threw = true;
            $this->assertStringContainsString('summary count mismatch', $e->getMessage());
            $this->assertStringContainsString('incomplete', $e->getMessage());
            // Disagreeing token must not be printed as authoritative.
            $this->assertStringNotContainsString('failed=0', $e->getMessage());
            $this->assertStringNotContainsString('failed=2', $e->getMessage());
            $this->assertStringNotContainsString('Description refresh complete.', $e->getMessage());
        }

        $this->assertTrue($threw, 'failed summary/row mismatch must force non-zero exit');
        $error = \WP_CLI::$messages['error'][0] ?? '';
        $this->assertStringContainsString('summary count mismatch', $error);
        $this->assertStringNotContainsString('failed=0', $error);
        $this->assertStringNotContainsString('failed=2', $error);
        $logs = implode("\n", \WP_CLI::$messages['log']);
        $this->assertStringContainsString('post_id=901', $logs);
        $this->assertStringContainsString('post_id=902', $logs);
    }

    /**
     * R20-BR-02: summary.changed disagreeing with changed rows is integrity
     * error — not printed as changed=N on success.
     */
    public function testApplyChangedSummaryDisagreeingWithRowsIsIntegrityError(): void
    {
        $service = new FixedRefreshService([
            'summary' => [
                'dry_run' => false,
                'candidates' => 3,
                'changed' => 5, // disagrees with three changed rows
                'failed' => 0,
                'skipped' => 0,
            ],
            'failed' => [],
            'changed' => [
                ['post_id' => 801, 'media_id' => 42],
                ['post_id' => 802, 'media_id' => 42],
                ['post_id' => 803, 'media_id' => 42],
            ],
            'skipped' => [],
        ]);

        $threw = false;
        try {
            (new DescriptionRefreshCommand($service))->__invoke(['42'], ['apply' => true, 'limit' => 10]);
        } catch (RuntimeException $e) {
            $threw = true;
            $this->assertStringContainsString('summary count mismatch', $e->getMessage());
            $this->assertStringContainsString('incomplete', $e->getMessage());
            $this->assertStringNotContainsString('changed=5', $e->getMessage());
            $this->assertStringNotContainsString('changed=3', $e->getMessage());
            $this->assertStringNotContainsString('Description refresh complete.', $e->getMessage());
        }

        $this->assertTrue($threw, 'changed summary/row mismatch must exit non-zero');
        $this->assertSame([], \WP_CLI::$messages['success']);
        $error = \WP_CLI::$messages['error'][0] ?? '';
        $this->assertStringContainsString('summary count mismatch', $error);
        $this->assertStringNotContainsString('changed=5', $error);
    }

    /**
     * R20-BR-02: summary.skipped disagreeing with skipped rows is integrity
     * error — not printed as skipped=N on success.
     */
    public function testApplySkippedSummaryDisagreeingWithRowsIsIntegrityError(): void
    {
        $service = new FixedRefreshService([
            'summary' => [
                'dry_run' => false,
                'candidates' => 0,
                'changed' => 0,
                'failed' => 0,
                'skipped' => 4, // disagrees with one skipped row
            ],
            'failed' => [],
            'changed' => [],
            'skipped' => [
                ['post_id' => 851, 'media_id' => 42, 'reason' => 'already_current'],
            ],
        ]);

        $threw = false;
        try {
            (new DescriptionRefreshCommand($service))->__invoke(['42'], ['apply' => true, 'limit' => 10]);
        } catch (RuntimeException $e) {
            $threw = true;
            $this->assertStringContainsString('summary count mismatch', $e->getMessage());
            $this->assertStringContainsString('incomplete', $e->getMessage());
            $this->assertStringNotContainsString('skipped=4', $e->getMessage());
            $this->assertStringNotContainsString('skipped=1', $e->getMessage());
            $this->assertStringNotContainsString('Description refresh complete.', $e->getMessage());
        }

        $this->assertTrue($threw, 'skipped summary/row mismatch must exit non-zero');
        $this->assertSame([], \WP_CLI::$messages['success']);
        $error = \WP_CLI::$messages['error'][0] ?? '';
        $this->assertStringContainsString('summary count mismatch', $error);
        $this->assertStringNotContainsString('skipped=4', $error);
    }

    /**
     * R20-BR-07: summary.failed exceeding failed rows is integrity error —
     * not printed as failed=N (max-side over-report).
     */
    public function testApplyOverReportedFailedCountIsIntegrityError(): void
    {
        $service = new FixedRefreshService([
            'summary' => [
                'dry_run' => false,
                'candidates' => 2,
                'changed' => 0,
                'failed' => 7, // over-reports two logged rows
                'skipped' => 0,
            ],
            'failed' => [
                [
                    'post_id' => 911,
                    'media_id' => 42,
                    'reason' => 'post_update_failed',
                ],
                [
                    'post_id' => 912,
                    'media_id' => 43,
                    'reason' => 'post_update_failed',
                ],
            ],
            'changed' => [],
            'skipped' => [],
        ]);

        $threw = false;
        try {
            (new DescriptionRefreshCommand($service))->__invoke(['42'], ['apply' => true, 'limit' => 10]);
        } catch (RuntimeException $e) {
            $threw = true;
            $this->assertStringContainsString('summary count mismatch', $e->getMessage());
            $this->assertStringContainsString('incomplete', $e->getMessage());
            $this->assertStringNotContainsString('failed=7', $e->getMessage());
            $this->assertStringNotContainsString('failed=2', $e->getMessage());
            $this->assertStringNotContainsString('Description refresh complete.', $e->getMessage());
        }

        $this->assertTrue($threw, 'failed summary over-report must exit non-zero');
        $this->assertSame([], \WP_CLI::$messages['success']);
        $error = \WP_CLI::$messages['error'][0] ?? '';
        $this->assertStringContainsString('summary count mismatch', $error);
        $this->assertStringNotContainsString('failed=7', $error);
        $logs = implode("\n", \WP_CLI::$messages['log']);
        $this->assertStringContainsString('post_id=911', $logs);
        $this->assertStringContainsString('post_id=912', $logs);
    }

    /**
     * R20-BR-03: apply path must not fabricate candidates=0 when the key is
     * absent (same array_key_exists discipline as report_dry_run).
     */
    public function testApplyMissingCandidatesKeyDoesNotFabricateZero(): void
    {
        $service = new FixedRefreshService([
            'summary' => [
                'dry_run' => false,
                // deliberately omit candidates
                'changed' => 0,
                'failed' => 0,
                'skipped' => 0,
            ],
            'failed' => [],
            'changed' => [],
            'skipped' => [],
        ]);

        (new DescriptionRefreshCommand($service))->__invoke(['42'], ['apply' => true, 'limit' => 10]);

        $success = \WP_CLI::$messages['success'][0] ?? '';
        $this->assertStringContainsString('dry_run=0', $success);
        $this->assertStringNotContainsString('candidates=', $success);
        $this->assertStringContainsString('changed=0', $success);
        $this->assertStringContainsString('failed=0', $success);
        $this->assertStringContainsString('Description refresh complete.', $success);
    }

    /**
     * F-20: dry-run path must not fabricate candidates=0 / skipped=0 when the
     * summary keys are absent (same array_key_exists discipline as apply).
     */
    public function testDryRunMissingCandidatesKeyDoesNotFabricateZero(): void
    {
        $service = new FixedRefreshService([
            'summary' => [
                'dry_run' => true,
                // deliberately omit candidates and skipped
            ],
            'failed' => [],
            'changed' => [],
            'skipped' => [],
        ]);

        (new DescriptionRefreshCommand($service))->__invoke(['42'], ['limit' => 10]);

        $success = \WP_CLI::$messages['success'][0] ?? '';
        $this->assertStringContainsString('dry_run=1', $success);
        $this->assertStringNotContainsString('candidates=', $success);
        $this->assertStringNotContainsString('skipped=', $success);
        $this->assertStringContainsString('Description refresh complete.', $success);
    }

    /**
     * R18-BR-03: apply-path omits skipped= when the summary key is absent.
     * Must not fabricate skipped=0.
     */
    public function testApplyMissingSkippedKeyDoesNotFabricateZero(): void
    {
        $service = new FixedRefreshService([
            'summary' => [
                'dry_run' => false,
                'candidates' => 1,
                'changed' => 1,
                'failed' => 0,
                // deliberately omit 'skipped'
            ],
            'failed' => [],
            'changed' => [
                ['post_id' => 801, 'media_id' => 42],
            ],
            'skipped' => [],
        ]);

        (new DescriptionRefreshCommand($service))->__invoke(['42'], ['apply' => true, 'limit' => 10]);

        $success = \WP_CLI::$messages['success'][0] ?? '';
        $this->assertStringContainsString('changed=1', $success);
        $this->assertStringContainsString('failed=0', $success);
        $this->assertStringNotContainsString('skipped=', $success);
        $this->assertStringContainsString('Description refresh complete.', $success);
    }

    /**
     * R18-BR-03 normal path: when skipped is present and matches rows it is printed.
     * Row array must agree with the summary count [R20-BR-02].
     */
    public function testApplyPresentSkippedKeyIsPrinted(): void
    {
        $service = new FixedRefreshService([
            'summary' => [
                'dry_run' => false,
                'candidates' => 0,
                'changed' => 0,
                'failed' => 0,
                'skipped' => 3,
            ],
            'failed' => [],
            'changed' => [],
            'skipped' => [
                ['post_id' => 831, 'media_id' => 42, 'reason' => 'already_current'],
                ['post_id' => 832, 'media_id' => 42, 'reason' => 'already_current'],
                ['post_id' => 833, 'media_id' => 42, 'reason' => 'already_current'],
            ],
        ]);

        (new DescriptionRefreshCommand($service))->__invoke(['42'], ['apply' => true, 'limit' => 10]);

        $success = \WP_CLI::$messages['success'][0] ?? '';
        $this->assertStringContainsString('skipped=3', $success);
        $this->assertStringContainsString('Description refresh complete.', $success);
    }

    private function getEmbeddedAlt(string $content): string
    {
        preg_match('/\salt="([^"]*)"/', $content, $matches);
        return (string) ($matches[1] ?? '');
    }
}

/**
 * Inject a fixed apply/dry_run result so CLI reporting can be exercised without
 * the real refresh service shape constraints.
 */
class FixedRefreshService extends DescriptionContentRefreshService
{
    /** @param array<string,mixed> $result */
    public function __construct(private array $result)
    {
    }

    public function apply(array $media_ids, int $limit = 50): array
    {
        return $this->result;
    }

    public function dry_run(array $media_ids, int $limit = 50): array
    {
        return $this->result;
    }
}
