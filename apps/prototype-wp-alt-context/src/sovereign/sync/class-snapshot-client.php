<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Sync;

use WP_Error;
use WP_REST_Response;

require_once __DIR__ . '/interface-snapshot-client.php';
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

class SnapshotClient implements SnapshotClientInterface {
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

	public function fetch_delta( string $tenant_id, int $since_version ): array|WP_Error {
		$normalized_tenant_id = $this->normalize_tenant_id_for_path( $tenant_id );
		if ( '' === $normalized_tenant_id ) {
			return new WP_Error( 'invalid_tenant_id', 'Tenant ID is required for delta fetch.', array( 'status' => 400 ) );
		}

		if ( $since_version < 0 ) {
			return new WP_Error( 'invalid_since_version', 'Delta fetch requires a non-negative since_version.', array( 'status' => 400 ) );
		}

		$path = sprintf( '/recognition/tenants/%s/clusters/delta', rawurlencode( $normalized_tenant_id ) );
		$response = $this->transport->request(
			'GET',
			$path,
			array(),
			array(
				'since_version' => $since_version,
			)
		);
		if ( ! ( $response instanceof WP_REST_Response ) ) {
			return $response;
		}

		if ( $response->get_status() >= 400 ) {
			return new WP_Error(
				'snapshot_delta_fetch_failed',
				'Delta endpoint returned an error status.',
				array(
					'status'   => $response->get_status(),
					'response' => $response->get_data(),
				)
			);
		}

		$data = $response->get_data();
		if ( ! is_array( $data ) ) {
			return new WP_Error( 'invalid_snapshot_delta_payload', 'Delta payload must be an object.', array( 'status' => 502 ) );
		}

		return $data;
	}

	/**
	 * @param string[] $cluster_ids
	 */
	public function fetch_targeted_snapshot( string $tenant_id, array $cluster_ids ): array|WP_Error {
		$normalized_tenant_id = $this->normalize_tenant_id_for_path( $tenant_id );
		if ( '' === $normalized_tenant_id ) {
			return new WP_Error( 'invalid_tenant_id', 'Tenant ID is required for targeted snapshot fetch.', array( 'status' => 400 ) );
		}

		$normalized_cluster_ids = array_values(
			array_filter(
				array_map(
					static function ( $cluster_id ): string {
						return sanitize_text_field( trim( (string) $cluster_id ) );
					},
					$cluster_ids
				),
				static function ( string $cluster_id ): bool {
					return '' !== $cluster_id;
				}
			)
		);
		if ( empty( $normalized_cluster_ids ) ) {
			return new WP_Error( 'invalid_cluster_ids', 'One or more cluster IDs are required for targeted snapshot fetch.', array( 'status' => 400 ) );
		}

		$path = sprintf( '/recognition/tenants/%s/clusters/targeted-snapshot', rawurlencode( $normalized_tenant_id ) );
		$response = $this->transport->request(
			'GET',
			$path,
			array(),
			array(
				'cluster_ids' => $normalized_cluster_ids,
			)
		);
		if ( ! ( $response instanceof WP_REST_Response ) ) {
			return $response;
		}

		if ( $response->get_status() >= 400 ) {
			return new WP_Error(
				'targeted_snapshot_fetch_failed',
				'Targeted snapshot endpoint returned an error status.',
				array(
					'status'   => $response->get_status(),
					'response' => $response->get_data(),
				)
			);
		}

		$data = $response->get_data();
		if ( ! is_array( $data ) ) {
			return new WP_Error( 'invalid_snapshot_payload', 'Targeted snapshot payload must be an object.', array( 'status' => 502 ) );
		}

		return $data;
	}

	public function acknowledge_projection( string $job_id, int $snapshot_version, ?string $snapshot_generation_id = null ): WP_REST_Response|WP_Error {
		return $this->transport->acknowledge_projection( $job_id, $snapshot_version, $snapshot_generation_id );
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
