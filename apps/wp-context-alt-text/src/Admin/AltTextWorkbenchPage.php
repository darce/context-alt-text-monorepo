<?php

declare(strict_types=1);

namespace ContextAltText\Admin;

class AltTextWorkbenchPage
{
    public const ROOT_ID = 'context-alt-text-workbench-root';

    public function render(): void
    {
        ?>
        <div class="wrap context-alt-text-admin">
            <h1><?php esc_html_e('Alt-Text Workbench', 'context-alt-text'); ?></h1>
            <div id="<?php echo esc_attr(self::ROOT_ID); ?>" class="context-alt-text-workbench-root">
                <p class="description">
                    <?php esc_html_e('Alt-text workbench UI loading…', 'context-alt-text'); ?>
                </p>
            </div>
        </div>
        <?php
    }
}

