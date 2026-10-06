<?php
/**
 * Credentialed recognition egress transport.
 *
 * Single chooser for loopback vs safe remote HTTP, with a hard never-follow-
 * redirects policy. Callers must not re-implement this split: forgetting
 * redirection => 0 at a call site walks X-API-Key / X-Tenant-ID onto any
 * public Location a compromised recognition host advertises (BR-137).
 *
 * @package AltContext\Support
 */

declare(strict_types=1);

namespace AltContext\Support;

require_once __DIR__ . '/class-loopback-host.php';

use Closure;
use WP_Error;

use function parse_url;
use function strtolower;
use function wp_remote_get;
use function wp_remote_request;
use function wp_safe_remote_get;
use function wp_safe_remote_request;

/**
 * Shared HTTP transport for credentialed recognition API calls.
 */
final class RecognitionTransport {
	private const ERROR_EGRESS_DENIED       = 'acx_egress_denied';
	private const ERROR_PIN_UNAVAILABLE     = 'acx_egress_pin_unavailable';
	private const PIN_UNAVAILABLE_MESSAGE   = 'Recognition egress pin is unavailable because the WordPress HTTP transport cannot use cURL.';

	/**
	 * Optional DNS resolver seam for deterministic transport tests.
	 *
	 * @var Closure(string):array<string>|null
	 */
	private static ?Closure $resolver = null;
	private static ?Closure $curl_capability_probe = null;
	private static ?Closure $curl_resolve_applier = null;
	private static ?Closure $http_api_curl_runner = null;

	/**
	 * Override DNS resolution. Passing null restores the system resolver.
	 *
	 * @param callable(string):array<string>|null $resolver
	 */
	public static function set_resolver( ?callable $resolver ): void {
		self::$resolver = null === $resolver ? null : Closure::fromCallable( $resolver );
	}

	/**
	 * Override the Requests cURL capability check for deterministic tests.
	 *
	 * @param callable(string):bool|null $probe
	 */
	public static function set_curl_capability_probe( ?callable $probe ): void {
		self::$curl_capability_probe = null === $probe ? null : Closure::fromCallable( $probe );
	}

	/**
	 * Override CURLOPT_RESOLVE application for deterministic transport tests.
	 *
	 * @param callable(mixed,list<string>):void|null $applier
	 */
	public static function set_curl_resolve_applier( ?callable $applier ): void {
		self::$curl_resolve_applier = null === $applier ? null : Closure::fromCallable( $applier );
	}

	/**
	 * Emulate WordPress firing http_api_curl while its HTTP request is active.
	 *
	 * @param callable(callable,callable,string):mixed|null $runner
	 */
	public static function set_http_api_curl_runner( ?callable $runner ): void {
		self::$http_api_curl_runner = null === $runner ? null : Closure::fromCallable( $runner );
	}

	/**
	 * Whether an IP address is publicly routable.
	 */
	public static function is_global_address( string $ip ): bool {
		if ( false === filter_var( $ip, FILTER_VALIDATE_IP ) ) {
			return false;
		}

		$packed = @inet_pton( $ip );
		if ( false === $packed ) {
			return false;
		}

		// Treat IPv4-mapped IPv6 addresses according to their embedded IPv4 address.
		if ( 16 === strlen( $packed ) && str_repeat( "\0", 10 ) === substr( $packed, 0, 10 ) && "\xff\xff" === substr( $packed, 10, 2 ) ) {
			$mapped_ipv4 = inet_ntop( substr( $packed, 12 ) );
			return is_string( $mapped_ipv4 ) && self::is_global_address( $mapped_ipv4 );
		}

		if ( false === filter_var( $ip, FILTER_VALIDATE_IP, FILTER_FLAG_NO_PRIV_RANGE | FILTER_FLAG_NO_RES_RANGE ) ) {
			return false;
		}

		$blocked_ranges = 4 === strlen( $packed )
			? [
				[ '100.64.0.0', 10 ],
				[ '169.254.0.0', 16 ],
				[ '0.0.0.0', 8 ],
				[ '224.0.0.0', 4 ],
				[ '192.0.0.0', 24 ],
				[ '198.18.0.0', 15 ],
			]
			: [
				[ 'fc00::', 7 ],
				[ 'fe80::', 10 ],
				[ 'ff00::', 8 ],
				[ '::', 128 ],
				[ '64:ff9b::', 96 ],
				[ '64:ff9b:1::', 48 ],
				[ '2002::', 16 ],
				[ '2001::', 32 ],
				[ '::', 96 ],
				[ '::ffff:0:0:0', 96 ],
				[ '100::', 64 ],
				[ 'fec0::', 10 ],
			];

		foreach ( $blocked_ranges as [ $network, $prefix ] ) {
			if ( self::is_in_subnet( $packed, $network, $prefix ) ) {
				return false;
			}
		}

		return true;
	}

	/**
	 * Build a CURLOPT_RESOLVE entry for an address that has already passed validation.
	 */
	public static function resolve_pin( string $host, int $port, string $ip ): string {
		$host = trim( $host, '[]' );
		$ip   = trim( $ip, '[]' );

		if ( false !== filter_var( $host, FILTER_VALIDATE_IP, FILTER_FLAG_IPV6 ) ) {
			$host = '[' . $host . ']';
		}
		if ( false !== filter_var( $ip, FILTER_VALIDATE_IP, FILTER_FLAG_IPV6 ) ) {
			$ip = '[' . $ip . ']';
		}

		return $host . ':' . $port . ':' . $ip;
	}

	/**
	 * Credentialed GET. Forces redirection => 0; non-loopback uses the safe
	 * transport after validating and pinning the resolved public address.
	 *
	 * @param array<string,mixed> $args
	 * @return array<string,mixed>|WP_Error
	 */
	public static function get( string $url, array $args ) {
		$args['redirection'] = 0;
		$host                = strtolower( (string) ( parse_url( $url, PHP_URL_HOST ) ?? '' ) );
		if ( LoopbackHost::is_loopback( $host ) ) {
			return wp_remote_get( $url, $args );
		}

		$addresses = self::resolve_host( $host );
		if ( empty( $addresses ) ) {
			return self::egress_denied();
		}

		foreach ( $addresses as $address ) {
			if ( ! is_string( $address ) || ! self::is_global_address( $address ) ) {
				return self::egress_denied();
			}
		}

		return self::with_pinned_address( $url, $host, $addresses[0], static function () use ( $url, $args ) {
			return wp_safe_remote_get( $url, $args );
		} );
	}

	/**
	 * Credentialed request (any method). Same loopback/safe split and
	 * never-follow-redirects policy as get().
	 *
	 * @param array<string,mixed> $args
	 * @return array<string,mixed>|WP_Error
	 */
	public static function request( string $url, array $args ) {
		$args['redirection'] = 0;
		$host                = strtolower( (string) ( parse_url( $url, PHP_URL_HOST ) ?? '' ) );
		if ( LoopbackHost::is_loopback( $host ) ) {
			return wp_remote_request( $url, $args );
		}

		$addresses = self::resolve_host( $host );
		if ( empty( $addresses ) ) {
			return self::egress_denied();
		}

		foreach ( $addresses as $address ) {
			if ( ! is_string( $address ) || ! self::is_global_address( $address ) ) {
				return self::egress_denied();
			}
		}

		return self::with_pinned_address( $url, $host, $addresses[0], static function () use ( $url, $args ) {
			return wp_safe_remote_request( $url, $args );
		} );
	}

	/**
	 * Resolve a host through the test seam or the system DNS resolver.
	 *
	 * @return list<string>
	 */
	private static function resolve_host( string $host ): array {
		if ( null !== self::$resolver ) {
			return ( self::$resolver )( $host );
		}

		$ip = trim( $host, '[]' );
		if ( false !== filter_var( $ip, FILTER_VALIDATE_IP ) ) {
			return [ $ip ];
		}

		$addresses = [];
		$ipv4      = @gethostbynamel( $host );
		if ( is_array( $ipv4 ) ) {
			$addresses = array_merge( $addresses, $ipv4 );
		}

		$records = @dns_get_record( $host, DNS_AAAA );
		if ( is_array( $records ) ) {
			foreach ( $records as $record ) {
				if ( isset( $record['ipv6'] ) && is_string( $record['ipv6'] ) ) {
					$addresses[] = $record['ipv6'];
				}
			}
		}

		return array_values( array_unique( $addresses ) );
	}

	/**
	 * Attach a request-scoped cURL DNS pin around the WordPress safe HTTP call.
	 *
	 * @param callable():array<string,mixed>|WP_Error $request
	 * @return array<string,mixed>|WP_Error
	 */
	private static function with_pinned_address( string $url, string $host, string $ip, callable $request ) {
		$parsed_url = parse_url( $url );
		$scheme     = strtolower( (string) ( $parsed_url['scheme'] ?? '' ) );
		if ( ! self::curl_transport_available( $scheme ) ) {
			return self::pin_unavailable();
		}

		$port       = isset( $parsed_url['port'] ) ? (int) $parsed_url['port'] : self::default_port( $scheme );
		$pin        = self::resolve_pin( $host, $port, $ip );
		$pin_host   = self::normalize_host( $host );
		$pin_port   = $port;
		$callback   = static function ( &$handle, $parsed_args, $request_url ) use ( $pin, $pin_host, $pin_port ): void {
			if ( ! is_string( $request_url ) ) {
				return;
			}

			$parsed = parse_url( $request_url );
			if ( ! is_array( $parsed ) ) {
				return;
			}

			$callback_host = self::normalize_host( (string) ( $parsed['host'] ?? '' ) );
			$scheme        = strtolower( (string) ( $parsed['scheme'] ?? '' ) );
			$callback_port = isset( $parsed['port'] ) ? (int) $parsed['port'] : self::default_port( $scheme );
			if ( $callback_host !== $pin_host || $callback_port !== $pin_port ) {
				return;
			}

			self::apply_curl_resolve_option( $handle, $pin );
		};

		add_action( 'http_api_curl', $callback, 10, 3 );
		try {
			if ( null !== self::$http_api_curl_runner ) {
				return ( self::$http_api_curl_runner )( $callback, $request, $url );
			}

			return $request();
		} finally {
			remove_action( 'http_api_curl', $callback, 10 );
		}
	}

	/**
	 * Match the WordPress Requests cURL transport's capability selection.
	 */
	private static function curl_transport_available( string $scheme ): bool {
		if ( null !== self::$curl_capability_probe ) {
			return ( self::$curl_capability_probe )( $scheme );
		}

		if ( ! function_exists( 'curl_init' ) || ! is_callable( 'curl_exec' ) ) {
			return false;
		}

		if ( 'https' !== $scheme ) {
			return true;
		}

		if ( ! function_exists( 'curl_version' ) || ! defined( 'CURL_VERSION_SSL' ) ) {
			return false;
		}

		$version = curl_version();
		return is_array( $version )
			&& isset( $version['features'] )
			&& 0 !== ( ( (int) $version['features'] ) & CURL_VERSION_SSL );
	}

	/**
	 * Apply the pin through the real cURL API or the test seam.
	 *
	 * @param mixed $handle
	 */
	private static function apply_curl_resolve_option( &$handle, string $pin ): void {
		if ( null !== self::$curl_resolve_applier ) {
			( self::$curl_resolve_applier )( $handle, [ $pin ] );
			return;
		}

		curl_setopt( $handle, CURLOPT_RESOLVE, [ $pin ] );
	}

	private static function default_port( string $scheme ): int {
		return 'https' === $scheme ? 443 : 80;
	}

	private static function normalize_host( string $host ): string {
		return strtolower( trim( $host, '[]' ) );
	}

	/**
	 * Compare a packed address with a CIDR network.
	 *
	 * @param string $packed_address inet_pton() result
	 */
	private static function is_in_subnet( string $packed_address, string $network, int $prefix ): bool {
		$packed_network = @inet_pton( $network );
		if ( false === $packed_network || strlen( $packed_network ) !== strlen( $packed_address ) ) {
			return false;
		}

		$whole_bytes = intdiv( $prefix, 8 );
		if ( substr( $packed_address, 0, $whole_bytes ) !== substr( $packed_network, 0, $whole_bytes ) ) {
			return false;
		}

		$remaining_bits = $prefix % 8;
		if ( 0 === $remaining_bits ) {
			return true;
		}

		$mask = ( 0xff << ( 8 - $remaining_bits ) ) & 0xff;
		return ( ord( $packed_address[ $whole_bytes ] ) & $mask ) === ( ord( $packed_network[ $whole_bytes ] ) & $mask );
	}

	private static function egress_denied(): WP_Error {
		return new WP_Error( self::ERROR_EGRESS_DENIED, 'Recognition host resolves to a non-public address.' );
	}

	private static function pin_unavailable(): WP_Error {
		return new WP_Error( self::ERROR_PIN_UNAVAILABLE, self::PIN_UNAVAILABLE_MESSAGE );
	}
}
