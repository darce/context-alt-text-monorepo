<?php

declare(strict_types=1);

namespace ContextAltText\Admin;

/**
 * Alt-Text Workbench admin page.
 *
 * Renders the React-based workbench interface for bulk editing alt text.
 *
 * @since 1.0.0
 */
class AltTextWorkbenchPage extends AbstractSpaPage
{
    public const ROOT_ID = 'context-alt-text-workbench-root';

    protected function getRootId(): string
    {
        return self::ROOT_ID;
    }

    protected function getRootClass(): string
    {
        return 'context-alt-text-workbench-root';
    }

    protected function getPageTitle(): string
    {
        return __('Alt-Text Workbench', 'context-alt-text');
    }

    protected function getLoadingMessage(): string
    {
        return __('Alt-text workbench UI loading…', 'context-alt-text');
    }
}

