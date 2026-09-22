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

	public function testFirstWriteRaceReportsRejectionAndPreservesWinner(): void
	{
		global $wpdb;

		$tenant = 'tenant-first-write-race';
		$stateOption = 'acx_reclaimer_liveness_' . $tenant;
		$lease = 'owner-a|1|1700000300';
		$winnerLease = 'owner-b|2|1700000300';
		$winnerState = array(
			'last_success_at' => '2023-11-14T22:13:20Z',
			'last_purged_count' => 7,
		);
		$leaseReads = 0;
		$wpdb->onGetVarResolve = static function (string $query) use (&$leaseReads, $lease, $winnerLease): ?string {
			++$leaseReads;
			return 1 === $leaseReads ? $lease : $winnerLease;
		};

		$stateReads = 0;
		$GLOBALS['__ac_get_option_before_read'][ $stateOption ] = static function () use (&$stateReads, $stateOption, $winnerState, $winnerLease): void {
			++$stateReads;
			if ( 1 === $stateReads ) {
				// Let the first read observe a missing value while the conditional
				// insert is about to lose the race.
				$GLOBALS['__ac_options'][ $stateOption ] = null;
				return;
			}

			$GLOBALS['__ac_options'][ $stateOption ] = $winnerState;
			$GLOBALS['__ac_options']['acx_reclaimer_lease_' . str_replace( '/', '_', 'tenant-first-write-race' )] = $winnerLease;
		};

		$result = $this->invokeFencedWrite(
			new ReclaimerLiveness(static fn (): int => 1_700_000_000),
			$tenant,
			array(
				'last_success_at' => '2023-11-14T22:30:00Z',
				'last_purged_count' => 99,
			),
			$lease
		);

		$this->assertIsArray($result);
		$this->assertFalse($result['committed']);
		$this->assertSame('fence_rejected', $result['status']);
		$this->assertSame($winnerState, get_option($stateOption));
	}

	public function testCleanFirstWriteReportsFencedSuccessAndStoresState(): void
	{
		global $wpdb;

		$tenant = 'tenant-first-write-clean';
		$lease = 'owner-a|1|1700000300';
		$wpdb->onGetVarResolve = static fn (string $query): string => $lease;
		$state = array(
			'last_success_at' => '2023-11-14T22:30:00Z',
			'last_purged_count' => 4,
		);

		$result = $this->invokeFencedWrite(
			new ReclaimerLiveness(static fn (): int => 1_700_000_000),
			$tenant,
			$state,
			$lease
		);

		$this->assertIsArray($result);
		$this->assertTrue($result['committed']);
		$this->assertSame('committed', $result['status']);
		$this->assertSame($state, get_option('acx_reclaimer_liveness_' . $tenant));
		$this->assertFalse($GLOBALS['__ac_option_autoload']['acx_reclaimer_liveness_' . $tenant]);
	}

	public function testStaleLeaseReportsRejectionWithoutWriting(): void
	{
		global $wpdb;

		$tenant = 'tenant-stale-write';
		$lease = 'owner-a|1|1700000300';
		$wpdb->onGetVarResolve = static fn (string $query): string => 'owner-b|2|1700000300';

		$result = $this->invokeFencedWrite(
			new ReclaimerLiveness(static fn (): int => 1_700_000_000),
			$tenant,
			array('last_purged_count' => 1),
			$lease
		);

		$this->assertIsArray($result);
		$this->assertFalse($result['committed']);
		$this->assertSame('fence_rejected', $result['status']);
		$this->assertArrayNotHasKey('acx_reclaimer_liveness_' . $tenant, $GLOBALS['__ac_options']);
		$this->assertArrayNotHasKey('acx_reclaimer_tenant_index', $GLOBALS['__ac_options']);
	}

	public function testUnreadableLeaseReportsPermissiveWriteDistinctly(): void
	{
		global $wpdb;

		$tenant = 'tenant-no-fence';
		$state = array(
			'last_success_at' => '2023-11-14T22:30:00Z',
			'last_purged_count' => 5,
		);
		$wpdb->onGetVarResolve = static fn (string $query): ?string => null;

		$result = $this->invokeFencedWrite(
			new ReclaimerLiveness(static fn (): int => 1_700_000_000),
			$tenant,
			$state,
			'owner-a|1|1700000300'
		);

		$this->assertIsArray($result);
		$this->assertTrue($result['committed']);
		$this->assertSame('committed_without_fence', $result['status']);
		$this->assertSame($state, get_option('acx_reclaimer_liveness_' . $tenant));
	}

	public function testRejectedFencedWriteDispatchesSovereignWarning(): void
	{
		global $wpdb;

		$tenant = 'tenant-rejection-warning';
		$wpdb->onGetVarResolve = static fn (string $query): ?string => null;
		$liveness = new ReclaimerLiveness(static fn (): int => 1_700_000_000);
		$this->assertIsString($liveness->claim($tenant));

		$wpdb->onGetVarResolve = static fn (string $query): string => 'owner-b|2|1700000300';
		$liveness->record_success($tenant, 1, 0, 0, false, ReclaimerLiveness::SCHEDULER_WP_CRON);

		$warnings = $this->sovereignWarnings();
		$this->assertCount(1, $warnings);
		$this->assertSame('reclaimer_liveness_write_fence_rejected', $warnings[0]['args'][0]);
		$this->assertSame($tenant, $warnings[0]['args'][1]['tenant_id']);
	}

	public function testRecordAttemptThenSuccessUnderLeasePersistsThroughObjectCache(): void
	{
		$liveness = new ReclaimerLiveness(static fn (): int => 1_700_000_000);
		$tenant = 'tenant-cache-coherent';
		$liveness->record_success(
			$tenant,
			1,
			8,
			40,
			false,
			ReclaimerLiveness::SCHEDULER_WP_CRON
		);

		$this->assertIsString($liveness->claim($tenant));
		$liveness->record_attempt($tenant, ReclaimerLiveness::SCHEDULER_WP_CRON);
		$liveness->record_success(
			$tenant,
			4,
			2,
			15,
			true,
			ReclaimerLiveness::SCHEDULER_WP_CRON
		);

		$state = $liveness->read($tenant);
		$this->assertSame(ReclaimerLiveness::OUTCOME_SUCCESS, $state['last_outcome']);
		$this->assertSame(4, $state['last_purged_count']);
		$this->assertSame(2, $state['backlog_remaining']);
		$this->assertSame(15, $state['backlog_oldest_age_seconds']);
		$this->assertTrue($state['batch_cap_reached']);
		$this->assertSame('2023-11-14T22:13:20Z', $state['last_success_at']);
		$this->assertSame(array(), $this->sovereignWarningCodes());
	}

	public function testStaleAlloptionsAndNotoptionsDoNotHideLaterFencedSuccess(): void
	{
		$liveness = new ReclaimerLiveness(static fn (): int => 1_700_000_000);
		$tenant = 'tenant-stale-option-caches';
		$option = 'acx_reclaimer_liveness_' . $tenant;
		$liveness->record_success(
			$tenant,
			1,
			9,
			90,
			false,
			ReclaimerLiveness::SCHEDULER_WP_CRON
		);
		$prior = get_option($option);
		$this->assertIsArray($prior);

		$this->assertIsString($liveness->claim($tenant));
		wp_cache_set($option, $prior, 'options');
		wp_cache_set('alloptions', array( $option => $prior ), 'options');
		wp_cache_set('notoptions', array( 'unrelated-missing-option' => true ), 'options');

		$liveness->record_attempt($tenant, ReclaimerLiveness::SCHEDULER_WP_CRON);
		$liveness->record_success(
			$tenant,
			6,
			1,
			3,
			false,
			ReclaimerLiveness::SCHEDULER_WP_CRON
		);

		$state = $liveness->read($tenant);
		$this->assertSame(ReclaimerLiveness::OUTCOME_SUCCESS, $state['last_outcome']);
		$this->assertSame(6, $state['last_purged_count']);
		$this->assertSame(1, $state['backlog_remaining']);
		$stored = get_option($option);
		$this->assertIsArray($stored);
		$this->assertSame(6, $stored['last_purged_count']);
		$notoptions = wp_cache_get('notoptions', 'options');
		$this->assertFalse(is_array($notoptions) && isset($notoptions[$option]));
		$alloptions = wp_cache_get('alloptions', 'options');
		$this->assertFalse(is_array($alloptions) && array_key_exists($option, $alloptions));
	}

	public function testFencedWritesKeepSeparateTenantsIsolatedWithStaleCache(): void
	{
		$liveness = new ReclaimerLiveness(static fn (): int => 1_700_000_000);
		$this->assertIsString($liveness->claim('tenant-cache-a'));
		$this->assertIsString($liveness->claim('tenant-cache-b'));

		$liveness->record_attempt('tenant-cache-a', ReclaimerLiveness::SCHEDULER_WP_CRON);
		$liveness->record_success(
			'tenant-cache-a',
			4,
			1,
			10,
			false,
			ReclaimerLiveness::SCHEDULER_WP_CRON
		);
		wp_cache_set(
			'acx_reclaimer_liveness_tenant-cache-a',
			array( 'last_purged_count' => 99, 'last_outcome' => ReclaimerLiveness::OUTCOME_FAILED ),
			'options'
		);
		$liveness->record_attempt('tenant-cache-b', ReclaimerLiveness::SCHEDULER_WP_CRON);
		$liveness->record_success(
			'tenant-cache-b',
			7,
			3,
			20,
			true,
			ReclaimerLiveness::SCHEDULER_WP_CRON
		);
		wp_cache_delete('acx_reclaimer_liveness_tenant-cache-a', 'options');

		$stateA = $liveness->read('tenant-cache-a');
		$stateB = $liveness->read('tenant-cache-b');
		$this->assertSame(ReclaimerLiveness::OUTCOME_SUCCESS, $stateA['last_outcome']);
		$this->assertSame(4, $stateA['last_purged_count']);
		$this->assertSame(ReclaimerLiveness::OUTCOME_SUCCESS, $stateB['last_outcome']);
		$this->assertSame(7, $stateB['last_purged_count']);
		$this->assertTrue($stateB['batch_cap_reached']);
		$this->assertFalse($stateA['batch_cap_reached']);
	}

	public function testRejectedFencingLeavesOtherTenantStateIntact(): void
	{
		global $wpdb;

		$liveness = new ReclaimerLiveness(static fn (): int => 1_700_000_000);
		$this->assertIsString($liveness->claim('tenant-kept'));
		$liveness->record_success(
			'tenant-kept',
			5,
			0,
			0,
			false,
			ReclaimerLiveness::SCHEDULER_WP_CRON
		);

		$rejected = 'tenant-rejected-neighbor';
		$wpdb->onGetVarResolve = static fn (string $query): ?string => null;
		$this->assertIsString($liveness->claim($rejected));
		$wpdb->onGetVarResolve = static fn (string $query): string => 'owner-b|2|1700000300';
		$liveness->record_success($rejected, 99, 0, 0, false, ReclaimerLiveness::SCHEDULER_WP_CRON);

		$kept = $liveness->read('tenant-kept');
		$this->assertSame(ReclaimerLiveness::OUTCOME_SUCCESS, $kept['last_outcome']);
		$this->assertSame(5, $kept['last_purged_count']);
		$this->assertFalse(get_option('acx_reclaimer_liveness_' . $rejected));
		$codes = $this->sovereignWarningCodes();
		$this->assertSame(array( 'reclaimer_liveness_write_fence_rejected' ), $codes);
	}

	public function testRepeatedIdenticalSuccessDoesNotWarn(): void
	{
		$liveness = new ReclaimerLiveness(static fn (): int => 1_700_000_000);
		$tenant = 'tenant-identical-success';
		$this->assertIsString($liveness->claim($tenant));
		$liveness->record_success(
			$tenant,
			3,
			1,
			8,
			false,
			ReclaimerLiveness::SCHEDULER_WP_CRON
		);
		$liveness->record_success(
			$tenant,
			3,
			1,
			8,
			false,
			ReclaimerLiveness::SCHEDULER_WP_CRON
		);

		$state = $liveness->read($tenant);
		$this->assertSame(ReclaimerLiveness::OUTCOME_SUCCESS, $state['last_outcome']);
		$this->assertSame(3, $state['last_purged_count']);
		$this->assertSame(array(), $this->sovereignWarningCodes());
	}

	public function testUnexpectedNoOpDispatchesSovereignWarning(): void
	{
		$liveness = new ReclaimerLiveness(static fn (): int => 1_700_000_000);
		$tenant = 'tenant-unexpected-noop';
		$option = 'acx_reclaimer_liveness_' . $tenant;
		$this->assertIsString($liveness->claim($tenant));
		$liveness->record_success(
			$tenant,
			1,
			0,
			0,
			false,
			ReclaimerLiveness::SCHEDULER_WP_CRON
		);

		$GLOBALS['__ac_option_before_update'][ $option ] = static function () use ( $option ): void {
			$GLOBALS['__ac_options'][ $option ] = array(
				'last_outcome' => ReclaimerLiveness::OUTCOME_FAILED,
				'last_purged_count' => 123,
			);
		};
		$liveness->record_success(
			$tenant,
			4,
			2,
			15,
			false,
			ReclaimerLiveness::SCHEDULER_WP_CRON
		);

		$codes = $this->sovereignWarningCodes();
		$this->assertContains('reclaimer_liveness_write_no_op', $codes);
	}

	/** @return list<array{hook:string,args:array<int,mixed>}> */
	private function sovereignWarnings(): array
	{
		return array_values(
			array_filter(
				$GLOBALS['__ac_do_action_log'],
				static fn (array $action): bool => 'acx_sovereign_warning' === $action['hook']
			)
		);
	}

	/** @return list<string> */
	private function sovereignWarningCodes(): array
	{
		$codes = array();
		foreach ( $this->sovereignWarnings() as $warning ) {
			if ( isset( $warning['args'][0] ) && is_string( $warning['args'][0] ) ) {
				$codes[] = $warning['args'][0];
			}
		}

		return $codes;
	}

	/** @return mixed */
	private function invokeFencedWrite(
		ReclaimerLiveness $liveness,
		string $tenant,
		array $state,
		string $lease
	) {
		$method = new \ReflectionMethod(ReclaimerLiveness::class, 'write_fenced_state');
		return $method->invoke($liveness, $tenant, $state, $lease);
	}
}
