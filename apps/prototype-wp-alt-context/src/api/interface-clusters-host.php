<?php

declare(strict_types=1);

namespace AltContext\Api;

use AltContext\Sovereign\Repositories\SyncStateRepositoryInterface;
use WP_Error;
use WP_REST_Response;

interface ClustersHostInterface {
	public function get_tenant_id(): string;

	/**
	 * @param array<string,mixed> $body
	 * @param array<string,mixed> $query
	 */
	public function proxy_recognition_request(
		string $method,
		string $path,
		array $body = array(),
		array $query = array(),
		string $request_class = 'auto',
		string $body_kind = 'json',
		?int $max_body_bytes = null
	): WP_REST_Response|WP_Error;

	public function host_should_use_local_projection_gate(
		SyncStateRepositoryInterface $sync_state_repository,
		string $tenant_id
	): bool;

	public function host_is_projection_stale( ?string $updated_at ): bool;
}
