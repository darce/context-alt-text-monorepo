<?php

declare(strict_types=1);

use ContextAltText\Admin\MediaLibraryPanel;
use ContextAltText\Services\Scan\MissingAltTextScanner;
use PHPUnit\Framework\TestCase;

require_once __DIR__ . '/../bootstrap.php';

final class MediaLibraryPanelTest extends TestCase
{
    protected function tearDown(): void
    {
        unset($_GET['context_alt_text']);
        parent::tearDown();
    }

    public function test_add_missing_alt_view_includes_count_and_current_class(): void
    {
        $_GET['context_alt_text'] = 'missing';

        $panel = new MediaLibraryPanel($this->createScanner(['missing' => 12]));

        $views = $panel->add_missing_alt_view([]);

        $this->assertArrayHasKey('context-alt-text-missing', $views);
        $link = $views['context-alt-text-missing'];

        $this->assertStringContainsString('current', $link);
        $this->assertStringContainsString('(12)', $link);
    }

    public function test_filter_missing_alt_query_sets_meta_query(): void
    {
        $_GET['context_alt_text'] = 'missing';

        $panel = new MediaLibraryPanel($this->createScanner(['missing' => 4]));
        $query = new WP_Query(true);

        $panel->filter_missing_alt_query($query);

        $vars = $query->get_vars();

        $this->assertSame('attachment', $vars['post_type']);
        $this->assertSame('image', $vars['post_mime_type']);
        $this->assertSame('inherit', $vars['post_status']);

        $this->assertArrayHasKey('meta_query', $vars);
        $meta = $vars['meta_query'];

        $this->assertSame('OR', $meta['relation']);
        $this->assertSame('_wp_attachment_image_alt', $meta[0]['key']);
        $this->assertSame('NOT EXISTS', $meta[0]['compare']);
        $this->assertSame('', $meta[1]['value']);
        $this->assertSame('=', $meta[1]['compare']);
    }

    public function test_render_active_filter_notice_outputs_message(): void
    {
        $_GET['context_alt_text'] = 'missing';
        $panel = new MediaLibraryPanel($this->createScanner(['missing' => 3]));

        ob_start();
        $panel->render_active_filter_notice();
        $output = ob_get_clean();

        $this->assertNotEmpty($output);
        $this->assertStringContainsString('Showing 3 images', $output);
    }

    private function createScanner(array $summary): MissingAltTextScanner
    {
        return new class($summary) extends MissingAltTextScanner {
            private array $summary;

            public function __construct(array $summary)
            {
                $this->summary = $summary;
            }

            public function get_summary(): array
            {
                return array_merge([
                    'total' => 0,
                    'with_alt' => 0,
                    'missing' => 0,
                    'updated_at' => time(),
                ], $this->summary);
            }
        };
    }
}
