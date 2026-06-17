<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Sync;

interface TopologyCommandRepositoryInterface {
	/**
	 * @param array<string,mixed> $payload
	 */
	public function enqueue(
		string $tenant_id,
		string $command_type,
		string $entity_key,
		int $expected_base_version,
		array $payload,
		?string $idempotency_key = null
	): int|false;

	/**
	 * @return array<int,array<string,mixed>>
	 */
	public function find_reconcilable( ?string $tenant_id = null, int $limit = 25 ): array;

	/**
	 * Atomically claim a command for processing, gated on its current status and the claim
	 * lease, so a second concurrent drain cannot re-dispatch or re-reconcile it (CON-4).
	 * Returns true only when this caller won the claim.
	 */
	public function claim_command( int $command_id, string $expected_status ): bool;

	/**
	 * @param array<string,mixed>|null $result_payload
	 * @param string|null $expected_status When set, the write is gated on the row still being in
	 *   this status (CON-4-FU-1) so a stale re-claimed worker's terminal write is a 0-row no-op.
	 */
	public function update_status(
		int $command_id,
		string $status,
		?array $result_payload = null,
		?string $backend_command_id = null,
		?string $expected_status = null
	): bool;

	/**
	 * @param array<string,mixed> $response
	 */
	public function record_dispatch_result( int $command_id, array $response, ?string $expected_status = null ): bool;

	/**
	 * @param array<string,mixed>|null $result_payload
	 */
	public function mark_reconciled( int $command_id, ?array $result_payload = null, ?string $expected_status = null ): bool;

	public function record_failure( int $command_id, string $status, string $error_code, string $error_message, bool $increment_attempt = true, ?string $expected_status = null ): bool;

	/**
	 * Record a failed local reconcile of an already-applied command, bumping the
	 * dedicated reconcile-attempt counter (independent of dispatch `attempts`).
	 */
	public function record_reconcile_failure( int $command_id, string $status, string $error_code, string $error_message, ?string $expected_status = null ): bool;
}
