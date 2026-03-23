<?php

declare(strict_types=1);

namespace AltContext\Admin;

use AltContext\Support\BatchLimits;

use function add_action;
use function apply_filters;
use function do_action;
use function admin_url;
use function esc_html;
use function esc_html__;
use function esc_url_raw;
use function file_get_contents;
use function get_site_url;
use function in_array;
use function is_array;
use function is_readable;
use function json_decode;
use function get_option;
use function parse_url;
use function sanitize_key;
use function strtolower;
use function trailingslashit;
use function rest_url;
use function wp_enqueue_script;
use function wp_enqueue_style;
use function wp_create_nonce;
use function wp_get_environment_type;
use function wp_localize_script;
use function wp_script_add_data;
use function wp_unslash;

/**
 * Coordinates admin-only concerns such as enqueueing the SPA bundle.
 */
class Admin {
	use BatchLimits;

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
	);

	private string $devServer;
	private string $manifestPath;
	private ?string $assetBootstrapFailureMessage = null;
	private bool $assetBootstrapNoticeHooked = false;

	public function __construct( ?string $manifestPath = null ) {
		$this->devServer = defined('ACX_VITE_DEV_SERVER') ? (string) ACX_VITE_DEV_SERVER : '';
		$this->manifestPath = null !== $manifestPath && '' !== $manifestPath
			? $manifestPath
			: ACX_PLUGIN_DIR . 'public/assets/dist/.vite/manifest.json';
	}

	public function init(): void {
		add_action( 'admin_enqueue_scripts', array( $this, 'enqueue_scripts' ) );
		add_action( 'admin_notices', array( $this, 'render_recognition_config_notice' ) );
	}

	public function enqueue_scripts( string $hookSuffix ): void {
		if ( ! $this->should_enqueue_assets( $hookSuffix ) ) {
			return;
		}

		$handle = null;

		if ( $this->should_use_dev_server() ) {
			$handle = $this->enqueue_dev_assets();
		} else {
			$handle = $this->enqueue_build_assets();
		}

		if ( ! is_string( $handle ) || '' === $handle ) {
			return;
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
		$page = isset( $_GET['page'] ) ? sanitize_key( wp_unslash( (string) $_GET['page'] ) ) : null;

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

		$deps = array( 'wp-element', 'wp-i18n', 'wp-hooks', $devHandle );
		wp_enqueue_script(
			$entryHandle,
			esc_url_raw( $base . self::ENTRY_POINT ),
			$deps,
			null,
			true
		);
		wp_script_add_data( $entryHandle, 'type', 'module' );

		return $entryHandle;
	}

	private function enqueue_build_assets(): ?string {
		$entry = $this->get_manifest_entry();

		if ( ! $entry || empty( $entry['file'] ) ) {
			$this->report_asset_bootstrap_failure( 'Missing or invalid build manifest entry for admin SPA bundle.' );
			return null;
		}

		wp_enqueue_script(
			self::SCRIPT_HANDLE,
			$this->build_asset_url( (string) $entry['file'] ),
			array( 'wp-element', 'wp-i18n', 'wp-hooks' ),
			ACX_VERSION,
			true
		);
		wp_script_add_data( self::SCRIPT_HANDLE, 'type', 'module' );

		if ( empty( $entry['css'] ) || ! is_array( $entry['css'] ) ) {
			return self::SCRIPT_HANDLE;
		}

		foreach ( $entry['css'] as $index => $cssFile ) {
			wp_enqueue_style(
				self::SCRIPT_HANDLE . '-' . $index,
				$this->build_asset_url( (string) $cssFile ),
				array(),
				ACX_VERSION
			);
		}

		return self::SCRIPT_HANDLE;
	}

	private function get_manifest_entry(): ?array {
		if ( ! is_readable( $this->manifestPath ) ) {
			return null;
		}

		$contents = file_get_contents( $this->manifestPath );

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
		$base = trailingslashit( ACX_PLUGIN_URL . 'public/assets/dist' );

		return esc_url_raw( $base . ltrim( $relative, '/' ) );
	}

	private function report_asset_bootstrap_failure( string $reason ): void {
		if ( null !== $this->assetBootstrapFailureMessage ) {
			return;
		}

		$this->assetBootstrapFailureMessage = $reason . ' Manifest path: ' . $this->manifestPath;

		if ( ! $this->assetBootstrapNoticeHooked ) {
			add_action( 'admin_notices', array( $this, 'render_asset_bootstrap_notice' ) );
			$this->assetBootstrapNoticeHooked = true;
		}

		if ( function_exists( '_doing_it_wrong' ) ) {
			_doing_it_wrong( __METHOD__, esc_html( $this->assetBootstrapFailureMessage ), '4.13.0' );
		}

		do_action(
			'acx_admin_asset_bootstrap_failure',
			$this->assetBootstrapFailureMessage,
			array(
				'manifest_path' => $this->manifestPath,
				'reason'        => $reason,
			)
		);
	}

	public function render_asset_bootstrap_notice(): void {
		if ( null === $this->assetBootstrapFailureMessage ) {
			return;
		}

		echo '<div class="notice notice-error"><p>';
		echo esc_html__( 'Alt Context admin assets could not be loaded. Run npm run build in apps/prototype-wp-alt-context and reload this page.', 'alt-context' );
		echo '</p></div>';
	}

	public function render_recognition_config_notice(): void {
		if ( ! $this->is_supported_page_request() ) {
			return;
		}

		if ( ! $this->should_render_recognition_fallback_notice() ) {
			return;
		}

		echo '<div class="notice notice-warning"><p>';
		echo esc_html__(
			'Alt Context is using the local recognition URL fallback (http://localhost:8000). Configure acx_recognition_url or ACX_RECOGNITION_URL for this environment.',
			'alt-context'
		);
		echo '</p></div>';
	}

	private function localize_spa_config( string $handle ): void {
		$is_dev_mode = wp_get_environment_type() === 'development';

		$tier = $this->get_tier();

		wp_localize_script(
			$handle,
			'AltContextAdmin',
			array(
				'nonce'     => wp_create_nonce( 'wp_rest' ),
				'devMode'   => $is_dev_mode,
				'tier'      => $tier,
				'tenant_id' => md5( (string) get_site_url() ), // v4.12.0: Keep query keys tenant-scoped
				'recognitionUrlFallback' => $this->should_render_recognition_fallback_notice(),
				'max_media_per_batch' => $this->get_tier_batch_limit_for( $tier ),
				'adminUrls' => array(
					'mediaEditBase' => admin_url( 'post.php' ),
					'rosterClusters' => admin_url( 'admin.php?page=alt-context-roster&tab=clusters' ),
				),
				'endpoints' => array(
					'workbenchMedia'                 => rest_url( 'acx/v1/workbench/media' ),
					'recognitionAnalyze'             => rest_url( 'acx/v1/recognition/analyze' ),
					'recognitionJobs'                => rest_url( 'acx/v1/recognition/jobs' ),
					'recognitionCluster'             => rest_url( 'acx/v1/recognition/cluster' ),
					'recognitionClusters'            => rest_url( 'acx/v1/recognition/clusters' ),
					'recognitionClusterLabels'       => rest_url( 'acx/v1/recognition/clusters/labels' ),
					'recognitionConflicts'          => rest_url( 'acx/v1/recognition/conflicts' ),
					'recognitionOutbox'             => rest_url( 'acx/v1/recognition/outbox' ),
					'recognitionFailedOutbox'       => rest_url( 'acx/v1/recognition/outbox/failed' ),
					'recognitionSyncStatus'          => rest_url( 'acx/v1/recognition/sync-status' ),
					'recognitionSyncTrigger'         => rest_url( 'acx/v1/recognition/sync/trigger' ),
					'recognitionMediaIdentities'     => rest_url( 'acx/v1/recognition/media-identities' ),
					'retentionStatus'                => rest_url( 'acx/v1/retention/status' ),
					'retentionPolicy'                => rest_url( 'acx/v1/retention/policy' ),
					'retentionExport'                => rest_url( 'acx/v1/retention/export' ),
					'retentionPurge'                 => rest_url( 'acx/v1/retention/purge' ),
					'retentionImport'                => rest_url( 'acx/v1/retention/import' ),
					'retentionAudit'                 => rest_url( 'acx/v1/retention/audit' ),
					'recognitionReassignIdentity'    => rest_url( 'acx/v1/recognition/clusters/reassign' ),
					'recognitionAssignOutlier'       => rest_url( 'acx/v1/recognition/clusters' ),
					'recognitionIdentitySuggestions' => rest_url( 'acx/v1/recognition/identities' ),
					'recognitionSuggestions'         => rest_url( 'acx/v1/recognition/suggestions' ),
					'recognitionMergeSuggestions'    => rest_url( 'acx/v1/recognition/suggestions/merge' ),
					'recognitionNameSuggestions'     => rest_url( 'acx/v1/recognition/suggestions/name' ),
					'recognitionBulkAcceptSuggestions' => rest_url( 'acx/v1/recognition/suggestions/bulk-accept' ),
					'recognitionRevertMerge'         => rest_url( 'acx/v1/recognition/clusters/revert-merge' ),
					'recognitionCreateClusterForIdentity' => rest_url( 'acx/v1/recognition/clusters/create-for-identity' ),
					'rosterEntries'                  => rest_url( 'acx/v1/roster/entries' ),
					'rosterPersons'                  => rest_url( 'acx/v1/roster/persons' ),
					'rosterClusters'                 => rest_url( 'acx/v1/roster/clusters' ),
					'dashboardStats'                 => rest_url( 'acx/v1/dashboard/stats' ),
				),
			)
		);
	}

	private function get_tier(): string {
		$tier = sanitize_key( (string) get_option( 'acx_tier', 'free' ) );
		if ( '' === $tier || ! $this->is_valid_tier( $tier ) ) {
			return 'free';
		}
		return $tier;
	}

	private function should_render_recognition_fallback_notice(): bool {
		return ! $this->has_valid_recognition_url_configuration();
	}

	private function has_valid_recognition_url_configuration(): bool {
		$candidates = array(
			$this->get_recognition_url_from_constant(),
			trim( (string) get_option( 'acx_recognition_url', '' ) ),
			trim( (string) apply_filters( 'acx_recognition_base_url', '' ) ),
		);

		foreach ( $candidates as $candidate ) {
			if ( $this->is_valid_recognition_base_url( $candidate ) ) {
				return true;
			}
		}

		return false;
	}

	private function get_recognition_url_from_constant(): string {
		if ( defined( 'ACX_RECOGNITION_URL' ) && is_string( ACX_RECOGNITION_URL ) ) {
			return trim( ACX_RECOGNITION_URL );
		}

		return '';
	}

	private function is_valid_recognition_base_url( string $candidate ): bool {
		if ( '' === $candidate ) {
			return false;
		}

		$parts = parse_url( $candidate );
		if ( false === $parts || ! is_array( $parts ) ) {
			return false;
		}

		$scheme = strtolower( (string) ( $parts['scheme'] ?? '' ) );
		$host   = (string) ( $parts['host'] ?? '' );

		if ( ! in_array( $scheme, array( 'http', 'https' ), true ) ) {
			return false;
		}

		return '' !== $host;
	}
}
