<?php

declare(strict_types=1);

namespace AltContext\Api;

use function apply_filters;
use function strtolower;
use function strtoupper;
use function trim;

final class RecognitionProxyPolicy {
	/**
	 * @return array{timeout_seconds:int,max_retries:int,base_delay_ms:int,circuit_enabled:bool}
	 */
	public function resolve( string $method, string $request_class ): array {
		$normalized_class = trim( strtolower( $request_class ) );
		if ( 'auto' === $normalized_class ) {
			$normalized_class = 'GET' === strtoupper( $method ) ? 'ui_read' : 'mutation';
		}

		if ( 'background_sync' === $normalized_class ) {
			return array(
				'timeout_seconds' => (int) apply_filters( 'acx_proxy_timeout_background_sync_seconds', 30 ),
				'max_retries' => (int) apply_filters( 'acx_proxy_max_retries_background_sync', 3 ),
				'base_delay_ms' => (int) apply_filters( 'acx_proxy_backoff_base_ms_background_sync', 500 ),
				'circuit_enabled' => false,
			);
		}

		if ( 'ui_read' === $normalized_class ) {
			return array(
				'timeout_seconds' => (int) apply_filters( 'acx_proxy_timeout_ui_read_seconds', 2 ),
				'max_retries' => (int) apply_filters( 'acx_proxy_max_retries_ui_read', 1 ),
				'base_delay_ms' => (int) apply_filters( 'acx_proxy_backoff_base_ms_ui_read', 0 ),
				'circuit_enabled' => true,
			);
		}

		if ( 'post_scan_read' === $normalized_class ) {
			return array(
				'timeout_seconds' => (int) apply_filters( 'acx_proxy_timeout_post_scan_read_seconds', 10 ),
				'max_retries' => (int) apply_filters( 'acx_proxy_max_retries_post_scan_read', 1 ),
				'base_delay_ms' => (int) apply_filters( 'acx_proxy_backoff_base_ms_post_scan_read', 0 ),
				'circuit_enabled' => false,
			);
		}

		return array(
			'timeout_seconds' => (int) apply_filters( 'acx_proxy_timeout_mutation_seconds', 60 ),
			'max_retries' => (int) apply_filters( 'acx_proxy_max_retries_mutation', 3 ),
			'base_delay_ms' => (int) apply_filters( 'acx_proxy_backoff_base_ms_mutation', 500 ),
			'circuit_enabled' => false,
		);
	}
}
