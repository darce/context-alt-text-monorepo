<?php

declare(strict_types=1);

namespace AltContext\PublicSite;

use AltContext\Support\ViteManifest;

use function add_action;
use function add_filter;
use function add_rewrite_rule;
use function array_values;
use function class_exists;
use function flush_rewrite_rules;
use function function_exists;
use function get_option;
use function in_array;
use function is_array;
use function is_object;
use function is_string;
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
	public const WATCH_ENTRY_POINT = 'js/guide/publicGuideWatch.ts';
	public const SCRIPT_HANDLE = 'acx-public-guide';
	public const WATCH_SCRIPT_HANDLE = 'acx-public-guide-watch';
	public const REWRITE_REGEX = '^guide/?$';

	// WHY: WordPress's own admin-bar chrome; the template emits the bar markup via wp_footer(), so stripping them leaves an unstyled bar.
	private const CORE_CHROME_HANDLES = array( 'admin-bar', 'dashicons' );

	private const FALLBACK_COPY = 'The walkthrough could not load. Reload the page and try again.';
	private const LOADING_COPY = 'Loading the walkthrough.';
	public const LOAD_TIMEOUT_MS = 8000;

	/** @var callable(string): ?array{js: string, css: list<string>} */
	private $assetResolver;

	/**
	 * @param callable(string): ?array{js: string, css: list<string>}|null $assetResolver
	 */
	public function __construct( ?callable $assetResolver = null ) {
		$this->assetResolver = $assetResolver ?? self::default_asset_resolver();
	}

	public function init(): void {
		add_action( 'update_option_' . self::OPTION_ENABLED, array( $this, 'on_enabled_option_change' ) );
		add_action( 'add_option_' . self::OPTION_ENABLED, array( $this, 'on_enabled_option_change' ) );
		add_action( 'delete_option_' . self::OPTION_ENABLED, array( $this, 'on_enabled_option_change' ) );
		add_action( 'init', array( $this, 'register_rewrite' ) );

		if ( ! self::is_enabled() ) {
			return;
		}

		add_filter( 'query_vars', array( $this, 'add_query_var' ) );
		add_filter( 'template_include', array( $this, 'template_include' ) );
		add_filter( 'show_admin_bar', array( $this, 'filter_admin_bar' ), PHP_INT_MAX );
		add_action( 'wp_enqueue_scripts', array( $this, 'enqueue_assets' ) );
		add_action( 'wp_enqueue_scripts', array( $this, 'dequeue_theme_assets' ), 100 );
	}

	public function filter_admin_bar( bool $show ): bool {
		return self::is_enabled() && $this->is_public_guide_request() ? false : $show;
	}

	public function register_rewrite(): void {
		if ( ! self::is_enabled() ) {
			return;
		}

		add_rewrite_rule( self::REWRITE_REGEX, 'index.php?' . self::QUERY_VAR . '=1', 'top' );
	}

	public function on_enabled_option_change(): void {
		if ( self::is_enabled() ) {
			$this->register_rewrite();
		} else {
			self::drop_rewrite_from_extra_rules_top();
		}

		if ( function_exists( 'flush_rewrite_rules' ) ) {
			flush_rewrite_rules( false );
		}
	}

	/**
	 * Drop ^guide/?$ from extra_rules_top so a later flush cannot persist it.
	 *
	 * WP_Rewrite::flush_rules() merges extra_rules_top first. Calling flush
	 * while this plugin is still loaded (deactivate, option delete) would
	 * otherwise write the stale rule into the rewrite_rules option.
	 */
	public static function drop_rewrite_from_extra_rules_top(): void {
		global $wp_rewrite;

		if ( isset( $wp_rewrite ) && is_object( $wp_rewrite ) && isset( $wp_rewrite->extra_rules_top ) && is_array( $wp_rewrite->extra_rules_top ) ) {
			unset( $wp_rewrite->extra_rules_top[ self::REWRITE_REGEX ] );
		}
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
		if ( ! self::is_enabled() || ! $this->is_public_guide_request() ) {
			return $template;
		}

		status_header( 200 );

		return $this->template_path();
	}

	public function enqueue_assets(): void {
		if ( ! self::is_enabled() || ! $this->is_public_guide_request() ) {
			return;
		}

		$resolver = $this->assetResolver;

		$watch = $resolver( self::WATCH_ENTRY_POINT );
		if ( is_array( $watch ) ) {
			$watch_js = $watch['js'] ?? '';
			if ( is_string( $watch_js ) && '' !== $watch_js ) {
				wp_enqueue_script( self::WATCH_SCRIPT_HANDLE, $watch_js, array(), ACX_VERSION, true );
				wp_script_add_data( self::WATCH_SCRIPT_HANDLE, 'type', 'module' );
			}
		}

		$assets = $resolver( self::ENTRY_POINT );
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
		if ( ! self::is_enabled() || ! $this->is_public_guide_request() ) {
			return;
		}

		$styles = function_exists( 'wp_styles' ) ? wp_styles() : null;
		if ( is_object( $styles ) && isset( $styles->queue ) && is_array( $styles->queue ) ) {
			foreach ( $styles->queue as $handle ) {
				$handle = (string) $handle;
				if ( ! $this->handle_survives_guide_sweep( $handle ) && function_exists( 'wp_dequeue_style' ) ) {
					wp_dequeue_style( $handle );
				}
			}
		}

		$scripts = function_exists( 'wp_scripts' ) ? wp_scripts() : null;
		if ( is_object( $scripts ) && isset( $scripts->queue ) && is_array( $scripts->queue ) ) {
			foreach ( $scripts->queue as $handle ) {
				$handle = (string) $handle;
				if ( ! $this->handle_survives_guide_sweep( $handle ) && function_exists( 'wp_dequeue_script' ) ) {
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

	public static function loading_copy(): string {
		return self::LOADING_COPY;
	}

	private function is_public_guide_request(): bool {
		$wp = $GLOBALS['wp'] ?? null;
		if ( ! is_object( $wp ) ) {
			return false;
		}

		$matched = isset( $wp->matched_rule ) ? (string) $wp->matched_rule : '';

		return self::REWRITE_REGEX === $matched;
	}

	private function template_path(): string {
		$path = __DIR__ . '/templates/public-guide.php';
		$real = realpath( $path );

		return is_string( $real ) ? $real : $path;
	}

	private function is_plugin_handle( string $handle ): bool {
		return str_starts_with( $handle, 'acx-' ) || str_starts_with( $handle, 'alt-context-' );
	}

	private function handle_survives_guide_sweep( string $handle ): bool {
		return $this->is_plugin_handle( $handle ) || in_array( $handle, self::CORE_CHROME_HANDLES, true );
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
