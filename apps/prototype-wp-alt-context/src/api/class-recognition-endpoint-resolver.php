<?php

declare(strict_types=1);

namespace AltContext\Api;

use function apply_filters;
use function defined;
use function get_option;
use function in_array;
use function parse_url;
use function strtolower;
use function trim;

/**
 * Canonical recognition endpoint resolution for proxy routing and settings UX.
 */
final class RecognitionEndpointResolver {
	public const DEFAULT_LOCAL_URL = 'http://localhost:8000';

	/**
	 * @return array{value: string, source: string}
	 */
	public function resolve_service_url_source(): array {
		$constant = $this->get_constant_value( 'ACX_RECOGNITION_URL' );
		if ( '' !== $constant && $this->is_valid_base_url( $constant ) ) {
			return array( 'value' => $constant, 'source' => 'constant' );
		}

		$filter = trim( (string) apply_filters( 'acx_recognition_base_url', '' ) );
		if ( '' !== $filter && $this->is_valid_base_url( $filter ) ) {
			return array( 'value' => $filter, 'source' => 'filter' );
		}

		$option = trim( (string) get_option( 'acx_recognition_url', '' ) );
		if ( '' !== $option && $this->is_valid_base_url( $option ) ) {
			return array( 'value' => $option, 'source' => 'option' );
		}

		return array( 'value' => '', 'source' => 'default' );
	}

	/**
	 * @return array{value: string, source: string}
	 */
	public function resolve_local_url_source(): array {
		$constant = $this->get_constant_value( 'ACX_RECOGNITION_LOCAL_URL' );
		if ( '' !== $constant && $this->is_valid_base_url( $constant ) ) {
			return array( 'value' => $constant, 'source' => 'constant' );
		}

		$filter = trim( (string) apply_filters( 'acx_recognition_local_url', '' ) );
		if ( '' !== $filter && $this->is_valid_base_url( $filter ) ) {
			return array( 'value' => $filter, 'source' => 'filter' );
		}

		$option = trim( (string) get_option( 'acx_recognition_local_url', '' ) );
		if ( '' !== $option && $this->is_valid_base_url( $option ) ) {
			return array( 'value' => $option, 'source' => 'option' );
		}

		return array( 'value' => self::DEFAULT_LOCAL_URL, 'source' => 'default' );
	}

	/**
	 * @param array{value: string, source: string} $service_url_resolution
	 * @return array{value: string, source: string}
	 */
	public function resolve_recognition_source_source( array $service_url_resolution ): array {
		$constant = trim( $this->get_constant_value( 'ACX_RECOGNITION_SOURCE' ) );
		if ( $this->is_valid_recognition_source( $constant ) ) {
			return array( 'value' => $constant, 'source' => 'constant' );
		}

		$filter = trim( (string) apply_filters( 'acx_recognition_source', '' ) );
		if ( $this->is_valid_recognition_source( $filter ) ) {
			return array( 'value' => $filter, 'source' => 'filter' );
		}

		$option = trim( (string) get_option( 'acx_recognition_source', '' ) );
		if ( $this->is_valid_recognition_source( $option ) ) {
			return array( 'value' => $option, 'source' => 'option' );
		}

		return array( 'value' => 'local', 'source' => 'default' );
	}

	public function get_recognition_source(): string {
		$service_url = $this->resolve_service_url_source();
		return $this->resolve_recognition_source_source( $service_url )['value'];
	}

	public function get_effective_base_url(): string {
		if ( 'local' === $this->get_recognition_source() ) {
			return $this->resolve_local_url_source()['value'];
		}

		return $this->resolve_service_url_source()['value'];
	}

	/**
	 * @return array{
	 *   effective_target_url: string,
	 *   effective_target_mode: string,
	 *   service_url: string,
	 *   service_url_source: string,
	 *   local_url: string,
	 *   local_url_source: string,
	 *   recognition_source: string,
	 *   recognition_source_source: string
	 * }
	 */
	public function resolve_settings_snapshot(): array {
		$service_url  = $this->resolve_service_url_source();
		$local_url    = $this->resolve_local_url_source();
		$source       = $this->resolve_recognition_source_source( $service_url );
		$effective      = 'local' === $source['value'] ? $local_url['value'] : $service_url['value'];
		$effective_mode = $source['value'];

		return array(
			'effective_target_url'        => $effective,
			'effective_target_mode'       => $effective_mode,
			'service_url'                 => $service_url['value'],
			'service_url_source'          => $service_url['source'],
			'local_url'                   => $local_url['value'],
			'local_url_source'            => $local_url['source'],
			'recognition_source'          => $source['value'],
			'recognition_source_source'   => $source['source'],
		);
	}

	private function get_constant_value( string $name ): string {
		if ( defined( $name ) && is_string( constant( $name ) ) ) {
			return trim( constant( $name ) );
		}

		return '';
	}

	private function is_valid_base_url( string $url ): bool {
		$parts = parse_url( $url );
		if ( false === $parts || ! is_array( $parts ) ) {
			return false;
		}

		$scheme = strtolower( (string) ( $parts['scheme'] ?? '' ) );
		$host   = (string) ( $parts['host'] ?? '' );

		return in_array( $scheme, array( 'http', 'https' ), true ) && '' !== $host;
	}

	private function is_valid_recognition_source( string $source ): bool {
		return in_array( $source, array( 'service', 'local' ), true );
	}
}
