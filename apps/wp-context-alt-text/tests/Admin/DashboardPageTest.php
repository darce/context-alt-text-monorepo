<?php

declare(strict_types=1);

use ContextAltText\Admin\DashboardPage;
use PHPUnit\Framework\TestCase;

require_once __DIR__ . '/../bootstrap.php';

final class DashboardPageTest extends TestCase
{
    public function test_render_outputs_spa_root(): void
    {
        $page = new DashboardPage();

        ob_start();
        $page->render();
        $output = ob_get_clean();

        $this->assertStringContainsString('context-alt-text-dashboard-root', $output);
        $this->assertStringContainsString('id="' . DashboardPage::ROOT_ID . '"', $output);
        $this->assertStringContainsString('Context Alt Text Dashboard', $output);
    }
}
