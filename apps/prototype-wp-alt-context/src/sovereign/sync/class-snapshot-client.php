<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Sync;

use AltContext\Api\AbstractRecognitionProxyController;
use WP_Error;
use WP_REST_Response;

use function apply_filters;
use function is_array;
use function rawurlencode;
use function sanitize_text_field;
use function sprintf;
use function trim;

class SnapshotClient extends AbstractRecognitionProxyController {
	public function register_routes(): void {
		// Intentionally empty. Snapshot client is not a public REST controller.
	}

	public function fetch_current_tenant_snapshot(): array|WP_Error {
		return $this->fetch_snapshot( $this->get_tenant_id() );
	}

	public function fetch_snapshot( string $tenant_id ): array|WP_Error {
		$normalized_tenant_id = sanitize_text_field( trim( $tenant_id ) );
		if ( '' === $normalized_tenant_id ) {
			return new WP_Error( 'invalid_tenant_id', 'Tenant ID is required for snapshot fetch.', array( 'status' => 400 ) );
		}

		$path_template = $this->get_snapshot_endpoint_path();
		$path          = sprintf( $path_template, rawurlencode( $normalized_tenant_id ) );
		if ( '' !== $path && '/' !== $path[0] ) {
			$path = '/' . $path;
		}

		$response = $this->proxy_request( 'GET', $path, array(), array() );
		if ( ! ( $response instanceof WP_REST_Response ) ) {
			return $response;
		}

		if ( $response->get_status() >= 400 ) {
			return new WP_Error(
				'snapshot_fetch_failed',
				'Snapshot endpoint returned an error status.',
				array(
					'status'   => $response->get_status(),
					'response' => $response->get_data(),
				)
			);
		}

		$data = $response->get_data();
		if ( ! is_array( $data ) ) {
			return new WP_Error( 'invalid_snapshot_payload', 'Snapshot payload must be an object.', array( 'status' => 502 ) );
		}

		return $data;
	}

	protected function get_snapshot_endpoint_path(): string {
		$default_path  = '/tenants/%s/clusters/snapshot';
		$filtered_path = apply_filters( 'acx_snapshot_endpoint_path', $default_path );
		if ( is_string( $filtered_path ) && '' !== trim( $filtered_path ) ) {
			return trim( $filtered_path );
		}

		return $default_path;
	}
}
