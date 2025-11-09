<?php

declare(strict_types=1);

namespace AltContext\Support;

class LifecycleManager {

	private const OPTION_VERSION      = 'alt_context_version';
	private const OPTION_INSTALLED_AT = 'alt_context_installed';

	/**
	 * Run when the plugin is activated.
	 *
	 * Stores install metadata and ensures rewrite rules are refreshed.
	 */
	public function activate(): void {
		if ( defined( 'ALT_CONTEXT_VERSION' ) ) {
			update_option( self::OPTION_VERSION, ALT_CONTEXT_VERSION );
		}

		if ( false === get_option( self::OPTION_INSTALLED_AT ) ) {
			update_option( self::OPTION_INSTALLED_AT, time() );
		}

		flush_rewrite_rules( false );
	}

	/**
	 * Run when the plugin is deactivated.
	 *
	 * Currently we just flush rewrite rules to remove custom routes.
	 */
	public function deactivate(): void {
		flush_rewrite_rules( false );
	}

	/**
	 * Run when the plugin is uninstalled.
	 *
	 * Cleans up any options created during activation.
	 */
	public function uninstall(): void {
		delete_option( self::OPTION_VERSION );
		delete_option( self::OPTION_INSTALLED_AT );
		flush_rewrite_rules( false );
	}
}
