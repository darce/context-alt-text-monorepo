<?php

declare(strict_types=1);

namespace AltContext\Admin;

require_once __DIR__ . '/../support/class-vite-manifest.php';

use AltContext\Api\RecognitionEndpointResolver;
use AltContext\Api\TenantIdentity;
use AltContext\Support\BatchLimits;
use AltContext\Support\ViteManifest;

use function absint;
use function add_action;
use function do_action;
use function admin_url;
use function current_user_can;
use function esc_html;
use function esc_html__;
use function esc_url_raw;
use function get_post_type;
use function in_array;
use function is_array;
use function get_option;
use function plugins_url;
use function sanitize_key;
use function trailingslashit;
use function rest_url;
use function wp_enqueue_script;
use function wp_enqueue_style;
use function wp_create_nonce;
use function wp_get_attachment_image_src;
use function wp_get_environment_type;
use function wp_localize_script;
use function wp_remote_head;
use function wp_remote_retrieve_response_code;
use function wp_script_add_data;
use function wp_set_script_translations;
use function wp_unslash;
use function wp_scripts;
use function is_wp_error;
use function add_filter;

/**
 * Coordinates admin-only concerns such as enqueueing the SPA and attachment-edit bundles.
 */
class Admin {
	use BatchLimits;

	private const DASHBOARD_HOOK = 'toplevel_page_alt-context-dashboard';
	private const SPA_SCRIPT_HANDLE = 'alt-context-admin';
	private const SPA_ENTRY_POINT = 'js/admin/main.tsx';
	private const ATTACHMENT_EDIT_SCRIPT_HANDLE = 'alt-context-attachment-edit';
	private const ATTACHMENT_EDIT_ENTRY_POINT = 'js/attachment-edit/main.tsx';
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
	private ?ViteManifest $viteManifest = null;
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
		// wp_script_add_data($handle,'type','module') does not itself render type="module";
		// without this the code-split Vite entry (top-level `import`) loads as a classic
		// script and the SPA never mounts ("Cannot use import statement outside a module").
		add_filter( 'script_loader_tag', array( $this, 'filter_module_script_tag' ), 10, 3 );
	}

	/**
	 * Render type="module" for any handle registered with wp_script_add_data($handle,'type','module').
	 */
	public function filter_module_script_tag( string $tag, string $handle, string $src ): string {
		$scripts = wp_scripts();

		if ( null === $scripts || 'module' !== $scripts->get_data( $handle, 'type' ) ) {
			return $tag;
		}

		if ( false !== strpos( $tag, 'type="module"' ) || false !== strpos( $tag, "type='module'" ) ) {
			return $tag;
		}

		// Anchor on the src-bearing <script>, not merely the first one: WordPress
		// prepends any `before` inline script / translations into $tag, and putting
		// type=module on that classic wrapper would re-introduce the SyntaxError this
		// fixes. No module handle uses a `before` inline today; the lookahead keeps it
		// safe if one is ever added ([RES-01] defensive robustness).
		return (string) preg_replace( '/<script\b(?=[^>]*\ssrc=)/', '<script type="module"', $tag, 1 );
	}

	public function enqueue_scripts( string $hookSuffix ): void {
		if ( $this->should_enqueue_attachment_edit_assets( $hookSuffix ) ) {
			$this->enqueue_entry(
				self::ATTACHMENT_EDIT_ENTRY_POINT,
				self::ATTACHMENT_EDIT_SCRIPT_HANDLE,
				array( $this, 'localize_attachment_edit_config' )
			);
			return;
		}

		if ( ! $this->should_enqueue_assets( $hookSuffix ) ) {
			return;
		}

		$this->enqueue_entry(
			self::SPA_ENTRY_POINT,
			self::SPA_SCRIPT_HANDLE,
			array( $this, 'localize_spa_config' )
		);
	}

	/**
	 * @param callable(string):void $localize
	 */
	private function enqueue_entry( string $entryPoint, string $scriptHandle, callable $localize ): void {
		$handle = null;

		if ( $this->should_use_dev_server() ) {
			$handle = $this->enqueue_dev_assets( $entryPoint, $scriptHandle );
		} else {
			$handle = $this->enqueue_build_assets( $entryPoint, $scriptHandle );
		}

		if ( ! is_string( $handle ) || '' === $handle ) {
			return;
		}

		// Load JS translations for __()/_x() strings in the bundle. Without this the
		// wp-i18n dependency ships but never receives a locale JED, so every SPA
		// string stays in the source language regardless of site locale ([RLSE-04]).
		wp_set_script_translations( $handle, 'alt-context', ACX_PLUGIN_DIR . 'public/languages' );

		$localize( $handle );
	}

	private function should_enqueue_assets( string $hookSuffix ): bool {
		if ( $hookSuffix === self::DASHBOARD_HOOK ) {
			return true;
		}

		return $this->is_supported_page_request();
	}

	/**
	 * post.php attachment edit screen — capability parity with media-identities.
	 */
	private function should_enqueue_attachment_edit_assets( string $hookSuffix ): bool {
		if ( 'post.php' !== $hookSuffix ) {
			return false;
		}

		if ( ! current_user_can( 'manage_options' ) ) {
			return false;
		}

		$post_id = isset( $_GET['post'] ) ? absint( wp_unslash( (string) $_GET['post'] ) ) : 0;
		if ( $post_id <= 0 ) {
			return false;
		}

		return get_post_type( $post_id ) === 'attachment';
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

	private function enqueue_dev_assets( string $entryPoint, string $scriptHandle ): string {
		$base = trailingslashit( $this->devServer );
		$devHandle = $scriptHandle . '-dev';
		$entryHandle = $scriptHandle . '-entry';

		wp_enqueue_script( $devHandle, esc_url_raw( $base . '@vite/client' ), array(), null, true );
		wp_script_add_data( $devHandle, 'type', 'module' );

		$deps = array( 'wp-element', 'wp-i18n', 'wp-hooks', $devHandle );
		wp_enqueue_script(
			$entryHandle,
			esc_url_raw( $base . $entryPoint ),
			$deps,
			null,
			true
		);
		wp_script_add_data( $entryHandle, 'type', 'module' );

		return $entryHandle;
	}

	private function enqueue_build_assets( string $entryPoint, string $scriptHandle ): ?string {
		$assets = $this->vite_manifest()->entry_assets( $entryPoint );

		if ( null === $assets ) {
			$this->report_asset_bootstrap_failure(
				'Missing or invalid build manifest entry for ' . $entryPoint . '.'
			);
			return null;
		}

		wp_enqueue_script(
			$scriptHandle,
			$assets['js'],
			array( 'wp-element', 'wp-i18n', 'wp-hooks' ),
			ACX_VERSION,
			true
		);
		wp_script_add_data( $scriptHandle, 'type', 'module' );

		foreach ( $assets['css'] as $index => $cssFile ) {
			wp_enqueue_style(
				$scriptHandle . '-' . $index,
				$cssFile,
				array(),
				ACX_VERSION
			);
		}

		return $scriptHandle;
	}

	private function vite_manifest(): ViteManifest {
		if ( null === $this->viteManifest ) {
			// Private build_asset_url is not a valid callable array from outside this class.
			$this->viteManifest = new ViteManifest(
				$this->manifestPath,
				function ( string $relative ): string {
					return $this->build_asset_url( $relative );
				}
			);
		}

		return $this->viteManifest;
	}

	/**
	 * Kept as the AdminEnqueueTest reflection seam; enqueue reads entry_assets().
	 *
	 * @return array<string, mixed>|null
	 * @phpstan-ignore method.unused
	 */
	private function get_manifest_entry( string $entryPoint ): ?array {
		return $this->vite_manifest()->get_entry( $entryPoint );
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

		// RECOG-1: local is a dev-only code hatch (ACX_RECOGNITION_SOURCE constant /
		// filter); the product Settings surface no longer exposes a target toggle, so
		// this notice is a developer diagnostic — remove the constant to return to the
		// hosted service, not a Settings link.
		$effective_url = $resolver->get_effective_base_url();
		echo '<div class="notice notice-warning"><p>';
		printf(
			/* translators: %s: effective local recognition URL */
			esc_html__( 'Alt Context is using the developer local-recognition hatch (ACX_RECOGNITION_SOURCE=local) and will send requests to %s. Remove that constant to use the hosted recognition service.', 'alt-context' ),
			esc_html( $effective_url )
		);
		echo '</p></div>';
	}

	/**
	 * Attachment the guided prototype describes on a live run.
	 *
	 * Operator-set and optional: the guided flow works from its saved draft
	 * without it, so an unset or invalid option publishes null rather than
	 * degrading the page.
	 */
	private function get_guided_live_media_id(): ?int {
		$raw = get_option( 'acx_guided_live_media_id', null );

		// Allow-list, not deny-list. `! is_scalar( $raw )` was dead -- every
		// non-scalar it caught is also refused by filter_var below -- and the
		// surviving `is_bool` half let floats through, which filter_var
		// truncates into a real id. Naming the two types an option can legally
		// hold gives one reachable, testable branch per input.
		if ( ! is_string( $raw ) && ! is_int( $raw ) ) {
			return null;
		}

		$id = filter_var( $raw, FILTER_VALIDATE_INT );

		// PHP counts to PHP_INT_MAX; the browser that reads this config stops
		// being exact at 2^53-1, so anything above it arrives in JS as a
		// neighbouring number and addresses the wrong attachment. Refuse here
		// rather than publish an id the consumer cannot hold.
		if ( false === $id || $id <= 0 || $id > 9007199254740991 ) {
			return null;
		}

		// A well-formed id is not a subject. A deleted attachment, a plain post
		// id, or a stale id copied from another environment all pass the
		// integer test and would enable a live run that can only fail. Publish
		// null so the panel shows the blocked line the feature designed for
		// this exact case.
		return 'attachment' === get_post_type( $id ) ? $id : null;
	}

	private function localize_spa_config( string $handle ): void {
		$is_dev_mode = wp_get_environment_type() === 'development';

		$tier = $this->get_tier();

		wp_localize_script(
			$handle,
			'AltContextAdmin',
				array(
					'nonce'     => wp_create_nonce( 'wp_rest' ),
					'ajaxUrl'   => admin_url( 'admin-ajax.php' ),
					'devMode'   => $is_dev_mode,
					'tier'      => $tier,
					'tenant_id' => TenantIdentity::resolve()['value'],
					'recognitionSource' => $this->get_recognition_source(),
					'effectiveTargetUrl' => $this->get_effective_target_url(),
					'max_media_per_batch' => $this->get_tier_batch_limit_for( $tier ),
					'guided_live_media_id' => $this->get_guided_live_media_id(),
					'adminUrls' => array(
					'mediaEditBase' => admin_url( 'post.php' ),
					'roster' => admin_url( 'admin.php?page=alt-context-roster' ),
					'mediaLibrary' => admin_url( 'upload.php' ),
				),
				'endpoints' => array(
					'workbenchMedia'                 => rest_url( 'acx/v1/workbench/media' ),
					'workbenchMediaDetail'           => rest_url( 'acx/v1/workbench/media/detail' ),
					'recognitionAnalyze'             => rest_url( 'acx/v1/recognition/analyze' ),
					'recognitionDescribe'            => rest_url( 'acx/v1/recognition/describe' ),
					'recognitionDescribeCandidates'  => rest_url( 'acx/v1/recognition/describe/candidates' ),
					'recognitionDescribeHistory'     => rest_url( 'acx/v1/recognition/describe/history' ),
					'recognitionDescribeRuns'        => rest_url( 'acx/v1/recognition/describe/runs' ),
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
					'recognitionSyncRetryFailed'     => rest_url( 'acx/v1/recognition/sync/retry-failed' ),
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

	/**
	 * Minimal config for the attachment-edit entry (not the SPA AltContextAdmin global).
	 */
	private function localize_attachment_edit_config( string $handle ): void {
		$attachment_id = isset( $_GET['post'] ) ? absint( wp_unslash( (string) $_GET['post'] ) ) : 0;
		$image         = $attachment_id > 0 ? wp_get_attachment_image_src( $attachment_id, 'full' ) : false;

		$image_url    = ( is_array( $image ) && isset( $image[0] ) ) ? (string) $image[0] : '';
		$image_width  = ( is_array( $image ) && isset( $image[1] ) ) ? (int) $image[1] : 0;
		$image_height = ( is_array( $image ) && isset( $image[2] ) ) ? (int) $image[2] : 0;

		wp_localize_script(
			$handle,
			'AltContextAttachmentEdit',
			array(
				'nonce'         => wp_create_nonce( 'wp_rest' ),
				'ajaxUrl'       => admin_url( 'admin-ajax.php' ),
				'attachmentId'  => $attachment_id,
				'imageUrl'      => $image_url,
				'imageWidth'    => $image_width,
				'imageHeight'   => $image_height,
				'workbenchUrl'  => admin_url( 'admin.php?page=alt-context-workbench' ),
				'endpoints'     => array(
					'recognitionMediaIdentities' => rest_url( 'acx/v1/recognition/media-identities' ),
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
