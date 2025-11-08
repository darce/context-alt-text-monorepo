<?php

declare(strict_types=1);

namespace ContextAltText\Admin;

use ContextAltText\Services\Scan\MissingAltTextScanner;
use WP_Query;

class MediaLibraryPanel
{
    private MissingAltTextScanner $scanner;

    public function __construct(MissingAltTextScanner $scanner)
    {
        $this->scanner = $scanner;
    }

    public function init(): void
    {
        add_action('load-upload.php', [$this, 'bootstrap_media_screen']);
    }

    /**
     * Hook handlers required for the media library screen.
     */
    public function bootstrap_media_screen(): void
    {
        add_filter('views_upload', [$this, 'add_missing_alt_view']);
        add_action('pre_get_posts', [$this, 'filter_missing_alt_query']);
        add_action('admin_notices', [$this, 'render_active_filter_notice']);
    }

    /**
     * Inject a custom view that surfaces attachments missing alt text.
     *
     * @param array<string,string> $views
     * @return array<string,string>
     */
    public function add_missing_alt_view(array $views): array
    {
        $summary = $this->scanner->get_summary();
        $missing = max(0, (int) ($summary['missing'] ?? 0));
        $classes = ['context-alt-text-view'];

        if ($this->is_missing_filter_active()) {
            $classes[] = 'current';
        }

        $label = sprintf(
            '%s <span class="count">(%d)</span>',
            esc_html__('Missing Alt Text', 'context-alt-text'),
            $missing
        );

        $views['context-alt-text-missing'] = sprintf(
            '<a href="%s" class="%s">%s</a>',
            esc_url(admin_url('upload.php?context_alt_text=missing')),
            esc_attr(implode(' ', $classes)),
            $label
        );

        return $views;
    }

    /**
     * Filter the media library query to only include attachments missing alt text.
     */
    public function filter_missing_alt_query($query): void
    {
        if (!$query instanceof WP_Query) {
            return;
        }

        if (!$this->is_missing_filter_active() || !is_admin() || !$query->is_main_query()) {
            return;
        }

        $query->set('post_type', 'attachment');
        $query->set('post_status', 'inherit');
        $query->set('post_mime_type', 'image');

        $query->set(
            'meta_query',
            [
                'relation' => 'OR',
                [
                    'key' => '_wp_attachment_image_alt',
                    'compare' => 'NOT EXISTS',
                ],
                [
                    'key' => '_wp_attachment_image_alt',
                    'value' => '',
                    'compare' => '=',
                ],
            ]
        );
    }

    /**
     * Surface a contextual notice when the missing-alt view is active.
     */
    public function render_active_filter_notice(): void
    {
        if (!$this->is_missing_filter_active()) {
            return;
        }

        $summary = $this->scanner->get_summary();
        $missing = max(0, (int) ($summary['missing'] ?? 0));

        printf(
            '<div class="notice notice-info"><p>%s</p></div>',
            esc_html(
                sprintf(
                    /* translators: %d is the count of images missing alt text. */
                    __('Showing %d images that are missing alt text.', 'context-alt-text'),
                    $missing
                )
            )
        );
    }

    private function is_missing_filter_active(): bool
    {
        return isset($_GET['context_alt_text']) && $_GET['context_alt_text'] === 'missing';
    }
}

