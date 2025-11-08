<?php

declare(strict_types=1);

use ContextAltText\Admin\AltTextWorkbenchPage;
use PHPUnit\Framework\TestCase;

require_once __DIR__ . '/../bootstrap.php';

final class AltTextWorkbenchPageTest extends TestCase
{
    public function test_render_outputs_workbench_root(): void
    {
        $page = new AltTextWorkbenchPage();

        ob_start();
        $page->render();
        $output = ob_get_clean();

        $this->assertStringContainsString(AltTextWorkbenchPage::ROOT_ID, $output);
        $this->assertStringContainsString('Alt-Text Workbench', $output);
    }
}
