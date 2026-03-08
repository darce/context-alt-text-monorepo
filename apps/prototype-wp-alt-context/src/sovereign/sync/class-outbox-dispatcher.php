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
use function trim;

class OutboxDispatcher {
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

	private function normalize_text( mixed $value, string $default ): string {
		if ( ! is_string( $value ) ) {
			return $default;
		}

		$normalized = trim( $value );

		return '' !== $normalized ? $normalized : $default;
	}
}
