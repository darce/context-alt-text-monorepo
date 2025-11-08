<?php

declare(strict_types=1);

namespace CAT\Admin;

class DashboardPage
{
    public const ROOT_ID = 'cat-admin-app';

    public function render(): void
    {   ?>
        <div class="wrap cat-admin">
            <h1><?php esc_html_e('Context Alt Text Dashboard', 'cat'); ?></h1>
            <div class="cat-dashboard" id="<?php echo esc_attr(self::ROOT_ID); ?>">
                Content Alt Text Dashboard App
            </div>
        </div>
        <?php
    }
}
