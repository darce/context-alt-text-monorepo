<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\RecognitionDataSource;
use AltContext\Tests\TestCase;
use FilesystemIterator;
use RecursiveDirectoryIterator;
use RecursiveIteratorIterator;
use SplFileInfo;

/**
 * @covers \AltContext\Api\RecognitionDataSource
 */
class RecognitionDataSourceTest extends TestCase
{
    private const DATA_SOURCE_LITERALS = [
        'local_projection',
        'backend_proxy',
        'endpoint_error',
        'unavailable',
    ];

    /**
     * Concrete floor: src/ currently holds well over this many PHP files. A
     * scrape that walks zero files (wrong ACX_PLUGIN_DIR, broken iterator)
     * must not pass as "no strays" [rg-005].
     */
    private const RUNTIME_PHP_FILE_FLOOR = 50;

    public function testConstantsPinnedToCanonicalVocabulary(): void
    {
        $this->assertSame('local_projection', RecognitionDataSource::LOCAL_PROJECTION);
        $this->assertSame('backend_proxy', RecognitionDataSource::BACKEND_PROXY);
        $this->assertSame('endpoint_error', RecognitionDataSource::ENDPOINT_ERROR);
        $this->assertSame('unavailable', RecognitionDataSource::UNAVAILABLE);
    }

    public function testBootstrapSyncHookNamePinned(): void
    {
        $this->assertSame('acx_bootstrap_sync', RecognitionDataSource::BOOTSTRAP_SYNC_HOOK);
    }

    public function testConstantsByteEqualToTypescriptDataSourceModule(): void
    {
        $tsPath = ACX_PLUGIN_DIR . 'js/admin/api/recognition/types/dataSource.ts';
        $this->assertFileExists($tsPath);
        $ts = (string) file_get_contents($tsPath);

        $this->assertSame(1, preg_match('/export const DATA_SOURCE = \{(.*?)\} as const;/s', $ts, $block), 'DATA_SOURCE block not found in dataSource.ts');

        $expected = [
            'LOCAL_PROJECTION' => RecognitionDataSource::LOCAL_PROJECTION,
            'BACKEND_PROXY' => RecognitionDataSource::BACKEND_PROXY,
            'ENDPOINT_ERROR' => RecognitionDataSource::ENDPOINT_ERROR,
            'UNAVAILABLE' => RecognitionDataSource::UNAVAILABLE,
        ];

        foreach ($expected as $key => $phpValue) {
            $this->assertSame(
                1,
                preg_match('/' . $key . ":\s*'([^']+)'/", $block[1], $match),
                sprintf('%s not declared in TS DATA_SOURCE block', $key)
            );
            $this->assertSame($match[1], $phpValue, sprintf('PHP %s diverges from TS DATA_SOURCE.%s', $key, $key));
        }
    }

    /**
     * Grep-guard (Slice 1): the four data_source literals may be declared only in
     * class-recognition-data-source.php. Scans runtime sources (src/**) for
     * declaration contexts — const / assignment / data_source array values /
     * positional call arguments — so UI copy and the distinct PROJECTION_STATUS
     * vocabulary do not false-positive.
     *
     * Fail-closed self-check: the same patterns must still resolve every
     * canonical literal inside class-recognition-data-source.php. If the
     * patterns drift (renamed form, broken alternation), that precondition
     * fails closed rather than leaving the empty-violations assertion green
     * while guarding nothing [rg-005].
     */
    public function testNoStrayDataSourceLiteralDeclarationsInRuntimeSources(): void
    {
        $srcDir = ACX_PLUGIN_DIR . 'src';
        $this->assertDirectoryExists($srcDir, 'runtime src/ directory must exist for the stray-literal scrape');

        $patterns = $this->dataSourceDeclarationPatterns();

        // Positive control: patterns must see every canonical literal in the
        // sole allowed declaration site. Previously this check was absent, so
        // a broken pattern set left the empty-violations assert green.
        $canonicalPath = $srcDir . '/api/class-recognition-data-source.php';
        $this->assertFileExists($canonicalPath, 'canonical RecognitionDataSource declaration file missing');
        $canonicalSource = (string) file_get_contents($canonicalPath);
        $seenInCanonical = $this->literalsMatchedByPatterns($canonicalSource, $patterns);
        $this->assertSame(
            self::DATA_SOURCE_LITERALS,
            array_values(array_intersect(self::DATA_SOURCE_LITERALS, $seenInCanonical)),
            'declaration-pattern self-check failed: patterns no longer see every DATA_SOURCE literal in class-recognition-data-source.php — scrape would fail open'
        );
        $this->assertCount(
            count(self::DATA_SOURCE_LITERALS),
            $seenInCanonical,
            'declaration-pattern self-check: expected exactly the four DATA_SOURCE literals in the canonical file'
        );

        $violations = [];
        $phpFilesScanned = 0;
        $iterator = new RecursiveIteratorIterator(
            new RecursiveDirectoryIterator($srcDir, FilesystemIterator::SKIP_DOTS)
        );

        /** @var SplFileInfo $file */
        foreach ($iterator as $file) {
            if ($file->getExtension() !== 'php') {
                continue;
            }
            if ($file->getBasename() === 'class-recognition-data-source.php') {
                continue;
            }

            $lines = file($file->getPathname());
            if (false === $lines) {
                $this->fail('unreadable runtime source: ' . $file->getPathname());
            }

            ++$phpFilesScanned;

            foreach ($lines as $lineNumber => $line) {
                foreach ($patterns as $pattern) {
                    if (1 === preg_match($pattern, $line, $match)) {
                        $violations[] = sprintf('%s:%d: %s', $file->getPathname(), $lineNumber + 1, trim($line));
                    }
                }
            }
        }

        $this->assertGreaterThanOrEqual(
            self::RUNTIME_PHP_FILE_FLOOR,
            $phpFilesScanned,
            sprintf(
                'stray-literal scrape walked %d PHP file(s); expected at least %d — corpus or ACX_PLUGIN_DIR is broken',
                $phpFilesScanned,
                self::RUNTIME_PHP_FILE_FLOOR
            )
        );

        $this->assertSame(
            [],
            $violations,
            "data_source literals must be declared only in class-recognition-data-source.php:\n" . implode("\n", $violations)
        );
    }

    /**
     * @return list<string>
     */
    private function dataSourceDeclarationPatterns(): array
    {
        $alternation = implode('|', self::DATA_SOURCE_LITERALS);

        // Single- and double-quoted forms. Covers:
        //  - const NAME = 'literal' / "literal"
        //  - $x = 'literal' / "literal" (property defaults, assignments)
        //  - 'data_source' => 'literal' / "data_source" => "literal"
        //  - call-arg ('literal') / ("literal")
        return [
            '/const\s+\w+\s*=\s*[\'"](' . $alternation . ')[\'"]/',
            '/(?<![:\w])\$\w+\s*=\s*[\'"](' . $alternation . ')[\'"]/',
            '/[\'"]data_source[\'"]\s*=>\s*[\'"](' . $alternation . ')[\'"]/',
            '/[(,]\s*[\'"](' . $alternation . ')[\'"]\s*[,)]/',
        ];
    }

    /**
     * @param list<string> $patterns
     * @return list<string> unique matched literals in source order of first appearance
     */
    private function literalsMatchedByPatterns(string $source, array $patterns): array
    {
        $found = [];
        $lines = preg_split('/\r?\n/', $source);
        if (! is_array($lines)) {
            $lines = [];
        }
        foreach ($lines as $line) {
            foreach ($patterns as $pattern) {
                if (1 === preg_match($pattern, $line, $match) && isset($match[1])) {
                    $found[$match[1]] = true;
                }
            }
        }

        $ordered = [];
        foreach (self::DATA_SOURCE_LITERALS as $literal) {
            if (isset($found[$literal])) {
                $ordered[] = $literal;
            }
        }

        return $ordered;
    }
}
