<?php

declare(strict_types=1);

use ContextAltText\Admin\AutomationQueuePage;
use PHPUnit\Framework\TestCase;

require_once __DIR__ . '/../bootstrap.php';

final class AutomationQueuePageTest extends TestCase
{
    public function test_render_outputs_queue_root(): void
    {
        $page = new AutomationQueuePage();

        ob_start();
        $page->render();
        $output = ob_get_clean();

        $this->assertStringContainsString(AutomationQueuePage::ROOT_ID, $output);
        $this->assertStringContainsString('Automation Queue', $output);
    }
}
