<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Sync;

use function is_string;
use function md5;
use function sprintf;
use function substr;
use function wp_generate_uuid4;
use function wp_json_encode;

/**
 * Shared deterministic idempotency-key derivation for curation outbox operations.
 *
 * Extracted from ClusterMutationsController::derive_curation_idempotency_key() /
 * format_idempotency_key() (E15-35 Slice 3, PR3-01) so the restore_local
 * synthesis path in ConflictResolutionService and the REST controller derive
 * BYTE-IDENTICAL keys: a double-submit (or a replayed restore resolution)
 * collapses onto a single outbox row via uq_idempotency, and the backend replay
 * cache absorbs a double-pushed op. A genuinely distinct operation (different
 * entity or a newer target revision) yields a different key and is enqueued
 * normally.
 */
final class CurationIdempotencyKey {

	/**
	 * @param array<string,mixed> $payload
	 */
	public static function derive(
		string $tenant_id,
		string $operation_type,
		string $entity_type,
		string $entity_key,
		int $target_revision,
		array $payload
	): string {
		$basis = wp_json_encode(
			array(
				'tenant_id'       => $tenant_id,
				'operation_type'  => $operation_type,
				'entity_type'     => $entity_type,
				'entity_key'      => $entity_key,
				'target_revision' => $target_revision,
				'payload'         => $payload,
			)
		);

		if ( ! is_string( $basis ) || '' === $basis ) {
			return wp_generate_uuid4();
		}

		return self::format( $basis );
	}

	/**
	 * UUID-style grouping of an md5 over the basis string. Must stay byte-identical
	 * to the pre-extraction controller formatting (characterization-tested).
	 */
	public static function format( string $basis ): string {
		$hash = md5( $basis );

		return sprintf(
			'%s-%s-%s-%s-%s',
			substr( $hash, 0, 8 ),
			substr( $hash, 8, 4 ),
			substr( $hash, 12, 4 ),
			substr( $hash, 16, 4 ),
			substr( $hash, 20, 12 )
		);
	}
}
