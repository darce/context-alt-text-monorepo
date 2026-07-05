<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Cli\DescriptionRefreshCommand;
use AltContext\Tests\TestCase;

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
    }

    private function getEmbeddedAlt(string $content): string
    {
        preg_match('/\salt="([^"]*)"/', $content, $matches);
        return (string) ($matches[1] ?? '');
    }
}
