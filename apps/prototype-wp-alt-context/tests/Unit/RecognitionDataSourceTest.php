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
     * declaration contexts only — `const … = '<literal>'` and hardcoded
     * `'data_source' => '<literal>'` array values — so UI copy and the distinct
     * PROJECTION_STATUS vocabulary do not false-positive.
     */
    public function testNoStrayDataSourceLiteralDeclarationsInRuntimeSources(): void
    {
        $srcDir = ACX_PLUGIN_DIR . 'src';
        $alternation = implode('|', self::DATA_SOURCE_LITERALS);
        $patterns = [
            '/const\s+\w+\s*=\s*\'(' . $alternation . ')\'/',
            '/\'data_source\'\s*=>\s*\'(' . $alternation . ')\'/',
        ];

        $violations = [];
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
                continue;
            }

            foreach ($lines as $lineNumber => $line) {
                foreach ($patterns as $pattern) {
                    if (1 === preg_match($pattern, $line)) {
                        $violations[] = sprintf('%s:%d: %s', $file->getPathname(), $lineNumber + 1, trim($line));
                    }
                }
            }
        }

        $this->assertSame(
            [],
            $violations,
            "data_source literals must be declared only in class-recognition-data-source.php:\n" . implode("\n", $violations)
        );
    }
}
