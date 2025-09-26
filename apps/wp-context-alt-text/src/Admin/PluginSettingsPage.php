<?php

declare(strict_types=1);

namespace ContextAltText\Admin;

class PluginSettingsPage
{
    public const ROOT_ID = 'context-alt-text-settings-root';

    public function render(): void
    {
        ?>
        <div class="wrap context-alt-text-admin">
            <h1><?php esc_html_e('Context Alt Text Settings', 'context-alt-text'); ?></h1>
            <div id="<?php echo esc_attr(self::ROOT_ID); ?>" class="context-alt-text-settings-root">
                <p class="description">
                    <?php esc_html_e('Settings UI loading…', 'context-alt-text'); ?>
                </p>
            </div>
        </div>
        <?php
    }
}

