<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Sync;

require_once __DIR__ . '/class-snapshot-client-transport.php';

use WP_REST_Response;

use function apply_filters;
use function array_fill;
use function count;
use function in_array;
use function is_array;
use function is_string;
use function is_wp_error;
use function ltrim;
use function max;
use function rawurlencode;
use function strpos;
use function trim;

class OutboxDispatcher {
	/**
	 * @var array<string,array{method:string,path:string}>
	 */
	private const TOPOLOGY_ROUTES = array(
		'cluster_merged' => array(
			'method' => 'POST',
			'path' => '/recognition/clusters/%s/merge',
		),
		'cluster_split' => array(
			'method' => 'POST',
			'path' => '/recognition/clusters/%s/split',
		),
		'identity_reassigned' => array(
			'method' => 'POST',
			'path' => '/recognition/clusters/reassign',
		),
		'cluster_created_for_identity' => array(
			'method' => 'POST',
			'path' => '/recognition/clusters/create-for-identity',
		),
	);

	private SnapshotClientTransport $transport;

	public function __construct( ?SnapshotClientTransport $transport = null ) {
		$this->transport = $transport ?? new SnapshotClientTransport();
	}

	/**
	 * Dispatch a single outbox operation to the remote curation endpoint.
	 *
	 * @param array<string,mixed> $operation
	 * @return array<string,mixed>
	 */
	public function dispatch( array $operation ): array {
		$operation_type = $this->normalize_text( $operation['operation_type'] ?? '', '' );
		if ( isset( self::TOPOLOGY_ROUTES[ $operation_type ] ) ) {
			return $this->dispatch_topology_operation( $operation );
		}

		$results = $this->dispatch_batch( array( $operation ) );
		return $results[0] ?? array(
			'status' => 'failed',
			'error_code' => 'unexpected_response',
			'error_message' => 'Remote curation replay did not return a result.',
			'retryable' => true,
		);
	}

	/**
	 * Dispatch one or more outbox operations to the remote curation endpoint.
	 *
	 * @param array<int,array<string,mixed>> $operations
	 * @return array<int,array<string,mixed>>
	 */
	public function dispatch_batch( array $operations ): array {
		if ( empty( $operations ) ) {
			return array();
		}

		$results = array_fill( 0, count( $operations ), array() );
		$state_indexes = array();
		$state_operations = array();

		foreach ( $operations as $index => $operation ) {
			$operation_type = $this->normalize_text( $operation['operation_type'] ?? '', '' );
			if ( isset( self::TOPOLOGY_ROUTES[ $operation_type ] ) ) {
				$results[ $index ] = $this->dispatch_topology_operation( $operation );
				continue;
			}

			$state_indexes[] = $index;
			$state_operations[] = $operation;
		}

		if ( empty( $state_operations ) ) {
			return $results;
		}

		$state_results = $this->dispatch_state_batch( $state_operations );
		foreach ( $state_indexes as $offset => $index ) {
			$results[ $index ] = $state_results[ $offset ] ?? array(
				'status' => 'failed',
				'error_code' => 'unexpected_response',
				'error_message' => 'Remote curation replay did not return a result for this operation.',
				'retryable' => true,
			);
		}

		return $results;
	}

	/**
	 * @param array<int,array<string,mixed>> $operations
	 * @return array<int,array<string,mixed>>
	 */
	private function dispatch_state_batch( array $operations ): array {
		$bodies = array();
		foreach ( $operations as $index => $operation ) {
			$body = $this->build_request_body( $operation );
			if ( ! is_array( $body ) ) {
				$bodies[ $index ] = null;
				continue;
			}

			$bodies[ $index ] = $body;
		}

		if ( in_array( null, $bodies, true ) ) {
			return array_map(
				static function ( $body ): array {
					if ( is_array( $body ) ) {
						return array();
					}

					return array(
						'status' => 'failed',
						'error_code' => 'invalid_payload',
						'error_message' => 'Outbox operation payload is missing required fields.',
						'retryable' => false,
					);
				},
				$bodies
			);
		}

		$request_body = 1 === count( $bodies )
			? $bodies[0]
			: array( 'operations' => array_values( $bodies ) );

		$response = $this->transport->request( 'POST', $this->resolve_endpoint_path(), $request_body, array() );

		if ( is_wp_error( $response ) ) {
			return array_fill(
				0,
				count( $operations ),
				array(
					'status' => 'failed',
					'error_code' => $this->normalize_text( $response->get_error_code(), 'transport_error' ),
					'error_message' => $this->normalize_text( $response->get_error_message(), 'Remote transport failed.' ),
					'retryable' => true,
				)
			);
		}

		if ( ! ( $response instanceof WP_REST_Response ) ) {
			return array_fill(
				0,
				count( $operations ),
				array(
					'status' => 'failed',
					'error_code' => 'unexpected_response',
					'error_message' => 'Remote transport returned an unexpected response type.',
					'retryable' => true,
				)
			);
		}

		if ( 1 === count( $bodies ) ) {
			return array( $this->normalize_single_response( $response ) );
		}

		return $this->normalize_batch_response( $response, count( $operations ) );
	}

	/**
	 * @return array<string,mixed>
	 */
	private function normalize_single_response( WP_REST_Response $response ): array {
		$status = $response->get_status();
		$data = $response->get_data();
		$data = is_array( $data ) ? $data : array();

		if ( $status >= 200 && $status < 300 ) {
			return array(
				'status' => 'acknowledged',
				'backend_version' => max( 0, (int) ( $data['backend_version'] ?? 0 ) ),
			);
		}

		if ( 409 === $status ) {
			$machine_payload = is_array( $data['machine_payload'] ?? null ) ? $data['machine_payload'] : array();

			return array(
				'status' => 'conflict',
				'conflict_code' => $this->normalize_text( $data['conflict_code'] ?? '', 'version_conflict' ),
				'backend_version' => max( 0, (int) ( $data['backend_version'] ?? 0 ) ),
				'machine_payload' => $machine_payload,
				'error_message' => $this->normalize_text( $data['message'] ?? '', 'Remote curation replay conflict.' ),
			);
		}

		$retryable = $status >= 500 || 408 === $status || 429 === $status;
		return array(
			'status' => 'failed',
			'error_code' => $this->normalize_text( $data['error_code'] ?? '', 'remote_error' ),
			'error_message' => $this->normalize_text( $data['message'] ?? '', 'Remote curation replay failed.' ),
			'retryable' => $retryable,
			'http_status' => $status,
		);
	}

	/**
	 * @return array<int,array<string,mixed>>
	 */
	private function normalize_batch_response( WP_REST_Response $response, int $expected_count ): array {
		$data = $response->get_data();
		$results = is_array( $data['results'] ?? null ) ? $data['results'] : array();
		if ( count( $results ) !== $expected_count ) {
			return array_fill(
				0,
				$expected_count,
				array(
					'status' => 'failed',
					'error_code' => 'unexpected_response',
					'error_message' => 'Remote curation replay returned an unexpected batch result count.',
					'retryable' => true,
				)
			);
		}

		return array_map(
			function ( $result ): array {
				if ( ! is_array( $result ) ) {
					return array(
						'status' => 'failed',
						'error_code' => 'unexpected_response',
						'error_message' => 'Remote curation replay returned an invalid batch result.',
						'retryable' => true,
					);
				}

				if ( 'conflict' === $this->normalize_text( $result['status'] ?? '', '' ) ) {
					return array(
						'status' => 'conflict',
						'conflict_code' => $this->normalize_text( $result['conflict_code'] ?? '', 'version_conflict' ),
						'backend_version' => max( 0, (int) ( $result['backend_version'] ?? 0 ) ),
						'machine_payload' => is_array( $result['machine_payload'] ?? null ) ? $result['machine_payload'] : array(),
						'error_message' => $this->normalize_text( $result['message'] ?? '', 'Remote curation replay conflict.' ),
					);
				}

				return array(
					'status' => 'acknowledged',
					'backend_version' => max( 0, (int) ( $result['backend_version'] ?? 0 ) ),
				);
			},
			$results
		);
	}

	private function resolve_endpoint_path(): string {
		$path = apply_filters( 'acx_curation_sync_endpoint_path', '/roster/curation/sync' );
		$normalized_path = is_string( $path ) ? trim( $path ) : '';
		if ( '' === $normalized_path ) {
			$normalized_path = '/roster/curation/sync';
		}

		return '/' . ltrim( $normalized_path, '/' );
	}

	/**
	 * @param array<string,mixed> $operation
	 * @return array<string,mixed>|null
	 */
	private function build_request_body( array $operation ): ?array {
		$operation_type = $this->normalize_text( $operation['operation_type'] ?? '', '' );
		$entity_type = $this->normalize_text( $operation['entity_type'] ?? '', '' );
		$entity_key = $this->normalize_text( $operation['entity_key'] ?? '', '' );
		$idempotency_key = $this->normalize_text( $operation['idempotency_key'] ?? '', '' );

		if ( '' === $operation_type || '' === $entity_type || '' === $entity_key || '' === $idempotency_key ) {
			return null;
		}

		$payload = is_array( $operation['payload'] ?? null ) ? $operation['payload'] : array();

		if ( isset( self::TOPOLOGY_ROUTES[ $operation_type ] ) ) {
			return $this->build_topology_request_body( $operation_type, $payload, $idempotency_key );
		}

		return array(
			'operation_type' => $operation_type,
			'entity_type' => $entity_type,
			'entity_key' => $entity_key,
			'idempotency_key' => $idempotency_key,
			'expected_base_version' => max( 0, (int) ( $operation['expected_base_version'] ?? 0 ) ),
			'local_revision' => max( 0, (int) ( $operation['local_revision'] ?? 0 ) ),
			'payload' => $payload,
		);
	}

	/**
	 * @param array<string,mixed> $operation
	 * @return array<string,mixed>
	 */
	private function dispatch_topology_operation( array $operation ): array {
		$operation_type = $this->normalize_text( $operation['operation_type'] ?? '', '' );
		$route = self::TOPOLOGY_ROUTES[ $operation_type ] ?? null;
		$body = $this->build_request_body( $operation );
		if ( ! is_array( $route ) || ! is_array( $body ) ) {
			return array(
				'status' => 'failed',
				'error_code' => 'invalid_payload',
				'error_message' => 'Outbox operation payload is missing required fields.',
				'retryable' => false,
			);
		}

		$path = $route['path'];
		if ( false !== strpos( $path, '%s' ) ) {
			$entity_key = $this->normalize_text( $operation['entity_key'] ?? '', '' );
			if ( '' === $entity_key ) {
				return array(
					'status' => 'failed',
					'error_code' => 'invalid_payload',
					'error_message' => 'Outbox topology operation is missing an entity key.',
					'retryable' => false,
				);
			}
			$path = sprintf( $path, rawurlencode( $entity_key ) );
		}

		$response = $this->transport->request( $route['method'], $path, $body, array() );
		if ( is_wp_error( $response ) ) {
			return array(
				'status' => 'failed',
				'error_code' => $this->normalize_text( $response->get_error_code(), 'transport_error' ),
				'error_message' => $this->normalize_text( $response->get_error_message(), 'Remote transport failed.' ),
				'retryable' => true,
			);
		}

		if ( ! ( $response instanceof WP_REST_Response ) ) {
			return array(
				'status' => 'failed',
				'error_code' => 'unexpected_response',
				'error_message' => 'Remote transport returned an unexpected response type.',
				'retryable' => true,
			);
		}

		return $this->normalize_single_response( $response );
	}

	/**
	 * @param array<string,mixed> $payload
	 * @return array<string,mixed>|null
	 */
	private function build_topology_request_body( string $operation_type, array $payload, string $idempotency_key ): ?array {
		$tenant_id = $this->transport->tenant_id();
		if ( '' === trim( $tenant_id ) ) {
			return null;
		}

		$body = $payload;
		$body['tenant_id'] = $tenant_id;
		$body['idempotency_key'] = $idempotency_key;

		if ( 'cluster_merged' === $operation_type ) {
			$target_cluster_id = $this->normalize_text( $payload['target_cluster_id'] ?? '', '' );
			if ( '' === $target_cluster_id ) {
				return null;
			}
			$body['target_cluster_id'] = $target_cluster_id;
		}

		if ( 'identity_reassigned' === $operation_type ) {
			$identity_id = $this->normalize_text( $payload['identity_id'] ?? '', '' );
			if ( '' === $identity_id ) {
				return null;
			}
			$body['identity_id'] = $identity_id;
		}

		if ( 'cluster_created_for_identity' === $operation_type ) {
			$identity_id = $this->normalize_text( $payload['identity_id'] ?? '', '' );
			$label = $this->normalize_text( $payload['label'] ?? '', '' );
			if ( '' === $identity_id || '' === $label ) {
				return null;
			}
			$body['identity_id'] = $identity_id;
			$body['label'] = $label;
			$desired_cluster_id = $this->normalize_text( $payload['desired_cluster_id'] ?? '', '' );
			if ( '' !== $desired_cluster_id ) {
				$body['desired_cluster_id'] = $desired_cluster_id;
			}
		}

		return $body;
	}

	private function normalize_text( mixed $value, string $default ): string {
		if ( ! is_string( $value ) ) {
			return $default;
		}

		$normalized = trim( $value );

		return '' !== $normalized ? $normalized : $default;
	}
}
