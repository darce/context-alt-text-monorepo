<?php

declare(strict_types=1);

namespace AltContext\Api;

use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

interface ClusterMutationHostInterface {
	public function get_tenant_id(): string;

	public function should_proxy_mutation_to_backend( string $tenant_id ): bool;

	/**
	 * @param array<string,mixed> $body
	 */
	public function proxy_cluster_mutation( string $method, string $path, array $body = array() ): WP_REST_Response|WP_Error;

	/**
	 * @return array<string,mixed>|WP_Error
	 */
	public function get_projected_cluster_or_error(
		string $cluster_id,
		string $missing_code = 'cluster_not_found',
		string $missing_message = 'Cluster not found.'
	): array|WP_Error;

	/**
	 * @param array<string,mixed> $context_row
	 * @param array<string,mixed> $payload
	 */
	public function enqueue_curation_operation(
		string $operation_type,
		string $entity_key,
		array $context_row,
		array $payload = array(),
		string $entity_type = 'cluster'
	): bool;

	/**
	 * @param string[] $cluster_ids
	 */
	public function trigger_xmp_refresh_for_cluster_ids( array $cluster_ids, string $context ): void;

	/**
	 * @param array<string,mixed> $payload
	 */
	public function resolve_split_idempotency_key(
		WP_REST_Request $request,
		string $cluster_id,
		int $expected_base_version,
		array $payload
	): string;
}
