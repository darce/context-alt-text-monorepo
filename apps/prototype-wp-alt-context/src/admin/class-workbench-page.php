<?php

declare(strict_types=1);

namespace AltContext\Admin;

/**
 * Workbench admin page shell that hosts the React SPA.
 */
class WorkbenchPage extends AbstractSpaPage {
	protected function getRootId(): string {
		return 'alt-context-admin-app';
	}

	protected function getRootClass(): string {
		return 'alt-context-workbench';
	}

	protected function getPageTitle(): string {
		return __( 'Alt Context Review Queue', 'alt-context' );
	}

	protected function getLoadingMessage(): string {
		return __(
			'Loading Alt Context Review Queue. Hang tight while we prepare your media workspace.',
			'alt-context'
		);
	}
}
