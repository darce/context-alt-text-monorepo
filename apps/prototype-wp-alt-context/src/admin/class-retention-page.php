<?php

declare(strict_types=1);

namespace AltContext\Admin;

/**
 * Retention admin page shell that hosts the React SPA.
 */
class RetentionPage extends AbstractSpaPage {
	protected function getRootId(): string {
		return 'alt-context-admin-app';
	}

	protected function getRootClass(): string {
		return 'alt-context-retention';
	}

	protected function getPageTitle(): string {
		return __( 'Alt Context Data Retention', 'alt-context' );
	}

	protected function getLoadingMessage(): string {
		return __(
			'Loading Alt Context Data Retention. Please wait while the application initializes.',
			'alt-context'
		);
	}

	protected function rendersOwnTitle(): bool {
		return true;
	}
}
