<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Tests\TestCase;
use RecursiveDirectoryIterator;
use RecursiveIteratorIterator;
use SplFileInfo;

/**
 * R5G-BR-05 / [rg-016]: production consumers of RecognitionTransport and
 * LoopbackHost must carry an explicit require_once. The PHPUnit kebab-case
 * fallback autoloader masks a missing require (suite stays green while
 * WordPress fatals on a stale classmap).
 *
 * Self-exemption compares the src-relative path for exact equality so a
 * spoofed filename ending in class-recognition-transport.php cannot opt out.
 * Satisfaction is token-based (T_REQUIRE_ONCE) so a comment mentioning the
 * require_once path cannot satisfy the guard.
 *
 * @coversNothing
 */
class RecognitionTransportRequireOnceGuardTest extends TestCase
{
    /**
     * Every src/ file that references RecognitionTransport:: must also
     * require class-recognition-transport.php. Same for LoopbackHost::.
     *
     * Keys are the static-reference needle; values are the defining file's
     * path relative to src/ (exact match for self-exemption).
     */
    public function testConsumersExplicitlyRequireTransportAndLoopbackHost(): void
    {
        $srcRoot = realpath(dirname(__DIR__, 2) . '/src');
        $this->assertIsString($srcRoot, 'src/ must exist');

        $checks = [
            'RecognitionTransport::' => 'support/class-recognition-transport.php',
            'LoopbackHost::' => 'support/class-loopback-host.php',
        ];

        $offenders = [];

        $iterator = new RecursiveIteratorIterator(
            new RecursiveDirectoryIterator($srcRoot, RecursiveDirectoryIterator::SKIP_DOTS)
        );

        /** @var SplFileInfo $file */
        foreach ($iterator as $file) {
            if (!$file->isFile() || 'php' !== $file->getExtension()) {
                continue;
            }

            $path = $file->getPathname();
            $contents = (string) file_get_contents($path);
            $relative = str_replace('\\', '/', substr($path, strlen($srcRoot) + 1));

            foreach ($checks as $reference => $requireRelative) {
                if (!str_contains($contents, $reference)) {
                    continue;
                }

                // The defining file itself need not re-require its own class
                // file, but RecognitionTransport must still require LoopbackHost
                // (caught by the LoopbackHost:: check on that file).
                // Exact src-relative path equality — not a suffix match — so
                // evil-class-recognition-transport.php cannot self-exempt.
                if ($relative === $requireRelative) {
                    continue;
                }

                $requireFile = basename($requireRelative);
                if (!$this->containsRequireOnceFor($contents, $requireFile)) {
                    $offenders[] = sprintf(
                        '%s references %s but has no require_once for %s',
                        $relative,
                        $reference,
                        $requireFile
                    );
                }
            }
        }

        $this->assertSame(
            [],
            $offenders,
            "src/ consumers must explicitly require_once transport/loopback hosts:\n"
            . implode("\n", $offenders)
        );
    }

    /**
     * True when a real T_REQUIRE_ONCE statement names $requireFile.
     * Comments and string-only mentions do not count.
     */
    private function containsRequireOnceFor(string $contents, string $requireFile): bool
    {
        $tokens = token_get_all($contents);
        $count = count($tokens);

        for ($i = 0; $i < $count; $i++) {
            $token = $tokens[$i];
            if (!is_array($token) || T_REQUIRE_ONCE !== $token[0]) {
                continue;
            }

            // Collect the require_once expression until ';' — comments skipped.
            $stmt = '';
            for ($j = $i + 1; $j < $count; $j++) {
                $t = $tokens[$j];
                if (';' === $t) {
                    break;
                }
                if (is_array($t)) {
                    if (in_array($t[0], [T_COMMENT, T_DOC_COMMENT], true)) {
                        continue;
                    }
                    $stmt .= $t[1];
                } else {
                    $stmt .= $t;
                }
            }

            if (str_contains($stmt, $requireFile)) {
                return true;
            }
        }

        return false;
    }
}
