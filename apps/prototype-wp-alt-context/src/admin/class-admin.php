<?php

declare(strict_types=1);

namespace AltContext\Admin;

use AltContext\Api\RecognitionEndpointResolver;
use AltContext\Api\TenantIdentity;
use AltContext\Support\BatchLimits;

use function add_action;
use function do_action;
use function admin_url;
use function esc_html;
use function esc_html__;
use function esc_url_raw;
use function file_get_contents;
use function in_array;
use function is_array;
use function is_readable;
use function json_decode;
use function get_option;
use function plugins_url;
use function sanitize_key;
use function trailingslashit;
use function rest_url;
use function wp_enqueue_script;
use function wp_enqueue_style;
use function wp_create_nonce;
use function wp_get_environment_type;
use function wp_localize_script;
use function wp_remote_head;
use function wp_remote_retrieve_response_code;
use function wp_script_add_data;
use function wp_unslash;
use function is_wp_error;

/**
 * Coordinates admin-only concerns such as enqueueing the SPA bundle.
 */
class Admin {
	use BatchLimits;

	private const DASHBOARD_HOOK = 'toplevel_page_alt-context-dashboard';
	private const SCRIPT_HANDLE = 'alt-context-admin';
	private const ENTRY_POINT = 'js/admin/main.tsx';
	private const CANONICAL_PLUGIN_FILE = 'alt-context/alt-context.php';

	/**
	 * Admin page slugs that should load the SPA bundle.
	 *
	 * @var string[]
	 */
	private const SUPPORTED_PAGE_SLUGS = array(
		'alt-context-dashboard',
		'alt-context-workbench',
		'alt-context-roster',
		'alt-context-description-history',
		'alt-context-settings',
	);

	private string $devServer;
	private string $manifestPath;
	private ?string $assetBootstrapFailureMessage = null;
	private bool $assetBootstrapNoticeHooked = false;
	private ?bool $devServerReachableCache = null;

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
		if ( wp_get_environment_type() !== 'development' ) {
			return false;
		}
		if ( '' === $this->devServer ) {
			return false;
		}
		return $this->is_dev_server_reachable();
	}

	/**
	 * Probe the Vite dev server with a short HEAD request and cache the result
	 * for this request lifetime. Falls back to the built bundle when Vite is not
	 * reachable, instead of letting the browser fail with ERR_CONNECTION_REFUSED.
	 *
	 * Tests can override this by providing an injected client; the default uses
	 * wp_remote_head with a 1-second timeout so admin page loads stay responsive
	 * even when ACX_VITE_DEV_SERVER is set but Vite is not running.
	 */
	private function is_dev_server_reachable(): bool {
		if ( null !== $this->devServerReachableCache ) {
			return $this->devServerReachableCache;
		}

		$probe_url = trailingslashit( $this->devServer ) . '@vite/client';
		$response = wp_remote_head(
			esc_url_raw( $probe_url ),
			array(
				'timeout'   => 1,
				'sslverify' => false,
			)
		);

		if ( is_wp_error( $response ) ) {
			$this->devServerReachableCache = false;
			return false;
		}

		$status = (int) wp_remote_retrieve_response_code( $response );
		$this->devServerReachableCache = ( $status >= 200 && $status < 500 );
		return $this->devServerReachableCache;
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
		$asset_path = 'public/assets/dist/' . ltrim( $relative, '/' );

		if ( \function_exists( 'plugins_url' ) ) {
			return esc_url_raw( plugins_url( $asset_path, self::CANONICAL_PLUGIN_FILE ) );
		}

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

		$resolver = new RecognitionEndpointResolver();
		if ( 'local' !== $resolver->get_recognition_source() ) {
			return;
		}

		$effective_url = $resolver->get_effective_base_url();
		$settings_url  = admin_url( 'admin.php?page=alt-context-settings' );
		echo '<div class="notice notice-warning"><p>';
		printf(
			/* translators: 1: effective local recognition URL, 2: link to settings page */
			esc_html__( 'Alt Context is in local recognition mode and will send requests to %1$s. %2$s to switch to the hosted recognition service.', 'alt-context' ),
			esc_html( $effective_url ),
			'<a href="' . esc_url( $settings_url ) . '">' . esc_html__( 'Go to Settings', 'alt-context' ) . '</a>'
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
					'tenant_id' => TenantIdentity::resolve()['value'],
					'recognitionSource' => $this->get_recognition_source(),
					'effectiveTargetUrl' => $this->get_effective_target_url(),
					'max_media_per_batch' => $this->get_tier_batch_limit_for( $tier ),
					'adminUrls' => array(
					'mediaEditBase' => admin_url( 'post.php' ),
					'rosterClusters' => admin_url( 'admin.php?page=alt-context-roster&tab=clusters' ),
				),
				'endpoints' => array(
					'workbenchMedia'                 => rest_url( 'acx/v1/workbench/media' ),
					'workbenchMediaDetail'           => rest_url( 'acx/v1/workbench/media/detail' ),
					'recognitionAnalyze'             => rest_url( 'acx/v1/recognition/analyze' ),
					'recognitionDescribe'            => rest_url( 'acx/v1/recognition/describe' ),
					'recognitionDescribeHistory'     => rest_url( 'acx/v1/recognition/describe/history' ),
					'recognitionBatchRuns'           => rest_url( 'acx/v1/recognition/batch-runs' ),
					'recognitionJobs'                => rest_url( 'acx/v1/recognition/jobs' ),
					'recognitionCluster'             => rest_url( 'acx/v1/recognition/cluster' ),
					'recognitionClusters'            => rest_url( 'acx/v1/recognition/clusters' ),
					'recognitionClusterLabels'       => rest_url( 'acx/v1/recognition/clusters/labels' ),
					'recognitionConflicts'          => rest_url( 'acx/v1/recognition/conflicts' ),
					'recognitionOutbox'             => rest_url( 'acx/v1/recognition/outbox' ),
					'recognitionFailedOutbox'       => rest_url( 'acx/v1/recognition/outbox/failed' ),
					'recognitionSyncStatus'          => rest_url( 'acx/v1/recognition/sync-status' ),
					'recognitionSyncHealth'          => rest_url( 'acx/v1/recognition/sync/health' ),
					'recognitionSyncTrigger'         => rest_url( 'acx/v1/recognition/sync/trigger' ),
					'recognitionSyncResetMirror'     => rest_url( 'acx/v1/recognition/sync/reset-mirror' ),
					'recognitionMediaIdentities'     => rest_url( 'acx/v1/recognition/media-identities' ),
					'retentionStatus'                => rest_url( 'acx/v1/retention/status' ),
					'retentionPolicy'                => rest_url( 'acx/v1/retention/policy' ),
					'retentionExport'                => rest_url( 'acx/v1/retention/export' ),
					'retentionPurge'                 => rest_url( 'acx/v1/retention/purge' ),
					'retentionImport'                => rest_url( 'acx/v1/retention/import' ),
					'retentionAudit'                 => rest_url( 'acx/v1/retention/audit' ),
					'recognitionReassignIdentity'    => rest_url( 'acx/v1/recognition/clusters/reassign' ),
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
					'settings'                       => rest_url( 'acx/v1/settings' ),
					'settingsTest'                   => rest_url( 'acx/v1/settings/test' ),
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

	private function get_recognition_source(): string {
		return $this->get_endpoint_resolver()->get_recognition_source();
	}

	private function get_effective_target_url(): string {
		return $this->get_endpoint_resolver()->get_effective_base_url();
	}

	private function get_endpoint_resolver(): RecognitionEndpointResolver {
		static $resolver = null;
		if ( null === $resolver ) {
			$resolver = new RecognitionEndpointResolver();
		}

		return $resolver;
	}
}
