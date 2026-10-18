<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Curation;

/** Local intent authority. No service I/O is permitted in the participant callback. */
final class BindingIntentJournal implements BindingIntentJournalInterface {
	private BindingJournalStore $store;

	public function __construct( BindingJournalStore $store ) {
		$this->store = $store;
	}

	/** Read durable authority; this does not attest reset/restore ancestry. */
	public function inspect( string $tenant_id ): array {
		return $this->store->transaction( $tenant_id, static function ( array &$state ): array {
			return $state;
		} );
	}

	/**
	 * @throws \Throwable On invalid input, a stale guard, or failed participant/storage.
	 *
	 * Immutable request identity covers the entire command, including writer guards.
	 * $participate must lock/re-read actual person/group/member/proof inputs, compare
	 * command['guards'], and write binding/audit/outbox effects on the SAME connection.
	 * Return true only when every guard and write succeeded; throw on any failure.
	 * A false result rolls back. Exact retries return the old receipt without effects.
	 *
	 * Commands: positive, unlink, undo, retire, rename, import. Only positive creates
	 * a new intent and clears suppression, and requires explicit reviewed authority.
	 * claims are keyed by immutable caller claim references; covered_claims names
	 * precisely the claims retired (never all of a person's unrelated associations).
	 */
	public function apply( string $tenant_id, array $command, callable $participate ): array {
		return $this->store->transaction( $tenant_id, function ( array &$state ) use ( $tenant_id, $command, $participate ): array {
			$receipt = $this->transition( $state, $tenant_id, $command, $participate );
			$this->assert_exclusive_claims( $state );
			return $receipt;
		} );
	}

	/**
	 * Atomic source/destination transitions under ONE fence and participant call.
	 * Batch and child request identities cannot be adopted from prior commands.
	 * Exact batch retries return the receipt without executing the participant.
	 *
	 * @throws \InvalidArgumentException On missing batch identity or transitions.
	 */
	public function apply_batch( string $tenant_id, string $request_id, array $commands, callable $participate ): array {
		if ( '' === trim( $request_id ) || array() === $commands ) {
			throw new \InvalidArgumentException( 'Missing batch identity or transitions.' );
		}
		$fingerprint = self::fingerprint( array( $tenant_id, $request_id, $commands ) );
		return $this->store->transaction( $tenant_id, function ( array &$state ) use ( $tenant_id, $request_id, $commands, $participate, $fingerprint ): array {
			$replay = $state['requests'][ $request_id ] ?? null;
			if ( null !== $replay ) {
				if ( $replay['fingerprint'] !== $fingerprint ) {
					throw new \DomainException( 'Changed request identity.' );
				}
				return $replay['receipt'];
			}
			$receipts = array();
			foreach ( $commands as $command ) {
				if ( ! is_array( $command ) || ! is_string( $command['request_id'] ?? null ) || $request_id === $command['request_id'] || isset( $state['requests'][ $command['request_id'] ] ) ) {
					throw new \DomainException( 'Batch requires fresh child request identities.' );
				}
				$receipts[] = $this->transition( $state, $tenant_id, $command, static fn(): bool => true );
			}
			$this->assert_exclusive_claims( $state );
			$receipt = array( 'tenant_id' => $tenant_id, 'request_id' => $request_id, 'fingerprint' => $fingerprint, 'transitions' => $receipts );
			if ( true !== $participate( $receipt ) ) {
				throw new \RuntimeException( 'Participant guard or write failed.' );
			}
			$state['requests'][ $request_id ] = array( 'fingerprint' => $fingerprint, 'receipt' => $receipt );
			return $receipt;
		} );
	}

	private function transition( array &$state, string $tenant_id, array $command, callable $participate ): array {
		foreach ( array( 'request_id', 'person_uuid', 'kind' ) as $field ) {
			if ( ! is_string( $command[ $field ] ?? null ) || '' === trim( $command[ $field ] ) ) {
				throw new \InvalidArgumentException( 'Missing command identity.' );
			}
		}
		if ( '' === trim( $tenant_id ) || ! is_int( $command['expected_revision'] ?? null ) || ! is_array( $command['guards'] ?? null ) ) {
			throw new \InvalidArgumentException( 'Missing tenant, revision or writer guards.' );
		}
		if ( ! in_array( $command['kind'], array( 'positive', 'unlink', 'undo', 'retire', 'rename', 'import' ), true ) ) {
			throw new \InvalidArgumentException( 'Unknown transition.' );
		}
		$fingerprint = self::fingerprint( array( $tenant_id, $command ) );
		$request_id = $command['request_id'];
		$replay = $state['requests'][ $request_id ] ?? null;
		if ( null !== $replay ) {
			if ( $replay['fingerprint'] !== $fingerprint ) {
				throw new \DomainException( 'Changed request identity.' );
			}
			return $replay['receipt'];
		}
		$person = $command['person_uuid'];
		$current = $state['people'][ $person ] ?? array(
			'binding_intent_revision' => 0,
			'binding_intent_id' => null,
			'auto_rebind_suppressed' => true,
			'claims' => array(),
		);
		if ( $current['binding_intent_revision'] !== $command['expected_revision'] ) {
			throw new \DomainException( 'Stale journal revision.' );
		}
		$kind = $command['kind'];
		$covered = $command['covered_claims'] ?? array();
		$claims = $command['claims'] ?? array();
		if ( ! is_array( $covered ) || ! is_array( $claims ) || ( 'positive' !== $kind && array() !== $claims ) ) {
			throw new \InvalidArgumentException( 'Only positive intent may activate claims.' );
		}
		if ( in_array( $kind, array( 'rename', 'import' ), true ) && array() !== $covered ) {
			throw new \InvalidArgumentException( 'Non-membership transition cannot retire claims.' );
		}
		foreach ( $covered as $reference ) {
			if ( ! is_string( $reference ) || ! isset( $current['claims'][ $reference ] ) ) {
				throw new \DomainException( 'Unknown covered claim.' );
			}
			$current['claims'][ $reference ]['authority_state'] = 'historical';
		}
		$historical = $command['historical_claims'] ?? array();
		if ( ! is_array( $historical ) ) {
			throw new \InvalidArgumentException( 'Invalid historical claim list.' );
		}
		foreach ( $historical as $reference => $claim ) {
			if ( ! is_string( $reference ) || '' === $reference || isset( $current['claims'][ $reference ] ) || ! is_array( $claim ) || ( $claim['tenant_id'] ?? null ) !== $tenant_id || ( $claim['person_uuid'] ?? null ) !== $person ) {
				throw new \DomainException( 'Invalid historical claim.' );
			}
			$claim['authority_state'] = 'historical';
			unset( $claim['binding_intent_id'] );
			$current['claims'][ $reference ] = $claim;
		}
		if ( 'positive' === $kind ) {
			if ( true !== ( $command['explicit_positive'] ?? false ) || array() === $claims ) {
				throw new \DomainException( 'Positive intent requires explicit source consent.' );
			}
			// UUID is generated here, never accepted from import/replay or reused.
			$bytes = random_bytes( 16 );
			$bytes[6] = chr( ( ord( $bytes[6] ) & 15 ) | 64 );
			$bytes[8] = chr( ( ord( $bytes[8] ) & 63 ) | 128 );
			$hex = bin2hex( $bytes );
			$intent_id = substr( $hex, 0, 8 ) . '-' . substr( $hex, 8, 4 ) . '-' . substr( $hex, 12, 4 ) . '-' . substr( $hex, 16, 4 ) . '-' . substr( $hex, 20 );
			if ( isset( $state['used_intents'][ $intent_id ] ) ) {
				throw new \RuntimeException( 'Intent UUID collision.' );
			}
			$state['used_intents'][ $intent_id ] = true;
			foreach ( $claims as $reference => $claim ) {
				if ( ! is_string( $reference ) || '' === $reference || isset( $current['claims'][ $reference ] ) || ! is_array( $claim ) ) {
					throw new \DomainException( 'Claim references cannot be reused.' );
				}
				if ( ( $claim['tenant_id'] ?? null ) !== $tenant_id || ( $claim['person_uuid'] ?? null ) !== $person ) {
					throw new \DomainException( 'Foreign claim.' );
				}
				if ( ! is_string( $claim['identity_uuid'] ?? null ) || '' === trim( $claim['identity_uuid'] ) || ! is_int( $claim['attachment_id'] ?? null ) || $claim['attachment_id'] <= 0 || ! is_string( $claim['from_cluster_uuid'] ?? null ) || '' === trim( $claim['from_cluster_uuid'] ) || ! is_int( $claim['snapshot_version'] ?? null ) || $claim['snapshot_version'] < 0 ) {
					throw new \DomainException( 'Missing claim membership provenance.' );
				}
				$authorization = $claim['authorization'] ?? null;
				if ( 'fresh_review' === $authorization ) {
					if ( ! is_string( $claim['review_source_ref'] ?? null ) || '' === trim( $claim['review_source_ref'] ) ) {
						throw new \DomainException( 'Missing reviewed source reference.' );
					}
				} elseif ( 'exact' !== $authorization || ! FaceCorrespondenceResolver::valid_face( $claim ) ) {
					throw new \DomainException( 'Missing eligible source evidence.' );
				}
				$claim['authority_state'] = 'active';
				$claim['binding_intent_id'] = $intent_id;
				$claim['binding_intent_revision'] = $current['binding_intent_revision'] + 1;
				$current['claims'][ $reference ] = $claim;
			}
			$current['binding_intent_id'] = $intent_id;
			$current['auto_rebind_suppressed'] = false;
		}
		if ( in_array( $kind, array( 'unlink', 'undo' ), true ) ) {
			$current['auto_rebind_suppressed'] = true;
		}
		++$current['binding_intent_revision'];
		$receipt = array(
			'tenant_id' => $tenant_id,
			'request_id' => $request_id,
			'fingerprint' => $fingerprint,
			'before' => $state['people'][ $person ] ?? null,
			'after' => $current,
		);
		if ( true !== $participate( $receipt ) ) {
			throw new \RuntimeException( 'Participant guard or write failed.' );
		}
		$state['people'][ $person ] = $current;
		$state['requests'][ $request_id ] = array( 'fingerprint' => $fingerprint, 'receipt' => $receipt );
		return $receipt;
	}

	private function assert_exclusive_claims( array $state ): void {
		$observations = array();
		foreach ( $state['people'] ?? array() as $person ) {
			foreach ( $person['claims'] as $claim ) {
				if ( 'active' !== $claim['authority_state'] || ! is_array( $claim['face_evidence_v1'] ?? null ) ) {
					continue;
				}
				$proof = $claim['face_evidence_v1'];
				$key = self::fingerprint( array( $claim['tenant_id'], $proof['identity_namespace_id'] ?? null, $proof['observation_id'] ?? null ) );
				if ( isset( $observations[ $key ] ) ) {
					throw new \DomainException( 'Competing active observation claim.' );
				}
				$observations[ $key ] = true;
			}
		}
	}

	/** Stable map order, strict scalar types, full list order and all evidence. */
	public static function fingerprint( array $value ): string {
		$canonicalize = static function ( $item ) use ( &$canonicalize ) {
			if ( is_array( $item ) ) {
				if ( array_keys( $item ) !== range( 0, count( $item ) - 1 ) ) {
					ksort( $item );
				}
				return array_map( $canonicalize, $item );
			}
			if ( ! is_null( $item ) && ! is_scalar( $item ) ) {
				throw new \InvalidArgumentException( 'Only JSON evidence is supported.' );
			}
			return $item;
		};
		return hash( 'sha256', json_encode( $canonicalize( $value ), JSON_THROW_ON_ERROR | JSON_PRESERVE_ZERO_FRACTION ) );
	}
}
