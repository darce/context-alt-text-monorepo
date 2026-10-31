<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Curation;

require_once __DIR__ . '/BindingIntentJournalInterface.php';
require_once __DIR__ . '/BindingIntentJournal.php';
require_once __DIR__ . '/WpBindingJournalStore.php';
require_once __DIR__ . '/../../sovereign/repositories/class-cluster-curation-writer.php';
require_once __DIR__ . '/../../sovereign/sync/class-outbox-writer.php';
require_once __DIR__ . '/../../sovereign/sync/class-curation-idempotency-key.php';
require_once __DIR__ . '/../../api/services/class-person-resolution-service.php';

use AltContext\Api\Services\PersonResolutionService;
use AltContext\Sovereign\Repositories\ClusterCurationWriter;
use AltContext\Sovereign\Repositories\SyncStateRepository;
use AltContext\Sovereign\Sync\CurationIdempotencyKey;
use AltContext\Sovereign\Sync\OutboxWriter;

/**
 * Bounded local rename/unlink participant; never an evidence/recovery producer.
 * The journal owns START/COMMIT. Existing writers use the identical global wpdb.
 * Legacy API, snapshot and topology writers still require coordinated adoption.
 */
final class WpBindingIntentParticipant {
	private object $database;
	private string $prefix;
	private WpBindingJournalStore $store;
	private BindingIntentJournal $journal;

	public function __construct( object $database ) {
		$this->database = $database;
		$this->prefix = (string) $database->prefix;
		$this->store = new WpBindingJournalStore( $database, $this->prefix . 'acx_binding_journal' );
		$this->journal = new BindingIntentJournal( $this->store );
	}

	/** Produce the exact local guard inputs; this does not attest displayed pixels. */
	public function inspect( string $tenant, string $person, string $cluster ): array {
		$this->assert_connection();
		return $this->store->transaction( $tenant, function ( array &$state ) use ( $tenant, $person, $cluster ): array {
			$intent = $state['people'][ $person ] ?? null;
			return array(
				'expected_revision' => $intent['binding_intent_revision'] ?? 0,
				'guards' => $this->lock_inputs( $tenant, $person, $cluster, $intent ),
				'positive_binding_available' => false,
			);
		} );
	}

	/**
	 * Only negative membership and UUID-preserving name changes are supported.
	 * No arbitrary participant callback, network I/O, merge-on-bind or proof flags.
	 */
	public function apply( string $tenant, string $cluster, array $input ): array {
		if ( ! in_array( $input['kind'] ?? null, array( 'unlink', 'rename' ), true ) ) {
			throw new \InvalidArgumentException( 'Unsupported binding intent.' );
		}
		$this->assert_connection();
		$command = $input;
		$command['cluster_uuid'] = $cluster;
		$command['covered_claims'] = array();
		$command['historical_claims'] = array();
		$guards = $command['guards'] ?? array();
		if ( ! is_array( $guards ) || ! is_array( $guards['person'] ?? null ) || ! is_array( $guards['groups'] ?? null ) || ! is_array( $guards['members'] ?? null ) ) {
			throw new \InvalidArgumentException( 'Missing local row guards.' );
		}
		if ( 'unlink' === $command['kind'] ) {
			foreach ( $guards['intent']['claims'] ?? array() as $reference => $claim ) {
				if ( ( $claim['from_cluster_uuid'] ?? null ) === $cluster && 'active' === ( $claim['authority_state'] ?? null ) ) {
					$command['covered_claims'][] = $reference;
				}
			}
			// Capture missing legacy proof as historical association, never active proof.
			foreach ( $guards['members'][ $cluster ] ?? array() as $member ) {
				if ( ! is_array( $member ) ) {
					throw new \InvalidArgumentException( 'Invalid member guard.' );
				}
				$reference = BindingIntentJournal::fingerprint( array( $tenant, $input['request_id'] ?? null, $cluster, $member['identity_uuid'] ?? null ) );
				$command['historical_claims'][ $reference ] = array(
					'tenant_id' => $tenant,
					'person_uuid' => $input['person_uuid'] ?? null,
					'identity_uuid' => $member['identity_uuid'] ?? null,
					'attachment_id' => (int) ( $member['attachment_id'] ?? 0 ),
					'bbox_json' => $member['bbox_json'] ?? null,
					'from_cluster_uuid' => $cluster,
					'snapshot_version' => (int) ( $guards['groups'][ $cluster ]['snapshot_version'] ?? 0 ),
				);
			}
		}
		return $this->journal->apply( $tenant, $command, function ( array $receipt ) use ( $tenant, $cluster, $command, $guards ): bool {
			$actual = $this->lock_inputs( $tenant, $command['person_uuid'], $cluster, $receipt['before'] );
			if ( BindingIntentJournal::fingerprint( $actual ) !== BindingIntentJournal::fingerprint( $guards ) ) {
				throw new \DomainException( 'Local person, association, membership or delivery inputs changed.' );
			}
			foreach ( $actual['outbox'] as $rows ) {
				foreach ( $rows as $row ) {
					if ( 'acknowledged' !== $row['status'] ) {
						throw new \DomainException( 'Unsettled predecessor delivery requires ordered recovery.' );
					}
				}
			}
			$person = $actual['person'];
			$writer = new ClusterCurationWriter( $this->prefix . 'acx_clusters' );
			if ( 'unlink' === $command['kind'] ) {
				if ( ! isset( $actual['groups'][ $cluster ] ) ) {
					throw new \DomainException( 'Local association authority is unavailable.' );
				}
				if ( 1 !== $writer->reset_curation( $cluster, $tenant ) ) {
					throw new \RuntimeException( 'Could not unlink the guarded association.' );
				}
				$this->enqueue( $tenant, $receipt, 'cluster_person_unbound', 'cluster', $cluster, $actual['groups'][ $cluster ], array( 'cluster_uuid' => $cluster, 'person_uuid' => null, 'person_name' => null ) );
			} else {
				$name = $command['name'];
				$normalized = PersonResolutionService::normalize_name( $name );
				$this->execute( $this->database->prepare( 'UPDATE %i SET name = %s, normalized_name = %s WHERE person_uuid = %s AND tenant_id = %s', $this->prefix . 'acx_persons', $name, $normalized, $command['person_uuid'], $tenant ) );
				foreach ( $actual['groups'] as $uuid => $group ) {
					if ( 1 !== $writer->update_label( $uuid, $name ) ) {
						throw new \RuntimeException( 'Could not rename a guarded group.' );
					}
					$this->enqueue( $tenant, $receipt, 'cluster_label_updated', 'cluster', $uuid, $group, array( 'cluster_uuid' => $uuid, 'label' => $name ) );
				}
				$tags = json_decode( (string) ( $person['tags'] ?? '[]' ), true, 512, JSON_THROW_ON_ERROR );
				$person_context = $person;
				$person_context['snapshot_version'] = (int) ( $actual['sync'][0]['last_snapshot_version'] ?? 0 );
				$this->enqueue( $tenant, $receipt, 'person_updated', 'person', $command['person_uuid'], $person_context, array( 'person_uuid' => $command['person_uuid'], 'name' => $name, 'tags' => $tags ?? array() ) );
			}
			$this->execute( $this->database->prepare( 'UPDATE %i SET local_revision = local_revision + 1, updated_at = %s WHERE person_uuid = %s AND tenant_id = %s', $this->prefix . 'acx_persons', gmdate( 'Y-m-d H:i:s' ), $command['person_uuid'], $tenant ) );
			( new SyncStateRepository() )->touch_local_curation_marker( $tenant );
			return true;
		} );
	}

	private function lock_inputs( string $tenant, string $person, string $cluster, ?array $intent ): array {
		$people = $this->rows( 'SELECT * FROM %i WHERE tenant_id = %s AND person_uuid = %s FOR UPDATE', $this->prefix . 'acx_persons', $tenant, $person );
		if ( 1 !== count( $people ) ) {
			throw new \DomainException( 'Local person authority is unavailable.' );
		}
		$person_row = $people[0];
		$groups = array();
		$members = array();
		$outbox = array();
		foreach ( $this->rows( 'SELECT * FROM %i WHERE tenant_id = %s AND person_id = %d ORDER BY cluster_uuid FOR UPDATE', $this->prefix . 'acx_clusters', $tenant, (int) $person_row['id'] ) as $group ) {
			$groups[ $group['cluster_uuid'] ] = $group;
		}
		$target = $groups[ $cluster ] ?? null;
		if ( null === $target ) {
			$targets = $this->rows( 'SELECT * FROM %i WHERE tenant_id = %s AND cluster_uuid = %s FOR UPDATE', $this->prefix . 'acx_clusters', $tenant, $cluster );
			if ( 1 !== count( $targets ) ) {
				throw new \DomainException( 'Local group authority is unavailable.' );
			}
			$target = $targets[0];
		}
		foreach ( $groups as $uuid => $group ) {
			// Members have no tenant column: the locked tenant-owned group scopes them.
			$members[ $uuid ] = $this->rows( 'SELECT * FROM %i WHERE cluster_uuid = %s ORDER BY identity_uuid FOR UPDATE', $this->prefix . 'acx_identity_members', $uuid );
			$outbox[ $uuid ] = $this->rows( 'SELECT * FROM %i WHERE tenant_id = %s AND entity_type = %s AND entity_key = %s ORDER BY id FOR UPDATE', $this->prefix . 'acx_sync_outbox', $tenant, 'cluster', $uuid );
		}
		$outbox['person:' . $person] = $this->rows( 'SELECT * FROM %i WHERE tenant_id = %s AND entity_type = %s AND entity_key = %s ORDER BY id FOR UPDATE', $this->prefix . 'acx_sync_outbox', $tenant, 'person', $person );
		$sync = $this->rows( 'SELECT * FROM %i WHERE stream_name = %s FOR UPDATE', $this->prefix . 'acx_sync_state', 'tenant:' . $tenant . ':clusters' );
		return array( 'person' => $person_row, 'groups' => $groups, 'target' => $target, 'members' => $members, 'outbox' => $outbox, 'sync' => $sync, 'intent' => $intent );
	}

	private function enqueue( string $tenant, array $receipt, string $operation, string $type, string $key, array $before, array $payload ): void {
		$payload['curation_intent_id'] = $receipt['request_id'];
		$step_key = CurationIdempotencyKey::format( BindingIntentJournal::fingerprint( array( $tenant, $receipt['request_id'], $receipt['fingerprint'], $operation, $type, $key ) ) );
		if ( false === ( new OutboxWriter() )->enqueue( $tenant, $operation, $type, $key, (int) ( $before['snapshot_version'] ?? 0 ), (int) $before['local_revision'] + 1, $payload, $step_key ) ) {
			throw new \RuntimeException( 'Could not enqueue binding intent effect.' );
		}
	}

	private function rows( string $sql, ...$arguments ): array {
		$this->database->last_error = '';
		$rows = $this->database->get_results( $this->database->prepare( $sql, ...$arguments ), ARRAY_A );
		if ( ! is_array( $rows ) || '' !== (string) $this->database->last_error ) {
			throw new \RuntimeException( 'Could not lock binding intent inputs.' );
		}
		return $rows;
	}

	private function execute( string $sql ): void {
		if ( 1 !== $this->database->query( $sql ) ) {
			throw new \RuntimeException( 'Binding intent write failed.' );
		}
	}

	private function assert_connection(): void {
		global $wpdb;
		if ( $wpdb !== $this->database ) {
			throw new \LogicException( 'Binding intent requires the writers connection.' );
		}
		foreach ( array( 'acx_binding_journal', 'acx_persons', 'acx_clusters', 'acx_identity_members', 'acx_sync_outbox', 'acx_sync_state', 'acx_sync_conflicts' ) as $suffix ) {
			$this->database->last_error = '';
			$engine = $this->database->get_var( $this->database->prepare( 'SELECT ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s', $this->prefix . $suffix ) );
			if ( ! is_string( $engine ) || 'innodb' !== strtolower( $engine ) || '' !== (string) $this->database->last_error ) {
				throw new \RuntimeException( 'Binding intent requires installed InnoDB participant tables.' );
			}
		}
	}
}
