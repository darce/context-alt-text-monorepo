<?php

declare(strict_types=1);

namespace ContextAltText\Admin;

use ContextAltText\Services\Scan\MissingAltTextScanner;

class Admin
{
    public const DASHBOARD_HOOK = 'toplevel_page_context-alt-text-dashboard';

    private MissingAltTextScanner $scanner;

    public function __construct(MissingAltTextScanner $scanner)
    {
        $this->scanner = $scanner;
    }

    public function bootstrap(): void
    {
        add_action('admin_enqueue_scripts', [$this, 'enqueue_script']);
    }

    public function enqueue_script(string $hookSuffix): void
    {
        if ($hookSuffix !== self::DASHBOARD_HOOK) {
            return;
        }

        wp_enqueue_style(
            'context-alt-text-admin',
            CONTEXT_ALT_TEXT_PLUGIN_URL . 'public/assets/css/admin.css',
            [],
            CONTEXT_ALT_TEXT_VERSION
        );

        wp_enqueue_script(
            'context-alt-text-admin',
            CONTEXT_ALT_TEXT_PLUGIN_URL . 'public/assets/js/admin.js',
            ['jquery'],
            CONTEXT_ALT_TEXT_VERSION,
            true
        );

        wp_localize_script(
            'context-alt-text-admin',
            'ContextAltTextAdmin',
            [
                'config' => $this->get_config(),
                'data' => $this->get_data(),
            ]
        );
    }

    public function get_config(): array
    {
        return [
            'missingAltMediaUrl' => admin_url('upload.php?context_alt_text=missing'),
        ];
    }

    public function get_data(): array
    {
        return $this->scanner->get_summary();
    }
}
