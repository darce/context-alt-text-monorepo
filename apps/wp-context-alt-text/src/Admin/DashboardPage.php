<?php

declare(strict_types=1);

namespace ContextAltText\Admin;

class DashboardPage
{
    public const ROOT_ID = 'context-alt-text-admin-app';

    public function render(): void
    {
        ?>
        <div class="wrap context-alt-text-admin">
            <h1><?php esc_html_e('Context Alt Text Dashboard', 'context-alt-text'); ?></h1>
            <div id="<?php echo esc_attr(self::ROOT_ID); ?>" class="context-alt-text-dashboard-root">
                <p class="description">
                    <?php esc_html_e('Admin dashboard shell initializing…', 'context-alt-text'); ?>
                </p>
            </div>
        </div>
        <?php
    }
}

