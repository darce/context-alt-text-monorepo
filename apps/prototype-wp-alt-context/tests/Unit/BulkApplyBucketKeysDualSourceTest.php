<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\AltTextWriteStatus;
use AltContext\Tests\TestCase;

/**
 * R21-BR-13 / R22-BR-08: BULK_APPLY_BUCKETS is dual-sourced.
 *
 * `array_fill_keys` / the response envelope iterate the const, while the apply
 * loop in DescribeController writes `$buckets['…']` as magic string literals.
 * Renaming a const member without updating every literal silently orphans media
 * ids from the wire envelope (response key becomes the new name; the loop still
 * fills the old one). The converse is also a hole: deleting every write to a
 * canonical bucket leaves the envelope advertising a key nothing ever fills.
 *
 * This pin derives the loop-written keys from the controller source so the test
 * is not a third hard-coded list. It asserts set equality both ways:
 *   loop keys ⊆ BULK_APPLY_BUCKETS  AND  BULK_APPLY_BUCKETS ⊆ loop keys.
 *
 * Scrape uses PHP's own lexer (`token_get_all`) so braces and subscripts inside
 * string literals, heredocs and comments cannot hide writes or truncate the
 * method body (R23-BR-03 / R23-BR-04). Non-literal `$buckets[…]` writes
 * (variable subscripts, concatenated keys) remain fail-closed rather than
 * reporting green when the pin cannot see the subject [rg-016].
 *
 * Routing the loop through the const members is a production fix owned by the
 * controller lane; this test only closes the detection gap.
 *
 * @covers \AltContext\Api\AltTextWriteStatus
 */
class BulkApplyBucketKeysDualSourceTest extends TestCase
{
    /**
     * Apply-loop `$buckets['…']` write keys must equal BULK_APPLY_BUCKETS in
     * both directions. A rename of a const member without updating the literal,
     * a const member no longer written by the loop, or a non-literal write each
     * turns this RED.
     */
    public function testApplyLoopBucketKeysMatchBulkApplyBucketsBothDirections(): void
    {
        $controllerPath = realpath(__DIR__ . '/../../src/api/class-describe-controller.php');
        self::assertIsString($controllerPath, 'class-describe-controller.php must exist');

        $source = (string) file_get_contents($controllerPath);
        $tokens = token_get_all($source);

        $bodyTokens = $this->extractMethodBodyTokens($tokens, 'apply_describe_run_drafts');
        if (null === $bodyTokens) {
            self::fail(
                'Could not locate a closed apply_describe_run_drafts() body in class-describe-controller.php'
            );
        }

        $loopKeys = $this->extractBucketWriteKeys($bodyTokens);
        if (array() === $loopKeys) {
            self::fail(
                'Expected at least one $buckets[…] write in apply_describe_run_drafts()'
            );
        }

        $loopKeys = array_values(array_unique($loopKeys));
        self::assertNotEmpty($loopKeys, 'Derived apply-loop bucket keys must be non-empty');

        // Both directions: loop keys ⊆ const AND const ⊆ loop keys.
        // (assertEqualsCanonicalizing is set-equality on the unique lists.)
        self::assertEqualsCanonicalizing(
            AltTextWriteStatus::BULK_APPLY_BUCKETS,
            $loopKeys,
            'Apply-loop $buckets[\'…\'] write keys must equal BULK_APPLY_BUCKETS both ways — '
                . 'a rename without updating the loop, or a const member the loop never '
                . 'writes, orphans media ids from the wire envelope'
        );
    }

    /**
     * Return the token slice of a method body by counting brace *tokens* only.
     *
     * Openers: bare `{`, T_CURLY_OPEN, T_DOLLAR_OPEN_CURLY_BRACES.
     * Closer: bare `}`.
     * Braces inside T_CONSTANT_ENCAPSED_STRING, T_ENCAPSED_AND_WHITESPACE,
     * T_COMMENT, T_DOC_COMMENT and heredoc bodies are not brace tokens and
     * cannot truncate the range.
     *
     * @param list<string|array{0:int,1:string,2:int}> $tokens
     * @return list<string|array{0:int,1:string,2:int}>|null
     */
    private function extractMethodBodyTokens(array $tokens, string $methodName): ?array
    {
        $count = count($tokens);
        $i     = 0;

        while ($i < $count) {
            $token = $tokens[ $i ];
            if (! is_array($token) || T_FUNCTION !== $token[0]) {
                ++$i;
                continue;
            }

            // Skip whitespace / comments between `function` and the name.
            $j = $this->skipInsignificant($tokens, $i + 1);
            if ($j >= $count) {
                return null;
            }

            $nameToken = $tokens[ $j ];
            if (! is_array($nameToken) || T_STRING !== $nameToken[0] || $methodName !== $nameToken[1]) {
                ++$i;
                continue;
            }

            // Advance to the opening brace of the method body.
            $k = $j + 1;
            while ($k < $count) {
                $t = $tokens[ $k ];
                if ('{' === $t || (is_array($t) && T_CURLY_OPEN === $t[0])) {
                    break;
                }
                ++$k;
            }
            if ($k >= $count) {
                return null;
            }

            $start = $k;
            $depth = 0;
            for ($p = $start; $p < $count; $p++) {
                $t = $tokens[ $p ];
                if ($this->isBraceOpenToken($t)) {
                    ++$depth;
                } elseif ($this->isBraceCloseToken($t)) {
                    --$depth;
                    if (0 === $depth) {
                        // Inclusive body range: opening `{` … closing `}`.
                        return array_slice($tokens, $start, $p - $start + 1);
                    }
                }
            }

            // Method found but body never closed.
            return null;
        }

        return null;
    }

    /**
     * Collect string-literal keys of every `$buckets[…]` *write* in the body.
     * Reads (`$body[$k] = $buckets[$k]`) are ignored. Non-literal subscripts
     * fail closed — the pin must not report green when it cannot verify [rg-016].
     *
     * @param list<string|array{0:int,1:string,2:int}> $bodyTokens
     * @return list<string>
     */
    private function extractBucketWriteKeys(array $bodyTokens): array
    {
        $keys  = array();
        $count = count($bodyTokens);

        for ($i = 0; $i < $count; $i++) {
            $token = $bodyTokens[ $i ];
            if (! is_array($token) || T_VARIABLE !== $token[0] || '$buckets' !== $token[1]) {
                continue;
            }

            // Must be followed by `[` (subscript access).
            $j = $this->skipInsignificant($bodyTokens, $i + 1);
            if ($j >= $count || '[' !== $bodyTokens[ $j ]) {
                continue;
            }

            // Parse the first subscript: content between this `[` and its matching `]`.
            $subStart = $j + 1;
            $subEnd   = $this->findMatchingBracket($bodyTokens, $j);
            if (null === $subEnd) {
                self::fail(
                    'Dual-source check cannot verify $buckets[…] write with unclosed subscript — '
                        . 'bucket routing must use a single string-literal key so the '
                        . 'pin can assert set equality with BULK_APPLY_BUCKETS'
                );
            }

            // After the first `]`, allow optional empty `[]` then require `=` for a write.
            $after = $this->skipInsignificant($bodyTokens, $subEnd + 1);
            if ($after < $count && '[' === $bodyTokens[ $after ]) {
                $innerClose = $this->skipInsignificant($bodyTokens, $after + 1);
                if ($innerClose < $count && ']' === $bodyTokens[ $innerClose ]) {
                    // Empty append form: `$buckets['k'][] = …`
                    $after = $this->skipInsignificant($bodyTokens, $innerClose + 1);
                }
            }

            // Not a write (e.g. `$body[$k] = $buckets[$k]` read) — skip.
            if ($after >= $count || '=' !== $bodyTokens[ $after ]) {
                continue;
            }

            // Fail closed: subscript must be exactly one T_CONSTANT_ENCAPSED_STRING.
            $significant = array();
            for ($s = $subStart; $s < $subEnd; $s++) {
                $st = $bodyTokens[ $s ];
                if (is_array($st) && (T_WHITESPACE === $st[0] || T_COMMENT === $st[0] || T_DOC_COMMENT === $st[0])) {
                    continue;
                }
                $significant[] = $st;
            }

            if (
                1 !== count($significant)
                || ! is_array($significant[0])
                || T_CONSTANT_ENCAPSED_STRING !== $significant[0][0]
            ) {
                $raw = $this->tokensToText(array_slice($bodyTokens, $subStart, $subEnd - $subStart));
                self::fail(
                    sprintf(
                        'Dual-source check cannot verify non-literal $buckets[%s] write — '
                            . 'bucket routing must use a single string-literal key so the '
                            . 'pin can assert set equality with BULK_APPLY_BUCKETS',
                        trim($raw)
                    )
                );
            }

            $keys[] = $this->decodeStringLiteral($significant[0][1]);
        }

        return $keys;
    }

    /**
     * @param string|array{0:int,1:string,2:int} $token
     */
    private function isBraceOpenToken(string|array $token): bool
    {
        if ('{' === $token) {
            return true;
        }
        if (! is_array($token)) {
            return false;
        }

        return T_CURLY_OPEN === $token[0]
            || T_DOLLAR_OPEN_CURLY_BRACES === $token[0];
    }

    /**
     * @param string|array{0:int,1:string,2:int} $token
     */
    private function isBraceCloseToken(string|array $token): bool
    {
        return '}' === $token;
    }

    /**
     * Skip whitespace and comments.
     *
     * @param list<string|array{0:int,1:string,2:int}> $tokens
     */
    private function skipInsignificant(array $tokens, int $from): int
    {
        $count = count($tokens);
        while ($from < $count) {
            $t = $tokens[ $from ];
            if (is_array($t) && (T_WHITESPACE === $t[0] || T_COMMENT === $t[0] || T_DOC_COMMENT === $t[0])) {
                ++$from;
                continue;
            }
            break;
        }

        return $from;
    }

    /**
     * Find the `]` that matches the `[` at $openIndex, brace-depth aware for
     * nested `[` / `]` only (subscripts do not nest `{` as PHP tokens).
     *
     * @param list<string|array{0:int,1:string,2:int}> $tokens
     */
    private function findMatchingBracket(array $tokens, int $openIndex): ?int
    {
        $count = count($tokens);
        $depth = 0;
        for ($i = $openIndex; $i < $count; $i++) {
            $t = $tokens[ $i ];
            if ('[' === $t) {
                ++$depth;
            } elseif (']' === $t) {
                --$depth;
                if (0 === $depth) {
                    return $i;
                }
            }
        }

        return null;
    }

    /**
     * Decode a T_CONSTANT_ENCAPSED_STRING token text to its string value.
     */
    private function decodeStringLiteral(string $tokenText): string
    {
        // token_get_all keeps the surrounding quotes; strip single layer.
        if (strlen($tokenText) >= 2) {
            $q = $tokenText[0];
            if (("'" === $q || '"' === $q) && $tokenText[ strlen($tokenText) - 1 ] === $q) {
                $inner = substr($tokenText, 1, -1);
                if ('"' === $q) {
                    // Minimal unescape for double-quoted constant strings.
                    return stripcslashes($inner);
                }

                // Single-quoted: only \\ and \' are escapes.
                return str_replace(array('\\\\', '\\\''), array('\\', "'"), $inner);
            }
        }

        return $tokenText;
    }

    /**
     * @param list<string|array{0:int,1:string,2:int}> $tokens
     */
    private function tokensToText(array $tokens): string
    {
        $out = '';
        foreach ($tokens as $t) {
            $out .= is_array($t) ? $t[1] : $t;
        }

        return $out;
    }
}
