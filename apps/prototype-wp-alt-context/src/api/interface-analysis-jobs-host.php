<?php

declare(strict_types=1);

namespace AltContext\Api;

use WP_Error;
use WP_REST_Response;

interface AnalysisJobsHostInterface {
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

	public function is_proxy_unavailable( WP_REST_Response|WP_Error $response ): bool;

	public function get_retry_after_seconds( WP_REST_Response|WP_Error $response ): ?int;

	public function backend_overloaded_response( WP_REST_Response|WP_Error $response ): WP_REST_Response;

	/**
	 * @param object $sync_state_repository
	 */
	public function should_use_local_projection_gate( $sync_state_repository, string $tenant_id ): bool;

	public function get_proxy_policy(): RecognitionProxyPolicy;

	public function get_recognition_base_url(): string;

	public function get_recognition_source(): string;

	public function get_recognition_api_key(): string;

	public function get_current_tier_batch_limit(): int;
}
