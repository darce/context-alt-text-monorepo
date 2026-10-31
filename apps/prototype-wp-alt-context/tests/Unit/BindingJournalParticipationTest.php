<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Api\ClusterMutationsController;
use AltContext\Tests\TestCase;
use AltContext\Tests\Support\ClusterMutationsRepositorySpy;
use AltContext\Tests\Support\ClusterMutationsSyncStateSpy;
use AltContext\Tests\Support\ClusterMutationsMembersSpy;
use AltContext\Tests\Support\ClusterMutationsTopologyCommandSpy;
use WP_REST_Request;
use AltContext\Sovereign\Curation\WpBindingIntentParticipant;
use AltContext\Sovereign\Curation\BindingIntentJournal;
use AltContext\Sovereign\Curation\WpBindingJournalStore;

/** Transactional extension of the existing SQL fixture; not an engine test. */
final class ParticipationConnection extends \WPDBStub {
	private ?array $preimage = null;
	public ?string $fail_sql_containing = null;

	public function query( $sql ) {
		if ( null !== $this->fail_sql_containing && str_contains( $sql, $this->fail_sql_containing ) ) {
			$this->queries[] = $sql;
			return false;
		}
		if ( 'START TRANSACTION' === $sql ) {
			$this->preimage = $this->tableRows;
		} elseif ( 'ROLLBACK' === $sql ) {
			$this->tableRows = $this->preimage;
			$this->preimage = null;
		} elseif ( 'COMMIT' === $sql ) {
			$this->preimage = null;
		}
		if ( str_starts_with( $sql, 'INSERT INTO `wp_acx_binding_journal`' ) && preg_match( "/VALUES \\('([^']+)'/", $sql, $match ) ) {
			foreach ( $this->tableRows['wp_acx_binding_journal'] ?? array() as $row ) {
				if ( $row['tenant_id'] === $match[1] ) {
					$this->queries[] = $sql;
					return 1;
				}
			}
		}
		return parent::query( $sql );
	}

	public function get_var( $sql, $x = 0, $y = 0 ) {
		if ( 'SELECT @@in_transaction' === $sql ) {
			return null === $this->preimage ? '0' : '1';
		}
		return parent::get_var( $sql, $x, $y );
	}
}

final class BindingJournalParticipationTest extends TestCase {
	private function seed(): ParticipationConnection {
		$db = new ParticipationConnection();
		$GLOBALS['wpdb'] = $db;
		foreach ( array( 'binding_journal', 'persons', 'clusters', 'identity_members', 'sync_outbox', 'sync_state', 'sync_conflicts' ) as $table ) {
			$db->tableEngines[ 'wp_acx_' . $table ] = 'InnoDB';
			$db->tableRows[ 'wp_acx_' . $table ] = array();
		}
		$db->tableRows['wp_acx_persons'] = array( array( 'id' => 1, 'tenant_id' => 'tenant', 'person_uuid' => 'person', 'name' => 'Saved name', 'normalized_name' => 'saved name', 'local_revision' => 4, 'tags' => '[]' ) );
		$db->tableRows['wp_acx_clusters'] = array(
			array( 'cluster_uuid' => 'group', 'tenant_id' => 'tenant', 'person_id' => 1, 'label' => 'Saved name', 'local_revision' => 2, 'snapshot_version' => 9, 'is_user_confirmed' => 1, 'curation_state' => 'confirmed' ),
			array( 'cluster_uuid' => 'unrelated', 'tenant_id' => 'tenant', 'person_id' => 1, 'label' => 'Saved name', 'local_revision' => 3, 'snapshot_version' => 8, 'is_user_confirmed' => 1, 'curation_state' => 'confirmed' ),
		);
		$db->tableRows['wp_acx_identity_members'] = array( array( 'identity_uuid' => 'face', 'cluster_uuid' => 'group', 'attachment_id' => 17, 'bbox_json' => '[1,2,3,4]', 'projection_version' => 9, 'is_curated' => 1 ) );
		$db->tableRows['wp_acx_sync_state'] = array( array( 'stream_name' => 'tenant:tenant:clusters', 'last_snapshot_version' => 12 ) );
		return $db;
	}

	private function command( WpBindingIntentParticipant $participant, string $kind = 'unlink' ): array {
		$input = $participant->inspect( 'tenant', 'person', 'group' );
		unset( $input['positive_binding_available'] );
		return array_merge( $input, array( 'kind' => $kind, 'person_uuid' => 'person', 'request_id' => 'request' ) );
	}

	public function test_actual_writers_and_receipt_commit_together_and_exact_retry_has_no_effects(): void {
		$db = $this->seed();
		$participant = new WpBindingIntentParticipant( $db );
		$command = $this->command( $participant );
		$receipt = $participant->apply( 'tenant', 'group', $command );
		self::assertNull( $db->tableRows['wp_acx_clusters'][0]['person_id'] );
		self::assertSame( 1, $db->tableRows['wp_acx_clusters'][1]['person_id'] );
		self::assertSame( 'Saved name', $db->tableRows['wp_acx_persons'][0]['name'] );
		self::assertTrue( $receipt['after']['auto_rebind_suppressed'] );
		self::assertSame( 'historical', array_values( $receipt['after']['claims'] )[0]['authority_state'] );
		self::assertSame( 'cluster_person_unbound', $db->tableRows['wp_acx_sync_outbox'][0]['operation_type'] );
		self::assertSame( 9, $db->tableRows['wp_acx_sync_outbox'][0]['expected_base_version'] );
		self::assertSame( 3, $db->tableRows['wp_acx_sync_outbox'][0]['local_revision'] );
		$after = $db->tableRows;
		self::assertSame( $receipt, ( new WpBindingIntentParticipant( $db ) )->apply( 'tenant', 'group', $command ) );
		self::assertSame( $after, $db->tableRows );
		$command['request_id'] = 'competing';
		$this->expectException( \DomainException::class );
		$participant->apply( 'tenant', 'group', $command );
	}

	public function test_outbox_failure_rolls_back_person_group_metrics_and_journal(): void {
		$db = $this->seed();
		$participant = new WpBindingIntentParticipant( $db );
		$command = $this->command( $participant );
		$db->defaultInsertResult = false;
		$before = $db->tableRows;
		try {
			$participant->apply( 'tenant', 'group', $command );
			self::fail( 'Outbox failure must abort.' );
		} catch ( \RuntimeException $error ) {
			self::assertSame( $before, $db->tableRows );
			self::assertContains( 'ROLLBACK', $db->queries );
		}
	}

	public function test_membership_drift_rejects_before_writer_effects(): void {
		$db = $this->seed();
		$participant = new WpBindingIntentParticipant( $db );
		$command = $this->command( $participant );
		$db->tableRows['wp_acx_identity_members'][0]['projection_version'] = 10;
		$before = $db->tableRows;
		try {
			$participant->apply( 'tenant', 'group', $command );
			self::fail( 'Changed member must abort.' );
		} catch ( \DomainException $error ) {
			self::assertSame( $before, $db->tableRows );
		}
	}

	public function test_rename_updates_canonical_person_all_groups_and_preserves_suppression(): void {
		$db = $this->seed();
		// Persisted pre-existing authority, not a fabricated successful participant.
		$db->tableRows['wp_acx_binding_journal'] = array( array( 'tenant_id' => 'tenant', 'state_json' => json_encode( array( 'people' => array( 'person' => array( 'binding_intent_revision' => 3, 'binding_intent_id' => null, 'auto_rebind_suppressed' => true, 'claims' => array() ) ) ) ) ) );
		$participant = new WpBindingIntentParticipant( $db );
		$command = $this->command( $participant, 'rename' );
		$command['name'] = 'New name';
		$receipt = $participant->apply( 'tenant', 'group', $command );
		self::assertTrue( $receipt['after']['auto_rebind_suppressed'] );
		self::assertSame( 'New name', $db->tableRows['wp_acx_persons'][0]['name'] );
		self::assertSame( array( 'New name', 'New name' ), array_column( $db->tableRows['wp_acx_clusters'], 'label' ) );
		self::assertCount( 3, $db->tableRows['wp_acx_sync_outbox'] );
		self::assertSame( 12, $db->tableRows['wp_acx_sync_outbox'][2]['expected_base_version'] );
	}

	public function test_guard_producer_and_unlink_are_reachable_through_actual_controller(): void {
		$db = $this->seed();
		$controller = new class( new ClusterMutationsRepositorySpy(), new ClusterMutationsSyncStateSpy(), new ClusterMutationsMembersSpy(), null, new ClusterMutationsTopologyCommandSpy() ) extends ClusterMutationsController {
			public function get_tenant_id(): string { return 'tenant'; }
		};
		$request = new WP_REST_Request( 'PATCH', '/acx/v1/recognition/clusters/group' );
		$request->set_param( 'cluster_id', 'group' );
		$request->set_param( 'binding_intent', array( 'kind' => 'inspect', 'person_uuid' => 'person' ) );
		$inspection = $controller->update_cluster_label( $request );
		self::assertInstanceOf( \WP_REST_Response::class, $inspection );
		$command = $inspection->get_data()['binding_intent'];
		unset( $command['positive_binding_available'] );
		$command += array( 'kind' => 'unlink', 'person_uuid' => 'person', 'request_id' => 'endpoint-request' );
		$request->set_param( 'binding_intent', $command );
		$result = $controller->update_cluster_label( $request );
		self::assertInstanceOf( \WP_REST_Response::class, $result );
		self::assertNull( $db->tableRows['wp_acx_clusters'][0]['person_id'] );
		self::assertTrue( $result->get_data()['binding_intent']['after']['auto_rebind_suppressed'] );
	}

	public function test_journal_and_commit_failures_rollback_writer_and_outbox_effects(): void {
		foreach ( array( 'UPDATE `wp_acx_binding_journal`', 'COMMIT', 'SET local_revision = local_revision + 1, updated_at' ) as $failure ) {
			$db = $this->seed();
			$participant = new WpBindingIntentParticipant( $db );
			$command = $this->command( $participant );
			$before = $db->tableRows;
			$db->fail_sql_containing = $failure;
			try {
				$participant->apply( 'tenant', 'group', $command );
				self::fail( 'Failure must abort: ' . $failure );
			} catch ( \RuntimeException $error ) {
				self::assertSame( $before, $db->tableRows, $failure );
				self::assertContains( 'ROLLBACK', $db->queries );
			}
		}
	}

	public function test_foreign_tenant_cannot_read_or_mutate_local_person(): void {
		$db = $this->seed();
		$participant = new WpBindingIntentParticipant( $db );
		$command = $this->command( $participant );
		$before = $db->tableRows;
		try {
			$participant->apply( 'foreign', 'group', $command );
			self::fail( 'Foreign tenant must abort.' );
		} catch ( \DomainException $error ) {
			self::assertSame( $before, $db->tableRows );
		}
	}

	public function test_unsettled_predecessor_holds_instead_of_inventing_delivery_order(): void {
		$db = $this->seed();
		$db->tableRows['wp_acx_sync_outbox'][] = array( 'id' => 42, 'tenant_id' => 'tenant', 'entity_type' => 'cluster', 'entity_key' => 'group', 'status' => 'pending', 'attempts' => 0 );
		$participant = new WpBindingIntentParticipant( $db );
		$command = $this->command( $participant );
		$before = $db->tableRows;
		try {
			$participant->apply( 'tenant', 'group', $command );
			self::fail( 'Unknown dispatch history cannot be cancelled.' );
		} catch ( \DomainException $error ) {
			self::assertSame( $before, $db->tableRows );
		}
	}
	public function test_production_label_route_holds_positive_without_inventing_source_authority(): void {
		$controller = new ClusterMutationsController( new ClusterMutationsRepositorySpy(), new ClusterMutationsSyncStateSpy(), new ClusterMutationsMembersSpy(), null, new ClusterMutationsTopologyCommandSpy() );
		$request = new WP_REST_Request( 'PATCH', '/acx/v1/recognition/clusters/cluster-xyz' );
		$request->set_param( 'cluster_id', 'cluster-xyz' );
		$request->set_param( 'binding_intent', array( 'kind' => 'positive', 'explicit_positive' => true, 'review_source_ref' => 'not-proof' ) );
		$result = $controller->update_cluster_label( $request );
		self::assertInstanceOf( \WP_Error::class, $result );
		self::assertSame( 'binding_review_unavailable', $result->get_error_code() );
	}

	public function test_malformed_command_does_not_fall_through_to_legacy_label_write(): void {
		$repository = new ClusterMutationsRepositorySpy();
		$controller = new ClusterMutationsController( $repository, new ClusterMutationsSyncStateSpy(), new ClusterMutationsMembersSpy(), null, new ClusterMutationsTopologyCommandSpy() );
		$request = new WP_REST_Request( 'PATCH', '/acx/v1/recognition/clusters/cluster-xyz' );
		$request->set_param( 'cluster_id', 'cluster-xyz' );
		$request->set_param( 'label', 'Must not write' );
		$request->set_param( 'binding_intent', false );
		$result = $controller->update_cluster_label( $request );
		self::assertInstanceOf( \WP_Error::class, $result );
		self::assertSame( 'invalid_binding_intent', $result->get_error_code() );
		self::assertSame( '', $repository->updatedLabelClusterId );
	}
}
