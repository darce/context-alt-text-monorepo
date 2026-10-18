<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Cli\DescriptionCommand;
use AltContext\Tests\TestCase;

/**
 * @covers \AltContext\Cli\DescriptionCommand
 */
class DescriptionCommandStatusTest extends TestCase
{
    protected function setUp(): void
    {
        parent::setUp();
        \WP_CLI::reset_cli_messages();
    }

    public function testStatusJsonReportsCandidateAndProvenanceWithoutWriting(): void
    {
        $GLOBALS['__ac_posts'][101] = (object) [
            'ID' => 101,
            'post_type' => 'attachment',
            'post_status' => 'inherit',
            'post_title' => 'Coastal image',
        ];
        $GLOBALS['__ac_attachment_mimes'][101] = 'image/jpeg';
        $this->setPostMeta(101, '_wp_attachment_image_alt', '');
        $this->setPostMeta(
            101,
            '_acx_description_provenance',
            [
                'generated_at' => '2026-07-04T12:00:00+00:00',
                'model_id' => 'seeded-local',
            ]
        );

        $command = new DescriptionCommand();
        $command->__invoke(['status'], ['media-id' => '101', 'format' => 'json']);

        $payload = json_decode(\WP_CLI::$messages['log'][0] ?? '', true);

        $this->assertSame([], \WP_CLI::$messages['success']);
        $this->assertSame('', get_post_meta(101, '_wp_attachment_image_alt', true));
        $this->assertIsArray($payload);
        $this->assertSame('status', $payload['command']);
        $this->assertSame(1, $payload['count']);
        $this->assertSame(101, $payload['rows'][0]['media_id']);
        $this->assertSame('Coastal image', $payload['rows'][0]['title']);
        $this->assertSame(false, $payload['rows'][0]['has_alt_text']);
        $this->assertSame('missing_alt', $payload['rows'][0]['candidate_reason']);
        $this->assertSame(
            ['generated_at' => '2026-07-04T12:00:00+00:00', 'model_id' => 'seeded-local'],
            $payload['rows'][0]['provenance']
        );
    }

    public function testStatusTableSupportsBoundedCandidateListing(): void
    {
        $GLOBALS['__ac_get_posts_results'] = [];
        foreach ([201, 202, 203] as $mediaId) {
            $post = (object) [
                'ID' => $mediaId,
                'post_type' => 'attachment',
                'post_status' => 'inherit',
                'post_title' => 'Image ' . $mediaId,
            ];
            $GLOBALS['__ac_posts'][$mediaId] = $post;
            $GLOBALS['__ac_get_posts_results'][] = $post;
            $GLOBALS['__ac_attachment_mimes'][$mediaId] = 'image/png';
            $this->setPostMeta($mediaId, '_wp_attachment_image_alt', '');
        }

        $command = new DescriptionCommand();
        $command->__invoke(['status'], ['limit' => '2']);

        $output = implode("\n", \WP_CLI::$messages['log']);

        $this->assertStringContainsString('media_id=201', $output);
        $this->assertStringContainsString('media_id=202', $output);
        $this->assertStringNotContainsString('media_id=203', $output);
        $this->assertContains('Description status rows: count=2', \WP_CLI::$messages['success']);
    }

    public function testCliRegistrationAddsDescribeCommand(): void
    {
        $pluginFile = file_get_contents(ACX_PLUGIN_DIR . 'alt-context.php');

        $this->assertIsString($pluginFile);
        $this->assertStringContainsString("use AltContext\\Cli\\DescriptionCommand;", $pluginFile);
        $this->assertStringContainsString("WP_CLI::add_command('alt-context describe', new DescriptionCommand());", $pluginFile);
    }
}
