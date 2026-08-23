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
	 * Whether the React view for this page renders its own visible hero title.
	 *
	 * WHY: pages whose React view renders its own hero title would otherwise
	 * show the title twice and ship two <h1>s. Those pages hide the shell
	 * heading from sight but keep it in the DOM for the a11y tree and for
	 * WordPress admin-notice anchoring.
	 *
	 * @return bool
	 */
	protected function rendersOwnTitle(): bool {
		return false;
	}

	/**
	 * Render the SPA page shell.
	 *
	 * Outputs the WordPress admin page wrapper with a React mount point
	 * and loading state. The actual content is rendered by JavaScript.
	 *
	 * @return void
	 */
	public function render(): void {
		?>
		<div class="wrap alt-context-admin">
			<h1 id="acx-page-title"<?php echo $this->rendersOwnTitle() ? ' class="screen-reader-text"' : ''; ?>><?php echo esc_html( $this->getPageTitle() ); ?></h1>
			<div id="<?php echo esc_attr( $this->getRootId() ); ?>" class="<?php echo esc_attr( $this->getRootClass() ); ?>">
				<p class="description">
					<?php echo esc_html( $this->getLoadingMessage() ); ?>
				</p>
			</div>
		</div>
		<?php
	}
}

