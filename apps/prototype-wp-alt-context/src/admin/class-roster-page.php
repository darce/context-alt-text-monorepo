<?php

declare(strict_types=1);

namespace AltContext\Admin;

/**
 * Roster admin page shell that hosts the React SPA.
 */
class RosterPage extends AbstractSpaPage {
	protected function getRootId(): string {
		return 'alt-context-admin-app';
	}

	protected function getRootClass(): string {
		return 'alt-context-roster';
	}

	protected function getPageTitle(): string {
		return __( 'Alt Context People', 'alt-context' );
	}

	protected function getLoadingMessage(): string {
		return __(
			'Loading the Alt Context roster. Please wait while the application initializes.',
			'alt-context'
		);
	}

	protected function rendersOwnTitle(): bool {
		return true;
	}
}
