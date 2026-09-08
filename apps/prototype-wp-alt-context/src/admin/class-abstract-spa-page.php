<?php

declare(strict_types=1);

namespace AltContext\Admin;

/**
 * Abstract base class for SPA (Single Page Application) admin pages.
 *
 * Provides common structure for React-based admin pages that render
 * a loading state while the JavaScript bundle loads and mounts.
 *
 * @since 1.0.0
 */
abstract class AbstractSpaPage {

	/**
	 * Get the DOM ID for the React root element.
	 *
	 * @return string The root element ID (without '#')
	 */
	abstract protected function getRootId(): string;

	/**
	 * Get the CSS class for the React root element.
	 *
	 * @return string The root element CSS class
	 */
	abstract protected function getRootClass(): string;

	/**
	 * Get the page title displayed in the WordPress admin header.
	 *
	 * @return string The translatable page title
	 */
	abstract protected function getPageTitle(): string;

	/**
	 * Get the loading message displayed before React mounts.
	 *
	 * @return string The translatable loading message
	 */
	abstract protected function getLoadingMessage(): string;

	/**
	 * Render the SPA page shell.
	 *
	 * Outputs the WordPress admin page wrapper with a React mount point
	 * and loading state. The actual content is rendered by JavaScript.
	 *
	 * Every React view now renders its own real, visible <h1> (ORCH-UX-UI
	 * BR-37/BR-38): the SPA shell mounts once per PHP request but the app is a
	 * single HashRouter, so a shell-owned title would go stale across in-app
	 * hash navigations with no page reload. This shell heading is therefore
	 * unconditionally visually hidden and stays in the DOM only as the first
	 * child of `.wrap` so WordPress can anchor admin-notice injection there,
	 * and for a11y-tree presence before the React bundle mounts.
	 *
	 * @return void
	 */
	public function render(): void {
		?>
		<div class="wrap alt-context-admin">
			<h1 id="acx-page-title" class="screen-reader-text" aria-hidden="true"><?php echo esc_html( $this->getPageTitle() ); ?></h1>
			<div id="<?php echo esc_attr( $this->getRootId() ); ?>" class="<?php echo esc_attr( $this->getRootClass() ); ?>">
				<p class="description">
					<?php echo esc_html( $this->getLoadingMessage() ); ?>
				</p>
			</div>
		</div>
		<?php
	}
}

