<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\Sync\SyncPullResult;
use AltContext\Tests\TestCase;
use InvalidArgumentException;
use ReflectionClass;

/**
 * @covers \AltContext\Sovereign\Sync\SyncPullResult
 */
class SyncPullResultTest extends TestCase
{
    public function testFactoriesExposeExpectedStatuses(): void
    {
        $this->assertSame('ok', SyncPullResult::ok()->status());
        $this->assertSame('failed', SyncPullResult::failed()->status());
        $this->assertSame('unreachable', SyncPullResult::unreachable()->status());
        $this->assertSame('skipped', SyncPullResult::skipped()->status());
    }

    public function testIsSuccessOnlyReturnsTrueForOk(): void
    {
        $this->assertTrue(SyncPullResult::ok()->is_success());
        $this->assertFalse(SyncPullResult::failed()->is_success());
        $this->assertFalse(SyncPullResult::unreachable()->is_success());
        $this->assertFalse(SyncPullResult::skipped()->is_success());
    }

    public function testAllowedStatusesReturnsAllKnownValues(): void
    {
        $this->assertSame(
            array('ok', 'failed', 'unreachable', 'skipped'),
            SyncPullResult::allowed_statuses()
        );
    }

    public function testInvalidStatusThrows(): void
    {
        $reflection = new ReflectionClass(SyncPullResult::class);
        $constructor = $reflection->getConstructor();
        $instance = $reflection->newInstanceWithoutConstructor();

        $this->expectException(InvalidArgumentException::class);
        $constructor?->invoke($instance, 'bogus');
    }
}
