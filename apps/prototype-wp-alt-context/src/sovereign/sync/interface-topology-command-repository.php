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
	 * @param array<string,mixed>|null $result_payload
	 */
	public function update_status(
		int $command_id,
		string $status,
		?array $result_payload = null,
		?string $backend_command_id = null
	): bool;

	/**
	 * @param array<string,mixed> $response
	 */
	public function record_dispatch_result( int $command_id, array $response ): bool;

	/**
	 * @param array<string,mixed>|null $result_payload
	 */
	public function mark_reconciled( int $command_id, ?array $result_payload = null ): bool;

	public function record_failure( int $command_id, string $status, string $error_code, string $error_message, bool $increment_attempt = true ): bool;
}
