<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Admin\AbstractSpaPage;
use AltContext\Tests\TestCase;

/**
 * ORCH-UX-UI-BR-23: every SPA page shell rendered exactly one visible <h1>,
 * duplicating the title React pages render for themselves. The shell heading
 * now stays in the DOM (id="acx-page-title") for a11y-tree presence and
 * WordPress admin-notice anchoring, but is visually hidden via
 * screen-reader-text when the page's React view renders its own hero title.
 *
 * @covers \AltContext\Admin\AbstractSpaPage
 */
class AbstractSpaPageTest extends TestCase
{
    private function makePage(bool $rendersOwnTitle): AbstractSpaPage
    {
        return new class ($rendersOwnTitle) extends AbstractSpaPage {
            public function __construct(private readonly bool $rendersOwnTitleValue)
            {
            }

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

            protected function rendersOwnTitle(): bool
            {
                return $this->rendersOwnTitleValue;
            }
        };
    }

    public function testShellHeadingIsVisibleWhenReactDoesNotRenderItsOwnTitle(): void
    {
        $page = $this->makePage(false);

        ob_start();
        $page->render();
        $output = (string) ob_get_clean();

        $this->assertStringContainsString('<h1 id="acx-page-title">Test Page Title</h1>', $output);
        $this->assertStringNotContainsString('screen-reader-text', $output);
    }

    public function testShellHeadingIsScreenReaderOnlyWhenReactRendersItsOwnTitle(): void
    {
        $page = $this->makePage(true);

        ob_start();
        $page->render();
        $output = (string) ob_get_clean();

        $this->assertStringContainsString(
            '<h1 id="acx-page-title" class="screen-reader-text">Test Page Title</h1>',
            $output,
        );
    }
}
