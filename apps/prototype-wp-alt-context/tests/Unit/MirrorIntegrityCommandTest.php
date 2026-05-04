<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Cli\MirrorIntegrityCommand;
use AltContext\Tests\TestCase;

/**
 * @covers \AltContext\Cli\MirrorIntegrityCommand
 */
class MirrorIntegrityCommandTest extends TestCase
{
	protected function setUp(): void
	{
		parent::setUp();
		\WP_CLI::reset_cli_messages();
	}

	public function testInvokeReportsSuspiciousAttachmentAssignments(): void
	{
		global $wpdb;
		$wpdb->mockResults = [
			[
				'attachment_id' => 6624,
				'distinct_cluster_count' => 6,
				'last_seen_at' => '2026-05-03 21:35:34',
				'cluster_uuids' => 'ab27da72,bf05ce91,d80bb6a0,fdcc7327',
			],
		];

		$command = new MirrorIntegrityCommand();
		$command->__invoke([], []);

		self::assertStringContainsString(
			'SELECT attachment_id, COUNT(DISTINCT cluster_uuid) AS distinct_cluster_count',
			\implode("\n", $wpdb->queries)
		);
		self::assertContains(
			'Suspicious mirror assignments at similarity >= 0.999:',
			\WP_CLI::$messages['log']
		);
		self::assertContains(
			'attachment_id=6624 distinct_clusters=6 last_seen_at=2026-05-03 21:35:34 cluster_uuids=ab27da72,bf05ce91,d80bb6a0,fdcc7327',
			\WP_CLI::$messages['log']
		);
		self::assertContains(
			'Found 1 suspicious attachment(s). Investigate mirror drift before trusting the local projection.',
			\WP_CLI::$messages['warning']
		);
	}

	public function testInvokeReportsCleanMirrorState(): void
	{
		global $wpdb;
		$wpdb->mockResults = [];

		$command = new MirrorIntegrityCommand();
		$command->__invoke( [], array( 'threshold' => '0.999' ) );

		self::assertContains(
			'No suspicious mirror assignments found at similarity >= 0.999.',
			\WP_CLI::$messages['success']
		);
		self::assertSame( array(), \WP_CLI::$messages['warning'] );
	}

	public function testInvokeScopesToSpecificAttachmentId(): void
	{
		global $wpdb;
		$wpdb->mockResults = [
			[
				'attachment_id' => 6624,
				'distinct_cluster_count' => 6,
				'last_seen_at' => '2026-05-03 21:35:34',
				'cluster_uuids' => 'ab27da72,bf05ce91,d80bb6a0,fdcc7327',
			],
		];

		$command = new MirrorIntegrityCommand();
		$command->__invoke( [], array( 'attachment-id' => '6624' ) );

		self::assertStringContainsString(
			'attachment_id = 6624',
			\implode( "\n", $wpdb->queries )
		);
		self::assertContains(
			'Suspicious mirror assignments for attachment 6624 at similarity >= 0.999:',
			\WP_CLI::$messages['log']
		);
	}
}