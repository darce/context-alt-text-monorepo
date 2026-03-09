<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Sync;

use AltContext\Api\AbstractRecognitionProxyController;
use WP_Error;
use WP_REST_Response;

use function rawurlencode;
use function sprintf;

class SnapshotClientTransport extends AbstractRecognitionProxyController {
	public function register_routes(): void {
		// Intentionally empty. Transport adapter is not a public REST controller.
	}

	public function request( string $method, string $path, array $body = array(), array $query = array() ): WP_REST_Response|WP_Error {
		return $this->proxy_request( $method, $path, $body, $query, 'background_sync' );
	}

	public function acknowledge_projection( string $job_id, int $snapshot_version ): WP_REST_Response|WP_Error {
		return $this->request(
			'POST',
			sprintf( '/recognition/jobs/%s/acknowledge-projection', rawurlencode( $job_id ) ),
			array( 'snapshot_version' => $snapshot_version ),
			array()
		);
	}

	public function tenant_id(): string {
		return $this->get_tenant_id();
	}
}
