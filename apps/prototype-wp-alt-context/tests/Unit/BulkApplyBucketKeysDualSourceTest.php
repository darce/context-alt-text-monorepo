<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\AltTextWriteStatus;
use AltContext\Tests\TestCase;

/**
 * R21-BR-13: BULK_APPLY_BUCKETS is dual-sourced.
 *
 * `array_fill_keys` / the response envelope iterate the const, while the apply
 * loop in DescribeController writes `$buckets['…']` as magic string literals.
 * Renaming a const member without updating every literal silently orphans media
 * ids from the wire envelope (response key becomes the new name; the loop still
 * fills the old one).
 *
 * This pin derives the loop-written keys from the controller source (regex) so
 * the test is not a third hard-coded list. Every extracted key must be a member
 * of BULK_APPLY_BUCKETS.
 *
 * Routing the loop through the const members is a production fix owned by the
 * controller lane; this test only closes the detection gap.
 *
 * @covers \AltContext\Api\AltTextWriteStatus
 */
class BulkApplyBucketKeysDualSourceTest extends TestCase
{
    /**
     * Every `$buckets['…']` key written by the bulk-apply loop must be a
     * BULK_APPLY_BUCKETS member. A rename of a const member without updating
     * the literal turns this RED.
     */
    public function testApplyLoopBucketKeysAreMembersOfBulkApplyBuckets(): void
    {
        $controllerPath = realpath(__DIR__ . '/../../src/api/class-describe-controller.php');
        self::assertIsString($controllerPath, 'class-describe-controller.php must exist');

        $source = (string) file_get_contents($controllerPath);

        // Derive keys the apply loop writes — not a hard-coded third list.
        // Matches $buckets['key'] and $buckets["key"] assignment/index forms.
        $matched = preg_match_all(
            '/\$buckets\s*\[\s*[\'"]([^\'"]+)[\'"]\s*\]/',
            $source,
            $matches
        );
        self::assertIsInt($matched);
        self::assertGreaterThan(
            0,
            $matched,
            'Expected at least one $buckets[\'…\'] write in class-describe-controller.php'
        );

        $loopKeys = array_values(array_unique($matches[1]));
        self::assertNotEmpty($loopKeys, 'Derived apply-loop bucket keys must be non-empty');

        foreach ($loopKeys as $key) {
            $this->assertContains(
                $key,
                AltTextWriteStatus::BULK_APPLY_BUCKETS,
                sprintf(
                    "Apply-loop bucket key %s is not a BULK_APPLY_BUCKETS member — "
                        . 'renaming a const member without updating the loop literal orphans media ids',
                    var_export($key, true)
                )
            );
        }
    }
}
