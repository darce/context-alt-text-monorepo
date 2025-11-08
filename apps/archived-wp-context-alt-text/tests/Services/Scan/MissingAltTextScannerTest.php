<?php

declare(strict_types=1);

use ContextAltText\Services\Scan\MissingAltTextScanner;
use PHPUnit\Framework\TestCase;

require_once __DIR__ . '/../../bootstrap.php';

final class MissingAltTextScannerTest extends TestCase
{
    protected function setUp(): void
    {
        parent::setUp();
        $GLOBALS['__cat_options'] = [];
    }

    public function test_maybe_prime_counts_triggers_handle_when_missing(): void
    {
        $scanner = new class extends MissingAltTextScanner {
            public int $handles = 0;

            public function handle(): void
            {
                $this->handles++;
            }
        };

        $scanner->maybe_prime_counts();

        $this->assertSame(1, $scanner->handles);
    }

    public function test_maybe_prime_counts_skips_when_recent_counts_exist(): void
    {
        update_option('context_alt_text_missing_counts', [
            'total' => 10,
            'with_alt' => 5,
            'missing' => 5,
            'updated_at' => time(),
        ]);

        $scanner = new class extends MissingAltTextScanner {
            public int $handles = 0;

            public function handle(): void
            {
                $this->handles++;
            }
        };

        $scanner->maybe_prime_counts();

        $this->assertSame(0, $scanner->handles);
    }

    public function test_handle_records_coverage_history(): void
    {
        $GLOBALS['__cat_options'] = [];
        $scanner = new class extends MissingAltTextScanner {
            protected function scan_missing_alt_text(): array
            {
                return [
                    'total' => 20,
                    'with_alt' => 15,
                    'missing' => 5,
                ];
            }
        };

        $scanner->handle();

        $history = get_option('context_alt_text_coverage_history', []);
        $this->assertIsArray($history);
        $this->assertNotEmpty($history);

        $latest = end($history);
        $this->assertSame(20, $latest['total']);
        $this->assertSame(5, $latest['missing']);
        $this->assertSame(75.0, $latest['coverage']);
        $this->assertArrayHasKey('timestamp', $latest);
    }
}
