<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Sync;

interface OutboxWriterInterface {
	/**
	 * Persist one durable curation operation in the local outbox.
	 *
	 * @param array<string,mixed> $payload
	 */
	public function enqueue(
		string $tenant_id,
		string $operation_type,
		string $entity_type,
		string $entity_key,
		int $expected_base_version,
		int $local_revision,
		array $payload,
		?string $idempotency_key = null
	): int|false;
}
