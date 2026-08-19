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
            foreach ($this->collectFortyHexTokens($content) as $sha) {
                $this->assertTrue(
                    $this->shaResolves($git, $root, $sha),
                    sprintf('%s cites unresolved commit %s', basename($path), $sha)
                );
            }
        }
    }

    /**
     * R9-01: a 40-hex token is exempt only when its line contains the
     * literal `sha-lint:allow`. The marker is not a blanket disable.
     * Mutant: skip every 40-hex token regardless of the marker.
     */
    public function testShaLintAllowMarkerExemptsTokensOnThatLineOnly(): void
    {
        $dead = str_repeat('0', 40);
        $allowed = sprintf(
            'DEAD %s <!-- sha-lint:allow verbatim mutant payload, not a commit citation -->',
            $dead
        );
        $denied = sprintf('DEAD %s', $dead);

        $this->assertSame(
            [],
            $this->collectFortyHexTokens($allowed),
            'sha-lint:allow on the line must skip every forty-hex token on that line'
        );
        $this->assertNotEmpty(
            $this->collectFortyHexTokens($denied),
            'unmarked forty-hex token must still be collected'
        );
        $this->assertSame([$dead], $this->collectFortyHexTokens($denied));

        $git = $this->gitBinary();
        if (null === $git) {
            $this->markTestSkipped('git is unavailable');
        }
        $this->assertFalse(
            $this->shaResolves($git, $this->repoRoot(), $dead),
            'fixture token must be unresolvable so the unmarked case is a real fail'
        );
    }

    /**
     * Forty-hex tokens that the lint must resolve. A line containing the
     * literal `sha-lint:allow` is skipped in full.
     *
     * @return list<string>
     */
    private function collectFortyHexTokens(string $content): array
    {
        $tokens = [];
        foreach (preg_split('/\R/', $content) as $line) {
            if (false !== strpos($line, 'sha-lint:allow')) {
                continue;
            }
            if (preg_match_all('/\b[0-9a-f]{40}\b/', $line, $matches) > 0) {
                foreach ($matches[0] as $sha) {
                    $tokens[] = $sha;
                }
            }
        }

        return $tokens;
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
