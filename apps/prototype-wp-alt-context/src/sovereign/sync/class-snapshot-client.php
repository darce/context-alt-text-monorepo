<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Sync;

use WP_Error;
use WP_REST_Response;

require_once __DIR__ . '/class-snapshot-client-transport.php';

use function apply_filters;
use function is_array;
use function preg_match;
use function rawurlencode;
use function sanitize_text_field;
use function sprintf;
use function strtolower;
use function substr;
use function trim;

class SnapshotClient {
	private SnapshotClientTransport $transport;

	public function __construct( ?SnapshotClientTransport $transport = null ) {
		$this->transport = $transport ?? new SnapshotClientTransport();
	}

	public function fetch_current_tenant_snapshot(): array|WP_Error {
		return $this->fetch_snapshot( $this->transport->tenant_id() );
	}

	public function fetch_snapshot( string $tenant_id ): array|WP_Error {
		$normalized_tenant_id = $this->normalize_tenant_id_for_path( $tenant_id );
		if ( '' === $normalized_tenant_id ) {
			return new WP_Error( 'invalid_tenant_id', 'Tenant ID is required for snapshot fetch.', array( 'status' => 400 ) );
		}

		$path_template = $this->get_snapshot_endpoint_path();
		$path          = sprintf( $path_template, rawurlencode( $normalized_tenant_id ) );
		if ( '' !== $path && '/' !== $path[0] ) {
			$path = '/' . $path;
		}

		$response = $this->transport->request( 'GET', $path, array(), array() );
		if ( ! ( $response instanceof WP_REST_Response ) ) {
			return $response;
		}

		if ( $response->get_status() >= 400 ) {
			// 404 = no clusters for this tenant; return an empty snapshot.
			if ( 404 === $response->get_status() ) {
				return array(
					'snapshot_version' => 0,
					'clusters'         => array(),
					'members'          => array(),
					'tenant_id'        => $tenant_id,
					'empty'            => true,
				);
			}
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

	public function acknowledge_projection( string $job_id, int $snapshot_version ): WP_REST_Response|WP_Error {
		return $this->transport->acknowledge_projection( $job_id, $snapshot_version );
	}

	private function get_snapshot_endpoint_path(): string {
		$default_path  = '/recognition/tenants/%s/clusters/snapshot';
		$filtered_path = apply_filters( 'acx_snapshot_endpoint_path', $default_path );
		if ( is_string( $filtered_path ) && '' !== trim( $filtered_path ) ) {
			return trim( $filtered_path );
		}

		return $default_path;
	}

	private function normalize_tenant_id_for_path( string $tenant_id ): string {
		$normalized = sanitize_text_field( trim( $tenant_id ) );
		if ( '' === $normalized ) {
			return '';
		}

		// Backend auth compares canonical UUID strings. Normalize compact 32-hex IDs.
		if ( 1 === preg_match( '/^[a-fA-F0-9]{32}$/', $normalized ) ) {
			$hex = strtolower( $normalized );
			return sprintf(
				'%s-%s-%s-%s-%s',
				substr( $hex, 0, 8 ),
				substr( $hex, 8, 4 ),
				substr( $hex, 12, 4 ),
				substr( $hex, 16, 4 ),
				substr( $hex, 20, 12 )
			);
		}

		return $normalized;
	}
}
