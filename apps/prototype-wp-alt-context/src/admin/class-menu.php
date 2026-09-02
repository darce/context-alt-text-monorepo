<?php
declare(strict_types=1);

namespace AltContext\Admin;

class Menu {

	/**
	 * MECE admin IA (NAV-05): one slug per user goal, frequency-ordered (NAV-06).
	 * Review Queue is the unique naming home; Description Runs is the unique
	 * description-history home. Data retention is a Settings concern, not a
	 * top-level destination (NAV-14: the retired slug still redirects).
	 *
	 * @var list<array{slug: string, menu_title: string, goal: string}>
	 */
	public const SUBMENU_IA = array(
		array( 'slug' => 'alt-context-dashboard', 'menu_title' => 'Overview', 'goal' => 'orient' ),
		array( 'slug' => 'alt-context-workbench', 'menu_title' => 'Review Queue', 'goal' => 'name_person' ),
		array( 'slug' => 'alt-context-roster', 'menu_title' => 'People', 'goal' => 'manage_named_people' ),
		array( 'slug' => 'alt-context-description-history', 'menu_title' => 'Description Runs', 'goal' => 'see_description_history' ),
		array( 'slug' => 'alt-context-settings', 'menu_title' => 'Settings', 'goal' => 'configure_service' ),
	);

	private DashboardPage $dashboardPage;
	private WorkbenchPage $workbenchPage;
	private RosterPage $rosterPage;
	private DescriptionHistoryPage $descriptionHistoryPage;
	private RetentionPage $retentionPage;
	private SettingsPage $settingsPage;

	public function __construct(
		DashboardPage $dashboardPage,
		WorkbenchPage $workbenchPage,
		RosterPage $rosterPage,
		SettingsPage $settingsPage,
		?DescriptionHistoryPage $descriptionHistoryPage = null,
		?RetentionPage $retentionPage = null
	) {
		$this->dashboardPage           = $dashboardPage;
		$this->workbenchPage           = $workbenchPage;
		$this->rosterPage              = $rosterPage;
		$this->settingsPage            = $settingsPage;
		$this->descriptionHistoryPage  = $descriptionHistoryPage ?? new DescriptionHistoryPage();
		$this->retentionPage           = $retentionPage ?? new RetentionPage();
	}

	public function init(): void {
		add_action( 'admin_menu', array( $this, 'register_menu' ) );
		add_action( 'admin_init', array( $this, 'render_retention_page' ) );
	}

	public function register_menu(): void {
		add_menu_page(
			__( 'Alt Context', 'alt-context' ),
			__( 'Alt Context', 'alt-context' ),
			'manage_options',
			'alt-context-dashboard',
			array( $this, 'render_dashboard_page' ),
			'dashicons-universal-access-alt',
			60
		);

		add_submenu_page(
			'alt-context-dashboard',
			__( 'Alt Context Overview', 'alt-context' ),
			__( 'Overview', 'alt-context' ),
			'manage_options',
			'alt-context-dashboard',
			array( $this, 'render_dashboard_page' )
		);

		add_submenu_page(
			'alt-context-dashboard',
			__( 'Alt Context Review Queue', 'alt-context' ),
			__( 'Review Queue', 'alt-context' ),
			'manage_options',
			'alt-context-workbench',
			array( $this, 'render_workbench_page' )
		);

		add_submenu_page(
			'alt-context-dashboard',
			__( 'Alt Context People', 'alt-context' ),
			__( 'People', 'alt-context' ),
			'manage_options',
			'alt-context-roster',
			array( $this, 'render_roster_page' )
		);

		add_submenu_page(
			'alt-context-dashboard',
			__( 'Alt Context Description Runs', 'alt-context' ),
			__( 'Description Runs', 'alt-context' ),
			'manage_options',
			'alt-context-description-history',
			array( $this, 'render_description_history_page' )
		);

		add_submenu_page(
			'alt-context-dashboard',
			__( 'Alt Context Settings', 'alt-context' ),
			__( 'Settings', 'alt-context' ),
			'manage_options',
			'alt-context-settings',
			array( $this, 'render_settings_page' )
		);
	}

	public function render_dashboard_page(): void {
		$this->dashboardPage->render();
	}

	public function render_workbench_page(): void {
		$this->workbenchPage->render();
	}

	public function render_roster_page(): void {
		$this->rosterPage->render();
	}

	public function render_description_history_page(): void {
		$this->descriptionHistoryPage->render();
	}

	public function render_retention_page(): void {
		$page = isset( $_GET['page'] ) ? sanitize_key( wp_unslash( (string) $_GET['page'] ) ) : '';
		if ( $page !== 'alt-context-retention' ) {
			return;
		}

		wp_safe_redirect( admin_url( 'admin.php?page=alt-context-settings#/settings?section=retention' ) );
		if ( defined( 'ACX_VERSION' ) && ACX_VERSION === 'test' ) {
			return;
		}
		exit;
	}

	public function render_settings_page(): void {
		$this->settingsPage->render();
	}
}
