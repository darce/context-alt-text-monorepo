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
 * Non-literal `$buckets[…]` writes (variable subscripts, concatenated keys) are
 * invisible to a literal-only scrape; the pin fails closed on those rather than
 * reporting green when it cannot see the subject [rg-016].
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

        // Prefer the apply method body so an unrelated `$buckets[…]` elsewhere
        // cannot dilute the pin. Method-name + brace match is robust to
        // formatting inside the body; fall back to whole-file if the method
        // cannot be located (fail closed only on missing writes, not on scope).
        $applySource = $this->extractMethodBody($source, 'apply_describe_run_drafts');
        self::assertNotNull(
            $applySource,
            'Could not locate apply_describe_run_drafts() body in class-describe-controller.php'
        );

        // Collect every `$buckets[…]` write (assignment forms, including `[]=`).
        // Reads such as `$body[$k] = $buckets[$k]` are not matched.
        $writeMatched = preg_match_all(
            '/\$buckets\s*\[\s*([^\]]+?)\s*\]\s*(?:\[\s*\])?\s*=/',
            $applySource,
            $writeMatches
        );
        self::assertIsInt($writeMatched);
        self::assertGreaterThan(
            0,
            $writeMatched,
            'Expected at least one $buckets[…] write in apply_describe_run_drafts()'
        );

        $loopKeys = array();
        foreach ($writeMatches[1] as $subscript) {
            $subscript = trim($subscript);
            // Fail closed: dual-source check can only verify single-quoted or
            // double-quoted string-literal subscripts. Variable / expression
            // keys are invisible to the scrape and must not report green.
            if (1 !== preg_match('/^[\'"]([^\'"]+)[\'"]$/', $subscript, $keyMatch)) {
                self::fail(
                    sprintf(
                        'Dual-source check cannot verify non-literal $buckets[%s] write — '
                            . 'bucket routing must use a single string-literal key so the '
                            . 'pin can assert set equality with BULK_APPLY_BUCKETS',
                        $subscript
                    )
                );
            }
            $loopKeys[] = $keyMatch[1];
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
     * Extract a method body by name via brace matching. Returns null when the
     * method is missing (caller fails closed). Not a formatting-fragile line
     * anchor: only the method name is fixed.
     */
    private function extractMethodBody(string $source, string $methodName): ?string
    {
        if (1 !== preg_match(
            '/function\s+' . preg_quote($methodName, '/') . '\s*\(/',
            $source,
            $match,
            PREG_OFFSET_CAPTURE
        )) {
            return null;
        }

        $from = (int) $match[0][1];
        $bracePos = strpos($source, '{', $from);
        if (false === $bracePos) {
            return null;
        }

        $depth = 0;
        $len   = strlen($source);
        for ($i = $bracePos; $i < $len; $i++) {
            $ch = $source[$i];
            if ('{' === $ch) {
                ++$depth;
            } elseif ('}' === $ch) {
                --$depth;
                if (0 === $depth) {
                    return substr($source, $bracePos, $i - $bracePos + 1);
                }
            }
        }

        return null;
    }
}
