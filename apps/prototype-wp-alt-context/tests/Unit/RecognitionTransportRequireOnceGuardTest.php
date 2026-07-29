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
 * Reference detection is token-scoped (R16-BR-01): comments, docblocks, and
 * substring class names (NotRecognitionTransport) do not count. Forms
 * detected (R19-BR-10 / R16-BR-12):
 *   - Static call / ::class: T_STRING short name followed by T_DOUBLE_COLON
 *   - FQCN identifier / use import: T_NAME_QUALIFIED / T_NAME_FULLY_QUALIFIED
 *   - Class-name string (callable-array / string class ref):
 *     T_CONSTANT_ENCAPSED_STRING whose unquoted value equals the FQCN
 *   - Heredoc / nowdoc body: T_ENCAPSED_AND_WHITESPACE containing the FQCN
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
     * Temp fixtures written under src/ for pin tests; unlinked in tearDown.
     *
     * @var list<string>
     */
    private array $tempFixtures = [];

    protected function tearDown(): void
    {
        foreach ($this->tempFixtures as $path) {
            if (is_file($path)) {
                // phpcs:ignore WordPress.WP.AlternativeFunctions.unlink_unlink -- test fixture cleanup
                unlink($path);
            }
        }
        $this->tempFixtures = [];
        parent::tearDown();
    }

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
        $offenders = $this->collectOffenders();
        $this->assertSame(
            [],
            $offenders,
            "src/ consumers must explicitly require_once transport/loopback hosts:\n"
            . implode("\n", $offenders)
        );
    }

    /**
     * R16-BR-01: a comment-only mention of RecognitionTransport:: must not
     * trip the guard (raw str_contains previously did).
     */
    public function testCommentOnlyShortNameDoesNotTriggerGuard(): void
    {
        $relative = 'api/_acx_guard_fixture_comment_short.php';
        $this->writeSrcFixture(
            $relative,
            "<?php\n// RecognitionTransport:: is mentioned only in a comment here.\n"
            . "namespace AltContext\\Api;\nclass ProbeCommentOnlyShort {}\n"
        );

        $offenders = $this->collectOffenders();
        $this->assertNotContains(
            sprintf(
                '%s references RecognitionTransport but has no require_once for class-recognition-transport.php',
                $relative
            ),
            $offenders,
            'Comment-only RecognitionTransport:: must not count as a reference'
        );
        $this->assertSame([], $offenders, 'Fixture must not introduce any offenders');
    }

    /**
     * R16-BR-01: a comment-only FQCN must not trip the guard.
     */
    public function testCommentOnlyFqcnDoesNotTriggerGuard(): void
    {
        $relative = 'api/_acx_guard_fixture_comment_fqcn.php';
        $this->writeSrcFixture(
            $relative,
            "<?php\n// AltContext\\Support\\RecognitionTransport mentioned only in a comment.\n"
            . "namespace AltContext\\Api;\nclass ProbeCommentOnlyFqcn {}\n"
        );

        $offenders = $this->collectOffenders();
        $this->assertNotContains(
            sprintf(
                '%s references RecognitionTransport but has no require_once for class-recognition-transport.php',
                $relative
            ),
            $offenders,
            'Comment-only FQCN must not count as a reference'
        );
        $this->assertSame([], $offenders, 'Fixture must not introduce any offenders');
    }

    /**
     * R16-BR-01: substring class names must not match the short name.
     */
    public function testSubstringClassNameDoesNotTriggerGuard(): void
    {
        $relative = 'api/_acx_guard_fixture_substring.php';
        $this->writeSrcFixture(
            $relative,
            "<?php\nnamespace AltContext\\Api;\n"
            . "class NotRecognitionTransport { public static function x(): void {} }\n"
            . "NotRecognitionTransport::x();\n"
        );

        $offenders = $this->collectOffenders();
        $this->assertNotContains(
            sprintf(
                '%s references RecognitionTransport but has no require_once for class-recognition-transport.php',
                $relative
            ),
            $offenders,
            'NotRecognitionTransport:: must not match RecognitionTransport'
        );
        $this->assertSame([], $offenders, 'Fixture must not introduce any offenders');
    }

    /**
     * R16-BR-01: a real static call without require_once must still fail.
     */
    public function testRealStaticCallWithoutRequireOnceIsDetected(): void
    {
        $relative = 'api/_acx_guard_fixture_real_call.php';
        $this->writeSrcFixture(
            $relative,
            "<?php\nnamespace AltContext\\Api;\n"
            . "class ProbeRealCall {\n"
            . "    public function run(): void { RecognitionTransport::get('http://x'); }\n"
            . "}\n"
        );

        $expected = sprintf(
            '%s references RecognitionTransport but has no require_once for class-recognition-transport.php',
            $relative
        );
        $this->assertContains(
            $expected,
            $this->collectOffenders(),
            'Real RecognitionTransport::get() without require_once must fail the guard'
        );
    }

    /**
     * Real use-import plus require_once stays green.
     */
    public function testRealUseWithRequireOnceIsGreen(): void
    {
        $relative = 'api/_acx_guard_fixture_use_ok.php';
        $this->writeSrcFixture(
            $relative,
            "<?php\nnamespace AltContext\\Api;\n"
            . "require_once __DIR__ . '/../support/class-recognition-transport.php';\n"
            . "use AltContext\\Support\\RecognitionTransport;\n"
            . "class ProbeUseOk {\n"
            . "    public function run(): void { RecognitionTransport::get('http://x'); }\n"
            . "}\n"
        );

        $offenders = $this->collectOffenders();
        $this->assertNotContains(
            sprintf(
                '%s references RecognitionTransport but has no require_once for class-recognition-transport.php',
                $relative
            ),
            $offenders
        );
        $this->assertSame([], $offenders, 'Valid consumer with require_once must stay green');
    }

    /**
     * R16-BR-12: heredoc body carrying the FQCN is a real reference.
     */
    public function testHeredocFqcnWithoutRequireOnceIsDetected(): void
    {
        $relative = 'api/_acx_guard_fixture_heredoc.php';
        $this->writeSrcFixture(
            $relative,
            "<?php\nnamespace AltContext\\Api;\n"
            . "class ProbeHeredoc {\n"
            . "    public function cname(): string {\n"
            . "        return <<<EOT\n"
            . "AltContext\\Support\\RecognitionTransport\n"
            . "EOT;\n"
            . "    }\n"
            . "}\n"
        );

        $expected = sprintf(
            '%s references RecognitionTransport but has no require_once for class-recognition-transport.php',
            $relative
        );
        $this->assertContains($expected, $this->collectOffenders());
    }

    /**
     * R16-BR-12: double-quoted FQCN with single backslashes must match after
     * unquote (PHP keeps \S for unrecognised escapes — same runtime value as \\).
     */
    public function testDoubleQuotedSingleBackslashFqcnWithoutRequireOnceIsDetected(): void
    {
        $relative = 'api/_acx_guard_fixture_dq_single_bs.php';
        // Build source so the file literally contains single-backslash sequences
        // inside a double-quoted string: "AltContext\Support\RecognitionTransport"
        $php = '<?php' . "\n" . 'namespace AltContext\\Api;' . "\n"
            . 'class ProbeDq {' . "\n"
            . '    public function cname(): string {' . "\n"
            . '        return "AltContext\\Support\\RecognitionTransport";' . "\n"
            . '    }' . "\n"
            . '}' . "\n";
        $this->writeSrcFixture($relative, $php);

        // Pin unquote semantics deliberately: both single- and double-bs source
        // forms unquote to the FQCN (PHP double-quote rules).
        $this->assertSame(
            'AltContext\\Support\\RecognitionTransport',
            $this->unquoteString('"AltContext\\Support\\RecognitionTransport"'),
            'single-bs double-quoted: unrecognised \\S keeps both chars'
        );
        $this->assertSame(
            'AltContext\\Support\\RecognitionTransport',
            $this->unquoteString('"AltContext\\\\Support\\\\RecognitionTransport"'),
            'double-bs double-quoted: \\\\ collapses to \\'
        );
        $this->assertSame(
            $this->unquoteString('"AltContext\\Support\\RecognitionTransport"'),
            $this->unquoteString('"AltContext\\\\Support\\\\RecognitionTransport"'),
            '"A\\Support" and "A\\\\Support" unquote to the same FQCN string'
        );

        $expected = sprintf(
            '%s references RecognitionTransport but has no require_once for class-recognition-transport.php',
            $relative
        );
        $this->assertContains($expected, $this->collectOffenders());
    }

    /**
     * @return list<string>
     */
    private function collectOffenders(): array
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

        return $offenders;
    }

    private function writeSrcFixture(string $relative, string $contents): void
    {
        $srcRoot = realpath(dirname(__DIR__, 2) . '/src');
        $this->assertIsString($srcRoot, 'src/ must exist');
        $path = $srcRoot . '/' . $relative;
        // phpcs:ignore WordPress.WP.AlternativeFunctions.file_system_operations_file_put_contents -- test fixture
        file_put_contents($path, $contents);
        $this->tempFixtures[] = $path;
    }

    /**
     * True when $contents references the class via token-scoped static `::`,
     * FQCN name token / use-import, class-name string, or heredoc/nowdoc body.
     * Comments and substring identifiers are ignored (R16-BR-01).
     */
    private function fileReferencesClass(string $contents, string $short, string $fqcn): bool
    {
        $tokens = token_get_all($contents);
        $count = count($tokens);
        $fqcnFullyQualified = '\\' . $fqcn;

        for ($i = 0; $i < $count; $i++) {
            $token = $tokens[$i];
            if (!is_array($token)) {
                continue;
            }

            [$id, $text] = $token;

            // Skip comments entirely — they must never count as references.
            if (T_COMMENT === $id || T_DOC_COMMENT === $id) {
                continue;
            }

            // Static call / ::class: exact T_STRING short name + T_DOUBLE_COLON.
            // NotRecognitionTransport / XRecognitionTransport do not match.
            if (T_STRING === $id && $text === $short) {
                $next = $this->nextSignificantToken($tokens, $i);
                if (is_array($next) && T_DOUBLE_COLON === $next[0]) {
                    return true;
                }
                continue;
            }

            // FQCN identifier or use-import (PHP 8+ name tokens).
            if (
                (defined('T_NAME_QUALIFIED') && T_NAME_QUALIFIED === $id && $text === $fqcn)
                || (defined('T_NAME_FULLY_QUALIFIED') && T_NAME_FULLY_QUALIFIED === $id
                    && ($text === $fqcnFullyQualified || $text === $fqcn))
            ) {
                return true;
            }

            // Class-name strings / callable arrays.
            if (T_CONSTANT_ENCAPSED_STRING === $id) {
                if ($this->unquoteString($text) === $fqcn) {
                    return true;
                }
                continue;
            }

            // Heredoc / nowdoc bodies (R16-BR-12): arrive as T_ENCAPSED_AND_WHITESPACE.
            if (T_ENCAPSED_AND_WHITESPACE === $id) {
                if ($this->heredocBodyReferencesFqcn($text, $fqcn)) {
                    return true;
                }
            }
        }

        return false;
    }

    /**
     * Heredoc/nowdoc body matches when it is (or contains as a whole line) the FQCN.
     */
    private function heredocBodyReferencesFqcn(string $body, string $fqcn): bool
    {
        if (trim($body) === $fqcn) {
            return true;
        }

        // Multi-line bodies: any full line equal to the FQCN.
        $lines = preg_split('/\R/', $body);
        if (!is_array($lines)) {
            return false;
        }
        foreach ($lines as $line) {
            if ($line === $fqcn) {
                return true;
            }
        }

        return false;
    }

    /**
     * Next non-whitespace, non-comment token after $index, or null.
     *
     * @param array<int, string|array{0:int,1:string,2:int}> $tokens
     * @return string|array{0:int,1:string,2:int}|null
     */
    private function nextSignificantToken(array $tokens, int $index)
    {
        $count = count($tokens);
        for ($j = $index + 1; $j < $count; $j++) {
            $t = $tokens[$j];
            if (!is_array($t)) {
                return $t;
            }
            if (in_array($t[0], [T_WHITESPACE, T_COMMENT, T_DOC_COMMENT], true)) {
                continue;
            }

            return $t;
        }

        return null;
    }

    /**
     * Recover the runtime string value from a T_CONSTANT_ENCAPSED_STRING token.
     *
     * Double-quoted deliberate rule (R16-BR-12): PHP retains both the backslash
     * and the following character for unrecognised escape sequences. Therefore
     * `"A\Support"` and `"A\\Support"` both unquote to `A\Support` (the FQCN
     * form). `stripcslashes` is wrong — it collapses `\S` → `S`.
     */
    private function unquoteString(string $text): string
    {
        if (strlen($text) < 2) {
            return $text;
        }

        $quote = $text[0];
        if (("'" === $quote || '"' === $quote) && $text[strlen($text) - 1] === $quote) {
            $inner = substr($text, 1, -1);
            if ("'" === $quote) {
                // Single-quoted: only \\ and \' are escapes.
                return str_replace(["\\\\", "\\'"], ["\\", "'"], $inner);
            }

            return $this->unquoteDoubleQuotedInner($inner);
        }

        return $text;
    }

    /**
     * Unescape a double-quoted string body per PHP runtime rules (subset needed
     * for class FQCNs, plus the common special escapes).
     */
    private function unquoteDoubleQuotedInner(string $inner): string
    {
        $result = '';
        $len = strlen($inner);
        for ($i = 0; $i < $len; $i++) {
            if ('\\' !== $inner[$i] || $i + 1 >= $len) {
                $result .= $inner[$i];
                continue;
            }

            $next = $inner[$i + 1];
            switch ($next) {
                case '\\':
                case '"':
                case '$':
                    $result .= $next;
                    $i++;
                    break;
                case 'n':
                    $result .= "\n";
                    $i++;
                    break;
                case 'r':
                    $result .= "\r";
                    $i++;
                    break;
                case 't':
                    $result .= "\t";
                    $i++;
                    break;
                case 'v':
                    $result .= "\v";
                    $i++;
                    break;
                case 'e':
                    $result .= "\e";
                    $i++;
                    break;
                case 'f':
                    $result .= "\f";
                    $i++;
                    break;
                default:
                    // Unrecognised escape: keep both backslash and character
                    // (PHP: "\S" === "\\S" for non-special S).
                    $result .= '\\' . $next;
                    $i++;
                    break;
            }
        }

        return $result;
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
