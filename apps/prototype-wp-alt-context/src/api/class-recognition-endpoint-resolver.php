<?php

declare(strict_types=1);

namespace AltContext\Api;

require_once __DIR__ . '/../support/class-loopback-host.php';

use AltContext\Support\LoopbackHost;

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
	 * BR-138: why a present service-URL value was discarded by is_valid_base_url.
	 * Single definition for the wire contract (sr-007) — mirror in settingsApi.ts.
	 */
	public const URL_REJECTION_REJECTED_SCHEME   = 'rejected_scheme';
	public const URL_REJECTION_NON_LOOPBACK_HTTP = 'non_loopback_http';
	public const URL_REJECTION_INVALID_URL       = 'invalid_url';

	/**
	 * @return array{
	 *   value: string,
	 *   source: string,
	 *   rejection_reason: string|null,
	 *   rejection_source: string|null,
	 *   rejection_value: string|null
	 * }
	 */
	public function resolve_service_url_source(): array {
		$rejection = null;

		$constant = $this->get_constant_value( 'ACX_RECOGNITION_URL' );
		if ( '' !== $constant ) {
			$reason = $this->base_url_rejection_reason( $constant );
			if ( null === $reason ) {
				return $this->accepted_service_url( $constant, 'constant' );
			}
			$rejection = array(
				'reason' => $reason,
				'source' => 'constant',
				'value'  => $constant,
			);
		}

		$filter = trim( (string) apply_filters( 'acx_recognition_base_url', '' ) );
		if ( '' !== $filter ) {
			$reason = $this->base_url_rejection_reason( $filter );
			if ( null === $reason ) {
				return $this->accepted_service_url( $filter, 'filter' );
			}
			if ( null === $rejection ) {
				$rejection = array(
					'reason' => $reason,
					'source' => 'filter',
					'value'  => $filter,
				);
			}
		}

		$option = trim( (string) get_option( 'acx_recognition_url', '' ) );
		if ( '' !== $option ) {
			$reason = $this->base_url_rejection_reason( $option );
			if ( null === $reason ) {
				return $this->accepted_service_url( $option, 'option' );
			}
			if ( null === $rejection ) {
				$rejection = array(
					'reason' => $reason,
					'source' => 'option',
					'value'  => $option,
				);
			}
		}

		if ( null !== $rejection ) {
			return array(
				'value'            => '',
				'source'           => 'default',
				'rejection_reason' => $rejection['reason'],
				'rejection_source' => $rejection['source'],
				'rejection_value'  => $rejection['value'],
			);
		}

		return array(
			'value'            => '',
			'source'           => 'default',
			'rejection_reason' => null,
			'rejection_source' => null,
			'rejection_value'  => null,
		);
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
	 *   service_url_rejection_reason: string|null,
	 *   service_url_rejection_source: string|null,
	 *   service_url_rejection_value: string|null,
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
			'effective_target_url'           => $effective,
			'effective_target_mode'          => $effective_mode,
			'service_url'                    => $service_url['value'],
			'service_url_source'             => $service_url['source'],
			'service_url_rejection_reason'   => $service_url['rejection_reason'],
			'service_url_rejection_source'   => $service_url['rejection_source'],
			'service_url_rejection_value'    => $service_url['rejection_value'],
			'recognition_source'             => $source['value'],
			'recognition_source_source'      => $source['source'],
		);
	}

	private function get_constant_value( string $name ): string {
		if ( defined( $name ) && is_string( constant( $name ) ) ) {
			return trim( constant( $name ) );
		}

		return '';
	}

	/**
	 * @return array{
	 *   value: string,
	 *   source: string,
	 *   rejection_reason: null,
	 *   rejection_source: null,
	 *   rejection_value: null
	 * }
	 */
	private function accepted_service_url( string $value, string $source ): array {
		return array(
			'value'            => $value,
			'source'           => $source,
			'rejection_reason' => null,
			'rejection_source' => null,
			'rejection_value'  => null,
		);
	}

	/**
	 * BR-131: require https for remote recognition endpoints. Permit http only
	 * for loopback hosts used by the local dev hatch (DEFAULT_LOCAL_URL /
	 * ACX_RECOGNITION_LOCAL_URL → localhost:8000) so LocalWP and the local
	 * description-service backend keep working without allowing
	 * http://attacker.invalid.
	 */
	private function is_valid_base_url( string $url ): bool {
		return null === $this->base_url_rejection_reason( $url );
	}

	/**
	 * Same acceptance rule as {@see is_valid_base_url}, with a structured reason
	 * when the value is discarded. Returns null when the URL is accepted.
	 * Reporting only — does not change which URLs resolve (BR-138).
	 */
	private function base_url_rejection_reason( string $url ): ?string {
		$parts = parse_url( $url );
		if ( false === $parts || ! is_array( $parts ) ) {
			return self::URL_REJECTION_INVALID_URL;
		}

		$scheme = strtolower( (string) ( $parts['scheme'] ?? '' ) );
		$host   = strtolower( (string) ( $parts['host'] ?? '' ) );
		if ( '' === $host ) {
			return self::URL_REJECTION_INVALID_URL;
		}

		if ( 'https' === $scheme ) {
			return null;
		}

		// Explicit loopback development path — matches the existing local hatch
		// convention (http://localhost:8000), not a new constant.
		if ( 'http' === $scheme ) {
			return LoopbackHost::is_loopback( $host )
				? null
				: self::URL_REJECTION_NON_LOOPBACK_HTTP;
		}

		return self::URL_REJECTION_REJECTED_SCHEME;
	}

	private function is_valid_recognition_source( string $source ): bool {
		return in_array( $source, array( 'service', 'local' ), true );
	}
}
