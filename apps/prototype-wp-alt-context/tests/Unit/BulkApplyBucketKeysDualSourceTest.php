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
 * method body (R23-BR-03 / R23-BR-04).
 *
 * Walker is a denylist, not an allowlist (R23-BR-12 / R23-BR-13 / R23-BR-27):
 * after `$buckets` plus any full subscript chain, the next significant token is
 * classified as write, read, or unknown. Unknown tokens `self::fail()` with
 * file:line — never bare-`continue`. Assignment-family ops (including
 * `T_CONCAT_EQUAL`, per-key `T_PLUS_EQUAL`, …) are writes; multi-level
 * subscripts (`$buckets['k']['sub'][] = …`) are skipped as a chain before the
 * op test. `array_push( $buckets['lit'], … )` is resolved. Reference-alias
 * `=& $buckets[…]` fails closed (not analysed). Whole-`$buckets` forms
 * (`+=` / `=` literal array / safe `array_fill_keys(BULK_APPLY_BUCKETS)`)
 * remain resolved. Non-literal write keys also fail closed.
 *
 * Routing the loop through the const members is a production fix owned by the
 * controller lane; this test only closes the detection gap.
 *
 * @covers \AltContext\Api\AltTextWriteStatus
 */
class BulkApplyBucketKeysDualSourceTest extends TestCase
{
    private const CONTROLLER_REL = 'src/api/class-describe-controller.php';

    /**
     * Apply-loop `$buckets['…']` write keys must equal BULK_APPLY_BUCKETS in
     * both directions. A rename of a const member without updating the literal,
     * a const member no longer written by the loop, or a non-literal write each
     * turns this RED.
     */
    public function testApplyLoopBucketKeysMatchBulkApplyBucketsBothDirections(): void
    {
        $scrape = $this->scrapeControllerApplyLoopBucketKeys();

        self::assertGreaterThan(
            1,
            $scrape['resolved_call_sites'],
            'walker must resolve more than one apply-loop bucket write site; '
                . '0 or 1 means the scrape is not seeing the corpus'
        );
        self::assertSame(
            0,
            $scrape['failed_closed_call_sites'],
            'unmutated controller must not hit fail-closed paths'
        );
        self::assertNotEmpty($scrape['keys'], 'Derived apply-loop bucket keys must be non-empty');

        // Both directions: loop keys ⊆ const AND const ⊆ loop keys.
        // (assertEqualsCanonicalizing is set-equality on the unique lists.)
        self::assertEqualsCanonicalizing(
            AltTextWriteStatus::BULK_APPLY_BUCKETS,
            $scrape['keys'],
            'Apply-loop $buckets[\'…\'] write keys must equal BULK_APPLY_BUCKETS both ways — '
                . 'a rename without updating the loop, or a const member the loop never '
                . 'writes, orphans media ids from the wire envelope'
        );
    }

    /**
     * False-failure / scrape-health pin: unmutated tree stays GREEN and the
     * walker resolves multiple real call sites (a count of 0–1 is meaningless).
     */
    public function testBucketKeyScrapeResolvesMultipleCallSitesWithoutFalseFailure(): void
    {
        $scrape = $this->scrapeControllerApplyLoopBucketKeys();

        self::assertGreaterThan(
            1,
            $scrape['resolved_call_sites'],
            'resolved call-site count must be > 1 on the unmutated controller'
        );
        self::assertSame(
            0,
            $scrape['failed_closed_call_sites'],
            'fail-closed count must be 0 on the unmutated controller'
        );
        self::assertEqualsCanonicalizing(
            AltTextWriteStatus::BULK_APPLY_BUCKETS,
            $scrape['keys'],
            'success path: unmutated apply-loop keys still match BULK_APPLY_BUCKETS'
        );
        // No-op re-check: same scrape still reports success.
        self::assertEqualsCanonicalizing(
            AltTextWriteStatus::BULK_APPLY_BUCKETS,
            $scrape['keys'],
            'no-op path: re-checking the same key set still reports success'
        );
    }

    /**
     * Plain `$buckets['lit'] = …` form (no empty-append) still surfaces a
     * fabricated key [TEST-15]. Distinct from the `$buckets['lit'][] =` pin.
     */
    public function testPlainLiteralWriteFormSurfacesFabricatedKey(): void
    {
        $php = <<<'PHP'
<?php
function apply_describe_run_drafts() {
    $buckets['applied'] = array( $media_id );
    $buckets['fabricated_plain_literal_xyz'] = array( $media_id );
}
PHP;
        $keys = $this->extractKeysFromSnippet($php, 'plain-literal-fixture.php');
        self::assertContains('fabricated_plain_literal_xyz', $keys);
        self::assertContains('applied', $keys);
    }

    /**
     * `array_push( $buckets['lit'], … )` is a resolved write form [TEST-15].
     */
    public function testArrayPushWriteFormSurfacesFabricatedKey(): void
    {
        $php = <<<'PHP'
<?php
function apply_describe_run_drafts() {
    array_push( $buckets['applied'], $media_id );
    array_push( $buckets['fabricated_array_push_xyz'], $media_id );
}
PHP;
        $keys = $this->extractKeysFromSnippet($php, 'array-push-fixture.php');
        self::assertContains('fabricated_array_push_xyz', $keys);
        self::assertContains('applied', $keys);
    }

    /**
     * `$buckets['lit'][] =` empty-append form is a resolved write form [TEST-15].
     */
    public function testAppendWriteFormSurfacesFabricatedKey(): void
    {
        $php = <<<'PHP'
<?php
function apply_describe_run_drafts() {
    $buckets['applied'][] = $media_id;
    $buckets['fabricated_append_form_xyz'][] = $media_id;
}
PHP;
        $keys = $this->extractKeysFromSnippet($php, 'append-form-fixture.php');
        self::assertContains('fabricated_append_form_xyz', $keys);
    }

    /**
     * `$buckets += array( 'lit' => … )` is a resolved write form [TEST-15].
     */
    public function testPlusEqualWriteFormSurfacesFabricatedKey(): void
    {
        $php = <<<'PHP'
<?php
function apply_describe_run_drafts() {
    $buckets += array(
        'applied' => array( $media_id ),
        'fabricated_plus_equal_xyz' => array( $media_id ),
    );
}
PHP;
        $keys = $this->extractKeysFromSnippet($php, 'plus-equal-fixture.php');
        self::assertContains('fabricated_plus_equal_xyz', $keys);
        self::assertContains('applied', $keys);
    }

    /**
     * Nested array *values* under a literal key still resolve the top-level key
     * [TEST-15] (R23-BR-13 nested form).
     */
    public function testNestedLiteralValueFormSurfacesFabricatedKey(): void
    {
        $php = <<<'PHP'
<?php
function apply_describe_run_drafts() {
    $buckets += array(
        'fabricated_nested_form_xyz' => array(
            'inner' => array( $media_id ),
        ),
    );
}
PHP;
        $keys = $this->extractKeysFromSnippet($php, 'nested-literal-fixture.php');
        self::assertContains('fabricated_nested_form_xyz', $keys);
    }

    /**
     * `$buckets['lit'] .= …` concat-equal is a resolved write form [R23-BR-12].
     */
    public function testConcatEqualWriteFormSurfacesFabricatedKey(): void
    {
        $php = <<<'PHP'
<?php
function apply_describe_run_drafts() {
    $buckets['applied'][] = $media_id;
    $buckets['fabricated_concat_equal_xyz'] .= 'x';
}
PHP;
        $keys = $this->extractKeysFromSnippet($php, 'concat-equal-fixture.php');
        self::assertContains('fabricated_concat_equal_xyz', $keys);
        self::assertContains('applied', $keys);
    }

    /**
     * Multi-level `$buckets['lit']['sub'][] =` is a resolved write form [R23-BR-13].
     */
    public function testNestedSubscriptWriteFormSurfacesFabricatedKey(): void
    {
        $php = <<<'PHP'
<?php
function apply_describe_run_drafts() {
    $buckets['applied'][] = $media_id;
    $buckets['fabricated_nested_sub_xyz']['sub'][] = $media_id;
}
PHP;
        $keys = $this->extractKeysFromSnippet($php, 'nested-sub-fixture.php');
        self::assertContains('fabricated_nested_sub_xyz', $keys);
        self::assertContains('applied', $keys);
    }

    /**
     * Per-key `$buckets['lit'] += …` is a resolved write form [R23-BR-27].
     */
    public function testPerKeyPlusEqualWriteFormSurfacesFabricatedKey(): void
    {
        $php = <<<'PHP'
<?php
function apply_describe_run_drafts() {
    $buckets['applied'][] = $media_id;
    $buckets['fabricated_per_key_plus_xyz'] += array( $media_id );
}
PHP;
        $keys = $this->extractKeysFromSnippet($php, 'per-key-plus-fixture.php');
        self::assertContains('fabricated_per_key_plus_xyz', $keys);
        self::assertContains('applied', $keys);
    }

    /**
     * Fail-closed: reference alias `=& $buckets[…]` is refused, not analysed [R23-BR-27].
     *
     * @throws \PHPUnit\Framework\AssertionFailedError When fail-closed does not fire.
     */
    public function testReferenceAliasToBucketsFailsClosed(): void
    {
        $php = <<<'PHP'
<?php
function apply_describe_run_drafts() {
    $buckets['applied'][] = $media_id;
    $r =& $buckets['ghost_alias'];
    $r[] = $media_id;
}
PHP;
        try {
            $this->extractKeysFromSnippet($php, 'ref-alias-fixture.php');
            self::fail('expected fail-closed on reference alias to $buckets');
        } catch (\PHPUnit\Framework\AssertionFailedError $e) {
            if (str_contains($e->getMessage(), 'expected fail-closed')) {
                throw $e;
            }
            self::assertStringContainsString(
                'reference alias to $buckets is not statically analysable',
                $e->getMessage()
            );
            self::assertMatchesRegularExpression(
                '/ref-alias-fixture\.php:\d+/',
                $e->getMessage()
            );
        }
    }

    /**
     * Fail-closed: token after `$buckets[…]` that is neither write nor read [R23-BR-12].
     *
     * @throws \PHPUnit\Framework\AssertionFailedError When fail-closed does not fire.
     */
    public function testUnrecognisedOperatorAfterBucketChainFailsClosed(): void
    {
        $php = <<<'PHP'
<?php
function apply_describe_run_drafts() {
    $buckets['applied'][] = $media_id;
    $buckets['ghost_inc']++;
}
PHP;
        try {
            $this->extractKeysFromSnippet($php, 'unknown-op-fixture.php');
            self::fail('expected fail-closed on unrecognised operator after $buckets[…]');
        } catch (\PHPUnit\Framework\AssertionFailedError $e) {
            if (str_contains($e->getMessage(), 'expected fail-closed')) {
                throw $e;
            }
            self::assertStringContainsString(
                'unrecognised token after $buckets[…] chain',
                $e->getMessage()
            );
            self::assertMatchesRegularExpression(
                '/unknown-op-fixture\.php:\d+/',
                $e->getMessage()
            );
        }
    }

    /**
     * Control: a pure read of `$buckets['lit']` must not fail or invent keys.
     */
    public function testControlReadOfBucketKeyIsSkipped(): void
    {
        $php = <<<'PHP'
<?php
function apply_describe_run_drafts() {
    $buckets['applied'][] = $media_id;
    $ignored = $buckets['applied'];
}
PHP;
        $keys = $this->extractKeysFromSnippet($php, 'control-read-fixture.php');
        self::assertSame(array( 'applied' ), $keys);
    }

    /**
     * Fail-closed pin: non-literal key-introducing forms name file:line [TEST-15].
     *
     * @throws \PHPUnit\Framework\AssertionFailedError When fail-closed does not fire.
     */
    public function testNonLiteralBucketWriteFailsClosedWithFileAndLine(): void
    {
        $php = <<<'PHP'
<?php
function apply_describe_run_drafts() {
    $buckets[$dynamic][] = $media_id;
}
PHP;
        try {
            $this->extractKeysFromSnippet($php, 'non-literal-fixture.php');
            self::fail('expected fail-closed on non-literal $buckets[$dynamic] write');
        } catch (\PHPUnit\Framework\AssertionFailedError $e) {
            if (str_contains($e->getMessage(), 'expected fail-closed')) {
                throw $e;
            }
            self::assertStringContainsString(
                'non-literal-fixture.php',
                $e->getMessage(),
                'fail-closed message must name the source file'
            );
            self::assertMatchesRegularExpression(
                '/non-literal-fixture\.php:\d+/',
                $e->getMessage(),
                'fail-closed message must include file:line'
            );
        }
    }

    /**
     * Fail-closed: unresolvable `array_push` target is not skipped [TEST-15].
     *
     * @throws \PHPUnit\Framework\AssertionFailedError When fail-closed does not fire.
     */
    public function testArrayPushNonLiteralTargetFailsClosed(): void
    {
        $php = <<<'PHP'
<?php
function apply_describe_run_drafts() {
    array_push( $buckets[$dynamic], $media_id );
}
PHP;
        try {
            $this->extractKeysFromSnippet($php, 'array-push-nonlit-fixture.php');
            self::fail('expected fail-closed on array_push with non-literal target');
        } catch (\PHPUnit\Framework\AssertionFailedError $e) {
            if (str_contains($e->getMessage(), 'expected fail-closed')) {
                throw $e;
            }
            self::assertMatchesRegularExpression(
                '/array-push-nonlit-fixture\.php:\d+/',
                $e->getMessage()
            );
        }
    }

    /**
     * Fail-closed: unresolvable `+=` RHS is not skipped [TEST-15].
     *
     * @throws \PHPUnit\Framework\AssertionFailedError When fail-closed does not fire.
     */
    public function testPlusEqualNonLiteralRhsFailsClosed(): void
    {
        $php = <<<'PHP'
<?php
function apply_describe_run_drafts() {
    $buckets += $dynamic_row;
}
PHP;
        try {
            $this->extractKeysFromSnippet($php, 'plus-equal-nonlit-fixture.php');
            self::fail('expected fail-closed on $buckets += $dynamic_row');
        } catch (\PHPUnit\Framework\AssertionFailedError $e) {
            if (str_contains($e->getMessage(), 'expected fail-closed')) {
                throw $e;
            }
            self::assertMatchesRegularExpression(
                '/plus-equal-nonlit-fixture\.php:\d+/',
                $e->getMessage()
            );
        }
    }

    /**
     * @return array{
     *     keys: list<string>,
     *     resolved_call_sites: int,
     *     failed_closed_call_sites: int
     * }
     */
    private function scrapeControllerApplyLoopBucketKeys(): array
    {
        $controllerPath = realpath(__DIR__ . '/../../' . self::CONTROLLER_REL);
        self::assertIsString($controllerPath, 'class-describe-controller.php must exist');

        $source = (string) file_get_contents($controllerPath);
        $tokens = token_get_all($source);

        $bodyTokens = $this->extractMethodBodyTokens($tokens, 'apply_describe_run_drafts');
        if (null === $bodyTokens) {
            self::fail(
                'Could not locate a closed apply_describe_run_drafts() body in class-describe-controller.php'
            );
        }

        $scrape = $this->extractBucketWriteKeys($bodyTokens, self::CONTROLLER_REL);
        if (array() === $scrape['keys']) {
            self::fail(
                'Expected at least one $buckets[…] write in apply_describe_run_drafts()'
            );
        }

        $scrape['keys'] = array_values(array_unique($scrape['keys']));

        return $scrape;
    }

    /**
     * @return list<string>
     */
    private function extractKeysFromSnippet(string $php, string $sourceLabel): array
    {
        $tokens = token_get_all($php);
        $bodyTokens = $this->extractMethodBodyTokens($tokens, 'apply_describe_run_drafts');
        if (null === $bodyTokens) {
            self::fail("Could not locate apply_describe_run_drafts() body in {$sourceLabel}");
        }

        $scrape = $this->extractBucketWriteKeys($bodyTokens, $sourceLabel);

        return array_values(array_unique($scrape['keys']));
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
     * Collect string-literal keys of every key-introducing `$buckets` write in
     * the body. Reads are recognised explicitly and skipped. Unrecognised
     * followers and unresolvable key-introducing forms fail closed with
     * file:line [rg-016] [R23-BR-12] [R23-BR-13] [R23-BR-27].
     *
     * @param list<string|array{0:int,1:string,2:int}> $bodyTokens
     * @return array{
     *     keys: list<string>,
     *     resolved_call_sites: int,
     *     failed_closed_call_sites: int
     * }
     */
    private function extractBucketWriteKeys(array $bodyTokens, string $sourceLabel): array
    {
        $keys  = array();
        $count = count($bodyTokens);
        $resolved = 0;
        // failed_closed is always 0 on success — self::fail aborts first.
        $failedClosed = 0;

        for ($i = 0; $i < $count; $i++) {
            $token = $bodyTokens[ $i ];

            // --- array_push( $buckets[…], … ) ---------------------------------
            if (is_array($token) && T_STRING === $token[0] && 'array_push' === $token[1]) {
                $line = $token[2];
                $result = $this->tryExtractArrayPushBucketKey($bodyTokens, $i, $sourceLabel, $line);
                if (null === $result) {
                    continue;
                }
                $keys[] = $result['key'];
                ++$resolved;
                continue;
            }

            if (! is_array($token) || T_VARIABLE !== $token[0] || '$buckets' !== $token[1]) {
                continue;
            }

            $line = $token[2];

            // Reference-alias target: `$r =& $buckets[…]` is not statically
            // analysable — fail closed rather than silently missing the write
            // through the alias (R23-BR-27). Detected by looking *behind*
            // `$buckets` for `=` then `&` (not T_AND_EQUAL, which is `&=`).
            if ($this->isReferenceAliasToBuckets($bodyTokens, $i)) {
                self::fail(
                    $this->unresolvableMessage(
                        $sourceLabel,
                        $line,
                        'reference alias to $buckets is not statically analysable — write the bucket directly'
                    )
                );
            }

            $j = $this->skipInsignificant($bodyTokens, $i + 1);
            if ($j >= $count) {
                continue;
            }

            // --- $buckets += array(…)|[…] ------------------------------------
            if (is_array($bodyTokens[ $j ]) && T_PLUS_EQUAL === $bodyTokens[ $j ][0]) {
                $rhsKeys = $this->extractKeysFromArrayAssignmentRhs(
                    $bodyTokens,
                    $j + 1,
                    $sourceLabel,
                    $line,
                    '+='
                );
                foreach ($rhsKeys as $k) {
                    $keys[] = $k;
                }
                ++$resolved;
                continue;
            }

            // --- $buckets = … (full assignment) ------------------------------
            if ('=' === $bodyTokens[ $j ]) {
                $next = $this->skipInsignificant($bodyTokens, $j + 1);
                if ($next < $count && $this->isArrayFillKeysOfBulkApplyBuckets($bodyTokens, $next)) {
                    // Safe init from the dual-source const — not a loop write.
                    continue;
                }
                if ($next < $count && $this->isLiteralArrayOpen($bodyTokens, $next)) {
                    $rhsKeys = $this->extractKeysFromArrayAssignmentRhs(
                        $bodyTokens,
                        $j + 1,
                        $sourceLabel,
                        $line,
                        '='
                    );
                    foreach ($rhsKeys as $k) {
                        $keys[] = $k;
                    }
                    ++$resolved;
                    continue;
                }
                // Unresolvable full assignment of $buckets (variable, call, …).
                self::fail(
                    $this->unresolvableMessage(
                        $sourceLabel,
                        $line,
                        'full $buckets assignment is not a literal array(…)/[…] or array_fill_keys(BULK_APPLY_BUCKETS)'
                    )
                );
            }

            // Bare `$buckets` (no subscript): recognise reads, fail on unknown.
            if ('[' !== $bodyTokens[ $j ]) {
                if ($this->isBucketReadFollower($bodyTokens[ $j ])) {
                    continue;
                }
                self::fail(
                    $this->unresolvableMessage(
                        $sourceLabel,
                        $line,
                        sprintf(
                            'unrecognised token after bare $buckets: %s',
                            $this->describeToken($bodyTokens[ $j ])
                        )
                    )
                );
            }

            // Skip the whole subscript chain (`['a']`, `['a']['b']`, `['a'][]`, …)
            // before classifying the operator. Empty `[]` is just a zero-token
            // subscript — no special branch (R23-BR-13).
            $firstSubStart = $j + 1;
            $firstSubEnd   = $this->findMatchingBracket($bodyTokens, $j);
            if (null === $firstSubEnd) {
                self::fail(
                    $this->unresolvableMessage(
                        $sourceLabel,
                        $line,
                        'unclosed $buckets[…] subscript'
                    )
                );
            }

            $chainEnd = $firstSubEnd;
            $after    = $this->skipInsignificant($bodyTokens, $firstSubEnd + 1);
            while ($after < $count && '[' === $bodyTokens[ $after ]) {
                $nextClose = $this->findMatchingBracket($bodyTokens, $after);
                if (null === $nextClose) {
                    self::fail(
                        $this->unresolvableMessage(
                            $sourceLabel,
                            $line,
                            'unclosed $buckets[…] subscript chain'
                        )
                    );
                }
                $chainEnd = $nextClose;
                $after    = $this->skipInsignificant($bodyTokens, $nextClose + 1);
            }
            unset($chainEnd);

            // End of body after a complete chain — treat as a non-write.
            if ($after >= $count) {
                continue;
            }

            $follower = $bodyTokens[ $after ];

            // Assignment-family write on a per-key `$buckets[…]` chain.
            if ($this->isAssignmentWriteOperator($follower)) {
                // Fail closed: first subscript must be exactly one string literal.
                // Empty `$buckets[]…` (no key) is unresolvable [R23-BR-12].
                $significant = $this->significantTokens(
                    array_slice($bodyTokens, $firstSubStart, $firstSubEnd - $firstSubStart)
                );

                if (array() === $significant) {
                    self::fail(
                        $this->unresolvableMessage(
                            $sourceLabel,
                            $line,
                            'unkeyed $buckets[] write cannot name a bucket key'
                        )
                    );
                }

                if (
                    1 !== count($significant)
                    || ! is_array($significant[0])
                    || T_CONSTANT_ENCAPSED_STRING !== $significant[0][0]
                ) {
                    $raw = $this->tokensToText(
                        array_slice($bodyTokens, $firstSubStart, $firstSubEnd - $firstSubStart)
                    );
                    self::fail(
                        $this->unresolvableMessage(
                            $sourceLabel,
                            $line,
                            sprintf('non-literal $buckets[%s] write', trim($raw))
                        )
                    );
                }

                $keys[] = $this->decodeStringLiteral($significant[0][1]);
                ++$resolved;
                continue;
            }

            // Recognised read follower (RHS use, isset arg, foreach, …).
            if ($this->isBucketReadFollower($follower)) {
                continue;
            }

            // Neither write nor read — fail closed so the next unknown form
            // reddens instead of disappearing (denylist, not allowlist).
            self::fail(
                $this->unresolvableMessage(
                    $sourceLabel,
                    $line,
                    sprintf(
                        'unrecognised token after $buckets[…] chain: %s',
                        $this->describeToken($follower)
                    )
                )
            );
        }

        return array(
            'keys' => $keys,
            'resolved_call_sites' => $resolved,
            'failed_closed_call_sites' => $failedClosed,
        );
    }

    /**
     * True when `$buckets` at $index is the RHS of a reference binding `=&`.
     * Lexes as `=` then `&` / T_AMPERSAND_* — not T_AND_EQUAL (`&=`).
     *
     * @param list<string|array{0:int,1:string,2:int}> $tokens
     */
    private function isReferenceAliasToBuckets(array $tokens, int $index): bool
    {
        $j = $this->skipInsignificantBackward($tokens, $index - 1);
        if ($j < 0 || ! $this->isAmpersandToken($tokens[ $j ])) {
            return false;
        }

        $j = $this->skipInsignificantBackward($tokens, $j - 1);

        return $j >= 0 && '=' === $tokens[ $j ];
    }

    /**
     * @param string|array{0:int,1:string,2:int} $token
     */
    private function isAmpersandToken(string|array $token): bool
    {
        if ('&' === $token) {
            return true;
        }
        if (! is_array($token)) {
            return false;
        }

        if (defined('T_AMPERSAND_FOLLOWED_BY_VAR_OR_VARARG')
            && T_AMPERSAND_FOLLOWED_BY_VAR_OR_VARARG === $token[0]
        ) {
            return true;
        }

        return defined('T_AMPERSAND_NOT_FOLLOWED_BY_VAR_OR_VARARG')
            && T_AMPERSAND_NOT_FOLLOWED_BY_VAR_OR_VARARG === $token[0];
    }

    /**
     * Assignment-family operators that introduce / mutate a bucket key write.
     *
     * @param string|array{0:int,1:string,2:int} $token
     */
    private function isAssignmentWriteOperator(string|array $token): bool
    {
        if ('=' === $token) {
            return true;
        }
        if (! is_array($token)) {
            return false;
        }

        static $ops = null;
        if (null === $ops) {
            $ops = array(
                T_CONCAT_EQUAL,
                T_PLUS_EQUAL,
                T_MINUS_EQUAL,
                T_MUL_EQUAL,
                T_DIV_EQUAL,
                T_MOD_EQUAL,
                T_POW_EQUAL,
                T_AND_EQUAL,
                T_OR_EQUAL,
                T_XOR_EQUAL,
                T_SL_EQUAL,
                T_SR_EQUAL,
                T_COALESCE_EQUAL,
            );
        }

        return in_array($token[0], $ops, true);
    }

    /**
     * Explicit read followers after a complete `$buckets` / `$buckets[…]` form.
     * Skip only when the follower is recognised as a read — never by default.
     *
     * @param string|array{0:int,1:string,2:int} $token
     */
    private function isBucketReadFollower(string|array $token): bool
    {
        if (! is_array($token)) {
            // RHS / arg / statement terminators and binary operators that read.
            return in_array(
                $token,
                array( ';', ',', ')', ']', '}', ':', '?', '.', '+', '-', '*', '/', '%', '|', '^', '<', '>', '&' ),
                true
            );
        }

        static $readIds = null;
        if (null === $readIds) {
            $readIds = array(
                T_AS,
                T_DOUBLE_ARROW,
                T_COALESCE,
                T_IS_EQUAL,
                T_IS_IDENTICAL,
                T_IS_NOT_EQUAL,
                T_IS_NOT_IDENTICAL,
                T_IS_SMALLER_OR_EQUAL,
                T_IS_GREATER_OR_EQUAL,
                T_SPACESHIP,
                T_BOOLEAN_AND,
                T_BOOLEAN_OR,
                T_LOGICAL_AND,
                T_LOGICAL_OR,
                T_LOGICAL_XOR,
                T_SL,
                T_SR,
                T_POW,
                T_INSTANCEOF,
                T_ELLIPSIS,
            );
        }

        return in_array($token[0], $readIds, true);
    }

    /**
     * @param string|array{0:int,1:string,2:int} $token
     */
    private function describeToken(string|array $token): string
    {
        if (! is_array($token)) {
            return "'" . $token . "'";
        }

        return token_name($token[0]) . '(' . $token[1] . ')';
    }

    /**
     * Walk backward past whitespace/comments; return index of previous significant
     * token, or -1 if none.
     *
     * @param list<string|array{0:int,1:string,2:int}> $tokens
     */
    private function skipInsignificantBackward(array $tokens, int $from): int
    {
        while ($from >= 0) {
            $t = $tokens[ $from ];
            if (is_array($t) && (T_WHITESPACE === $t[0] || T_COMMENT === $t[0] || T_DOC_COMMENT === $t[0])) {
                --$from;
                continue;
            }
            break;
        }

        return $from;
    }

    /**
     * When $i points at `array_push`, resolve `array_push( $buckets['lit'], … )`.
     * Returns null when the call is not a $buckets write (unrelated array_push).
     *
     * @param list<string|array{0:int,1:string,2:int}> $tokens
     * @return array{key: string}|null
     */
    private function tryExtractArrayPushBucketKey(
        array $tokens,
        int $i,
        string $sourceLabel,
        int $line
    ): ?array {
        $count = count($tokens);
        $j = $this->skipInsignificant($tokens, $i + 1);
        if ($j >= $count || '(' !== $tokens[ $j ]) {
            return null;
        }

        $args = $this->splitCallArguments($tokens, $j);
        if (null === $args || array() === $args) {
            self::fail(
                $this->unresolvableMessage(
                    $sourceLabel,
                    $line,
                    'array_push(…) argument list is unclosed or empty'
                )
            );
        }

        $first = $args[0];
        $k = $this->skipInsignificant($first, 0);
        if ($k >= count($first)
            || ! is_array($first[ $k ])
            || T_VARIABLE !== $first[ $k ][0]
            || '$buckets' !== $first[ $k ][1]
        ) {
            // array_push on some other array — not a bucket write.
            return null;
        }

        $k = $this->skipInsignificant($first, $k + 1);
        if ($k >= count($first) || '[' !== $first[ $k ]) {
            self::fail(
                $this->unresolvableMessage(
                    $sourceLabel,
                    $line,
                    'array_push( $buckets, … ) without a string-literal subscript cannot name a bucket key'
                )
            );
        }

        $subStart = $k + 1;
        $subEnd = $this->findMatchingBracket($first, $k);
        if (null === $subEnd) {
            self::fail(
                $this->unresolvableMessage(
                    $sourceLabel,
                    $line,
                    'array_push( $buckets[…] ) has an unclosed subscript'
                )
            );
        }

        $significant = $this->significantTokens(array_slice($first, $subStart, $subEnd - $subStart));
        if (
            1 !== count($significant)
            || ! is_array($significant[0])
            || T_CONSTANT_ENCAPSED_STRING !== $significant[0][0]
        ) {
            $raw = $this->tokensToText(array_slice($first, $subStart, $subEnd - $subStart));
            self::fail(
                $this->unresolvableMessage(
                    $sourceLabel,
                    $line,
                    sprintf('array_push( $buckets[%s], … ) target key is not a string literal', trim($raw))
                )
            );
        }

        return array('key' => $this->decodeStringLiteral($significant[0][1]));
    }

    /**
     * Extract top-level string-literal keys from the array RHS of `$buckets =` /
     * `$buckets +=`. Nested array *values* are skipped; non-literal keys fail closed.
     *
     * @param list<string|array{0:int,1:string,2:int}> $tokens
     * @return list<string>
     */
    private function extractKeysFromArrayAssignmentRhs(
        array $tokens,
        int $from,
        string $sourceLabel,
        int $line,
        string $op
    ): array {
        $count = count($tokens);
        $i = $this->skipInsignificant($tokens, $from);
        if ($i >= $count) {
            self::fail(
                $this->unresolvableMessage(
                    $sourceLabel,
                    $line,
                    "\$buckets {$op} RHS is empty"
                )
            );
        }

        $open = $tokens[ $i ];
        $close = null;
        if (is_array($open) && T_ARRAY === $open[0]) {
            $i = $this->skipInsignificant($tokens, $i + 1);
            if ($i >= $count || '(' !== $tokens[ $i ]) {
                self::fail(
                    $this->unresolvableMessage(
                        $sourceLabel,
                        $line,
                        "\$buckets {$op} array keyword without ("
                    )
                );
            }
            $close = ')';
        } elseif ('[' === $open) {
            $close = ']';
        } else {
            self::fail(
                $this->unresolvableMessage(
                    $sourceLabel,
                    $line,
                    "\$buckets {$op} RHS is not a literal array(…)/[…]"
                )
            );
        }

        $bodyStart = $i + 1;
        $depthParen = 0;
        $depthBracket = 0;
        $depthBrace = 0;
        if (')' === $close) {
            $depthParen = 1;
        } else {
            $depthBracket = 1;
        }

        $bodyEnd = null;
        for ($p = $bodyStart; $p < $count; $p++) {
            $t = $tokens[ $p ];
            if ('(' === $t) {
                ++$depthParen;
            } elseif (')' === $t) {
                --$depthParen;
                if (')' === $close && 0 === $depthParen && 0 === $depthBracket && 0 === $depthBrace) {
                    $bodyEnd = $p;
                    break;
                }
            } elseif ('[' === $t) {
                ++$depthBracket;
            } elseif (']' === $t) {
                --$depthBracket;
                if (']' === $close && 0 === $depthBracket && 0 === $depthParen && 0 === $depthBrace) {
                    $bodyEnd = $p;
                    break;
                }
            } elseif ('{' === $t || (is_array($t) && (T_CURLY_OPEN === $t[0] || T_DOLLAR_OPEN_CURLY_BRACES === $t[0]))) {
                ++$depthBrace;
            } elseif ('}' === $t) {
                --$depthBrace;
            }
        }

        if (null === $bodyEnd) {
            self::fail(
                $this->unresolvableMessage(
                    $sourceLabel,
                    $line,
                    "\$buckets {$op} array RHS is unclosed"
                )
            );
        }

        $keys = array();
        $k = $bodyStart;
        while ($k < $bodyEnd) {
            $k = $this->skipInsignificant($tokens, $k);
            if ($k >= $bodyEnd) {
                break;
            }
            if (',' === $tokens[ $k ]) {
                ++$k;
                continue;
            }

            // Spread — not a resolvable literal key set.
            if (is_array($tokens[ $k ]) && T_ELLIPSIS === $tokens[ $k ][0]) {
                self::fail(
                    $this->unresolvableMessage(
                        $sourceLabel,
                        $line,
                        "\$buckets {$op} array uses ...spread"
                    )
                );
            }

            // Key must be a single string literal followed by =>.
            if (
                ! is_array($tokens[ $k ])
                || T_CONSTANT_ENCAPSED_STRING !== $tokens[ $k ][0]
            ) {
                self::fail(
                    $this->unresolvableMessage(
                        $sourceLabel,
                        $line,
                        "\$buckets {$op} array entry key is not a string literal"
                    )
                );
            }

            $keyToken = $tokens[ $k ][1];
            $k = $this->skipInsignificant($tokens, $k + 1);
            if ($k >= $bodyEnd || ! is_array($tokens[ $k ]) || T_DOUBLE_ARROW !== $tokens[ $k ][0]) {
                self::fail(
                    $this->unresolvableMessage(
                        $sourceLabel,
                        $line,
                        "\$buckets {$op} array entry is missing => after key (list-append values are not bucket keys)"
                    )
                );
            }

            $keys[] = $this->decodeStringLiteral($keyToken);

            // Skip the value (balanced) — nested array literals are fine here.
            $k = $this->skipInsignificant($tokens, $k + 1);
            $k = $this->skipArrayValue($tokens, $k, $bodyEnd);
        }

        return $keys;
    }

    /**
     * True when $from points at `array_fill_keys( AltTextWriteStatus::BULK_APPLY_BUCKETS , … )`.
     *
     * @param list<string|array{0:int,1:string,2:int}> $tokens
     */
    private function isArrayFillKeysOfBulkApplyBuckets(array $tokens, int $from): bool
    {
        $count = count($tokens);
        $t = $tokens[ $from ];
        if (! is_array($t) || T_STRING !== $t[0] || 'array_fill_keys' !== $t[1]) {
            return false;
        }

        $j = $this->skipInsignificant($tokens, $from + 1);
        if ($j >= $count || '(' !== $tokens[ $j ]) {
            return false;
        }

        $args = $this->splitCallArguments($tokens, $j);
        if (null === $args || array() === $args) {
            return false;
        }

        // First arg must be AltTextWriteStatus::BULK_APPLY_BUCKETS (optionally leading \).
        $arg = $args[0];
        $k = $this->skipInsignificant($arg, 0);
        if ($k < count($arg) && is_array($arg[ $k ]) && T_NS_SEPARATOR === $arg[ $k ][0]) {
            $k = $this->skipInsignificant($arg, $k + 1);
        }
        if ($k >= count($arg) || ! is_array($arg[ $k ]) || T_STRING !== $arg[ $k ][0]
            || 'AltTextWriteStatus' !== $arg[ $k ][1]
        ) {
            return false;
        }
        $k = $this->skipInsignificant($arg, $k + 1);
        if ($k >= count($arg) || ! is_array($arg[ $k ]) || T_DOUBLE_COLON !== $arg[ $k ][0]) {
            return false;
        }
        $k = $this->skipInsignificant($arg, $k + 1);
        if ($k >= count($arg) || ! is_array($arg[ $k ]) || T_STRING !== $arg[ $k ][0]
            || 'BULK_APPLY_BUCKETS' !== $arg[ $k ][1]
        ) {
            return false;
        }
        // Nothing else significant in the first arg.
        $k = $this->skipInsignificant($arg, $k + 1);

        return $k >= count($arg);
    }

    /**
     * @param list<string|array{0:int,1:string,2:int}> $tokens
     */
    private function isLiteralArrayOpen(array $tokens, int $from): bool
    {
        $t = $tokens[ $from ];
        if ('[' === $t) {
            return true;
        }

        return is_array($t) && T_ARRAY === $t[0];
    }

    /**
     * Split a call's argument token slices. $openIndex points at '('.
     *
     * @param list<string|array{0:int,1:string,2:int}> $tokens
     * @return list<list<string|array{0:int,1:string,2:int}>>|null
     */
    private function splitCallArguments(array $tokens, int $openIndex): ?array
    {
        $count = count($tokens);
        $depthParen = 0;
        $depthBracket = 0;
        $depthBrace = 0;
        $args = array();
        $current = array();
        $started = false;

        for ($i = $openIndex; $i < $count; $i++) {
            $t = $tokens[ $i ];

            if ('(' === $t) {
                ++$depthParen;
                if (1 === $depthParen) {
                    $started = true;
                    continue;
                }
                $current[] = $t;
                continue;
            }

            if (')' === $t) {
                --$depthParen;
                if (0 === $depthParen) {
                    if ($current !== array() || $args !== array()) {
                        $args[] = $current;
                    }

                    return $args;
                }
                $current[] = $t;
                continue;
            }

            if (! $started) {
                continue;
            }

            if ('[' === $t) {
                ++$depthBracket;
                $current[] = $t;
                continue;
            }
            if (']' === $t) {
                --$depthBracket;
                $current[] = $t;
                continue;
            }
            if ('{' === $t || (is_array($t) && (T_CURLY_OPEN === $t[0] || T_DOLLAR_OPEN_CURLY_BRACES === $t[0]))) {
                ++$depthBrace;
                $current[] = $t;
                continue;
            }
            if ('}' === $t) {
                --$depthBrace;
                $current[] = $t;
                continue;
            }

            if (',' === $t && 1 === $depthParen && 0 === $depthBracket && 0 === $depthBrace) {
                $args[] = $current;
                $current = array();
                continue;
            }

            $current[] = $t;
        }

        return null;
    }

    /**
     * Advance past one array value, stopping at the next top-level comma or body end.
     *
     * @param list<string|array{0:int,1:string,2:int}> $tokens
     */
    private function skipArrayValue(array $tokens, int $from, int $bodyEnd): int
    {
        $depthParen = 0;
        $depthBracket = 0;
        $depthBrace = 0;

        for ($i = $from; $i < $bodyEnd; $i++) {
            $t = $tokens[ $i ];
            if ('(' === $t) {
                ++$depthParen;
                continue;
            }
            if (')' === $t) {
                --$depthParen;
                continue;
            }
            if ('[' === $t) {
                ++$depthBracket;
                continue;
            }
            if (']' === $t) {
                --$depthBracket;
                continue;
            }
            if ('{' === $t || (is_array($t) && (T_CURLY_OPEN === $t[0] || T_DOLLAR_OPEN_CURLY_BRACES === $t[0]))) {
                ++$depthBrace;
                continue;
            }
            if ('}' === $t) {
                --$depthBrace;
                continue;
            }
            if (',' === $t && 0 === $depthParen && 0 === $depthBracket && 0 === $depthBrace) {
                return $i;
            }
        }

        return $bodyEnd;
    }

    /**
     * @param list<string|array{0:int,1:string,2:int}> $tokens
     * @return list<string|array{0:int,1:string,2:int}>
     */
    private function significantTokens(array $tokens): array
    {
        $out = array();
        foreach ($tokens as $st) {
            if (is_array($st) && (T_WHITESPACE === $st[0] || T_COMMENT === $st[0] || T_DOC_COMMENT === $st[0])) {
                continue;
            }
            $out[] = $st;
        }

        return $out;
    }

    private function unresolvableMessage(string $sourceLabel, int $line, string $reason): string
    {
        return sprintf(
            'Dual-source check cannot resolve bucket key write at %s:%d (%s) — '
                . 'bucket routing must use a resolvable string-literal key so the '
                . 'pin can assert set equality with BULK_APPLY_BUCKETS',
            $sourceLabel,
            $line,
            $reason
        );
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
