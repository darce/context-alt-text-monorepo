<?php

declare(strict_types=1);

namespace AltContext\PublicSite;

use AltContext\Support\ViteManifest;

use function add_action;
use function add_filter;
use function add_rewrite_rule;
use function array_values;
use function class_exists;
use function function_exists;
use function get_404_template;
use function get_option;
use function get_query_var;
use function is_array;
use function is_object;
use function is_string;
use function nocache_headers;
use function status_header;
use function str_starts_with;
use function wp_dequeue_script;
use function wp_dequeue_style;
use function wp_enqueue_script;
use function wp_enqueue_style;
use function wp_script_add_data;
use function wp_scripts;
use function wp_styles;

/**
 * Public signed-out /guide/ route for the recorded walkthrough.
 */
final class PublicGuideRoute {
	public const QUERY_VAR = 'acx_public_guide';
	public const OPTION_ENABLED = 'acx_public_guide_enabled';
	public const ENTRY_POINT = 'js/guide/main.tsx';
	public const SCRIPT_HANDLE = 'acx-public-guide';

	private const FALLBACK_COPY = 'The walkthrough could not load. Reload the page, or watch the recorded video on the case study page.';

	/** @var callable(string): ?array{js: string, css: list<string>} */
	private $assetResolver;

	/**
	 * @param callable(string): ?array{js: string, css: list<string>}|null $assetResolver
	 */
	public function __construct( ?callable $assetResolver = null ) {
		$this->assetResolver = $assetResolver ?? self::default_asset_resolver();
	}

	public function init(): void {
		add_action( 'init', array( $this, 'register_rewrite' ) );
		add_filter( 'query_vars', array( $this, 'add_query_var' ) );
		add_filter( 'template_include', array( $this, 'template_include' ) );
		add_action( 'wp_enqueue_scripts', array( $this, 'enqueue_assets' ) );
		add_action( 'wp_enqueue_scripts', array( $this, 'dequeue_theme_assets' ), 100 );
	}

	public function register_rewrite(): void {
		add_rewrite_rule( '^guide/?$', 'index.php?acx_public_guide=1', 'top' );
	}

	/**
	 * @param list<string> $vars
	 * @return list<string>
	 */
	public function add_query_var( array $vars ): array {
		$vars[] = self::QUERY_VAR;

		return $vars;
	}

	public function template_include( string $template ): string {
		if ( ! $this->is_public_guide_request() ) {
			return $template;
		}

		if ( ! self::is_enabled() ) {
			status_header( 404 );
			nocache_headers();
			$not_found = function_exists( 'get_404_template' ) ? get_404_template() : '';

			return is_string( $not_found ) && '' !== $not_found ? $not_found : $template;
		}

		status_header( 200 );

		return $this->template_path();
	}

	public function enqueue_assets(): void {
		if ( ! $this->is_public_guide_request() || ! self::is_enabled() ) {
			return;
		}

		$resolver = $this->assetResolver;
		$assets   = $resolver( self::ENTRY_POINT );
		if ( ! is_array( $assets ) ) {
			return;
		}

		$js = $assets['js'] ?? '';
		if ( ! is_string( $js ) || '' === $js ) {
			return;
		}

		wp_enqueue_script( self::SCRIPT_HANDLE, $js, array(), ACX_VERSION, true );
		wp_script_add_data( self::SCRIPT_HANDLE, 'type', 'module' );

		$css = $assets['css'] ?? array();
		if ( ! is_array( $css ) ) {
			return;
		}

		foreach ( array_values( $css ) as $index => $url ) {
			if ( ! is_string( $url ) || '' === $url ) {
				continue;
			}

			wp_enqueue_style( self::SCRIPT_HANDLE . '-' . $index, $url, array(), ACX_VERSION );
		}
	}

	public function dequeue_theme_assets(): void {
		if ( ! $this->is_public_guide_request() ) {
			return;
		}

		$styles = function_exists( 'wp_styles' ) ? wp_styles() : null;
		if ( is_object( $styles ) && isset( $styles->queue ) && is_array( $styles->queue ) ) {
			foreach ( $styles->queue as $handle ) {
				$handle = (string) $handle;
				if ( ! $this->is_plugin_handle( $handle ) && function_exists( 'wp_dequeue_style' ) ) {
					wp_dequeue_style( $handle );
				}
			}
		}

		$scripts = function_exists( 'wp_scripts' ) ? wp_scripts() : null;
		if ( is_object( $scripts ) && isset( $scripts->queue ) && is_array( $scripts->queue ) ) {
			foreach ( $scripts->queue as $handle ) {
				$handle = (string) $handle;
				if ( ! $this->is_plugin_handle( $handle ) && function_exists( 'wp_dequeue_script' ) ) {
					wp_dequeue_script( $handle );
				}
			}
		}
	}

	public static function is_enabled(): bool {
		$value = get_option( self::OPTION_ENABLED, false );

		return true === $value || 1 === $value || '1' === $value;
	}

	public static function fallback_copy(): string {
		return self::FALLBACK_COPY;
	}

	private function is_public_guide_request(): bool {
		if ( ! function_exists( 'get_query_var' ) ) {
			return false;
		}

		$value = get_query_var( self::QUERY_VAR );

		return '' !== (string) $value && '0' !== (string) $value;
	}

	private function template_path(): string {
		$path = __DIR__ . '/templates/public-guide.php';
		$real = realpath( $path );

		return is_string( $real ) ? $real : $path;
	}

	private function is_plugin_handle( string $handle ): bool {
		return str_starts_with( $handle, 'acx-' ) || str_starts_with( $handle, 'alt-context-' );
	}

	/**
	 * @return callable(string): ?array{js: string, css: list<string>}
	 */
	private static function default_asset_resolver(): callable {
		return static function ( string $entry ): ?array {
			if ( ! class_exists( ViteManifest::class ) ) {
				return null;
			}

			$assets = ViteManifest::from_plugin()->entry_assets( $entry );

			return is_array( $assets ) ? $assets : null;
		};
	}
}
