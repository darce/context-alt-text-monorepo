<?php

declare(strict_types=1);

namespace ContextAltText\Admin;

class AutomationQueuePage
{
    public const ROOT_ID = 'context-alt-text-automation-root';

    public function render(): void
    {
        ?>
        <div class="wrap context-alt-text-admin">
            <h1><?php esc_html_e('Automation Queue', 'context-alt-text'); ?></h1>
            <div id="<?php echo esc_attr(self::ROOT_ID); ?>" class="context-alt-text-automation-root">
                <p class="description">
                    <?php esc_html_e('Automation queue UI loading…', 'context-alt-text'); ?>
                </p>
            </div>
        </div>
        <?php
    }
}

