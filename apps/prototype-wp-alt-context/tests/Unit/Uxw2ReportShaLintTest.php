<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Tests\TestCase;

/**
 * R8-07 / R6-03: every 40-hex token in docs/tasks/uxw2/*.md must resolve
 * to a commit on this tree. Empty glob is a failure, not a vacuous pass.
 *
 * @coversNothing
 */
class Uxw2ReportShaLintTest extends TestCase
{
    private const REPORTS_GLOB = 'docs/tasks/uxw2/*.md';

    public function testEveryFortyHexTokenInUxw2ReportsResolvesToACommit(): void
    {
        $paths = $this->globReports(self::REPORTS_GLOB);
        $this->assertNotEmpty(
            $paths,
            'uxw2 report glob must match at least one markdown file'
        );

        $git = $this->gitBinary();
        if (null === $git) {
            $this->markTestSkipped('git is unavailable');
        }

        $root = $this->repoRoot();
        foreach ($paths as $path) {
            $content = (string) file_get_contents($path);
            preg_match_all('/\b[0-9a-f]{40}\b/', $content, $matches);
            foreach ($matches[0] as $sha) {
                $this->assertTrue(
                    $this->shaResolves($git, $root, $sha),
                    sprintf('%s cites unresolved commit %s', basename($path), $sha)
                );
            }
        }
    }

    /**
     * @return list<string>
     */
    private function globReports(string $relativeGlob): array
    {
        $matches = glob($this->repoRoot() . '/' . $relativeGlob);

        return is_array($matches) ? $matches : [];
    }

    private function repoRoot(): string
    {
        $cursor = __DIR__;
        for ($i = 0; $i < 8; $i++) {
            if (is_dir($cursor . '/.git') || is_file($cursor . '/.git')) {
                return $cursor;
            }
            $cursor = dirname($cursor);
        }
        $this->fail('Could not resolve git repository root');
    }

    private function gitBinary(): ?string
    {
        $which = trim((string) shell_exec('command -v git 2>/dev/null'));

        return '' === $which ? null : $which;
    }

    private function shaResolves(string $git, string $root, string $sha): bool
    {
        $command = sprintf(
            '%s -C %s cat-file -e %s',
            escapeshellcmd($git),
            escapeshellarg($root),
            escapeshellarg($sha . '^{commit}')
        );
        $output = [];
        $exit = 0;
        exec($command, $output, $exit);

        return 0 === $exit;
    }
}
