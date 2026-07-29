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
 * Reference forms detected (R19-BR-10):
 *   - Static call / ::class: `RecognitionTransport::`, `LoopbackHost::`
 *   - FQCN identifier / use import: `AltContext\Support\RecognitionTransport`
 *   - Fully-qualified class-name string (callable-array / string class ref):
 *     `'AltContext\\Support\\RecognitionTransport'` (token value match)
 *
 * Not detected (accepted boundary): dynamically assembled FQCNs
 * (`'AltContext\\Support\\' . 'RecognitionTransport'`), variable class names
 * with no literal FQCN in the file, and reflection-only indirection. Those
 * still need a human review path; the `::` / FQCN / string forms cover every
 * call site in src/ today and the forms that hide a missing require_once.
 *
 * @coversNothing
 */
class RecognitionTransportRequireOnceGuardTest extends TestCase
{
    /**
     * Every src/ file that references RecognitionTransport or LoopbackHost
     * (static `::`, FQCN identifier, or class-name string / callable array)
     * must also require the defining file.
     *
     * @return array<string, array{require: string, short: string, fqcn: string}>
     */
    private static function classChecks(): array
    {
        return [
            'RecognitionTransport' => [
                'require' => 'support/class-recognition-transport.php',
                'short' => 'RecognitionTransport',
                'fqcn' => 'AltContext\\Support\\RecognitionTransport',
            ],
            'LoopbackHost' => [
                'require' => 'support/class-loopback-host.php',
                'short' => 'LoopbackHost',
                'fqcn' => 'AltContext\\Support\\LoopbackHost',
            ],
        ];
    }

    public function testConsumersExplicitlyRequireTransportAndLoopbackHost(): void
    {
        $srcRoot = realpath(dirname(__DIR__, 2) . '/src');
        $this->assertIsString($srcRoot, 'src/ must exist');

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

            foreach (self::classChecks() as $label => $check) {
                if (!$this->fileReferencesClass($contents, $check['short'], $check['fqcn'])) {
                    continue;
                }

                // The defining file itself need not re-require its own class
                // file, but RecognitionTransport must still require LoopbackHost
                // (caught by the LoopbackHost check on that file).
                // Exact src-relative path equality — not a suffix match — so
                // evil-class-recognition-transport.php cannot self-exempt.
                if ($relative === $check['require']) {
                    continue;
                }

                $requireFile = basename($check['require']);
                if (!$this->containsRequireOnceFor($contents, $requireFile)) {
                    $offenders[] = sprintf(
                        '%s references %s but has no require_once for %s',
                        $relative,
                        $label,
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
     * True when $contents references the class via static `::`, FQCN text, or
     * a string literal whose value is the FQCN (callable-array / class string).
     */
    private function fileReferencesClass(string $contents, string $short, string $fqcn): bool
    {
        // Static call / ::class — original needle.
        if (str_contains($contents, $short . '::')) {
            return true;
        }

        // FQCN identifier or use-import (single backslash in source).
        if (str_contains($contents, $fqcn)) {
            return true;
        }

        // Class-name strings / callable arrays: token value equals FQCN even
        // when the source writes escaped backslashes ('AltContext\\Support\\...').
        $tokens = token_get_all($contents);
        foreach ($tokens as $token) {
            if (!is_array($token) || T_CONSTANT_ENCAPSED_STRING !== $token[0]) {
                continue;
            }
            if ($this->unquoteString($token[1]) === $fqcn) {
                return true;
            }
        }

        return false;
    }

    private function unquoteString(string $text): string
    {
        if (strlen($text) < 2) {
            return $text;
        }

        $quote = $text[0];
        if (("'" === $quote || '"' === $quote) && $text[strlen($text) - 1] === $quote) {
            $inner = substr($text, 1, -1);
            // Single-quoted: only \\ and \' are escapes. Double-quoted: strip
            // common escapes enough to recover a class FQCN.
            if ("'" === $quote) {
                return str_replace(["\\\\", "\\'"], ["\\", "'"], $inner);
            }

            return stripcslashes($inner);
        }

        return $text;
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
