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

	public function testSchedulerModeUsesTheBookingOutcomeInsteadOfCapabilityProbe(): void
	{
		$liveness = new ReclaimerLiveness(static fn (): int => 1_700_000_000);

		$this->assertSame(
			ReclaimerLiveness::SCHEDULER_WP_CRON,
			$liveness->current_scheduler_mode(ReclaimerLiveness::SCHEDULER_WP_CRON)
		);
		$this->assertSame(ReclaimerLiveness::SCHEDULER_WP_CRON, $liveness->current_scheduler_mode());
		$this->assertSame(
			ReclaimerLiveness::WP_CRON_PERIOD_SECONDS,
			$liveness->effective_period_seconds(
				$liveness->current_scheduler_mode(ReclaimerLiveness::SCHEDULER_WP_CRON)
			)
		);
	}

	public function testPurgeAllOptionsRemovesRegisteredTenantStateAndLeavesUnrelatedOptions(): void
	{
		$liveness = new ReclaimerLiveness(static fn (): int => 1_700_000_000);
		$tenants = array( 'tenant-z', 'tenant/with spaces', 'tenant-a' );

		foreach ( $tenants as $tenant ) {
			$liveness->record_success(
				$tenant,
				1,
				0,
				0,
				false,
				ReclaimerLiveness::SCHEDULER_WP_CRON
			);
			$this->assertIsString( $liveness->claim( $tenant ) );
			$this->setOption( 'acx_reclaimer_lease_' . str_replace( array( '/', ' ' ), '_', $tenant ), 'owner|1|1700000300' );
		}
		$liveness->record_booked_scheduler_mode( ReclaimerLiveness::SCHEDULER_WP_CRON );
		$this->setOption( 'acx_persons', 'must-survive' );
		$this->setOption( 'acx_reclaimer_unrelated_thing', 'must-also-survive' );

		$this->assertSame(
			array( 'tenant-a', 'tenant-z', 'tenant_with_spaces' ),
			get_option( 'acx_reclaimer_tenant_index' )
		);

		$this->assertSame( 2 * count( $tenants ) + 2, $liveness->purge_all_options() );
		foreach ( $tenants as $tenant ) {
			$safe_key = str_replace( array( '/', ' ' ), '_', $tenant );
			$this->assertFalse( get_option( 'acx_reclaimer_liveness_' . $safe_key ) );
			$this->assertFalse( get_option( 'acx_reclaimer_lease_' . $safe_key ) );
		}
		$this->assertFalse( get_option( 'acx_reclaimer_purge_scheduler' ) );
		$this->assertFalse( get_option( 'acx_reclaimer_tenant_index' ) );
		$this->assertSame( 'must-survive', get_option( 'acx_persons' ) );
		$this->assertSame( 'must-also-survive', get_option( 'acx_reclaimer_unrelated_thing' ) );
		$this->assertSame( 0, $liveness->purge_all_options() );
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

	public function testExpiredOwnerCannotOverwriteNewerFencedLivenessState(): void
	{
		global $wpdb;

		// The lightweight test adapter does not expose raw option reads. The
		// implementation must still issue distinct monotonic fallback tokens so
		// the stale-owner CAS is exercised below.
		$wpdb->onGetVarResolve = static function (string $query): ?string {
			return null;
		};
		$now = 1_700_000_000;
		$first = new ReclaimerLiveness(static function () use (&$now): int {
			return $now;
		});
		$second = new ReclaimerLiveness(static function () use (&$now): int {
			return $now;
		});

		$this->assertIsString($first->claim('tenant-fenced'));
		$first->record_success(
			'tenant-fenced',
			1,
			9,
			90,
			false,
			ReclaimerLiveness::SCHEDULER_WP_CRON
		);

		$now += 301;
		$this->assertIsString($second->claim('tenant-fenced'));
		$second->record_success(
			'tenant-fenced',
			2,
			3,
			30,
			false,
			ReclaimerLiveness::SCHEDULER_WP_CRON
		);

		// The first worker resumes after its lease has been replaced. Its stale
		// snapshot must not replace the newer worker's committed liveness.
		$first->record_success(
			'tenant-fenced',
			99,
			0,
			0,
			false,
			ReclaimerLiveness::SCHEDULER_WP_CRON
		);

		$state = $second->read('tenant-fenced');
		$this->assertSame(2, $state['last_purged_count']);
		$this->assertSame(3, $state['backlog_remaining']);
	}
}
