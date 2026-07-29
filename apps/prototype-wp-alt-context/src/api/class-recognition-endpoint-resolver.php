<?php

declare(strict_types=1);

namespace AltContext\Api;

use function apply_filters;
use function defined;
use function get_option;
use function in_array;
use function parse_url;
use function str_ends_with;
use function str_starts_with;
use function strtolower;
use function substr;
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

		// Option tier retired (RECOG-1): local is a dev-only code hatch reachable via the
		// ACX_RECOGNITION_LOCAL_URL constant or the acx_recognition_local_url filter only.
		return array( 'value' => self::DEFAULT_LOCAL_URL, 'source' => 'default' );
	}

	/**
	 * @return array{value: string, source: string}
	 */
	public function resolve_recognition_source_source(): array {
		$constant = trim( $this->get_constant_value( 'ACX_RECOGNITION_SOURCE' ) );
		if ( $this->is_valid_recognition_source( $constant ) ) {
			return array( 'value' => $constant, 'source' => 'constant' );
		}

		$filter = trim( (string) apply_filters( 'acx_recognition_source', '' ) );
		if ( $this->is_valid_recognition_source( $filter ) ) {
			return array( 'value' => $filter, 'source' => 'filter' );
		}

		// Option tier retired (RECOG-1): the product no longer writes acx_recognition_source.
		// Local remains a dev-only hatch via the ACX_RECOGNITION_SOURCE constant / filter above.
		return array( 'value' => 'service', 'source' => 'default' );
	}

	public function get_recognition_source(): string {
		return $this->resolve_recognition_source_source()['value'];
	}

	public function get_effective_base_url(): string {
		if ( 'local' === $this->get_recognition_source() ) {
			return $this->resolve_local_url_source()['value'];
		}

		return $this->resolve_service_url_source()['value'];
	}

	/**
	 * Settings GET snapshot. RECOG-1 retired the product-facing local target, so
	 * `local_url`/`local_url_source` are no longer emitted; `recognition_source`
	 * and `recognition_source_source` remain as read-only dev-hatch diagnostics.
	 * When the dev hatch is active (constant/filter source=local), the effective
	 * target still resolves to the local URL chain internally.
	 *
	 * @return array{
	 *   effective_target_url: string,
	 *   effective_target_mode: string,
	 *   service_url: string,
	 *   service_url_source: string,
	 *   recognition_source: string,
	 *   recognition_source_source: string
	 * }
	 */
	public function resolve_settings_snapshot(): array {
		$service_url  = $this->resolve_service_url_source();
		$source       = $this->resolve_recognition_source_source();
		$effective      = 'local' === $source['value'] ? $this->resolve_local_url_source()['value'] : $service_url['value'];
		$effective_mode = $source['value'];

		return array(
			'effective_target_url'        => $effective,
			'effective_target_mode'       => $effective_mode,
			'service_url'                 => $service_url['value'],
			'service_url_source'          => $service_url['source'],
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

	/**
	 * BR-131: require https for remote recognition endpoints. Permit http only
	 * for loopback hosts used by the local dev hatch (DEFAULT_LOCAL_URL /
	 * ACX_RECOGNITION_LOCAL_URL → localhost:8000) so LocalWP and the local
	 * description-service backend keep working without allowing
	 * http://attacker.invalid.
	 */
	private function is_valid_base_url( string $url ): bool {
		$parts = parse_url( $url );
		if ( false === $parts || ! is_array( $parts ) ) {
			return false;
		}

		$scheme = strtolower( (string) ( $parts['scheme'] ?? '' ) );
		$host   = strtolower( (string) ( $parts['host'] ?? '' ) );
		if ( '' === $host ) {
			return false;
		}

		if ( 'https' === $scheme ) {
			return true;
		}

		// Explicit loopback development path — matches the existing local hatch
		// convention (http://localhost:8000), not a new constant.
		return 'http' === $scheme && $this->is_loopback_host( $host );
	}

	private function is_loopback_host( string $host ): bool {
		if ( str_starts_with( $host, '[' ) && str_ends_with( $host, ']' ) ) {
			$host = substr( $host, 1, -1 );
		}

		return in_array( $host, array( 'localhost', '127.0.0.1', '::1' ), true );
	}

	private function is_valid_recognition_source( string $source ): bool {
		return in_array( $source, array( 'service', 'local' ), true );
	}
}
