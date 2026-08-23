<?php

declare(strict_types=1);

namespace AltContext\Admin;

/**
 * Dashboard admin page shell that hosts the React SPA.
 */
class DashboardPage extends AbstractSpaPage {
	protected function getRootId(): string {
		return 'alt-context-admin-app';
	}

	protected function getRootClass(): string {
		return 'alt-context-dashboard';
	}

	protected function getPageTitle(): string {
		return __( 'Alt Context Overview', 'alt-context' );
	}

	protected function getLoadingMessage(): string {
		return __(
			'Loading the Alt Context dashboard. Please wait while the application initializes.',
			'alt-context'
		);
	}
}
