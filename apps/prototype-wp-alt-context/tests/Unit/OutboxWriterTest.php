<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\Sync\OutboxWriter;
use AltContext\Tests\TestCase;

class OutboxWriterTest extends TestCase
{
	public function testEnqueuePersistsPendingOutboxOperation(): void
	{
		global $wpdb;

		$writer = new OutboxWriter();
		$result = $writer->enqueue(
			'tenant-test-123',
			'person_created',
			'person',
			'person-uuid-1',
			12,
			3,
			array(
				'person_uuid' => 'person-uuid-1',
				'name' => 'Ada',
			)
		);

		$this->assertSame(1, $result);
		$insertQuery = $this->findQueryContaining($wpdb->queries, 'INSERT INTO wp_acx_sync_outbox');
		$this->assertStringContainsString("'person_created'", $insertQuery);
		$this->assertStringContainsString("'pending'", $insertQuery);
		$this->assertStringContainsString("'tenant-test-123'", $insertQuery);
		$this->assertTrue($this->isHookScheduled('acx_sync_drain_curation_outbox'));
	}

	public function testEnqueueFallsBackToWpCronWhenActionSchedulerEnqueueFails(): void
	{
		global $wpdb;

		$GLOBALS['__ac_action_scheduler_enqueue_result'] = 0;

		$writer = new OutboxWriter();
		$result = $writer->enqueue(
			'tenant-test-123',
			'person_created',
			'person',
			'person-uuid-1',
			12,
			3,
			array(
				'person_uuid' => 'person-uuid-1',
				'name' => 'Ada',
			)
		);

		$this->assertSame(1, $result);
		$this->assertFalse(as_next_scheduled_action('acx_sync_drain_curation_outbox', [], 'acx-sync'));
		$this->assertNotFalse(wp_next_scheduled('acx_sync_drain_curation_outbox'));
		$this->assertNotEmpty($wpdb->queries);
	}

	/**
	 * @param array<int,string> $queries
	 */
	private function findQueryContaining(array $queries, string $needle): string
	{
		foreach ($queries as $query) {
			if (str_contains($query, $needle)) {
				return $query;
			}
		}

		$this->fail(sprintf('Unable to find query containing "%s".', $needle));
		return '';
	}

	private function isHookScheduled(string $hook): bool
	{
		foreach (array_keys($GLOBALS['__ac_scheduled']) as $key) {
			if (str_starts_with($key, $hook . '::')) {
				return true;
			}
		}

		foreach (array_keys($GLOBALS['__ac_action_scheduler'] ?? []) as $key) {
			if (str_starts_with($key, $hook . '::')) {
				return true;
			}
		}

		return false;
	}
}
