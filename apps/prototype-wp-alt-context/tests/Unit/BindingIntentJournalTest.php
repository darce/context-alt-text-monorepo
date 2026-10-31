<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\Curation\BindingIntentJournal;
use AltContext\Sovereign\Curation\FaceCorrespondenceResolver;
use AltContext\Sovereign\Curation\WpBindingJournalStore;
use PHPUnit\Framework\TestCase;

/** Transactional connection double: exercises the production SQL adapter, no live DB. */
final class BindingJournalConnection {
	public array $rows = array();
	public array $effects = array();
	public array $queries = array();
	public ?string $fail = null;
	private ?array $before = null;
	private array $prepared = array();

	public function prepare( string $sql, ...$arguments ): string {
		$key = 'prepared-' . count( $this->prepared );
		$this->prepared[ $key ] = array( $sql, $arguments );
		return $key;
	}
	public function get_var( string $key ) {
		if ( 'SELECT @@in_transaction' === $key ) {
			return null === $this->before ? '0' : '1';
		}
		list( $sql, $args ) = $this->prepared[ $key ];
		if ( ! str_contains( $sql, 'FOR UPDATE' ) || null === $this->before ) {
			throw new \LogicException( 'Missing transaction lock.' );
		}
		$this->queries[] = $sql;
		return $this->rows[ $args[1] ] ?? null;
	}
	public function query( string $key ) {
		list( $sql, $args ) = $this->prepared[ $key ] ?? array( $key, array() );
		$this->queries[] = $sql;
		if ( $this->fail === $sql || ( 'UPDATE' === $this->fail && str_starts_with( $sql, 'UPDATE' ) ) ) {
			return false;
		}
		if ( 'START TRANSACTION' === $sql ) {
			$this->before = array( $this->rows, $this->effects );
		} elseif ( 'COMMIT' === $sql ) {
			$this->before = null;
		} elseif ( 'ROLLBACK' === $sql ) {
			list( $this->rows, $this->effects ) = $this->before;
			$this->before = null;
		} elseif ( str_starts_with( $sql, 'INSERT' ) ) {
			$this->rows[ $args[1] ] ??= $args[2];
		} elseif ( str_starts_with( $sql, 'UPDATE' ) ) {
			$this->rows[ $args[2] ] = $args[1];
		} else {
			throw new \LogicException( 'Unexpected SQL.' );
		}
		return 1;
	}
}

final class BindingIntentJournalTest extends TestCase {
	private BindingJournalConnection $db;
	private BindingIntentJournal $journal;

	protected function setUp(): void {
		$this->db = new BindingJournalConnection();
		$this->journal = $this->new_journal();
	}
	private function new_journal(): BindingIntentJournal {
		return new BindingIntentJournal( new WpBindingJournalStore( $this->db, 'wp_acx_binding_journal' ) );
	}
	private function command( string $request = 'request', string $kind = 'positive', int $revision = 0 ): array {
		$command = array( 'request_id' => $request, 'person_uuid' => 'person', 'kind' => $kind, 'expected_revision' => $revision, 'guards' => array( 'person_revision' => 5, 'snapshot_version' => 7 ) );
		if ( 'positive' === $kind ) {
			$command['explicit_positive'] = true;
			$command['claims'] = array( $request . '-claim' => FaceCorrespondenceResolverTest::face() + array( 'person_uuid' => 'person', 'authorization' => 'exact', 'from_cluster_uuid' => 'group', 'snapshot_version' => 7 ) );
		}
		return $command;
	}
	private function participate(): callable {
		return function ( array $receipt ): bool {
			$this->db->effects[] = $receipt['request_id'];
			return true;
		};
	}
	public function test_durable_replay_does_not_reexecute_and_changed_request_is_rejected(): void {
		$command = $this->command();
		$first = $this->journal->apply( 'tenant', $command, $this->participate() );
		self::assertSame( $first, $this->new_journal()->apply( 'tenant', $command, $this->participate() ) );
		self::assertSame( array( 'request' ), $this->db->effects );
		$command['guards']['snapshot_version'] = 8;
		$this->expectExceptionMessage( 'Changed request identity.' );
		$this->journal->apply( 'tenant', $command, $this->participate() );
	}
	public function test_failed_participant_and_commit_and_storage_roll_back_all_effects(): void {
		foreach ( array( 'participant', 'COMMIT', 'UPDATE' ) as $failure ) {
			$this->setUp();
			$this->db->fail = $failure;
			try {
				$this->journal->apply( 'tenant', $this->command(), function () use ( $failure ): bool {
					$this->db->effects[] = 'binding-and-outbox';
					return 'participant' !== $failure;
				} );
				self::fail( 'Failure must abort.' );
			} catch ( \RuntimeException $error ) {
				self::assertSame( array(), $this->db->rows );
				self::assertSame( array(), $this->db->effects );
				self::assertContains( 'ROLLBACK', $this->db->queries );
			}
		}
	}
	public function test_two_stale_callers_cannot_advance_same_revision(): void {
		$this->journal->apply( 'tenant', $this->command(), $this->participate() );
		$this->expectExceptionMessage( 'Stale journal revision.' );
		$this->new_journal()->apply( 'tenant', $this->command( 'concurrent' ), $this->participate() );
	}
	public function test_unlink_rename_import_reload_retry_preserve_suppression_and_history(): void {
		$first = $this->journal->apply( 'tenant', $this->command(), $this->participate() );
		$unlink = $this->command( 'unlink', 'unlink', 1 );
		$unlink['covered_claims'] = array( 'request-claim' );
		$this->journal->apply( 'tenant', $unlink, $this->participate() );
		$this->journal->apply( 'tenant', $this->command( 'rename', 'rename', 2 ), $this->participate() );
		$import = $this->command( 'import', 'import', 3 );
		$import['historical_claims'] = array( 'renamed-legacy' => array( 'person_uuid' => 'person', 'tenant_id' => 'tenant', 'label' => 'Human rename' ) );
		$receipt = $this->new_journal()->apply( 'tenant', $import, $this->participate() );
		self::assertTrue( $receipt['after']['auto_rebind_suppressed'] );
		self::assertSame( 'historical', $receipt['after']['claims']['request-claim']['authority_state'] );
		self::assertSame( 'historical', $receipt['after']['claims']['renamed-legacy']['authority_state'] );
		self::assertSame( $receipt, $this->new_journal()->apply( 'tenant', $import, $this->participate() ) );
		$redo = $this->new_journal()->apply( 'tenant', $this->command( 'redo', 'positive', 4 ), $this->participate() );
		self::assertFalse( $redo['after']['auto_rebind_suppressed'] );
		self::assertNotSame( $first['after']['binding_intent_id'], $redo['after']['binding_intent_id'] );
		self::assertSame( 'historical', $redo['after']['claims']['request-claim']['authority_state'] );
	}
	public function test_failed_positive_cannot_clear_undo_suppression(): void {
		$this->journal->apply( 'tenant', $this->command(), $this->participate() );
		$this->journal->apply( 'tenant', $this->command( 'undo', 'undo', 1 ), $this->participate() );
		try {
			$this->journal->apply( 'tenant', $this->command( 'redo', 'positive', 2 ), static fn(): bool => false );
			self::fail( 'Guard must abort.' );
		} catch ( \RuntimeException $error ) {
			$stored = json_decode( $this->db->rows['tenant'], true );
			self::assertTrue( $stored['people']['person']['auto_rebind_suppressed'] );
			self::assertSame( 2, $stored['people']['person']['binding_intent_revision'] );
		}
	}
	public function test_adapter_refuses_nested_transaction_across_instances(): void {
		$this->expectExceptionMessage( 'idle transaction connection' );
		$this->journal->apply( 'tenant', $this->command(), function (): bool {
			$this->new_journal()->apply( 'tenant', $this->command( 'nested' ), $this->participate() );
			return true;
		} );
	}
	public function test_fresh_review_is_separate_from_historical_exact_correspondence(): void {
		$command = $this->command();
		$claim = &$command['claims']['request-claim'];
		$claim['authorization'] = 'fresh_review';
		$claim['review_source_ref'] = 'pinned-reviewed-source';
		unset( $claim['face_evidence_v1'], $claim['lifecycle_eligible'] );
		$this->journal->apply( 'tenant', $command, $this->participate() );
		$state = $this->new_journal()->inspect( 'tenant' );
		$person = $state['people']['person'];
		$intent = $person + array( 'person_uuid' => 'person', 'ancestry_attested' => true );
		$result = ( new \AltContext\Sovereign\Curation\FaceCorrespondenceResolver() )->resolve(
			array( 'tenant_id' => 'tenant', 'identity_namespace_id' => 'namespace', 'snapshot_version' => 7, 'available' => true, 'complete' => true, 'claims_complete' => true, 'lifecycle_attested' => true, 'faces' => array( FaceCorrespondenceResolverTest::face() ) ),
			$person['claims'], $intent
		);
		self::assertSame( 'insufficient_evidence', $result['correspondence_status'] );
		self::assertSame( array(), $result['matched_faces'] );
	}
	public function test_retirement_preserves_unrelated_active_claims_and_reuse_is_rejected(): void {
		$command = $this->command();
		$other = $command['claims']['request-claim'];
		$other['identity_uuid'] = 'face-2';
		$other['face_evidence_v1']['observation_id'] = 'obs-2';
		$other['face_evidence_v1']['region']['x'] = 40;
		$command['claims']['other-claim'] = $other;
		$this->journal->apply( 'tenant', $command, $this->participate() );
		$unlink = $this->command( 'unlink', 'unlink', 1 );
		$unlink['covered_claims'] = array( 'request-claim' );
		$receipt = $this->journal->apply( 'tenant', $unlink, $this->participate() );
		self::assertSame( 'active', $receipt['after']['claims']['other-claim']['authority_state'] );
		self::assertSame( 'historical', $receipt['after']['claims']['request-claim']['authority_state'] );
		$reuse = $this->command( 'redo', 'positive', 2 );
		$reuse['claims'] = array( 'request-claim' => $other );
		$this->expectExceptionMessage( 'Claim references cannot be reused.' );
		$this->journal->apply( 'tenant', $reuse, $this->participate() );
	}

	public function test_batch_reassignment_is_atomic_replayable_and_preserves_source_history(): void {
		$this->journal->apply( 'tenant', $this->command(), $this->participate() );
		$retire = $this->command( 'retire', 'retire', 1 );
		$retire['covered_claims'] = array( 'request-claim' );
		$bind = $this->command( 'destination', 'positive', 0 );
		$bind['person_uuid'] = 'destination-person';
		$bind['claims']['destination-claim']['person_uuid'] = 'destination-person';
		$before = $this->db->rows;
		try {
			$this->journal->apply_batch( 'tenant', 'batch', array( $retire, $bind ), static fn(): bool => false );
			self::fail( 'Batch must roll back.' );
		} catch ( \RuntimeException $error ) {
			self::assertSame( $before, $this->db->rows );
		}
		$receipt = $this->journal->apply_batch( 'tenant', 'batch', array( $retire, $bind ), $this->participate() );
		self::assertSame( $receipt, $this->new_journal()->apply_batch( 'tenant', 'batch', array( $retire, $bind ), $this->participate() ) );
		self::assertSame( array( 'request', 'batch' ), $this->db->effects );
		$state = $this->journal->inspect( 'tenant' );
		self::assertSame( 'historical', $state['people']['person']['claims']['request-claim']['authority_state'] );
		self::assertSame( 'active', $state['people']['destination-person']['claims']['destination-claim']['authority_state'] );
	}

	/** Accepted JSON evidence with zero-fraction floats, which fingerprints keep distinct from integers. */
	private function command_with_json_floats( string $request = 'request' ): array {
		$command = $this->command( $request );
		$command['claims'][ $request . '-claim' ]['confidence'] = 1.0;
		$command['claims'][ $request . '-claim' ]['quality'] = 0.25;
		$command['claims'][ $request . '-claim' ]['face_evidence_v1']['producer_extension'] = 1.0;
		$command['claims'][ $request . '-claim' ]['face_evidence_v1']['producer_offset'] = -0.0;
		return $command;
	}
	public function test_exact_retry_returns_identical_receipt_after_storage_round_trip(): void {
		$command = $this->command_with_json_floats();
		$first = $this->journal->apply( 'tenant', $command, $this->participate() );
		self::assertSame( 1.0, $first['after']['claims']['request-claim']['confidence'], 'Control: the first receipt carries the accepted float.' );
		$retry = $this->new_journal()->apply( 'tenant', $command, $this->participate() );
		self::assertSame( array( 'request' ), $this->db->effects, 'Control: an exact retry must not repeat participant effects.' );
		self::assertSame( $first, $retry, 'Exact retry must return the identical stored receipt, including accepted JSON float scalars.' );
		self::assertSame( $first['after'], $this->new_journal()->inspect( 'tenant' )['people']['person'], 'Durable person state must keep accepted claim scalars unchanged.' );
	}
	public function test_exact_batch_retry_returns_identical_receipt_after_storage_round_trip(): void {
		$bind = $this->command_with_json_floats( 'destination' );
		$first = $this->journal->apply_batch( 'tenant', 'batch', array( $bind ), $this->participate() );
		$retry = $this->new_journal()->apply_batch( 'tenant', 'batch', array( $bind ), $this->participate() );
		self::assertSame( array( 'batch' ), $this->db->effects, 'Control: an exact batch retry must not repeat participant effects.' );
		self::assertSame( $first, $retry, 'Exact batch retry must return the identical stored receipt, including accepted JSON float scalars.' );
	}
	public function test_accepted_proof_stays_exact_after_storage_round_trip(): void {
		$command = $this->command_with_json_floats();
		$face = $command['claims']['request-claim'];
		self::assertTrue( FaceCorrespondenceResolver::valid_face( $face ), 'Control: the public validator accepts this JSON proof.' );
		$first = $this->journal->apply( 'tenant', $command, $this->participate() );
		$incoming = array( 'tenant_id' => 'tenant', 'identity_namespace_id' => 'namespace', 'snapshot_version' => 7, 'available' => true, 'complete' => true, 'claims_complete' => true, 'lifecycle_attested' => true, 'faces' => array( $face ) );
		$resolver = new FaceCorrespondenceResolver();
		$intent = $first['after'] + array( 'person_uuid' => 'person', 'ancestry_attested' => true );
		self::assertSame( 'exact', $resolver->resolve( $incoming, $first['after']['claims'], $intent )['correspondence_status'], 'Control: correspondence is exact before persisted state is read.' );
		$stored = $this->new_journal()->inspect( 'tenant' )['people']['person'];
		$intent = $stored + array( 'person_uuid' => 'person', 'ancestry_attested' => true );
		self::assertSame( 'exact', $resolver->resolve( $incoming, $stored['claims'], $intent )['correspondence_status'], 'Unchanged producer proof must stay exact after the journal storage round trip.' );
	}
	public function test_competing_positive_claim_rolls_back_instead_of_picking_a_person(): void {
		$this->journal->apply( 'tenant', $this->command(), $this->participate() );
		$other = $this->command( 'other' );
		$other['person_uuid'] = 'other-person';
		$other['claims']['other-claim']['person_uuid'] = 'other-person';
		$before = $this->db->rows;
		try {
			$this->journal->apply( 'tenant', $other, $this->participate() );
			self::fail( 'Competition must abort.' );
		} catch ( \DomainException $error ) {
			self::assertSame( 'Competing active observation claim.', $error->getMessage() );
			self::assertSame( $before, $this->db->rows );
			self::assertSame( array( 'request' ), $this->db->effects );
		}
	}

	public function test_same_request_and_person_ids_are_isolated_by_tenant(): void {
		$command = $this->command();
		$first = $this->journal->apply( 'tenant', $command, $this->participate() );
		$foreign = $command;
		$foreign['claims']['request-claim']['tenant_id'] = 'other-tenant';
		$second = $this->new_journal()->apply( 'other-tenant', $foreign, $this->participate() );
		self::assertNotSame( $first['fingerprint'], $second['fingerprint'] );
		self::assertSame( $first, $this->new_journal()->apply( 'tenant', $command, $this->participate() ) );
		self::assertSame( $second, $this->new_journal()->apply( 'other-tenant', $foreign, $this->participate() ) );
		self::assertSame( array( 'request', 'request' ), $this->db->effects );
		self::assertSame( $first['after'], $this->journal->inspect( 'tenant' )['people']['person'] );
		self::assertSame( $second['after'], $this->journal->inspect( 'other-tenant' )['people']['person'] );
	}

	public function test_retry_accepts_map_reordering_but_rejects_changed_scalar_type(): void {
		$command = $this->command();
		$first = $this->journal->apply( 'tenant', $command, $this->participate() );
		$command['guards'] = array_reverse( $command['guards'], true );
		self::assertSame( $first, $this->new_journal()->apply( 'tenant', $command, $this->participate() ) );
		$before = $this->db->rows;
		$command['guards']['person_revision'] = 5.0;
		try {
			$this->journal->apply( 'tenant', $command, $this->participate() );
			self::fail( 'A changed typed guard must not adopt a cached receipt.' );
		} catch ( \DomainException $error ) {
			self::assertSame( 'Changed request identity.', $error->getMessage() );
			self::assertSame( $before, $this->db->rows );
			self::assertSame( array( 'request' ), $this->db->effects );
		}
	}
}
