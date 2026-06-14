<?php

declare(strict_types=1);

namespace AltContext\Api;

use WP_Error;
use WP_REST_Response;

/**
 * Narrow host seam the DescribeMediaService dispatches through. Mirrors the
 * AnalysisJobsHostInterface surface but without the batch-tier methods — the
 * describe path is single-image and never builds MediaItems.
 */
interface DescribeHostInterface {
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
}
