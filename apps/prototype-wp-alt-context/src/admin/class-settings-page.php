<?php

declare(strict_types=1);

namespace AltContext\Admin;

/**
 * SPA shell for the Settings admin page.
 */
class SettingsPage extends AbstractSpaPage {

	protected function getRootId(): string {
		return 'alt-context-admin-app';
	}

	protected function getRootClass(): string {
		return 'alt-context-settings';
	}

	protected function getPageTitle(): string {
		return __( 'Alt Context Settings', 'alt-context' );
	}

	protected function getLoadingMessage(): string {
		return __(
			'Loading Alt Context Settings. Please wait while the application initializes.',
			'alt-context'
		);
	}
}
