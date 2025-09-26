<?php

declare(strict_types=1);

use ContextAltText\Admin\PluginSettingsPage;
use PHPUnit\Framework\TestCase;

require_once __DIR__ . '/../bootstrap.php';

final class PluginSettingsPageTest extends TestCase
{
    public function test_render_outputs_settings_root(): void
    {
        $page = new PluginSettingsPage();

        ob_start();
        $page->render();
        $output = ob_get_clean();

        $this->assertStringContainsString(PluginSettingsPage::ROOT_ID, $output);
        $this->assertStringContainsString('Settings', $output);
    }
}
