<?php

declare(strict_types=1);

use ContextAltText\Admin\AccountCenterPage;
use PHPUnit\Framework\TestCase;

require_once __DIR__ . '/../bootstrap.php';

final class AccountCenterPageTest extends TestCase
{
    public function test_render_outputs_account_root(): void
    {
        $page = new AccountCenterPage();

        ob_start();
        $page->render();
        $output = ob_get_clean();

        $this->assertStringContainsString(AccountCenterPage::ROOT_ID, $output);
        $this->assertStringContainsString('Account Center', $output);
    }
}
