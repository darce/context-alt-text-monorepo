<?php

declare(strict_types=1);

use ContextAltText\Admin\DashboardPage;
use ContextAltText\Services\Scan\MissingAltTextScanner;
use PHPUnit\Framework\TestCase;

require_once __DIR__ . '/../bootstrap.php';

final class DashboardPageTest extends TestCase
{
    public function test_render_outputs_scan_summary(): void
    {
        $scanner = new class extends MissingAltTextScanner {
            public int $primeCalls = 0;

            public function maybe_prime_counts(): void
            {
                $this->primeCalls++;
            }

            public function get_summary(): array
            {
                return [
                    'total' => 12,
                    'with_alt' => 7,
                    'missing' => 5,
                    'updated_at' => time() - 120,
                ];
            }
        };

        $page = new DashboardPage($scanner);

        ob_start();
        $page->render();
        $output = ob_get_clean();

        $this->assertSame(1, $scanner->primeCalls, 'Scan should prime counts');
        $this->assertStringContainsString('context-alt-text-dashboard-root', $output);
        $this->assertStringContainsString('We found 5 images missing alt text', $output);
        $this->assertStringContainsString('Total images scanned', $output);
    }
}
