<?php

declare(strict_types=1);

namespace AltContext\Support;

use function esc_url_raw;
use function file_get_contents;
use function function_exists;
use function is_array;
use function is_dir;
use function is_readable;
use function is_string;
use function json_decode;
use function json_last_error;
use function ltrim;
use function plugins_url;

/**
 * Resolves Vite 5 build-manifest entry JS and recursively imported CSS.
 */
final class ViteManifest {
	private string $manifestPath;

	/** @var callable(string):string */
	private $urlBuilder;

	/** @var array<string, mixed>|null */
	private ?array $manifest = null;

	private bool $loaded = false;

	/**
	 * @param callable(string):string $urlBuilder
	 */
	public function __construct( string $manifestPath, callable $urlBuilder ) {
		$this->manifestPath = $manifestPath;
		$this->urlBuilder   = $urlBuilder;
	}

	public static function from_plugin(): self {
		return new self(
			self::plugin_manifest_path(),
			static function ( string $relative ): string {
				$asset_path = 'public/assets/dist/' . ltrim( $relative, '/' );
				$url        = plugins_url( $asset_path, 'alt-context/alt-context.php' );

				return function_exists( 'esc_url_raw' ) ? esc_url_raw( $url ) : $url;
			}
		);
	}

	public static function plugin_manifest_path(): string {
		$primary  = ACX_PLUGIN_DIR . 'public/assets/dist/.vite/manifest.json';
		$fallback = ACX_PLUGIN_DIR . 'public/assets/dist/manifest.json';

		return is_readable( $primary ) ? $primary : $fallback;
	}

	public function manifest_path(): string {
		return $this->manifestPath;
	}

	/**
	 * @return array{js: string, css: list<string>}|null
	 */
	public function entry_assets( string $entryPoint ): ?array {
		$entry = $this->chunk( $entryPoint );
		if ( null === $entry ) {
			return null;
		}

		$file = $entry['file'] ?? null;
		if ( ! is_string( $file ) || '' === $file ) {
			return null;
		}

		$visited  = array();
		$seen_css = array();
		$css      = $this->collect_css( $entryPoint, $visited, $seen_css );
		$build    = $this->urlBuilder;

		$css_urls = array();
		foreach ( $css as $css_file ) {
			$css_urls[] = (string) $build( $css_file );
		}

		return array(
			'js'  => (string) $build( $file ),
			'css' => $css_urls,
		);
	}

	/**
	 * Raw Vite chunk for $entryPoint, or null when the manifest/entry is unusable.
	 *
	 * @return array<string, mixed>|null
	 */
	public function get_entry( string $entryPoint ): ?array {
		return $this->chunk( $entryPoint );
	}

	/**
	 * @return array<string, mixed>|null
	 */
	private function chunk( string $key ): ?array {
		$manifest = $this->load_manifest();
		if ( null === $manifest ) {
			return null;
		}

		$entry = $manifest[ $key ] ?? null;

		return is_array( $entry ) ? $entry : null;
	}

	/**
	 * @return array<string, mixed>|null
	 */
	private function load_manifest(): ?array {
		if ( $this->loaded ) {
			return $this->manifest;
		}

		$this->loaded = true;

		if ( ! is_readable( $this->manifestPath ) || is_dir( $this->manifestPath ) ) {
			$this->manifest = null;
			return null;
		}

		$contents = file_get_contents( $this->manifestPath );
		if ( false === $contents ) {
			$this->manifest = null;
			return null;
		}

		$decoded = json_decode( $contents, true );
		if ( ! is_array( $decoded ) || json_last_error() !== JSON_ERROR_NONE ) {
			$this->manifest = null;
			return null;
		}

		$this->manifest = $decoded;
		return $this->manifest;
	}

	/**
	 * @param array<string, true> $visited
	 * @param array<string, true> $seen_css
	 * @return list<string>
	 */
	private function collect_css( string $key, array &$visited, array &$seen_css ): array {
		if ( isset( $visited[ $key ] ) ) {
			return array();
		}
		$visited[ $key ] = true;

		$chunk = $this->chunk( $key );
		if ( null === $chunk ) {
			return array();
		}

		$css = array();
		if ( isset( $chunk['imports'] ) && is_array( $chunk['imports'] ) ) {
			foreach ( $chunk['imports'] as $import ) {
				if ( ! is_string( $import ) || '' === $import ) {
					continue;
				}
				foreach ( $this->collect_css( $import, $visited, $seen_css ) as $imported ) {
					$css[] = $imported;
				}
			}
		}

		// Post-order: imported CSS first so this chunk can override shared rules.
		if ( isset( $chunk['css'] ) && is_array( $chunk['css'] ) ) {
			foreach ( $chunk['css'] as $file ) {
				if ( ! is_string( $file ) || '' === $file || isset( $seen_css[ $file ] ) ) {
					continue;
				}
				$seen_css[ $file ] = true;
				$css[]             = $file;
			}
		}

		return $css;
	}
}
