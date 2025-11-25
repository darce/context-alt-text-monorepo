<?php

declare(strict_types=1);

namespace AltContext\Admin;

use function add_action;
use function esc_url_raw;
use function file_get_contents;
use function in_array;
use function is_array;
use function is_readable;
use function json_decode;
use function trailingslashit;
use function rest_url;
use function wp_enqueue_script;
use function wp_enqueue_style;
use function wp_create_nonce;
use function wp_get_environment_type;
use function wp_localize_script;
use function wp_script_add_data;

/**
 * Coordinates admin-only concerns such as enqueueing the SPA bundle.
 */
class Admin {
	private const DASHBOARD_HOOK = 'toplevel_page_alt-context-dashboard';
	private const SCRIPT_HANDLE = 'alt-context-admin';
	private const ENTRY_POINT = 'js/admin/main.tsx';

	/**
	 * Admin page slugs that should load the SPA bundle.
	 *
	 * @var string[]
	 */
	private const SUPPORTED_PAGE_SLUGS = array(
		'alt-context-dashboard',
		'alt-context-workbench',
		'alt-context-roster',
		'alt-context-settings',
	);

	private string $devServer;

	public function __construct() {
		$this->devServer = defined('ALT_CONTEXT_VITE_DEV_SERVER') ? (string) ALT_CONTEXT_VITE_DEV_SERVER : '';
	}

	public function init(): void {
		add_action( 'admin_enqueue_scripts', array( $this, 'enqueue_scripts' ) );
	}

	public function enqueue_scripts( string $hookSuffix ): void {
		if ( ! $this->should_enqueue_assets( $hookSuffix ) ) {
			return;
		}

		$handle = self::SCRIPT_HANDLE;

		if ( $this->should_use_dev_server() ) {
			$handle = $this->enqueue_dev_assets();
		} else {
			$this->enqueue_build_assets();
		}

		$this->localize_spa_config( $handle );
	}

	private function should_enqueue_assets( string $hookSuffix ): bool {
		if ( $hookSuffix === self::DASHBOARD_HOOK ) {
			return true;
		}

		return $this->is_supported_page_request();
	}

	private function is_supported_page_request(): bool {
		$page = $_GET['page'] ?? null;

		if ( ! is_string( $page ) ) {
			return false;
		}

		return in_array( $page, self::SUPPORTED_PAGE_SLUGS, true );
	}

	private function should_use_dev_server(): bool {
		return wp_get_environment_type() === 'development' && '' !== $this->devServer;
	}

	private function enqueue_dev_assets(): string {
		$base = trailingslashit( $this->devServer );
		$devHandle = self::SCRIPT_HANDLE . '-dev';
		$entryHandle = self::SCRIPT_HANDLE . '-entry';

		wp_enqueue_script( $devHandle, esc_url_raw( $base . '@vite/client' ), array(), null, true );
		wp_script_add_data( $devHandle, 'type', 'module' );

		wp_enqueue_script(
			$entryHandle,
			esc_url_raw( $base . self::ENTRY_POINT ),
			array( $devHandle ),
			null,
			true
		);
		wp_script_add_data( $entryHandle, 'type', 'module' );

		return $entryHandle;
	}

	private function enqueue_build_assets(): void {
		$entry = $this->get_manifest_entry();

		if ( ! $entry || empty( $entry['file'] ) ) {
			return;
		}

		wp_enqueue_script(
			self::SCRIPT_HANDLE,
			$this->build_asset_url( (string) $entry['file'] ),
			array(),
			ALT_CONTEXT_VERSION,
			true
		);
		wp_script_add_data( self::SCRIPT_HANDLE, 'type', 'module' );

		if ( empty( $entry['css'] ) || ! is_array( $entry['css'] ) ) {
			return;
		}

		foreach ( $entry['css'] as $index => $cssFile ) {
			wp_enqueue_style(
				self::SCRIPT_HANDLE . '-' . $index,
				$this->build_asset_url( (string) $cssFile ),
				array(),
				ALT_CONTEXT_VERSION
			);
		}
	}

	private function get_manifest_entry(): ?array {
		$manifestPath = ALT_CONTEXT_PLUGIN_DIR . 'public/assets/dist/.vite/manifest.json';

		if ( ! is_readable( $manifestPath ) ) {
			return null;
		}

		$contents = file_get_contents( $manifestPath );

		if ( false === $contents ) {
			return null;
		}

		$manifest = json_decode( $contents, true );
		if ( ! is_array( $manifest ) ) {
			return null;
		}

		$entry = $manifest[ self::ENTRY_POINT ] ?? null;

		return is_array( $entry ) ? $entry : null;
	}

	private function build_asset_url( string $relative ): string {
		$base = trailingslashit( ALT_CONTEXT_PLUGIN_URL . 'public/assets/dist' );

		return esc_url_raw( $base . ltrim( $relative, '/' ) );
	}

	private function localize_spa_config( string $handle ): void {
		wp_localize_script(
			$handle,
			'AltContextAdmin',
			array(
				'nonce'     => wp_create_nonce( 'wp_rest' ),
				'endpoints' => array(
					'workbenchMedia'                 => rest_url( 'acx/v1/workbench/media' ),
					'workbenchRecognitionAnalyze'    => rest_url( 'acx/v1/workbench/recognition/analyze' ),
					'workbenchRecognitionJobs'       => rest_url( 'acx/v1/workbench/recognition/jobs' ),
					'workbenchRecognitionCluster'    => rest_url( 'acx/v1/workbench/recognition/cluster' ),
					'workbenchRecognitionClusters'   => rest_url( 'acx/v1/workbench/recognition/clusters' ),
					'workbenchRecognitionMediaIdentities' => rest_url( 'acx/v1/workbench/recognition/media-identities' ),
					'workbenchRecognitionReassignIdentity' => rest_url( 'acx/v1/workbench/recognition/clusters/reassign' ),
					'workbenchRecognitionIdentitySuggestions' => rest_url( 'acx/v1/workbench/recognition/identities' ),
					'workbenchRecognitionRevertMerge' => rest_url( 'acx/v1/workbench/recognition/clusters/revert-merge' ),
					// Legacy keys kept for backward compatibility with older bundles that still use "face" terminology.
					'workbenchFaceScan'                   => rest_url( 'acx/v1/workbench/recognition/analyze' ),
					'workbenchFaceClusters'               => rest_url( 'acx/v1/workbench/recognition/clusters' ),
					'recognitionAnalyze'  => rest_url( 'acx/v1/recognition/analyze' ),
					'recognitionJobs'     => rest_url( 'acx/v1/recognition/jobs' ),
					'recognitionCluster'  => rest_url( 'acx/v1/recognition/cluster' ),
					'recognitionClusters' => rest_url( 'acx/v1/recognition/clusters' ),
					'recognitionIdentitySuggestions' => rest_url( 'acx/v1/recognition/identities' ),
					'recognitionRevertMerge' => rest_url( 'acx/v1/recognition/clusters/revert-merge' ),
					'rosterEntries'       => rest_url( 'acx/v1/roster/entries' ),
					'rosterClusters'      => rest_url( 'acx/v1/roster/clusters' ),
				),
			)
		);
	}
}
