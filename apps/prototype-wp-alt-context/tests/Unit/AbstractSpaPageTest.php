<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Admin\AbstractSpaPage;
use AltContext\Tests\TestCase;

/**
 * ORCH-UX-UI BR-37/BR-38: the SPA shell mounts once per PHP request, but
 * js/admin/App.tsx mounts a single HashRouter for all six page routes, and
 * every in-app link is a bare hash change with no page reload. A shell-owned
 * visible <h1> therefore goes stale the moment the user navigates in-app: it
 * keeps showing the originally-server-loaded page's title (or, for pages that
 * hid it, nothing at all — because a hidden node that is directly referenced
 * by aria-labelledby is still pulled into the accessible name, per A11Y-58).
 *
 * The fix makes every React page render its own real, self-contained <h1>.
 * The shell heading is now unconditionally visually hidden
 * (screen-reader-text + aria-hidden="true") and stays in the DOM only as the
 * first child of `.wrap` so WordPress can anchor admin-notice injection
 * there. `rendersOwnTitle()` is deleted — it is no longer read by anything.
 *
 * @covers \AltContext\Admin\AbstractSpaPage
 */
class AbstractSpaPageTest extends TestCase
{
    private function makePage(): AbstractSpaPage
    {
        return new class () extends AbstractSpaPage {
            protected function getRootId(): string
            {
                return 'acx-test-root';
            }

            protected function getRootClass(): string
            {
                return 'acx-test-class';
            }

            protected function getPageTitle(): string
            {
                return 'Test Page Title';
            }

            protected function getLoadingMessage(): string
            {
                return 'Loading...';
            }
        };
    }

    public function testShellHeadingIsAlwaysScreenReaderOnlyAndAriaHidden(): void
    {
        $page = $this->makePage();

        ob_start();
        $page->render();
        $output = (string) ob_get_clean();

        $this->assertStringContainsString(
            '<h1 id="acx-page-title" class="screen-reader-text" aria-hidden="true">Test Page Title</h1>',
            $output,
        );
    }

    public function testRendersOwnTitleHookNoLongerExists(): void
    {
        $this->assertFalse(
            method_exists(AbstractSpaPage::class, 'rendersOwnTitle'),
            'rendersOwnTitle() is dead now that every React page renders its own <h1>; '
                . 'it must be deleted, not left as a vestigial always-true hook.',
        );
    }
}
