<?php

declare(strict_types=1);

namespace AltContext\Admin;

/**
 * Description history admin page shell that hosts the React SPA.
 */
class DescriptionHistoryPage extends AbstractSpaPage {
	protected function getRootId(): string {
		return 'alt-context-admin-app';
	}

	protected function getRootClass(): string {
		return 'alt-context-description-history';
	}

	protected function getPageTitle(): string {
		return __( 'Alt Context Description Runs', 'alt-context' );
	}

	protected function getLoadingMessage(): string {
		return __(
			'Loading Alt Context Description Runs. Please wait while the application initializes.',
			'alt-context'
		);
	}
}
