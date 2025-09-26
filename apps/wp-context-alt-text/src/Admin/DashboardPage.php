<?php

declare(strict_types=1);

namespace ContextAltText\Admin;

use ContextAltText\Services\Scan\MissingAltTextScanner;

class DashboardPage
{
    public const ROOT_ID = 'context-alt-text-admin-app';

    private MissingAltTextScanner $scanner;

    public function __construct(MissingAltTextScanner $scanner)
    {
        $this->scanner = $scanner;
    }

    public function render(): void
    {
        $this->scanner->maybe_prime_counts();
        $summary = $this->scanner->get_summary();

        $total = (int) ($summary['total'] ?? 0);
        $withAlt = (int) ($summary['with_alt'] ?? 0);
        $missing = (int) ($summary['missing'] ?? 0);
        $updatedAt = $summary['updated_at'] ?? null;

        $statusLine = sprintf(
            /* translators: %d is the number of images missing alt text. */
            __('We found %d images missing alt text.', 'context-alt-text'),
            $missing
        );

        ?>
        <div class="wrap context-alt-text-admin">
            <h1><?php esc_html_e('Context Alt Text Dashboard', 'context-alt-text'); ?></h1>
            <div id="<?php echo esc_attr(self::ROOT_ID); ?>" class="context-alt-text-dashboard-root">
                <div class="context-alt-text-dashboard-summary">
                    <p class="context-alt-text-dashboard-status">
                        <?php echo esc_html($statusLine); ?>
                    </p>
                    <ul class="context-alt-text-dashboard-metrics">
                        <li>
                            <strong><?php esc_html_e('Total images scanned', 'context-alt-text'); ?></strong>
                            <span><?php echo esc_html((string) $total); ?></span>
                        </li>
                        <li>
                            <strong><?php esc_html_e('With alt text', 'context-alt-text'); ?></strong>
                            <span><?php echo esc_html((string) $withAlt); ?></span>
                        </li>
                        <li>
                            <strong><?php esc_html_e('Missing alt text', 'context-alt-text'); ?></strong>
                            <span><?php echo esc_html((string) $missing); ?></span>
                        </li>
                    </ul>
                    <p class="description">
                        <?php
                        if ($updatedAt) {
                            printf(
                                /* translators: %s is a human readable time difference. */
                                esc_html__('Last updated %s ago.', 'context-alt-text'),
                                esc_html(human_time_diff((int) $updatedAt, time()))
                            );
                        } else {
                            esc_html_e('Initial scan is running… refresh in a few seconds.', 'context-alt-text');
                        }
                        ?>
                    </p>
                </div>
            </div>
        </div>
        <?php
    }
}
