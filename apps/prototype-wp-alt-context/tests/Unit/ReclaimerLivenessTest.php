<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\Sync\ReclaimerLiveness;
use AltContext\Tests\TestCase;

class ReclaimerLivenessTest extends TestCase
{
	public function testReadWithoutHistoryReturnsNeverRunContractShape(): void
	{
		$liveness = new ReclaimerLiveness(static fn (): int => 1_700_000_000);

		$state = $liveness->read('tenant-never-run');

		$this->assertSame(
			array(
				'state',
				'scheduler_mode',
				'effective_period_seconds',
				'last_attempt_at',
				'last_success_at',
				'last_outcome',
				'last_purged_count',
				'backlog_remaining',
				'backlog_oldest_age_seconds',
				'batch_cap_reached',
			),
			array_keys($state)
		);
		$this->assertSame('never_run', $state['state']);
		$this->assertNull($state['last_attempt_at']);
		$this->assertNull($state['last_success_at']);
		$this->assertNull($state['last_outcome']);
		$this->assertNull($state['last_purged_count']);
		$this->assertNull($state['backlog_remaining']);
		$this->assertNull($state['backlog_oldest_age_seconds']);
		$this->assertFalse($state['batch_cap_reached']);
	}

	public function testSuccessAgesFromHealthyToOverdueToBreachForBothSchedulerModes(): void
	{
		foreach (
			array(
				ReclaimerLiveness::SCHEDULER_ACTION_SCHEDULER => ReclaimerLiveness::ACTION_SCHEDULER_PERIOD_SECONDS,
				ReclaimerLiveness::SCHEDULER_WP_CRON => ReclaimerLiveness::WP_CRON_PERIOD_SECONDS,
			) as $mode => $period
		) {
			$now = 1_700_000_000;
			$liveness = new ReclaimerLiveness(static function () use (&$now): int {
				return $now;
			});
			$tenant = 'tenant-' . $mode;
			$liveness->record_success($tenant, 1, 0, 0, false, $mode);

			$this->assertSame(ReclaimerLiveness::STATE_HEALTHY, $liveness->read($tenant)['state']);
			$now += $period;
			$this->assertSame(ReclaimerLiveness::STATE_HEALTHY, $liveness->read($tenant)['state']);
			++$now;
			$this->assertSame(ReclaimerLiveness::STATE_OVERDUE, $liveness->read($tenant)['state']);
			$now += $period - 1;
			$this->assertSame(ReclaimerLiveness::STATE_OVERDUE, $liveness->read($tenant)['state']);
			++$now;
			$this->assertSame(ReclaimerLiveness::STATE_BREACH, $liveness->read($tenant)['state']);
		}
	}

	public function testTenantHistoryIsNonAutoloadedAndIsolated(): void
	{
		$liveness = new ReclaimerLiveness(static fn (): int => 1_700_000_000);
		$liveness->record_success(
			'tenant-a',
			4,
			2,
			90,
			true,
			ReclaimerLiveness::SCHEDULER_WP_CRON
		);

		$this->assertSame(ReclaimerLiveness::STATE_HEALTHY, $liveness->read('tenant-a')['state']);
		$this->assertSame(ReclaimerLiveness::STATE_NEVER_RUN, $liveness->read('tenant-b')['state']);
		$this->assertSame(86400, $liveness->read('tenant-a')['effective_period_seconds']);
		$this->assertFalse(
			$GLOBALS['__ac_option_autoload']['acx_reclaimer_liveness_tenant-a'] ?? true,
			'Reclaimer history must never be autoloaded.'
		);
	}

	public function testClaimUsesOneConditionalOptionsSqlAndReleaseIsOwnerChecked(): void
	{
		global $wpdb;

		$liveness = new ReclaimerLiveness(static fn (): int => 1_700_000_000);
		$owner = $liveness->claim('tenant-lease');

		$this->assertIsString($owner);
		$this->assertStringContainsString('INSERT INTO `wp_options`', $wpdb->queries[0]);
		$this->assertStringContainsString('ON DUPLICATE KEY UPDATE', $wpdb->queries[0]);
		$this->assertTrue($liveness->release('tenant-lease', $owner));
		$this->assertFalse($liveness->release('tenant-lease', $owner));
	}
}
